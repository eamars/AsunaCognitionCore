"""ADR-062 phase 1, the shadow pilot: her own items are indexed apart from the memories her turns read, and each turn
writes which of them it would have surfaced (ids, scores, the turn's kind and conversation), off the reply path."""
import time

import pytest

from asuna import memory_pilot, visibility
from asuna.context import ContextBuilder
from asuna.documents import DocumentStore
from asuna.group_admin import notes_slug
from asuna.self_state import SelfState

TOPICS = ('松饼', '登山', '星星')


def vector(text, purpose):
    """One direction per topic: items on one topic score 1.0 against it, 0.5 against the others and the rest."""
    rest = 0.0 if any(t in text for t in TOPICS) else 1.0
    return [1.0 if topic in text else 0.0 for topic in TOPICS] + ([rest, 0.0] if purpose == 'document' else [0.0, rest])


class Route:
    revision = 'fake-route'

    def __init__(self):
        self.calls = []

    def embed(self, texts, purpose):
        self.calls.append(purpose)
        return [vector(text, purpose) for text in texts]


def write(docs, slug, heading, body, visibility='public', mutation=None):
    docs.apply(slug, {'op': 'append_section', 'heading': heading, 'reason': 'r', 'visibility': visibility}, body,
               base_revision_id=docs.read(slug)[0], author='character', mutation_id=mutation or slug + heading)


@pytest.fixture
def items(store):
    docs = DocumentStore(store, 'P1')
    write(docs, 'persona', '周六', '周六早上烤松饼，这件事我一直在做')
    write(docs, 'persona', '周六配方', '松饼配方我记在心里，周六照着做', mutation='p2')
    write(docs, 'persona', '家里的事', '主人说松饼别放太多糖', visibility='owner_private')
    write(docs, 'persona', '山', '秋天去登山，看红叶')
    write(docs, 'work_log', '今天', '今天又看了一晚星星')
    write(docs, notes_slug('g1'), '这个群', '这个群里大家都爱聊登山')
    SelfState(store).commit({'_id': 'ep-self', 'persona': 'P1', 'monologue_refs': [],
                             'manifest': {'session_class': visibility.OWNER_PRIVATE}}, 'current_self',
                            '- 最近我在学着把天上星星的名字一颗一颗记下来，已经记住了猎户座和北斗\n短行不算')
    return store


def turn(pilot, query, scene, *, kind='external', home=False, recall=False):
    found = pilot.store.db.scenes.find_one({'_id': scene})
    return pilot.run_job({'query': query, 'vector': None, 'scope': found['scope_key'],
                          'private_scope': visibility.owner_private_scope('P1') if home else None,
                          'scene_id': scene, 'scene_kind': found['kind'], 'session_class': 'owner_private' if home else 'public',
                          'turn_kind': kind, 'event_id': 'e-1', 'recall': recall, 'at': '2026-10-14T01:00:00+00:00',
                          'previous_submit_ms': 0.01})


def test_her_items_are_indexed_apart_from_the_memories_she_reads(items):
    memories = items.db.memory_units.count_documents({})
    route = Route()
    pilot = memory_pilot.Pilot(items, 'P1', route)
    pilot.sync()
    rows = list(items.db[memory_pilot.COLLECTION].find({'row': 'item'}))
    assert {row['store'] for row in rows} == {'persona', 'self', 'journal', 'group_notes'}
    scopes = {(row['store'], row['scope_key']) for row in rows}
    assert ('persona', visibility.owner_private_scope('P1')) in scopes and ('persona', 'global-safe') in scopes
    assert ('group_notes', 'scene:g1') in scopes and ('self', 'global-safe') in scopes
    assert sum(row['store'] == 'self' for row in rows) == 1, 'current_self as split today: its list lines'
    assert items.db.memory_units.count_documents({}) == memories, 'the index her turns read is untouched'
    assert set(route.calls) == {'document'}
    route.calls.clear()
    pilot.sync()
    assert route.calls == [], 'an unchanged item is not embedded again'


def test_a_turn_records_what_it_would_surface_and_nothing_else(items):
    pilot = memory_pilot.Pilot(items, 'P1', Route())
    row = turn(pilot, '松饼', 'dm-a')
    surfaced = [hit['item'] for hit in row['surfaced']]
    assert len(surfaced) == 2 and all(hit['score'] >= memory_pilot.FLOOR for hit in row['surfaced'])
    assert {hit['store'] for hit in row['surfaced']} == {'persona'}
    private = {r['_id'] for r in items.db[memory_pilot.COLLECTION].find({'scope_key': visibility.owner_private_scope('P1')})}
    assert not private & {hit['item'] for hit in row['top']}, 'an owner-private item is not readable in a public turn'
    assert (row['turn_kind'], row['scene_id'], row['scene_kind']) == ('external', 'dm-a', 'dm')
    assert '松饼' not in str(row) and 'query' not in row, 'ids and scores only, never her text or the query'
    assert turn(pilot, '天气', 'dm-a')['surfaced'] == [], 'nothing under the floor'
    group = turn(pilot, '登山', 'g1')
    assert {hit['store'] for hit in group['top']} == {'persona', 'group_notes'}, "a group's notes in that group"
    assert 'group_notes' not in {hit['store'] for hit in turn(pilot, '登山', 'g2')['top']}
    home = turn(pilot, '松饼', 'dm-a', home=True)
    assert private & {hit['item'] for hit in home['top']}
    # Which conversation surfaced what: the same item from two conversations is marked with both.
    turn(pilot, '松饼', 'dm-b')
    marked = items.db[memory_pilot.COLLECTION].find_one({'_id': surfaced[0]})
    assert set(marked['surfaced_in']) == {'dm-a', 'dm-b'}


