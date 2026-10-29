"""ADR-062 phase 2, delivery and recall: her own items at hand come up by themselves in two of six memory slots, above
an absolute floor, never one she already carries; recall says where it searched and what else exists there."""
import json

import pytest

from asuna import memory_pilot, memory_tiers
from asuna.context import ContextBuilder
from asuna.coordinator import Coordinator
from asuna.documents import DocumentStore
from asuna.lanes import FakeLane, FakeTurn
from asuna.memory_tiers import AT_HAND, CARRIED, PUT_AWAY, Tiers
from asuna.render import render_system
from test_adr009_p2 import owner, THINK
from test_engineering_m1 import event
from test_memory_pilot import Route


class Retrieval:
    """No memories of her conversations; the query's vector as the memory route would give it."""
    def __init__(self, memories=()):
        self.memories, self.route = list(memories), Route()

    def search(self, scope, epoch, query, **kwargs):
        found = [] if query == '天气' else [dict(m) for m in self.memories]       # nothing she said is about it
        return found, {'path': 'stub', 'coverage': 'sufficient'}

    def query_vector(self, query):
        return None

    def own_thoughts(self, scopes, query, limit=3):
        return []

    def embed(self, texts, purpose):
        return self.route.embed(texts, purpose)


def write(docs, slug, heading, body, visibility='public'):
    docs.apply(slug, {'op': 'append_section', 'heading': heading, 'reason': 'r', 'visibility': visibility}, body,
               base_revision_id=docs.read(slug)[0], author='character', mutation_id=slug + heading)
    return docs.read(slug)[1]['sections'][-1]['sid']


@pytest.fixture
def setup(store, monkeypatch):
    monkeypatch.setattr(memory_tiers, 'ENABLED', True)
    owner(store)
    docs = DocumentStore(store, 'P1')
    sids = {'baking': write(docs, 'persona', '周六', '周六早上烤松饼，这件事我一直在做'),
            'recipe': write(docs, 'persona', '配方', '松饼配方我记在心里，周六照着做'),
            'mountain': write(docs, 'persona', '山', '秋天去登山，看红叶'),
            'stars': write(docs, 'persona', '星星', '晚上看星星认猎户座')}
    tiers = Tiers(store, 'P1')
    tiers.sync()
    for key in ('baking', 'stars'):
        row = tiers.item('persona', sids[key])
        tiers.store.db['memory_tiers'].update_one({'_id': row['_id']}, {'$set': {'place': AT_HAND}})
    tiers.store.db['memory_tiers'].update_one({'_id': tiers.item('persona', sids['mountain'])['_id']}, {'$set': {'place': PUT_AWAY}})
    pilot = memory_pilot.Pilot(store, 'P1', Route())
    pilot.sync()
    builder = ContextBuilder(store, Retrieval([{'_id': 'chunk-%d' % n, 'body_markdown': '聊过的事 %d' % n,
                                               'kind': 'chat_chunk'} for n in range(6)]))
    builder.pilot = pilot
    return store, builder, sids, tiers


def test_an_item_at_hand_comes_up_in_two_of_six_slots_and_a_carried_one_never(setup):
    store, builder, sids, tiers = setup
    _, context, _ = builder.prepare(event('e-1', text='松饼'), 'P1')
    own = [m for m in context['memories'] if m.get('kind') == 'own_item']
    assert [m['_id'] for m in own] == ['doc:persona#' + sids['baking']], 'the carried recipe is in front of her already'
    [item] = own
    assert (item['store'], item['place'], item['age']) == ('人设', '手边', '事实')
    assert len(context['memories']) == 6, 'her items take slots from the six, never add to them'
    assert item['body_markdown'] not in render_system(store, 'P1')[0]
    _, quiet, _ = builder.prepare(event('e-2', text='天气'), 'P1')
    assert not [m for m in quiet['memories'] if m.get('kind') == 'own_item'], 'nothing under the floor'
    _, away, _ = builder.prepare(event('e-3', text='登山'), 'P1')
    assert not [m for m in away['memories'] if m.get('kind') == 'own_item'], 'put away comes back by recall only'


def test_with_the_pilot_switched_off_her_items_still_come_up_and_nothing_is_logged(setup, monkeypatch):
    """A measurement switch never turns off a live feature: tiered memory keeps its item index."""
    store, builder, sids, tiers = setup
    monkeypatch.setattr(memory_pilot, 'SHADOW_PILOT', False)
    fresh = ContextBuilder(store, builder.retrieval)
    index = memory_pilot.attach(fresh, store, 'P1', Route)
    try:
        assert index is not None and not index.logging
        index.run_job({'query': '松饼', 'vector': None, 'scope': 'scene:dm-a', 'private_scope': None, 'scene_id': 'dm-a',
                       'scene_kind': 'dm', 'session_class': 'owner_private', 'turn_kind': 'external', 'event_id': 'e',
                       'recall': False, 'at': '2026-10-14T01:00:00+00:00', 'previous_submit_ms': None})
        _, context, _ = fresh.prepare(event('e-off', text='松饼'), 'P1')
    finally:
        index.close()
    assert [m['_id'] for m in context['memories'] if m.get('kind') == 'own_item'] == ['doc:persona#' + sids['baking']]
    assert not store.db[memory_pilot.COLLECTION].find_one({'row': {'$in': ['turn', 'recall']}}), 'no shadow logging'
    monkeypatch.setattr(memory_tiers, 'ENABLED', False)
    assert memory_pilot.attach(ContextBuilder(store, builder.retrieval), store, 'P1', Route) is None


