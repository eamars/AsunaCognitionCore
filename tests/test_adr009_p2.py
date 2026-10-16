"""ADR-009 P2 MongoDB tests: documents, render budget, write_document, recall sections, seeds."""
from concurrent.futures import ThreadPoolExecutor
import json
import threading


from asuna.context import ContextBuilder
from asuna.coordinator import Coordinator
from asuna.documents import DocumentStore, PREAMBLE
from asuna.lanes import FakeLane, FakeTurn
from asuna.render import action_values
from asuna.state import Conflict
from conftest import FIXTURES
from test_engineering_m1 import event

SEED = (FIXTURES / 'personas/demo/seeds/persona.md').read_text(encoding='utf-8')


def owner(store, scene='dm-a', person='A'):
    """Make (scene, person) the owner's local scene: its turns are owner_private."""
    store.config['chat'] = {**store.config.get('chat', {}), 'scene_id': scene, 'person_id': person,
                            'persona': 'P1', 'display_name': '示例角色'}
    return store


def test_T2_1_concurrent_writes_on_one_base(store):
    docs = DocumentStore(store, 'P1')
    docs.seed('ledger', 'ledger', '## 答应过的事\n暂无。')
    base = docs.read('ledger')[0]
    barrier = threading.Barrier(2)

    def write(i):
        barrier.wait()
        try:
            docs.apply('ledger', {'op': 'append_section', 'heading': f'事项{i}', 'reason': '并发', 'visibility': 'public'},
                       f'第{i}件事', base_revision_id=base, author='character', mutation_id=f't21-{i}')
            return 'ok'
        except Conflict as exc:
            return str(exc).split(':', 1)[0]

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(write, (1, 2))) == ['BASE_REVISION_STALE', 'ok']
    sections = docs.read('ledger')[1]['sections']
    assert len(sections) == 2 and sections[0]['body'] == '暂无。'


THINK = ('think', {'thought': '他说了一件小事，值得记下来。'})


def test_T2_6_documents_are_written_in_the_call_and_refusals_do_not_stop_the_turn(store):
    owner(store)
    store.config['persona_contribution'] = {'seeds': []}
    entry = {'doc': 'diary', 'do': 'append_section', 'heading': '今天', 'why': '值得记下',
             'content': '今天他提到了一件小事。'}
    tags = {'doc': 'persona', 'do': 'set_tags', 'section': PREAMBLE, 'tags': ['values'], 'why': '标注'}
    lane = FakeLane(store, [FakeTurn([THINK, ('write_document', entry), ('write_document', tags),
                                      ('set_policy', {'key': 'nope', 'value': 1, 'why': 'x'})], '记下了。')])
    ep = Coordinator(store, lane).ingest(event('write-1'))
    assert ep['state'] == 'COMMITTED', ep.get('failure')
    assert ep['manifest']['session_class'] == 'owner_private', ep['manifest']['session_class']
    assert [c['phase'] for c in lane.calls] == ['TURN']             # the body is in the call: no WRITE stage
    assert 'feel' not in lane.calls[0]['tools']                     # no affect ledger: no feel tool this turn
    entry_row = DocumentStore(store, 'P1').read('diary')[1]['sections'][-1]
    assert entry_row['body'] == '今天他提到了一件小事。' and entry_row['visibility'] == 'owner_private'
    assert DocumentStore(store, 'P1').read('persona')[1]['sections'][0]['tags'] == ['values']
    _, wrote, tagged, policy = lane.tool_results
    assert wrote[5] and tagged[5], (wrote, tagged)
    # A refused call goes back to her in words, in the same turn; the turn still speaks.
    assert not policy[5] and '没有可以改的参数' in policy[4] and 'POLICY_KEY_UNDECLARED' not in policy[4]
    assert ep['tool_calls'][policy[1]]['code'] == 'POLICY_KEY_UNDECLARED', 'the code stays in the record'
    assert [r['text'] for r in store.db.messages.find({'episode_id': ep['_id'], 'direction': 'outbound'})] == ['记下了。']
    # A group (public) turn may not write any document of hers.
    before = DocumentStore(store, 'P1').read('diary')[0]
    group = FakeLane(store, [FakeTurn([THINK, ('write_document', {**entry, 'heading': '群里'})], '好。')])
    ep = Coordinator(store, group).ingest(event('write-group', scene='g1'))
    assert ep['state'] == 'COMMITTED' and [c['phase'] for c in group.calls] == ['TURN']
    refusal = group.tool_results[1]
    assert not refusal[5] and '只能在家里' in refusal[4] and '主人私聊' in refusal[4]
    assert DocumentStore(store, 'P1').read('diary')[0] == before