def test_a_recall_is_its_own_row_and_marks_no_conversation(items):
    pilot = memory_pilot.Pilot(items, 'P1', Route())
    row = turn(pilot, '星星', 'dm-a', recall=True, kind='presence')
    assert row['row'] == 'recall' and row['turn_kind'] == 'presence' and row['surfaced']
    assert not items.db[memory_pilot.COLLECTION].find_one({'surfaced_in': {'$exists': True}})


def test_near_duplicates_are_paired_within_a_store_only(items):
    pilot = memory_pilot.Pilot(items, 'P1', Route())
    pilot.sync()
    pairs = list(items.db[memory_pilot.COLLECTION].find({'row': 'pair'}))
    stores = {row['_id']: row['store'] for row in items.db[memory_pilot.COLLECTION].find({'row': 'item'})}
    assert pairs and all(stores[a] == stores[b] == row['store'] for row in pairs for a, b in [row['items']])
    assert not any(row['store'] in ('self', 'journal') for row in pairs), 'stars in the journal and in self are two stores'


def test_the_report_counts_by_day_and_kind_and_finds_the_floor(items):
    pilot = memory_pilot.Pilot(items, 'P1', Route())
    turn(pilot, '松饼', 'dm-a')
    turn(pilot, '松饼', 'dm-b')
    turn(pilot, '天气', 'dm-a', kind='presence')
    turn(pilot, '星星', 'dm-a', recall=True)
    out = memory_pilot.report(items, 'Etc/GMT-8')
    assert out['days'] == {'2026-10-14': {'turns': {'external': 2, 'presence': 1}, 'surfaced': {'external': 4, 'presence': 0},
                                          'turns_with_any': {'external': 2, 'presence': 0}}}
    assert out['floor_that_fits'] is None, 'two own items in two of three turns is over one a turn at every floor'
    assert out['surfaced_in_two_or_more_conversations'] == {'persona': 2}
    assert out['near_duplicate_pairs']['0.97']['persona'] >= 1 and out['recall']['recalls'] == 1
    assert out['cost']['rows'] == 4 and out['cost']['reply_path_ms_median'] == 0.01
    for _ in range(4):
        turn(pilot, '天气', 'dm-a')
    assert memory_pilot.report(items, 'UTC')['floor_that_fits'] == 0.8


def test_the_reply_path_only_queues_and_its_context_does_not_change(items):
    class Search:
        def search(self, *args, **kwargs):
            return [], {'path': 'stub', 'coverage': 'insufficient'}

        def query_vector(self, query):
            return None
    event = {'event_id': 'e-1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '松饼'}
    builder = ContextBuilder(items, Search())
    builder.prepare(event, 'P1')                       # the first turn gives the person a label
    _, without, _ = builder.prepare(event, 'P1')
    pilot = memory_pilot.attach(builder, items, 'P1', Route)
    try:
        _, with_pilot, _ = builder.prepare(event, 'P1')
        deadline = time.monotonic() + 10
        while not items.db[memory_pilot.COLLECTION].find_one({'row': 'turn'}) and time.monotonic() < deadline:
            time.sleep(.05)
    finally:
        pilot.close()
    assert items.db[memory_pilot.COLLECTION].find_one({'row': 'turn'})['scene_id'] == 'dm-a'
    assert without == with_pilot, 'nothing of the pilot reaches the turn'


def test_the_turns_query_vector_is_reused_not_embedded_again(store, tmp_path, monkeypatch):
    from asuna.evidence import Evidence
    from asuna.retrieval import Retrieval
    retrieval = Retrieval(store, Evidence(tmp_path / 'evidence'))
    try:
        monkeypatch.setattr(retrieval, 'embed', lambda texts, purpose: [[0.5] * 768 for _ in texts])
        scene = store.db.scenes.find_one({'_id': 'dm-a'})
        retrieval.search(scene['scope_key'], scene['policy_epoch'], '松饼')
        assert retrieval.query_vector('松饼') == [0.5] * 768 and retrieval.query_vector('别的') is None
    finally:
        retrieval.close()


def test_the_switch_off_starts_no_pilot(items, monkeypatch):
    builder = ContextBuilder(items, object())
    monkeypatch.setattr(memory_pilot, 'SHADOW_PILOT', False)
    assert memory_pilot.attach(builder, items, 'P1', Route) is None and builder.pilot is None
    assert memory_pilot.attach(ContextBuilder(items), items, 'P1', Route) is None, 'no retrieval, nothing to measure'
