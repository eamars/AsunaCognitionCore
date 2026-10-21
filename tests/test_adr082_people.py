"""ADR-082: knowing the people who talk to her. In a group the person who starts a turn (and whoever's @ or reply to
her waits behind it) comes as an entry of familiarity, stance and her short lines; the full layers come with recall's
person; she writes about anyone present against what a recall showed. One-to-one conversations keep the relationship
block as before. Synthetic people only (the fixture world's A, B, C and an unnamed E)."""
import json

import pytest

from asuna import attend, familiarity, role_tools, switches
from asuna import understanding as people_mod
from asuna.context import PEOPLE_NOTE, UNDERSTANDING_NOTE, ContextBuilder
from asuna.coordinator import Coordinator
from asuna.ingress import persist_input
from asuna.lanes import FakeLane, FakeTurn, LaneResult
from asuna.memory import MemoryService
from asuna.native_api import NativeMemory
from asuna.people import People
from asuna.privacy import PrivacyService
from asuna.understanding import LIST_HOME_ONLY, NO_HERE, NO_PERSON, SHORT_CHARS
from test_adr009_p2 import owner
from test_native_cognition import snapshot, view  # noqa: F401  (the memory page over an in-memory store)

THINK = ('think', {'thought': '先看看是谁。'})
DM = {'event_id': 'dm-1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '我说话一向直接。'}


def event(key, person='A', wake='mentioned_account', text='@演示 在吗'):
    return {'event_id': key, 'scene_id': 'g1', 'person_id': person, 'text': text,
            'group_context': {'wake_reason': wake, 'topic_id': 't', 'mentioned_account_ids': []}}


def room(store):
    """g1 with four members: A and C share a name (林), E has none the program knows."""
    store.db.scenes.update_one({'_id': 'g1'}, {'$set': {'members': ['A', 'B', 'C', 'E']}})


def label(store, person, scene='g1'):
    return People(store, 'P1').speaker(store.db.scenes.find_one({'_id': scene}), person)


def turn(store, ev, *calls, gate=None, speech='在。'):
    lane = FakeLane(store, [FakeTurn([THINK, *calls], speech)])
    coordinator = Coordinator(store, lane)
    if gate:
        coordinator.attend = FakeLane(store, [LaneResult('接话：' + gate)])
    ep = coordinator.ingest(ev)
    assert ep['state'] == 'COMMITTED', ep.get('failure')
    return ep, lane


def results(lane, tool):
    """[(result or refusal text, ok)] of one tool's calls, in order."""
    return [(row[4], row[5]) for row in lane.tool_results if row[2] == tool]


def write_dm(store, layer='person', body='A 说话直接，先给结论。', short='直接，先给结论', key='dm-1'):
    ep, lane = turn(store, {**DM, 'event_id': key},
                    ('understand_person', {'layer': layer, 'content': body, 'short': short}), speech='好。')
    assert results(lane, 'understand_person') == [({'state': 'COMMITTED'}, True)]
    return ep


def stance(store):
    from asuna.persona_model import neutral
    model = neutral('P1', '演示')
    model['people'] = {'familiarity': {'known': {'stance': '熟人随意些。'}, 'new': {'stance': '不熟先客气。'}}}
    store.config['persona_model'] = model


# ---- the entry ----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('wake,gate', [('mentioned_account', None), ('reply_to_character', None),
                                       ('catchup_mention', '漏收的 @'), ('name_called', '叫了我的名字'),
                                       ('poked', '戳了我'), ('reacted', '给我点了表情')])
def test_a_group_turn_shows_the_person_who_started_it_whatever_woke_it(store, wake, gate):
    ep, _ = turn(store, event('w-' + wake, wake=wake, text='[戳一戳]' if wake == 'poked' else '演示 在吗'), gate=gate)
    context = ep['context']
    assert [item['who'] for item in context['people_from_program']['items']] == [label(store, 'A')]
    assert context['people_from_program']['note'] == PEOPLE_NOTE
    assert 'relationship' not in context and 'relationship_shared_from_program' not in context
    assert 'understanding_update_from_program' not in context
    assert list(ep['manifest']['people_shown']) == ['A']