def test_a_carried_item_the_turn_would_have_brought_up_is_used_there_and_memorable_from_a_second(setup):
    """The day-14 root fix: a carried item is never brought up, so the turn that would have brought it up above the
    floor counts as its use in that conversation."""
    store, builder, sids, tiers = setup
    _, context, _ = builder.prepare(event('e-1', text='松饼'), 'P1')
    recipe = tiers.item('persona', sids['recipe'])
    assert recipe['place'] == CARRIED and recipe['surfaced_in'] == ['dm-a']
    assert 'doc:persona#' + sids['recipe'] not in [m['_id'] for m in context['memories']], 'still not sent twice'
    builder.prepare(event('e-2', scene='dm-b', person='B', text='松饼'), 'P1')
    assert tiers.item('persona', sids['recipe'])['uses'] == 1, 'a second conversation: memorable'
    builder.prepare(event('e-3', text='天气'), 'P1')
    assert tiers.item('persona', sids['recipe'])['surfaced_in'] == ['dm-a', 'dm-b'], 'nothing under the floor'


def test_an_item_brought_up_in_a_second_conversation_is_memorable(setup):
    store, builder, sids, tiers = setup
    builder.prepare(event('e-1', text='松饼'), 'P1')
    assert tiers.item('persona', sids['baking'])['uses'] == 0
    builder.prepare(event('e-2', scene='dm-b', person='B', text='松饼'), 'P1')
    row = tiers.item('persona', sids['baking'])
    assert set(row['surfaced_in']) == {'dm-a', 'dm-b'} and row['uses'] == 1


def recall_turn(store, builder, args):
    lane = FakeLane(store, [FakeTurn([THINK, ('recall', args)], '好。')])
    ep = Coordinator(store, lane, context=builder).ingest(event('e-recall-' + args['query']))
    return next(call['result'] for call in ep['tool_calls'].values() if call['tool'] == 'recall')


def test_a_recall_says_where_it_searched_and_reaches_what_is_put_away(setup):
    store, builder, sids, tiers = setup
    found = recall_turn(store, builder, {'query': '登山'})
    assert found['searched'] == memory_tiers.SEARCHED and 'found' not in found
    assert [m['_id'] for m in found['memories'] if m.get('kind') == 'own_item'] == ['doc:persona#' + sids['mountain']]
    assert tiers.item('persona', sids['mountain'])['uses'] == 1, 'a recall that returns an item is a use'
    words = recall_turn(store, builder, {'query': '红叶'})
    assert not [m for m in words['memories'] if m.get('kind') == 'own_item'], 'the question is not about it'
    assert 'headings' not in words, 'a word of its body is not a key (ADR-097): headings list by keys only'


def test_an_empty_recall_says_all_three_places_and_a_doc_without_sid_lists_its_headings(setup):
    store, builder, sids, tiers = setup
    empty = recall_turn(store, builder, {'query': '天气'})
    assert empty['found'] == memory_tiers.NOTHING
    listed = recall_turn(store, builder, {'query': '人设有什么', 'sections': [{'doc': 'persona'}]})
    [doc] = listed['documents']
    places = {h['sid']: h['place'] for h in doc['headings']}
    assert places[sids['mountain']] == PUT_AWAY and places[sids['recipe']] == CARRIED


def test_a_long_documents_headings_are_listed_latest_first_within_bounds(setup):
    """B15: a log of hundreds of sections listed whole spilled past what a tool result carries inline. The listing keeps
    the latest headings that fit, after one entry naming how many earlier ones there are and how to reach them."""
    store, builder, sids, tiers = setup
    docs = DocumentStore(store, 'P1')
    for n in range(500):
        write(docs, 'work_log', '第 %03d 天：照着清单把那一批事情做完了，记一笔' % n, '做完了。')
    listed = recall_turn(store, builder, {'query': '记了什么', 'sections': [{'doc': 'work_log'}]})
    [doc] = listed['documents']
    first, rest = doc['headings'][0], doc['headings'][1:]
    assert first == {'earlier': memory_tiers.EARLIER_HEADINGS % (500 - len(rest), 500)}
    assert rest[-1]['heading'].startswith('第 499 天') and rest[0]['heading'].startswith('第 %03d 天' % (500 - len(rest)))
    assert len(json.dumps(rest, ensure_ascii=False)) <= memory_tiers.LISTED_HEADINGS_CHARS
    short = recall_turn(store, builder, {'query': '人设有什么', 'sections': [{'doc': 'persona'}]})
    assert all('earlier' not in h for h in short['documents'][0]['headings']), 'a short one is listed whole'


def test_a_turn_with_tiers_on_sends_nothing_twice(setup):
    """The ADR-062 profile's check on a synthetic turn: no text of 60 characters or more in two blocks, and nothing
    carried in the system prompt surfaced again among memories."""
    store, builder, sids, tiers = setup
    _, context, _ = builder.prepare(event('e-1', text='松饼'), 'P1')
    system = render_system(store, 'P1')[0]
    seen = {}

    def leaves(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for inner in value.values():
                yield from leaves(inner)
        elif isinstance(value, list):
            for inner in value:
                yield from leaves(inner)
    for key, value in context.items():
        for text in leaves(value):
            if len(text) >= 60:
                seen.setdefault(text, set()).add(key)
    assert not {text: keys for text, keys in seen.items() if len(keys) > 1}
    for memory in context['memories']:
        assert memory.get('kind') != 'own_item' or memory['body_markdown'] not in system
    assert json.dumps(context, ensure_ascii=False).count('周六早上烤松饼') == 1
