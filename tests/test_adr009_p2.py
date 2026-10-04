"""ADR-009 P2 MongoDB tests: documents, render budget, WRITE stage, dossier, read, conversion, seeds."""
from concurrent.futures import ThreadPoolExecutor
import json
import threading

import pytest

from asuna.context import ContextBuilder
from asuna.coordinator import Coordinator
from asuna.documents import DocumentError, DocumentStore, PREAMBLE
from asuna.lanes import FakeLane, LaneResult
from asuna.render import action_values, compose, common_text, render_system, budget_gate
from asuna.state import Conflict
from conftest import FIXTURES
from test_engineering_m1 import event

SEED = (FIXTURES / 'personas/demo/seeds/persona.md').read_text(encoding='utf-8')


def owner(store, scene='dm-a', person='A'):
    """Make (scene, person) the owner's local scene: its turns are owner_private."""
    store.config['chat'] = {**store.config.get('chat', {}), 'scene_id': scene, 'person_id': person,
                            'persona': 'P1', 'display_name': '示例角色'}
    return store


def decide(**extra):
    return LaneResult(json.dumps({'next': 'speak', 'goal': '回应', 'constraints': [], 'recall_query': '',
                                  'speak_before_action': False, **extra}, ensure_ascii=False))


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
            return str(exc)

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(write, (1, 2))) == ['BASE_REVISION_STALE', 'ok']
    sections = docs.read('ledger')[1]['sections']
    assert len(sections) == 2 and sections[0]['body'] == '暂无。'


def test_T2_3_budget_refuses_growth_but_never_truncates(store):
    owner(store)
    store.config['character'] = {**store.config['character'], 'context_window': 4000}  # × 0.25 = 1000-token limit
    docs = DocumentStore(store, 'P1')
    base = docs.read('persona')[0]
    gate = budget_gate(store, 'P1')
    with pytest.raises(DocumentError, match='PERSONA_RENDER_OVER_BUDGET') as refused:
        docs.apply('persona', {'op': 'append_section', 'heading': '很长', 'reason': '加长', 'visibility': 'public'},
                   '长' * 800, base_revision_id=base, author='character', mutation_id='t23-grow', budget=gate)
    assert 'estimate' in refused.value.detail and docs.read('persona')[0] == base
    # Already over budget (a smaller window): the render is complete, the turn runs, status is red and audited.
    store.config['character']['context_window'] = 400
    text, _ = render_system(store, 'P1', 'owner_private')
    assert text == compose(common_text(store.config), docs.read('persona')[1], None, 'owner_private')
    assert store.db.audit_events.find_one({'type': 'render.over_budget'})
    lane = FakeLane(store, [LaneResult('想。'), decide(), LaneResult('好。')])
    assert Coordinator(store, lane).ingest(event('over-budget'))['state'] == 'COMMITTED'
    # A change that shrinks the render is always accepted.
    largest = max(docs.read('persona')[1]['sections'], key=lambda section: len(section['body']))['sid']
    shrunk = docs.apply('persona', {'op': 'replace_section', 'sid': largest, 'reason': '精简'},
                        '# 示例角色\n我是示例角色，一个只用于测试的虚构数字角色，没有现实身体。' * 3,
                        base_revision_id=docs.read('persona')[0], author='character', mutation_id='t23-shrink', budget=gate)
    assert shrunk['_id'] == docs.read('persona')[0]


def dossier(store):
    docs = DocumentStore(store, 'P1')
    docs.seed('dossier:A', 'dossier', '## 写法规矩\n记具体的事。\n', subject='A')
    for i, (tags, vis) in enumerate([(['entry', 'injectable'], 'owner_private'), (['entry'], 'owner_private'),
                                     (['entry', 'injectable'], 'public'), (['entry', 'injectable'], 'owner_private')]):
        docs.apply('dossier:A', {'op': 'append_section', 'heading': f'条目{i}', 'entry_date': f'2026-01-0{i + 1}',
                                 'tags': tags, 'visibility': vis, 'reason': '记录'}, f'ENTRY_BODY_{i}',
                   base_revision_id=docs.read('dossier:A')[0], author='character', mutation_id=f'dossier-{i}')
    return docs


def test_T2_4_dossier_injection_by_session_class(store):
    owner(store)
    store.config['persona_model'] = {'model_version': 1, 'persona': {'id': 'P1', 'display_name': 'x'},
                                     'dossier': {'inject_last': 2, 'index_size': 30}}
    docs = dossier(store)
    docs.apply('dossier:A', {'op': 'set_tags', 'sid': '写法规矩', 'tags': ['preamble'], 'inject': 'always', 'reason': '前言'},
               base_revision_id=docs.read('dossier:A')[0], author='character', mutation_id='dossier-pre')
    _, private, _ = ContextBuilder(store).prepare(event('dossier-private'), 'P1')
    block = private['dossier_from_program']
    bodies = [s['body'] for s in block['sections']]
    assert bodies == ['记具体的事。', 'ENTRY_BODY_2', 'ENTRY_BODY_3'], bodies          # preamble + last 2 injectable
    assert [i['heading'] for i in block['index']] == ['条目0', '条目2', '条目3']          # injectable titles only
    assert 'ENTRY_BODY_1' not in json.dumps(private, ensure_ascii=False)               # never auto-injected
    _, public, _ = ContextBuilder(store).prepare(event('dossier-group', scene='g1'), 'P1')
    assert 'dossier_from_program' not in public                                       # no public+always section
    assert 'ENTRY_BODY' not in action_values(store, 'P1')