def test_queued_addressers_get_an_entry_and_a_bystander_does_not(store):
    room(store)
    persist_input(store, event('before', 'E', None, '今天好热'))          # in history only: a bystander
    trigger = event('trigger')
    persist_input(store, trigger)
    persist_input(store, event('q-at', 'B'))                                # an @ waiting behind it
    persist_input(store, event('q-reply', 'C', 'reply_to_character', '对'))  # a reply to her waiting behind it
    persist_input(store, event('q-chat', 'E', None, '哈哈'))                # talk, not to her
    ep, _ = turn(store, trigger)
    items = ep['context']['people_from_program']['items']
    assert [item['who'] for item in items] == [label(store, p) for p in ('A', 'B', 'C')]
    assert set(ep['manifest']['people_shown']) == {'A', 'B', 'C'}
    assert label(store, 'E') in json.dumps(ep['context']['delivered_history'], ensure_ascii=False)


@pytest.mark.parametrize('home', [False, True])
def test_one_to_one_turns_keep_the_relationship_block_and_get_no_entry(store, home):
    if home:
        owner(store)
    _, context, manifest = ContextBuilder(store).prepare(DM)
    relation = context['relationship']
    assert relation['here'] == store.head('relationship:A', 'scene:dm-a')[1]['content']['body']
    assert relation['person']['text'] == NO_PERSON and relation['familiarity']
    assert context['understanding_update_from_program']['available'] is True
    assert context['understanding_update_from_program']['note'] == UNDERSTANDING_NOTE
    assert 'people_from_program' not in context and 'people_shown' not in manifest
    write_dm(store, body='A 说话直接。', short='直接')
    _, after, _ = ContextBuilder(store).prepare({**DM, 'event_id': 'dm-2'})
    assert after['relationship']['person']['text'] == 'A 说话直接。', 'the full layer, not the short'
    assert 'people_from_program' not in after


def test_every_entry_has_familiarity_and_stance_and_nothing_unwritten(store):
    room(store)
    stance(store)
    expected = {'who': label(store, 'C'), **familiarity.words(store, 'C', 'P1')}     # as the turn starts
    ep, _ = turn(store, event('t-new', 'C'))
    [item] = ep['context']['people_from_program']['items']
    assert item == expected, 'familiarity and stance, nothing of her understanding'
    assert item['stance'] == '不熟先客气。' and item['familiarity'] == familiarity.CORE_WORDS['new']
    [known] = turn(store, event('t-known', 'A'))[0]['context']['people_from_program']['items']
    assert known['stance'] == '熟人随意些。' and known['familiarity'] == familiarity.CORE_WORDS['known']
    audits = {row['type'] for row in store.db.audit_events.find({'stream_id': ep['_id']}, {'type': 1})}
    assert not {kind for kind in audits if 'understanding' in kind or kind.startswith('people')}, audits


def test_a_layer_written_before_shorts_shows_its_body_named_as_a_body(store):
    store.init_head('relationship:A', 'person', {'body': '旧的人那层，没有 short。'}, [])
    store.init_head('relationship:A', 'scene:g1', {'body': '旧的这里那层。'}, [])
    ep, _ = turn(store, event('t-old'))
    [item] = ep['context']['people_from_program']['items']
    assert item['short_body'] == '旧的人那层，没有 short。' and item['here_body'] == '旧的这里那层。'
    assert 'short' not in item and 'here' not in item
    assert item['written_at'] == store.head('relationship:A', 'scene:g1')[1]['created_at']
    person, here = store.head('relationship:A', 'person')[0], store.head('relationship:A', 'scene:g1')[0]
    assert ep['manifest']['people_shown'] == {'A': {'person': person['revision_id'], 'here': here['revision_id']}}


# ---- recall person -------------------------------------------------------------------------------------------------

