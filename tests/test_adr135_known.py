"""ADR-135 landing 3 (D1), on the fixture world in memory with her real coordinator (test_whose's): in an outside turn
her hands move (a task, a note, a plan) only for the owner, for someone she wrote her understanding of on an earlier
day than the ask, or for an ask that is nobody's; knowing is her written understanding, never a count; someone she has
not written about is shown nothing. g1 is an outside group: F (A, written about yesterday), B (written about today in the fixture world) and N
(nothing written)."""
from datetime import timedelta

import pytest

from asuna import clock, familiarity, guard, notes, places, role_tools, understanding, whose
from asuna.records import heads as head_records
from asuna.records import plans as plan_records
from asuna.records import scenes as scene_records
from asuna.records import tasks as task_records
from asuna.role_tools import Refused
from test_whose import coordinator, home, line  # noqa: F401  (home, coordinator: fixtures)

F, B, N = 'A', 'B', 'N'


def understood(store, person, at):
    """Her understanding of `person`, first written at `at` (the person layer)."""
    key = familiarity._ids(store, person)[0]
    entity = 'relationship:%s|%s' % (key, understanding.PERSON_SCOPE)
    head_records.save_revision(store, {'_id': 'rev-' + person, 'entity_key': entity, 'mutation_id': 'm-' + person,
                                       'scope_key': understanding.PERSON_SCOPE, 'created_at': at.isoformat(),
                                       'content': {'body': '造的：一个朋友', 'short': '朋友'}, 'source_ids': [],
                                       'parent_revision_id': None}, stream='seed')
    head_records.save_head(store, {'_id': entity, 'scope_key': understanding.PERSON_SCOPE, 'revision_id': 'rev-' + person},
                           stream='seed')


def ask(store, person, key, kind='external', scene='g1'):
    """A turn of hers opened by `person`'s line in g1, as the program prepares it."""
    event, ep_id = line(store, scene, person, key, kind=kind, group_context={'wake_reason': 'mentioned_account'})
    ep = store.put('episodes', {
        '_id': ep_id, 'scene_id': scene, 'scope_key': 'scene:' + scene, 'policy_epoch': 1, 'persona': 'P1',
        'person_id': person, 'episode_kind': kind, 'state': 'TURN', 'source_event_id': key, 'monologue_refs': [],
        'context': {'action_capabilities_from_program': {'available': True},
                    'note_places_from_program': {'items': []}},
        'manifest': {'session_class': 'public', 'people_shown': {person: 1}, 'persona_revision': 1}, 'tool_calls': {}, 'turn_thought': True,
        'whose': whose.of_turn(store, None, event)}, stream=ep_id)
    ep = store.put('episodes', {**ep, 'turn_tools': role_tools.exposed(store, ep)}, expected=ep['revision'], stream=ep_id)
    return ep


def call(coordinator, ep, name, args):
    n = len((coordinator.store.collection('episodes').get(ep['_id']) or {}).get('tool_calls') or {})
    return coordinator.tools.call(ep['_id'], '%s:%d' % (ep['_id'], n), name, args)


def denied(coordinator, ep, name, args):
    with pytest.raises(Refused) as caught:
        call(coordinator, ep, name, args)
    return caught.value


HANDS = (('delegate', {'title': '查一下', 'brief': '造的：查一下天气'}),
         ('note', {'to': '家里', 'text': '造的：帮他问问'}),
         ('plan', {'do': 'create', 'intent': '造的：回头帮他看看', 'in_minutes': 30}))


@pytest.fixture
def room(coordinator):
    store = coordinator.store
    scene = scene_records.get(store, 'g1')
    scene_records.save(store, {**scene, 'members': [*scene['members'], N]}, expected=scene['revision'])
    route = store.config['channels']['fixture']['routes']['g1']
    route['members'][N] = {**route['members'][B], 'person_id': N, 'workspace': route['members'][B]['workspace'] + '-n'}
    understood(store, F, clock.now() - timedelta(days=1))
    return coordinator


