"""ADR-062 phase 2, state and moves: her items' places, kept up by memorable moments and moved down by the program,
behind memory_tiers.ENABLED (off by default: nothing is read or written)."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from asuna import memory_tiers
from asuna.coordinator import Coordinator
from asuna.context import ContextBuilder
from asuna.documents import DocumentStore
from asuna.lanes import FakeLane, FakeTurn
from asuna.memory_tiers import AT_HAND, CARRIED, PUT_AWAY, Tiers
from asuna.render import render_system
from test_adr009_p2 import owner, THINK
from test_engineering_m1 import event


@pytest.fixture
def tiers_on(monkeypatch):
    monkeypatch.setattr(memory_tiers, 'ENABLED', True)


def write(docs, slug, intent, body=None, mutation=None):
    before = docs.read(slug)
    docs.apply(slug, {'reason': 'r', **intent}, body, base_revision_id=before[0], author='character',
               mutation_id=mutation or '%s:%s:%s' % (slug, intent.get('op'), intent.get('heading') or intent.get('sid')))
    return before[1], docs.read(slug)[1]


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def persona_sids(store):
    return [s['sid'] for s in DocumentStore(store, 'P1').read('persona')[1]['sections']]


def test_with_the_switch_off_nothing_is_kept_and_her_turn_has_no_things_block(store, monkeypatch):
    monkeypatch.setattr(memory_tiers, 'ENABLED', False)
    owner(store)
    Coordinator(store, FakeLane(store, [FakeTurn([THINK], '在呢。')])).ingest(event('e-off'))
    assert store.db[memory_tiers.COLLECTION].count_documents({}) == 0     # declared, so ensure made it: no rows
    _, context, _ = ContextBuilder(store).prepare(event('e-off-2'), 'P1')
    assert 'things_from_program' not in context


def test_on_day_one_places_follow_the_tags_and_the_prompt_is_as_before(store, monkeypatch):
    from asuna.block_guide import guide
    owner(store)
    before = render_system(store, 'P1')[0][:-len(guide(store.config))]       # her persona and voice as rendered
    monkeypatch.setattr(memory_tiers, 'ENABLED', True)
    tiers = Tiers(store, 'P1')
    tiers.sync()
    sections = DocumentStore(store, 'P1').read('persona')[1]['sections']
    rows = {row['sid']: row for row in tiers.items(doc='persona')}
    assert {s['sid']: memory_tiers.FROM_INJECT[s['inject']] for s in sections} == {k: r['place'] for k, r in rows.items()}
    assert all(r['fact'] and r['store'] == 'persona' for r in rows.values())
    assert render_system(store, 'P1')[0][:-len(guide(store.config))] == before, \
        'nothing lapses on the day the switch goes on (only the told text is added, test_memory_tiers_told.py)'
    assert tiers.tick() == []


def test_a_carried_item_lapses_when_its_stay_runs_out_and_leaves_the_prompt(store, tiers_on):
    owner(store)
    tiers = Tiers(store, 'P1')
    tiers.sync()
    row = next(r for r in tiers.items(doc='persona') if r['place'] == CARRIED)
    body = next(s['body'] for s in DocumentStore(store, 'P1').read('persona')[1]['sections'] if s['sid'] == row['sid'])
    assert body in render_system(store, 'P1')[0]
    tiers.store.db['memory_tiers'].update_one({'_id': row['_id']}, {'$set': {'memorable_at': ago(row['stay_days'] + 1)}})
    [move] = tiers.tick()
    assert (move['from'], move['to'], move['reason']) == (CARRIED, AT_HAND, 'stay')
    assert tiers.item('persona', row['sid'])['place'] == AT_HAND
    assert body not in render_system(store, 'P1')[0], 'at hand is not carried'
    assert store.db.audit_events.find_one({'type': 'memory.moved', 'payload.item': row['_id']})
    assert DocumentStore(store, 'P1').read('persona')[1]['sections'], 'her text is untouched'


def test_a_memorable_moment_starts_the_stay_again_and_doubles_it_once_per_stay(store, tiers_on):
    owner(store)
    tiers = Tiers(store, 'P1')
    tiers.sync()
    row = tiers.items(doc='persona')[0]
    tiers.store.db['memory_tiers'].update_one({'_id': row['_id']}, {'$set': {'memorable_at': ago(10)}})
    tiers.used([('persona', row['sid'])], 'recalled', 'dm-a')
    tiers.used([('persona', row['sid'])], 'cited', 'dm-a')
    after = tiers.item('persona', row['sid'])
    assert after['stay_days'] == min(56, 2 * row['stay_days']) and after['uses'] == 2 and after['recalled_in'] == ['dm-a']
    assert (datetime.now(timezone.utc) - datetime.fromisoformat(after['memorable_at'])).total_seconds() < 60


def test_on_the_switch_on_day_first_stays_spread_over_two_weeks_and_later_items_take_the_usual_stay(store, tiers_on):
    """After the dry run (owner 2026-10-13): her 16 carried persona sections all lapsed on day 14; first stays on the
    switch-on day are spread per item from 14 to 28 days, deterministically."""
    owner(store)
    docs, tiers = DocumentStore(store, 'P1'), Tiers(store, 'P1')
    for n in range(12):
        write(docs, 'persona', {'op': 'append_section', 'heading': '一节 %d' % n}, '第 %d 节' % n)
    tiers.sync()
    stays = [row['stay_days'] for row in tiers.items(doc='persona')]
    assert all(14 <= days <= 28 for days in stays) and len(set(stays)) > 3, stays
    again = Tiers(store, 'P1')
    again.store.db['memory_tiers'].delete_many({'row': 'item'})
    again.sync()
    assert [row['stay_days'] for row in again.items(doc='persona')] == stays, 'the same spread every time'
    before, after = write(docs, 'persona', {'op': 'append_section', 'heading': '后来写的'}, '后来写的一节')
    tiers.written('persona', {'op': 'append_section'}, before, after)
    assert tiers.item('persona', after['sections'][-1]['sid'])['stay_days'] == 14, 'later: the usual first stay'


def test_a_second_conversation_surfacing_an_item_is_memorable_one_echoing_itself_is_not(store, tiers_on):
    owner(store)
    tiers = Tiers(store, 'P1')
    tiers.sync()
    row = tiers.items(doc='persona')[0]
    tiers.surfaced([('persona', row['sid'])], 'dm-a')
    tiers.surfaced([('persona', row['sid'])], 'dm-a')
    assert tiers.item('persona', row['sid'])['uses'] == 0
    tiers.surfaced([('persona', row['sid'])], 'g1')
    assert tiers.item('persona', row['sid'])['uses'] == 1


def test_a_new_item_starts_carried_and_over_the_cap_she_is_shown_the_carried_list_before_anything_lapses(store, tiers_on):
    from asuna import visibility
    owner(store)
    docs, tiers = DocumentStore(store, 'P1'), Tiers(store, 'P1')
    tiers.sync()
    oldest = None
    for n in range(memory_tiers.CAPS['persona'] + 1):
        before, after = write(docs, 'persona', {'op': 'append_section', 'heading': '新的 %d' % n}, '一条新的事 %d' % n)
        moves = tiers.written('persona', {'op': 'append_section'}, before, after, scene_id='dm-a')
        if n == 0:
            oldest = after['sections'][-1]['sid']
            tiers.store.db['memory_tiers'].update_one({'_id': memory_tiers.item_id('P1', 'persona', oldest)},
                                  {'$set': {'memorable_at': ago(3)}})
    newest = after['sections'][-1]['sid']
    assert tiers.item('persona', newest)['place'] == CARRIED
    assert len(tiers.items(doc='persona', place=CARRIED)) == memory_tiers.CAPS['persona'] + 1, 'one over, for her'
    # Her next turn that reads it lists what is carried, with days unused, and names the default.
    block = tiers.things(visibility.OWNER_PRIVATE, {'_id': 'dm-a'}, {'tz': ZoneInfo('UTC')})
    [line] = block['over']
    cap = memory_tiers.CAPS['persona']
    assert line.startswith('随身满了（人设 %d/%d）：随身的有 「' % (cap + 1, cap)) and '天没用到；' in line
    default = line.rsplit('放最久没用到的「', 1)[1].rstrip('」。')
    [named] = [row for row in tiers.items(doc='persona') if row.get('heading') == default]
    # She did not choose: the turn after, the named one lapses by the program's rule, and is told as before.
    block = tiers.things(visibility.OWNER_PRIVATE, {'_id': 'dm-b'}, {'tz': ZoneInfo('UTC')})
    assert 'over' not in block
    assert tiers.item('persona', named['sid'])['place'] == AT_HAND
    assert len(tiers.items(doc='persona', place=CARRIED)) == cap


def test_when_she_lets_one_go_over_the_cap_nothing_else_lapses(store, tiers_on):
    from asuna import visibility
    owner(store)
    docs, tiers = DocumentStore(store, 'P1'), Tiers(store, 'P1')
    tiers.sync()
    sids = []
    for n in range(memory_tiers.CAPS['persona'] + 1):
        before, after = write(docs, 'persona', {'op': 'append_section', 'heading': '另一条 %d' % n}, '内容 %d' % n)
        tiers.written('persona', {'op': 'append_section'}, before, after, scene_id='dm-a')
        sids.append(after['sections'][-1]['sid'])
    assert tiers.things(visibility.OWNER_PRIVATE, {'_id': 'dm-a'}, {'tz': ZoneInfo('UTC')}).get('over')
    tiers.let_go('persona', sids[5])                       # her choice
    tiers.things(visibility.OWNER_PRIVATE, {'_id': 'dm-b'}, {'tz': ZoneInfo('UTC')})
    places = {sid: tiers.item('persona', sid)['place'] for sid in sids}
    assert places[sids[5]] == AT_HAND and list(places.values()).count(CARRIED) == memory_tiers.CAPS['persona']


def test_memories_cool_by_disuse_facts_do_not_and_a_correction_supersedes(store, tiers_on):
    owner(store)
    docs, tiers = DocumentStore(store, 'P1'), Tiers(store, 'P1')
    before, after = write(docs, 'work_log', {'op': 'append_section', 'heading': '那天'}, '那天的事')
    tiers.written('work_log', {'op': 'append_section'}, before, after)
    before, after = write(docs, 'promises', {'op': 'append_section', 'heading': '答应过', 'kind': 'ledger'}, '周六带蛋糕')
    tiers.written('promises', {'op': 'append_section'}, before, after)
    journal = tiers.items(doc='work_log')[0]
    promise = tiers.items(doc='promises')[0]
    assert journal['place'] == AT_HAND and promise['place'] == CARRIED and promise['fact'] and not journal['fact']
    for row in (journal, promise):
        tiers.store.db['memory_tiers'].update_one({'_id': row['_id']}, {'$set': {'memorable_at': ago(200), 'place': AT_HAND}})
    tiers.tick()
    assert tiers.item('work_log', journal['sid'])['place'] == PUT_AWAY, 'a memory cools'
    assert tiers.item('promises', promise['sid'])['place'] == AT_HAND, 'a fact never cools by disuse'
    before, after = write(docs, 'promises', {'op': 'correction', 'sid': promise['sid']}, '改成周日')
    moves = tiers.written('promises', {'op': 'correction', 'sid': promise['sid']}, before, after)
    old = tiers.item('promises', promise['sid'])
    assert old['place'] == PUT_AWAY and old['superseded_at'] and moves[-1]['reason'] == 'superseded'


def test_a_rewrite_that_changes_an_item_brings_it_back_and_one_that_does_not_is_nothing(store, tiers_on):
    owner(store)
    docs, tiers = DocumentStore(store, 'P1'), Tiers(store, 'P1')
    tiers.sync()
    row = tiers.items(doc='persona')[0]
    tiers.store.db['memory_tiers'].update_one({'_id': row['_id']}, {'$set': {'place': AT_HAND}})
    body = next(s['body'] for s in docs.read('persona')[1]['sections'] if s['sid'] == row['sid'])
    before, after = write(docs, 'persona', {'op': 'replace_section', 'sid': row['sid']}, body, 'same')
    assert tiers.written('persona', {'op': 'replace_section', 'sid': row['sid']}, before, after) == []
    before, after = write(docs, 'persona', {'op': 'replace_section', 'sid': row['sid']}, body + '（改过）', 'changed')
    [move] = tiers.written('persona', {'op': 'replace_section', 'sid': row['sid']}, before, after)
    assert (move['to'], move['reason']) == (CARRIED, 'rewritten')


def test_let_go_in_her_turn_and_where_things_are_told_once_per_conversation(store, tiers_on):
    owner(store)
    tiers = Tiers(store, 'P1')
    tiers.sync()
    row = next(r for r in tiers.items(doc='persona') if r['place'] == CARRIED and r['visibility'] == 'public')
    lane = FakeLane(store, [FakeTurn([THINK, ('write_document', {'doc': 'persona', 'do': 'let_go', 'section': row['sid'],
                                                                 'why': '用不着天天带着'})], '好。'),
                            FakeTurn([THINK], '嗯。'), FakeTurn([THINK], '嗯。')])
    coordinator = Coordinator(store, lane)
    ep = coordinator.ingest(event('e-let'))
    assert ep['state'] == 'COMMITTED', ep.get('failure')
    assert tiers.item('persona', row['sid'])['place'] == AT_HAND
    second = coordinator.ingest(event('e-after'))['context']['things_from_program']
    assert any('你放手了' in line for line in second['moved']) and '人设' in second['places']
    # 随身 says the room left under the cap, counted as the cap is: every carried item, readable here or not.
    left = memory_tiers.CAPS['persona'] - len(tiers._carried(None, 'persona'))
    assert second['places']['人设'].startswith('随身 ' + memory_tiers.words(memory_tiers.ROOM_WORDS, max(0, left)) + '、')
    assert [memory_tiers.words(memory_tiers.ROOM_WORDS, n) for n in (0, 1, 3, 9, 10)] == [
        '满了', '还能放一条', '还能放两三条', '还能放好几条', '还空着很多']
    third = coordinator.ingest(event('e-later'))['context']['things_from_program']
    assert 'moved' not in third, 'told once in a conversation'
    assert third['self_items'] == memory_tiers.SELF_OFFER, 'offered until she writes herself as items'


def test_a_tag_lets_an_item_go_down_but_never_carries_it_back_up(store, tiers_on):
    """No pin (owner 2026-10-13): inject always on an item at hand changes nothing of its place, and says how one
    comes back; on_demand on a carried one is letting it go."""
    owner(store)
    tiers = Tiers(store, 'P1')
    tiers.sync()
    up = next(r for r in tiers.items(doc='persona') if r['place'] == CARRIED and r['visibility'] == 'public')
    down = next(r for r in tiers.items(doc='persona') if r['place'] == CARRIED and r['_id'] != up['_id'])
    tiers.store.db['memory_tiers'].update_one({'_id': up['_id']}, {'$set': {'place': AT_HAND}})
    pin = {'doc': 'persona', 'do': 'set_tags', 'section': up['sid'], 'when_shown': 'always', 'why': '想一直带着'}
    tuck = {'doc': 'persona', 'do': 'set_tags', 'section': down['sid'], 'when_shown': 'on_demand', 'why': '收起来'}
    lane = FakeLane(store, [FakeTurn([THINK, ('write_document', pin), ('write_document', tuck)], '好。')])
    ep = Coordinator(store, lane).ingest(event('e-pin'))
    assert tiers.item('persona', up['sid'])['place'] == AT_HAND, 'a tag is not a way up'
    assert tiers.item('persona', down['sid'])['place'] == AT_HAND, 'a tag down is letting go'
    pinned = next(call for call in ep['tool_calls'].values() if call['tool'] == 'write_document')
    # The tag that cannot carry it back is not written either, so the document never says always while it is at hand.
    assert pinned['result']['note'] == 'when_shown 没改。' + memory_tiers.NOT_BACK % AT_HAND
    assert 'revision_id' not in pinned['result']


def test_her_numbers_and_words(store, tiers_on):
    """Her answers (2026-10-13): persona carries 18, a group's notes 10; her voice is a memory; 7 to 14 days ago is
    前阵子."""
    from datetime import datetime, timedelta, timezone
    assert (memory_tiers.CAPS['persona'], memory_tiers.CAPS['group_notes'], memory_tiers.CAPS['self']) == (18, 10, 12)
    assert 'voice' in memory_tiers.MEMORIES and 'voice' not in memory_tiers.FACTS
    moment = datetime.now(timezone.utc)
    assert memory_tiers.age_word((moment - timedelta(days=10)).isoformat(), moment) == '前阵子'
    owner(store)
    tiers = Tiers(store, 'P1')
    tiers.sync()
    assert all(row['nature'] == '记忆' for row in tiers.items(doc='voice'))


def test_an_item_is_a_fact_or_a_memory_by_what_she_says_not_by_its_store(store, tiers_on):
    """Her answer (2026-10-13): her persona holds her own judgments (memories), her self holds checked facts."""
    owner(store)
    docs, tiers = DocumentStore(store, 'P1'), Tiers(store, 'P1')
    judgment = {'op': 'append_section', 'heading': '先不放开', 'from': '我自己的judgment'.replace('judgment', '判断')}
    before, after = write(docs, 'persona', judgment, '这个群先不放开')
    tiers.written('persona', judgment, before, after)
    checked = {'op': 'append_section', 'heading': '沙箱里', 'from': '查过的'}
    before, after = write(docs, 'self', checked, '沙箱里不用 tempfile：查过，建出来的目录自己读不了')
    tiers.written('self', checked, before, after)
    mine = tiers.item('persona', after and docs.read('persona')[1]['sections'][-1]['sid'])
    fact = tiers.items(doc='self')[0]
    assert (mine['nature'], mine['from'], mine['fact']) == ('记忆', '我自己的判断', False)
    assert (fact['nature'], fact['from'], fact['fact']) == ('事实', '查过的', True)
    for row in (mine, fact):
        tiers.store.db['memory_tiers'].update_one({'_id': row['_id']}, {'$set': {'memorable_at': ago(400), 'place': AT_HAND}})
    tiers.tick()
    assert tiers.item('persona', mine['sid'])['place'] == PUT_AWAY, 'her judgment follows the cycle'
    assert tiers.item('self', fact['sid'])['place'] == AT_HAND, 'a checked fact does not fade'


def test_saying_what_an_item_is_writes_no_new_revision_and_update_self_writes_items(store, tiers_on):
    owner(store)
    first = {'doc': 'self', 'do': 'append_section', 'heading': '做饭', 'why': '拆', 'content': '最近在学做饭'}
    sid = '做饭'
    tag = {'doc': 'self', 'do': 'set_tags', 'section': sid, 'nature': '事实', 'why': '这是事实'}
    old_name = {'target': 'current_self', 'content': '- 早上跑步\n跑了一周了', 'why': '新的'}
    lane = FakeLane(store, [FakeTurn([THINK, ('write_document', first)], '好。'),
                            FakeTurn([THINK, ('write_document', tag)], '嗯。'),
                            FakeTurn([THINK, ('update_self', old_name)], '嗯。')])
    coordinator = Coordinator(store, lane)
    coordinator.ingest(event('e-1'))
    docs = DocumentStore(store, 'P1')
    revision = docs.read('self')[0]
    coordinator.ingest(event('e-2'))
    assert docs.read('self')[0] == revision and Tiers(store, 'P1').item('self', sid)['nature'] == '事实'
    ep = coordinator.ingest(event('e-3'))
    sections = docs.read('self')[1]['sections']
    assert [s['heading'] for s in sections] == ['做饭', '早上跑步'], ep['tool_calls']
    assert Tiers(store, 'P1').item('self', sections[-1]['sid'])['place'] == CARRIED


def test_her_self_as_items_is_what_she_reads_of_herself(store, tiers_on):
    owner(store)
    entry = {'doc': 'self', 'do': 'append_section', 'heading': '最近', 'why': '拆成一条一条', 'content': '最近在学做饭'}
    lane = FakeLane(store, [FakeTurn([THINK, ('write_document', entry)], '好。'), FakeTurn([THINK], '嗯。')])
    coordinator = Coordinator(store, lane)
    coordinator.ingest(event('e-self'))
    content = DocumentStore(store, 'P1').read('self')[1]
    assert content['kind'] == 'self' and content['sections'][0]['visibility'] == 'public'
    context = coordinator.ingest(event('e-self-2'))['context']
    [item] = context['self_state_from_program']['current_self']['items']
    assert item['body'] == '最近在学做饭' and item['ref'].startswith('doc:self#')
    assert 'self_items' not in context['things_from_program']


def test_let_go_finds_a_section_by_its_heading_and_an_unknown_one_lists_the_ids(store, tiers_on):
    """Her finding 10-18: let_go refused a section by name without listing what there is."""
    owner(store)
    tiers = Tiers(store, 'P1')
    tiers.sync()
    headings = {s['sid']: s['heading'] for s in DocumentStore(store, 'P1').read('persona')[1]['sections']}
    row = next(r for r in tiers.items(doc='persona') if r['place'] == CARRIED and r['visibility'] == 'public'
               and headings.get(r['sid']))
    heading = '「' + headings[row['sid']] + '」'           # her remembered spelling, with other punctuation
    lane = FakeLane(store, [FakeTurn([THINK, ('write_document', {'doc': 'persona', 'do': 'let_go', 'section': '没有这一节的名字',
                                                                 'why': '试'}),
                                      ('write_document', {'doc': 'persona', 'do': 'let_go', 'section': heading,
                                                          'why': '用不着天天带着'})], '好。')])
    ep = Coordinator(store, lane).ingest(event('e-named'))
    assert ep['state'] == 'COMMITTED', ep.get('failure')
    refused, done = [r for r in lane.tool_results if r[2] == 'write_document']
    assert '照抄一个' in str(refused) and row['sid'] in str(refused), refused
    assert tiers.item('persona', row['sid'])['place'] == AT_HAND, done