def test_recall_person_reads_both_layers_pins_them_and_never_searches(store, monkeypatch):
    write_dm(store)
    store.init_head('relationship:A', 'scene:g1', {'body': '在群里爱开玩笑。', 'short': '群里爱开玩笑'}, [])
    original = ContextBuilder.prepare

    def no_search(self, ev, persona='P1', recall=False, turn_kind=None):
        assert not recall, 'recall person must not reach the retrieval prepare'
        return original(self, ev, persona, recall, turn_kind)

    monkeypatch.setattr(ContextBuilder, 'prepare', no_search)
    ep, lane = turn(store, event('t-recall'), ('recall', {'person': label(store, 'A'), 'query': '他是谁'}),
                    ('recall', {'person': '[没这人 #9]'}))
    (read, ok), (refused, refused_ok) = results(lane, 'recall')
    assert ok and read['who'] == label(store, 'A')
    assert read['person']['text'] == 'A 说话直接，先给结论。' and read['person']['short'] == '直接，先给结论'
    assert read['here'] == {'text': '在群里爱开玩笑。', 'short': '群里爱开玩笑'}
    assert 'query' in read['not_used'], 'a query beside person is said to be unused'
    person, here = store.head('relationship:A', 'person')[0], store.head('relationship:A', 'scene:g1')[0]
    saved = store.db.episodes.find_one({'_id': ep['_id']})
    assert saved['understanding_seen'] == {'A': {'person': person['revision_id'], 'here': here['revision_id']}}
    assert saved['recall_count'] == 1, 'a refused label spends no recall'
    assert not refused_ok and '[没这人 #9]' in refused and label(store, 'A') in refused


def test_people_list_at_home_and_refused_outside(store, monkeypatch):
    write_dm(store)
    _, lane = turn(store, event('t-list'), ('recall', {'person': '名单'}))
    assert results(lane, 'recall') == [(LIST_HOME_ONLY, False)]
    owner(store)
    _, lane = turn(store, {**DM, 'event_id': 'home-list'}, ('recall', {'person': '名单'}),
                   ('recall', {'person': '明'}))
    (listed, ok), (by_name, named_ok) = results(lane, 'recall')
    assert ok and named_ok
    rows = {row['name']: row['layers'] for row in listed['people']}
    assert set(rows) == {'林', '明'} and 'person' not in json.dumps(list(listed['people'][0]), ensure_ascii=False)
    person_layer = next(layer for layer in rows['林'] if layer['layer'] == '人那层')
    assert person_layer['chars'] == len('A 说话直接，先给结论。') and person_layer['written_in'] and person_layer['written_at']
    assert person_layer['short'] == (store.head('relationship:A', 'person')[1]['content'].get('short') or '没有')
    [b_here] = rows['明']
    assert b_here['layer'].startswith('这里那层') and b_here['chars'] > 0 and b_here['short'] == '没有'
    # At home a read names anyone on the list; his here layer is the one of the conversation it is read in.
    assert by_name['who'] and by_name['person']['text'] == NO_PERSON and by_name['here'] == {'text': NO_HERE}
    assert '另外 1 个对话' in by_name['person']['first']
    # B15: it grows with everyone she writes; past its bound, the newest, then how many earlier ones are left out.
    from asuna import understanding
    whole = understanding.listing(store, 'P1')
    cut = understanding.listing(store, 'P1', limit=len(json.dumps(
        {k: v for k, v in whole[0].items() if k != 'person'}, ensure_ascii=False, default=str)) + 2)
    assert cut == [whole[0], {'earlier': understanding.EARLIER_PEOPLE % (1, 2), 'left_out': 1}]
    # Through recall: she sees the closing line without its count; the audit counts the people listed and left out.
    monkeypatch.setattr(understanding, 'LISTED_CHARS', len(json.dumps(
        {k: v for k, v in whole[0].items() if k != 'person'}, ensure_ascii=False, default=str)) + 2)
    ep, lane = turn(store, {**DM, 'event_id': 'home-list-cut'}, ('recall', {'person': '名单'}))
    [(shown, ok)] = results(lane, 'recall')
    assert ok and shown['people'][-1] == {'earlier': understanding.EARLIER_PEOPLE % (1, 2)}
    audit = store.db.audit_events.find_one({'type': 'recall.people', 'stream_id': ep['_id']})
    assert audit['payload'] == {'listed': 1, 'left_out': 1}