def test_K1_a_person_she_has_not_written_about_gets_the_plain_sentence_for_her_hands_and_is_shown_nothing(room):
    store = room.store
    ep = ask(store, N, 'k1')
    for name, args in HANDS:
        refusal = denied(room, ep, name, args)
        assert (str(refusal), list(refusal.codes)) == (guard.NOT_DONE, ['asker_not_known']), name
    assert task_records.of_episode(store, ep['_id']).rows() == [] and notes.count_sent(store, ep['_id']) == 0
    assert plan_records.of_conversation(store, 'g1').rows() == []
    events = [row['payload'] for row in store.collection('audit_events').find({'type': 'guard.denied', 'stream_id': ep['_id']})]
    assert sorted(event['tool'] for event in events) == ['delegate', 'note', 'plan']
    assert all(event['code'] == 'asker_not_known' and event['asker'] for event in events)
    from asuna.people import People
    item, _ = understanding.entry(store, scene_records.get(store, 'g1'), N, 'P1', People(store, 'P1'))
    assert set(item) <= {'who', 'feelings_toward'} and familiarity.words(store, N, 'P1') == {}
    assert guard.check(store, room.store.collection('episodes').get(ep['_id']), 'speak',
                       {'parts': [{'kind': 'text', 'text': '造的：好'}]}) is None     # speaking is never her hands


def test_K2_writing_about_someone_today_does_not_open_her_hands_today(room):
    store = room.store
    for key in ('k2a', 'k2b'):                                 # two turns, the same day
        ep = ask(store, N, key)
        understood(store, N, clock.now()) if key == 'k2a' else None
        assert familiarity.level(store, N) == 'known'
        assert list(denied(room, ep, 'delegate', HANDS[0][1]).codes) == ['asker_not_known']
    tomorrow = clock.moment(guard.asked_at(store, ep)) + timedelta(days=1)
    assert familiarity.known_before(store, N, tomorrow)       # the next day it would pass


def test_K3_someone_she_wrote_about_on_an_earlier_day_gets_a_task_with_the_place_s_grant(room):
    store = room.store
    ep = ask(store, F, 'k3')
    result, _ = call(room, ep, 'delegate', HANDS[0][1])
    task = task_records.get(store, result['task'])
    assert task['requester_id'] == F and 'sandbox_run' not in task['allowed_capabilities'] and task['network'] == 'public'


def test_K4_many_answered_asks_do_not_make_someone_known(room):
    store = room.store
    for n in range(25):
        line(store, 'g1', N, 'k4-%d' % n, text='造的：第 %d 问' % n)
        store.put('episodes', {'_id': 'ep-k4-%d' % n, 'scene_id': 'g1', 'scope_key': 'scene:g1', 'policy_epoch': 1,
                               'persona': 'P1', 'person_id': N, 'episode_kind': 'external', 'state': 'COMMITTED',
                               'source_event_id': 'k4-%d' % n, 'monologue_refs': [], 'context': {}, 'manifest': {},
                               'tool_calls': {}}, stream='ep-k4-%d' % n)
        if n in (0, 24):
            assert familiarity.level(store, N) is None and familiarity.words(store, N, 'P1') == {}


def test_X1_the_carry_outside_a_visit_of_her_own_hands_over_with_the_outside_grant_only(room):
    store = room.store
    assert list(denied(room, ask(store, N, 'x1a'), 'delegate', HANDS[0][1]).codes) == ['asker_not_known']
    asked = ask(store, N, 'x1b')                              # then a visit she made there: nobody's ask
    visit = {**asked, 'episode_kind': 'visit', 'whose': whose.record('own', 'g1', N)}
    visit = store.put('episodes', {**visit, 'turn_tools': role_tools.exposed(store, visit)}, expected=asked['revision'],
                      stream=asked['_id'])
    result, _ = call(room, visit, 'delegate', HANDS[0][1])
    task = task_records.get(store, result['task'])
    assert 'sandbox_run' not in task['allowed_capabilities'] and task['network'] == 'public' \
        and not task['development_grant']


def test_at_home_the_asker_rule_does_not_apply(room):
    store = room.store
    ep = ask(store, N, 'h1')
    home_ep = store.put('episodes', {**ep, 'manifest': {**ep['manifest'], 'session_class': 'owner_private'}},
                        expected=ep['revision'], stream=ep['_id'])
    assert guard._asker_not_known(store, home_ep, 'delegate', HANDS[0][1]) is False