def test_T2_5_dossier_entries_are_append_only(store):
    docs = dossier(store)
    entry = docs.read('dossier:A')[1]['sections'][1]
    with pytest.raises(DocumentError, match='DOC_OP_NOT_ALLOWED'):
        docs.apply('dossier:A', {'op': 'replace_section', 'sid': entry['sid'], 'reason': '改写'}, '改掉',
                   base_revision_id=docs.read('dossier:A')[0], author='character', mutation_id='t25-replace')
    docs.apply('dossier:A', {'op': 'correction', 'sid': entry['sid'], 'reason': '记错了'}, '那天其实是周二',
               base_revision_id=docs.read('dossier:A')[0], author='character', mutation_id='t25-correct')
    sections = docs.read('dossier:A')[1]['sections']
    assert sections[1] == entry and sections[-1]['corrects'] == entry['sid'] and 'correction' in sections[-1]['tags']


def test_T2_6_write_stage_commits_and_failures_do_not_stop_the_turn(store):
    owner(store)
    store.config['persona_contribution'] = {'seeds': []}
    writes = [{'doc': 'dossier:A', 'op': 'append_section', 'heading': '今天', 'entry_date': '2026-01-02',
               'tags': ['entry', 'injectable'], 'reason': '值得记下'},
              {'doc': 'persona', 'op': 'set_tags', 'sid': PREAMBLE, 'tags': ['values'], 'reason': '标注'}]
    lane = FakeLane(store, [LaneResult('想记下。'), decide(write_docs=writes, policy_set=[{'key': 'nope', 'value': 1, 'reason': 'x'}],
                                                           affect=[{'val': 1, 'arl': 1, 'ref': 'e', 'why': 'w'}]),
                            LaneResult('今天他提到了一件小事。'), LaneResult('记下了。')])
    ep = Coordinator(store, lane).ingest(event('write-1'))
    assert ep['state'] == 'COMMITTED', ep.get('failure')
    assert ep['manifest']['session_class'] == 'owner_private', (ep['manifest']['session_class'], ep.get('rejections'))
    assert [c['phase'] for c in lane.calls] == ['MONOLOGUE', 'DECIDE', 'WRITE', 'SPEAK'], ep.get('rejections')   # set_tags has no WRITE
    entry = DocumentStore(store, 'P1').read('dossier:A')[1]['sections'][-1]
    assert entry['body'] == '今天他提到了一件小事。' and entry['visibility'] == 'owner_private'
    assert DocumentStore(store, 'P1').read('persona')[1]['sections'][0]['tags'] == ['values']
    codes = {(r['field'], r['code']) for r in ep['rejections']}
    assert ('policy_set', 'POLICY_KEY_UNDECLARED') in codes and ('affect', 'AFFECT_DISABLED') in codes
    speak = lane.calls[-1]['messages'][-1]['content']
    assert '"write_docs"' in speak and 'POLICY_KEY_UNDECLARED' in speak
    # A group (public) turn may not write any document.
    group = FakeLane(store, [LaneResult('想。'), decide(write_docs=writes[:1]), LaneResult('好。')])
    ep = Coordinator(store, group).ingest(event('write-group', scene='g1'))
    assert ep['state'] == 'COMMITTED' and [c['phase'] for c in group.calls] == ['MONOLOGUE', 'DECIDE', 'SPEAK']
    assert ep['rejections'][0]['code'] == 'DOC_WRITE_REQUIRES_OWNER_PRIVATE'


def test_T2_7_read_on_recall_follows_visibility(store):
    owner(store)
    docs = DocumentStore(store, 'P1')
    docs.seed('notes', 'working', '<!-- asuna-seed {"visibility": "owner_private"} -->\n## 私密\nPRIVATE_NOTE_BODY\n')
    recall = decide(next='recall', recall_query='笔记', read=[{'doc': 'notes', 'sid': '私密'}])
    lane = FakeLane(store, [LaneResult('想看笔记。'), recall, LaneResult('看到了。'), decide(), LaneResult('好。')])
    Coordinator(store, lane).ingest(event('read-private'))
    assert 'PRIVATE_NOTE_BODY' in lane.calls[2]['messages'][-1]['content']
    group = FakeLane(store, [LaneResult('想看。'), recall, LaneResult('没看到。'), decide(), LaneResult('好。')])
    ep = Coordinator(store, group).ingest(event('read-group', scene='g1'))
    assert 'PRIVATE_NOTE_BODY' not in json.dumps(group.calls, ensure_ascii=False)
    assert any(r['code'] == 'DOC_READ_DENIED' for r in ep['rejections'])


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
    owner(store)
    docs = DocumentStore(store, 'P1')
    for i, (vis, tags) in enumerate([('public', ['values']), ('owner_private', ['values']), ('public', [])]):
        docs.apply('persona', {'op': 'append_section', 'heading': f'节{i}', 'visibility': vis, 'tags': tags,
                               'reason': '测试'}, f'SECTION_BODY_{i}', base_revision_id=docs.read('persona')[0],
                   author='operator', mutation_id=f't210-{i}')
    text = action_values(store, 'P1')
    assert 'SECTION_BODY_0' in text and 'SECTION_BODY_1' not in text and 'SECTION_BODY_2' not in text