# ---- the write -----------------------------------------------------------------------------------------------------

def test_a_group_write_against_an_unread_layer_is_refused_with_its_text_then_accepted(store):
    write_dm(store)
    old = store.head('relationship:A', 'person')[1]
    call = ('understand_person', {'layer': 'person', 'content': 'A 直接，也肯听人说完。', 'short': '直接但肯听'})
    ep, lane = turn(store, event('t-write'), call, call)
    (refused, first_ok), (accepted, ok) = results(lane, 'understand_person')
    assert not first_ok and '还没读过' in refused and old['content']['body'] in refused
    assert ok and accepted == {'state': 'COMMITTED'}
    new = store.head('relationship:A', 'person')[1]
    assert new['content'] == {'body': 'A 直接，也肯听人说完。', 'short': '直接但肯听'}
    assert new['parent_revision_id'] == old['_id'] and new['origin']['scene_id'] == 'g1'


def test_keep_body_changes_only_the_short_byte_for_byte(store):
    write_dm(store, body='  A 说话直接，先给结论。\n第二行留着。', short='旧的一句')
    old = store.head('relationship:A', 'person')[1]
    _, lane = turn(store, event('t-keep'), ('recall', {'person': label(store, 'A')}),
                   ('understand_person', {'layer': 'person', 'content': '不更新', 'short': '新的一句'}))
    assert results(lane, 'understand_person') == [({'state': 'COMMITTED'}, True)]
    new = store.head('relationship:A', 'person')[1]
    assert new['content']['body'] == old['content']['body'] and new['content']['short'] == '新的一句'
    _, lane = turn(store, event('t-same'), ('recall', {'person': label(store, 'A')}),
                   ('understand_person', {'layer': 'person', 'content': '不更新', 'short': '新的一句'}),
                   ('understand_person', {'layer': 'here', 'content': '不更新', 'short': '没有正文'}))
    (same, ok), (nothing, kept_ok) = results(lane, 'understand_person')
    assert ok and same == {'state': 'NO_CHANGE'}
    assert store.head('relationship:A', 'person')[1]['_id'] == new['_id']
    assert not kept_ok and '没有正文可以留着' in str(nothing)          # UNDERSTANDING_NOTHING_TO_KEEP
    assert store.head('relationship:A', 'scene:g1') is None


def test_once_per_person_and_layer_a_turn_and_a_second_person_too(store):
    room(store)
    write_dm(store)
    trigger = event('t-two')
    persist_input(store, trigger)
    persist_input(store, event('q-b', 'B'))
    ep, lane = turn(store, trigger, ('recall', {'person': label(store, 'A')}),
                    ('understand_person', {'layer': 'person', 'content': 'A 在纠正我。', 'short': 'A 会纠正我'}),
                    ('understand_person', {'layer': 'person', 'content': 'A 第二次。', 'short': '第二次'}),
                    ('understand_person', {'person': label(store, 'B'), 'layer': 'person', 'content': 'B 第一次来。',
                                           'short': '新来的 B'}))
    (a, a_ok), (again, again_ok), (b, b_ok) = results(lane, 'understand_person')
    assert a_ok and b_ok and a == b == {'state': 'COMMITTED'}
    assert not again_ok and '每人每层一回合只写一次' in again
    assert store.head('relationship:A', 'person')[1]['content']['body'] == 'A 在纠正我。'
    b_rev = store.head('relationship:B', 'person')[1]
    assert b_rev['content'] == {'body': 'B 第一次来。', 'short': '新来的 B'}
    assert b_rev['mutation_id'] == ep['_id'] + ':understanding:person:B'
    saved = store.db.episodes.find_one({'_id': ep['_id']})
    assert saved['person_understanding_update']['state'] == 'COMMITTED'
    assert saved['understanding_writes']['person|B']['state'] == 'COMMITTED'
    assert b_rev['source_ids'] == saved['monologue_refs']