def test_person_files_are_retired(store):
    owner(store)
    lane = FakeLane(store, [FakeTurn([THINK, ('write_document', {'doc': 'dossier:A', 'do': 'append_section',
                                     'heading': '今天', 'why': '记一笔', 'content': '他提到了一件小事。'})], '好。')])
    ep = Coordinator(store, lane).ingest(event('dossier-retired'))
    refusal = lane.tool_results[1]
    assert ep['state'] == 'COMMITTED' and not refusal[5] and 'understand_person' in refusal[4]
    assert DocumentStore(store, 'P1').read('dossier:A') == (None, None)
    assert 'dossier' not in json.dumps(lane.calls[0]['tools'], ensure_ascii=False)


def test_T2_7_recall_reads_sections_by_visibility(store):
    owner(store)
    docs = DocumentStore(store, 'P1')
    docs.seed('notes', 'working', '<!-- asuna-seed {"visibility": "owner_private"} -->\n## 私密\nPRIVATE_NOTE_BODY\n')
    read = ('recall', {'query': '笔记', 'sections': [{'doc': 'notes', 'sid': '私密'}]})
    lane = FakeLane(store, [FakeTurn([THINK, read], '看到了。')])
    Coordinator(store, lane).ingest(event('read-private'))
    result = lane.tool_results[1]
    assert result[5] and 'PRIVATE_NOTE_BODY' in result[4]['documents'][0]['body']
    group = FakeLane(store, [FakeTurn([THINK, read], '没看到。')])
    ep = Coordinator(store, group).ingest(event('read-group', scene='g1'))
    result = group.tool_results[1]
    assert ep['state'] == 'COMMITTED' and result[5] and 'documents' not in result[4]
    assert result[4]['not_read'] == ['notes#私密：这里读不到']
    assert 'PRIVATE_NOTE_BODY' not in json.dumps([group.calls, group.tool_results], ensure_ascii=False)


def test_T2_9_seeds_fill_missing_heads_only_and_adopt_by_sid(store):
    docs = DocumentStore(store, 'demo')
    assert docs.seed('persona', 'persona', SEED)
    assert docs.seed('persona', 'persona', SEED + '\n## 新节\n包里新加的。') is None        # restart never overwrites
    sections = docs.read('persona')[1]['sections']
    assert [s for s in sections if s['sid'] == '价值'][0]['tags'] == ['values']          # front-matter applied
    mine = docs.apply('persona', {'op': 'replace_section', 'sid': '说话方式', 'reason': '我改了'}, '我自己的口吻。',
                      base_revision_id=docs.read('persona')[0], author='character', mutation_id='t29-mine')
    upgraded = SEED.replace('说话简短直接，一次只说一两件事。', '包里改了说话方式。').replace(
        '我喜欢清茶', '我喜欢热茶') + '\n## 新节\n包里新加的。\n'
    result = docs.adopt_seed('persona', 'persona', upgraded, base_revision_id=mine['_id'], author='operator',
                             mutation_id='t29-adopt')
    assert result['state'] == 'updated' and '新节' in result['changed'] and '我的性格与处理方式' in result['changed']
    assert result['conflicts'] == ['说话方式']
    after = {s['sid']: s['body'] for s in docs.read('persona')[1]['sections']}
    assert after['说话方式'] == '我自己的口吻。' and '热茶' in after['我的性格与处理方式']


def test_T2_10_action_brain_gets_public_values_only(store):
    from asuna.persona_model import neutral
    owner(store)
    model = neutral('P1', 'P1')
    store.config['persona_model'] = {**model, 'render': {**model.get('render', {}), 'action_persona': 'values'}}
    docs = DocumentStore(store, 'P1')
    for i, (vis, tags) in enumerate([('public', ['values']), ('owner_private', ['values']), ('public', [])]):
        docs.apply('persona', {'op': 'append_section', 'heading': f'节{i}', 'visibility': vis, 'tags': tags,
                               'reason': '测试'}, f'SECTION_BODY_{i}', base_revision_id=docs.read('persona')[0],
                   author='operator', mutation_id=f't210-{i}')
    text = action_values(store, 'P1')
    assert 'SECTION_BODY_0' in text and 'SECTION_BODY_1' not in text and 'SECTION_BODY_2' not in text


def test_the_action_brain_is_a_person_from_her_core_sentences_not_her_rules_for_talking(store):
    """Owner 2026-10-14: core is the default; her persona's rules for talking stay out."""
    owner(store)
    docs = DocumentStore(store, 'P1')
    docs.apply('core', {'op': 'append_section', 'heading': '一', 'visibility': 'public', 'reason': '我是谁', 'kind': 'working'},
               'CORE_SENTENCE', base_revision_id=None, author='character', mutation_id='core-a')
    docs.apply('persona', {'op': 'append_section', 'heading': '说话', 'visibility': 'public', 'reason': '规矩'},
               'TALKING_RULE', base_revision_id=docs.read('persona')[0], author='operator', mutation_id='persona-a')
    text = action_values(store, 'P1')
    assert 'CORE_SENTENCE' in text and 'TALKING_RULE' not in text and '下面是你自己写的「我是谁」' in text
