"""ADR-062 phase 2, state and moves: her items' places, kept up by memorable moments and moved down by the program,
behind memory_tiers.ENABLED (off by default: nothing is read or written)."""
from datetime import datetime, timedelta, timezone

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


def test_with_the_switch_off_nothing_is_kept_and_her_turn_has_no_things_block(store):
    owner(store)
    Coordinator(store, FakeLane(store, [FakeTurn([THINK], '在呢。')])).ingest(event('e-off'))
    assert memory_tiers.COLLECTION not in store.db.list_collection_names()
    _, context, _ = ContextBuilder(store).prepare(event('e-off-2'), 'P1')
    assert 'things_from_program' not in context


def test_on_day_one_places_follow_the_tags_and_the_prompt_is_as_before(store, monkeypatch):
    owner(store)
    before = render_system(store, 'P1')[0]
    monkeypatch.setattr(memory_tiers, 'ENABLED', True)
    tiers = Tiers(store, 'P1')
    tiers.sync()
    sections = DocumentStore(store, 'P1').read('persona')[1]['sections']
    rows = {row['sid']: row for row in tiers.items(doc='persona')}
    assert {s['sid']: memory_tiers.FROM_INJECT[s['inject']] for s in sections} == {k: r['place'] for k, r in rows.items()}
    assert all(r['fact'] and r['store'] == 'persona' for r in rows.values())
    assert render_system(store, 'P1')[0] == before, 'nothing lapses on the day the switch goes on'
    assert tiers.tick() == []


def test_a_carried_item_lapses_when_its_stay_runs_out_and_leaves_the_prompt(store, tiers_on):
    owner(store)
    tiers = Tiers(store, 'P1')
    tiers.sync()
    row = next(r for r in tiers.items(doc='persona') if r['place'] == CARRIED)
    body = next(s['body'] for s in DocumentStore(store, 'P1').read('persona')[1]['sections'] if s['sid'] == row['sid'])
    assert body in render_system(store, 'P1')[0]
    tiers.rows.update_one({'_id': row['_id']}, {'$set': {'memorable_at': ago(15)}})
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
    tiers.rows.update_one({'_id': row['_id']}, {'$set': {'memorable_at': ago(10)}})
    tiers.used([('persona', row['sid'])], 'recalled', 'dm-a')
    tiers.used([('persona', row['sid'])], 'cited', 'dm-a')
    after = tiers.item('persona', row['sid'])
    assert after['stay_days'] == 28 and after['uses'] == 2 and after['recalled_in'] == ['dm-a']
    assert (datetime.now(timezone.utc) - datetime.fromisoformat(after['memorable_at'])).total_seconds() < 60


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


def test_a_new_item_starts_carried_and_an_overflow_lapses_the_least_recently_memorable(store, tiers_on):
    owner(store)
    docs, tiers = DocumentStore(store, 'P1'), Tiers(store, 'P1')
    tiers.sync()
    oldest = None
    for n in range(memory_tiers.CAPS['persona'] + 1):
        before, after = write(docs, 'persona', {'op': 'append_section', 'heading': '新的 %d' % n}, '一条新的事 %d' % n)
        moves = tiers.written('persona', {'op': 'append_section'}, before, after, scene_id='dm-a')
        if n == 0:
            oldest = after['sections'][-1]['sid']
            tiers.rows.update_one({'_id': memory_tiers.item_id('P1', 'persona', oldest)},
                                  {'$set': {'memorable_at': ago(3)}})
    carried = tiers.items(doc='persona', place=CARRIED)
    assert len(carried) == memory_tiers.CAPS['persona']
    newest = after['sections'][-1]['sid']
    assert tiers.item('persona', newest)['place'] == CARRIED
    assert any(m['reason'] == 'overflow' for m in moves), 'the write that overflowed names what lapsed'


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
        tiers.rows.update_one({'_id': row['_id']}, {'$set': {'memorable_at': ago(200), 'place': AT_HAND}})
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
    tiers.rows.update_one({'_id': row['_id']}, {'$set': {'place': AT_HAND}})
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
    lane = FakeLane(store, [FakeTurn([THINK, ('write_document', {'doc': 'persona', 'op': 'let_go', 'sid': row['sid'],
                                                                 'reason': '用不着天天带着'})], '好。'),
                            FakeTurn([THINK], '嗯。'), FakeTurn([THINK], '嗯。')])
    coordinator = Coordinator(store, lane)
    ep = coordinator.ingest(event('e-let'))
    assert ep['state'] == 'COMMITTED', ep.get('failure')
    assert tiers.item('persona', row['sid'])['place'] == AT_HAND
    second = coordinator.ingest(event('e-after'))['context']['things_from_program']
    assert any('你放手了' in line for line in second['moved']) and '人设' in second['places']
    third = coordinator.ingest(event('e-later'))['context']['things_from_program']
    assert 'moved' not in third, 'told once in a conversation'
    assert third['self_items'] == memory_tiers.SELF_OFFER, 'offered until she writes herself as items'


def test_her_self_as_items_is_what_she_reads_of_herself(store, tiers_on):
    owner(store)
    entry = {'doc': 'self', 'op': 'append_section', 'heading': '最近', 'reason': '拆成一条一条', 'body': '最近在学做饭'}
    lane = FakeLane(store, [FakeTurn([THINK, ('write_document', entry)], '好。'), FakeTurn([THINK], '嗯。')])
    coordinator = Coordinator(store, lane)
    coordinator.ingest(event('e-self'))
    content = DocumentStore(store, 'P1').read('self')[1]
    assert content['kind'] == 'self' and content['sections'][0]['visibility'] == 'public'
    context = coordinator.ingest(event('e-self-2'))['context']
    [item] = context['self_state_from_program']['current_self']['items']
    assert item['body'] == '最近在学做饭' and item['ref'].startswith('doc:self#')
    assert 'self_items' not in context['things_from_program']