def test_a_write_about_someone_present_takes_the_summaries_that_cover_that_person(store):
    room(store)
    trigger = event('t-src')
    persist_input(store, trigger)
    persist_input(store, event('q-src', 'B'))
    ep, _ = turn(store, trigger)
    ep = store.db.episodes.find_one({'_id': ep['_id']})

    def summary(key, participants):
        store.db.memory_units.insert_one({
            '_id': key, 'schema_version': 1, 'revision': 1, 'kind': 'dialogue_summary', 'scope_key': 'scene:g1',
            'policy_epoch': ep['policy_epoch'], 'character_id': 'demo', 'epistemic_type': 'derived_summary',
            'status': 'active', 'body_markdown': '摘要', 'source_event_ids': [], 'scene_id': 'g1',
            'participants': participants})

    summary('sum-b', ['B', 'demo'])
    summary('sum-a', ['A', 'demo'])
    shown = {**ep, 'manifest': {**ep['manifest'], 'selected': ['sum-a', 'sum-b']}}
    result = MemoryService(store).commit_understanding(shown, 'B 说他周日有空。', 'here', person_id='B', short='周日有空',
                                                       base={'person': None, 'here': None})
    assert result['state'] == 'COMMITTED', result
    assert result['auto_source_ids'] == ['sum-b']
    assert result['auto_source_skipped'] == [{'id': 'sum-a', 'reason': 'person_not_in_participants'}]
    assert result['source_ids'] == ep['monologue_refs'] + ['sum-b']
    assert store.head('relationship:B', 'scene:g1')[1]['content'] == {'body': 'B 说他周日有空。', 'short': '周日有空'}


def test_she_may_recall_and_write_about_a_bystander_whose_lines_are_in_the_turn(store):
    persist_input(store, event('by-b', 'B', None, '今天好热'))
    _, lane = turn(store, event('t-by'), ('recall', {'person': label(store, 'B')}),
                   ('understand_person', {'person': label(store, 'B'), 'layer': 'here', 'content': 'B 怕热。',
                                          'short': '怕热'}))
    assert [ok for _, ok in results(lane, 'recall') + results(lane, 'understand_person')] == [True, True]


def test_a_second_write_after_a_first_record_gets_the_once_a_turn_refusal(store):
    _, lane = turn(store, event('t-first'),
                   ('understand_person', {'layer': 'person', 'content': 'A 第一次。', 'short': '第一次'}),
                   ('understand_person', {'layer': 'person', 'content': 'A 第二次。', 'short': '第二次'}))
    (_, first_ok), (again, _) = results(lane, 'understand_person')
    assert first_ok and '每人每层一回合只写一次' in again


def test_a_long_short_is_kept_and_the_result_says_by_how_much(store):
    short = '长' * (SHORT_CHARS + 13)
    _, lane = turn(store, {**DM, 'event_id': 'dm-long'},
                   ('understand_person', {'layer': 'person', 'content': 'A 说话直接。', 'short': short}))
    [(result, ok)] = results(lane, 'understand_person')
    assert ok and result['state'] == 'COMMITTED' and '超了 13 字' in result['short']
    assert store.head('relationship:A', 'person')[1]['content']['short'] == short


def test_understand_person_is_closed_in_a_group_plan_turn_and_says_so(store):
    base = {'_id': 'ep-x', 'scene_id': 'g1', 'person_id': 'A', 'persona': 'P1', 'context': {},
            'manifest': {'session_class': 'public'}}
    for kind in ('external', 'task_feedback', 'visit'):
        assert 'understand_person' in role_tools._turn_rules(store, {**base, 'episode_kind': kind}), kind
    scheduled = {**base, 'episode_kind': 'scheduled'}
    assert 'understand_person' not in role_tools._turn_rules(store, scheduled)
    assert '计划到点' in role_tools.not_now(store, scheduled, 'understand_person')
    # One-to-one turns: offered as before, by the context's own block.
    dm = {**base, 'scene_id': 'dm-a', 'episode_kind': 'external'}
    assert 'understand_person' not in role_tools._turn_rules(store, dm)
    assert 'understand_person' in role_tools._turn_rules(
        store, {**dm, 'context': {'understanding_update_from_program': {'available': True}}})
    described = role_tools.TOOLS['understand_person']
    assert '在群里先 speak 再写' in described['description'] and people_mod.ASK in described['description']
    assert {'layer', 'content', 'short'} <= {k for k, v in described['parameters'].items() if v.get('required')}


# ---- readers -------------------------------------------------------------------------------------------------------

def test_the_relevance_gate_shows_the_two_shorts(store):
    scene = store.db.scenes.find_one({'_id': 'g1'})
    assert attend.speaker_understanding(store, scene, 'A') is None
    store.init_head('relationship:A', 'person', {'body': '人那层很长的正文。' * 30}, [])
    assert attend.speaker_understanding(store, scene, 'A') == attend._cut('人那层很长的正文。' * 30,
                                                                         attend.UNDERSTANDING_CHARS)
    write_dm(store, body='A 说话直接。', short='直接的人')
    _, lane = turn(store, event('t-gate'), ('recall', {'person': label(store, 'A')}),
                   ('understand_person', {'layer': 'here', 'content': '在群里爱开玩笑。', 'short': '群里爱开玩笑'}))
    assert results(lane, 'understand_person')[-1][1]
    assert attend.speaker_understanding(store, scene, 'A') == '直接的人\n群里爱开玩笑'


def test_the_memory_page_shows_the_short_first(view):
    store, worker, binding = view
    store.init_head('relationship:qq:11', 'person', {'body': '哪儿都成立的那层', 'short': '给自己的一句'}, [])
    texts = {scope: text for scope, text, _ in NativeMemory(worker, 'role').relation_records('qq:11')['qq:11']}
    assert texts == {'person': '给自己的一句\n\n哪儿都成立的那层', 'scene:one': '这个人偏好简洁表达'}


def test_what_an_entry_or_a_recall_showed_of_someone_is_marked_used(view):
    store, worker, binding = view
    store.init_head('relationship:qq:22', 'person', {'body': '另一个人的人那层', 'short': '另一个人'}, [])
    store.init_head('relationship:qq:22', 'scene:one', {'body': '另一个人在这里'}, [])
    person = store.head('relationship:qq:22', 'person')[0]['revision_id']
    here = store.head('relationship:qq:22', 'scene:one')[0]['revision_id']
    snapshot(store, binding, understanding_seen={'qq:22': {'person': person, 'here': None}})
    usage = NativeMemory(worker, 'role').cognition.usage
    assert usage('head:relationship:qq:22|person', revision=person) == 'used'          # a recall pinned it
    assert usage('head:relationship:qq:22|scene:one', revision=here) == 'unused'
    store.db.episodes.update_one({'_id': 'ep'}, {'$set': {'manifest.people_shown': {
        'qq:22': {'person': None, 'here': here}}}})
    assert NativeMemory(worker, 'role').cognition.usage('head:relationship:qq:22|scene:one', revision=here) == 'used'


def test_erase_takes_the_short_back_with_its_revision(store):
    write_dm(store, body='他重视守时。', short='守时的人')
    ep, _ = turn(store, event('t-before-erase'))
    assert ep['context']['people_from_program']['items'][0]['short'] == '守时的人'
    PrivacyService(store).delete_memory('M09', operator=True)
    assert store.head('relationship:A', 'person') is None
    ep, _ = turn(store, event('t-after-erase'))
    [item] = ep['context']['people_from_program']['items']
    assert 'short' not in item and '守时' not in json.dumps(item, ensure_ascii=False)


def test_watch_block_blocks_the_turns_person_and_never_at_home(store):
    assert 'block' in role_tools.TOOLS['watch']['parameters']['do']['enum']
    assert 'block' not in role_tools.TOOLS['understand_person']['parameters']
    lane = FakeLane(store, [FakeTurn([THINK], '在。'), FakeTurn([THINK], '在。')])
    coordinator = Coordinator(store, lane)
    owner(store)
    home = coordinator.ingest({**DM, 'event_id': 'home-block'})
    with pytest.raises(role_tools.Refused, match='家里的人屏蔽不了'):
        coordinator.tools.tool_watch(store.db.episodes.find_one({'_id': home['_id']}), 'c1', {'op': 'block'})
    assert switches.blocked(store, 'A') is None
    room(store)
    ep = coordinator.ingest(event('t-block', person='B'))
    blocked = coordinator.tools.tool_watch(store.db.episodes.find_one({'_id': ep['_id']}), 'c2',
                                           {'op': 'block', 'hours': 2})[0]
    assert label(store, 'B') in blocked['done'] and switches.blocked(store, 'B')['_id'] == blocked['id']


def test_watch_block_names_someone_here_never_anyone_from_home(store):
    """block takes person as on does (a label, #number or name here); without it, the one speaking. The owner is
    never blocked, in any conversation: a block silences that person's lines everywhere, his own chat included."""
    owner(store, person='O')
    room(store)
    lane = FakeLane(store, [FakeTurn([THINK], '在。') for _ in range(3)])
    coordinator = Coordinator(store, lane)
    ep = store.db.episodes.find_one({'_id': coordinator.ingest(event('t-name'))['_id']})
    named = coordinator.tools.tool_watch(ep, 'c1', {'op': 'block', 'person': label(store, 'B'), 'hours': 2})[0]
    assert label(store, 'B') in named['done'] and switches.blocked(store, 'B') and switches.blocked(store, 'A') is None
    speaking = coordinator.tools.tool_watch(ep, 'c2', {'op': 'block', 'hours': 2})[0]
    assert label(store, 'A') in speaking['done'] and switches.blocked(store, 'A')
    with pytest.raises(role_tools.Refused) as unknown:
        coordinator.tools.tool_watch(ep, 'c3', {'op': 'block', 'person': '[没这人 #99]'})
    assert '这个对话里没有「[没这人 #99]」' in str(unknown.value) and '能用的：' in str(unknown.value)
    assert str(unknown.value).endswith('能用的：%s、%s。' % (label(store, 'A'), label(store, 'B'))), 'the people seen here'
    visit = {**ep, 'episode_kind': 'visit', 'turn_kind': 'visit'}
    assert label(store, 'C') in coordinator.tools.tool_watch(visit, 'c4', {'op': 'block', 'person': label(store, 'C')})[0]['done'], \
        'named, it needs no one speaking'
    owner(store, person='A')
    with pytest.raises(role_tools.Refused, match='家里的人屏蔽不了'):
        coordinator.tools.tool_watch(ep, 'c5', {'op': 'block', 'person': label(store, 'A').split()[-1]})   # [林 #1]
    with pytest.raises(role_tools.Refused, match='家里的人屏蔽不了'):
        coordinator.tools.tool_watch(ep, 'c6', {'op': 'block'})


@pytest.mark.parametrize('kind', ['visit', 'scheduled', 'task_feedback'])
def test_watch_block_is_refused_in_a_turn_nobody_spoke_in(store, kind):
    """A visit's person only authorizes the visit (places.visitor); a plan or a report has no speaker either."""
    lane = FakeLane(store, [FakeTurn([THINK], '在。')])
    coordinator = Coordinator(store, lane)
    ep = coordinator.ingest(event('t-quiet-' + kind))
    quiet = {**store.db.episodes.find_one({'_id': ep['_id']}), 'episode_kind': kind, 'turn_kind': kind}
    with pytest.raises(role_tools.Refused, match='这一回合没有人在跟你说话'):
        coordinator.tools.tool_watch(quiet, 'c1', {'op': 'block', 'hours': 2})
    assert switches.blocked(store, 'A') is None
