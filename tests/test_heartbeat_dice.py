"""ADR-058: the heartbeat rolls a die before it reaches her. Nothing (no turn, unless an hour would lose something
only a heartbeat shows), interesting, self development, self evaluation; awake and asleep weights she sets; the roll is
one line of text, reproducible from the beat, and recorded."""
import collections

import pytest

from asuna import dice
from test_adr009_p5_rhythm import fire, scheduler


def test_a_roll_follows_its_weights_is_the_same_for_the_same_beat_and_a_zero_never_comes():
    weights = dice.parse('40/35/0/25')
    rolls = collections.Counter(dice.roll('beat-%d' % n, weights) for n in range(4000))
    assert rolls['self_development'] == 0
    assert all(abs(rolls[o] / 4000 - weights[o] / 100) < 0.03 for o in ('nothing', 'interesting', 'self_evaluation'))
    assert dice.roll('beat-7', weights) == dice.roll('beat-7', weights)
    for bad in ('40/35/10', '0/0/0/0', 'a/b/c/d', None):
        with pytest.raises(ValueError):
            dice.parse(bad)


def beat(store, weights):
    service = scheduler(store)
    store.config['persona_model']['heartbeat'].update(dice_awake=weights, dice_asleep=weights)
    store.config['self_development'] = {'enabled': True}
    plan = service.ensure_presence()
    return service, fire(service, plan)


def test_nothing_does_not_reach_her_and_says_why_in_its_record(store):
    service, plan = beat(store, '1/0/0/0')
    assert plan['last_outcome'] == 'SKIPPED:DICE_NOTHING' and not service.controller.offers
    rolled = store.db.audit_events.find_one({'type': 'presence.rolled'})['payload']
    assert rolled['outcome'] == 'nothing' and rolled['reaches'] is False and rolled['period'] == 'awake'


def test_nothing_still_reaches_her_when_only_a_heartbeat_would_show_what_waits(store, monkeypatch):
    monkeypatch.setattr(dice, 'waiting', lambda *args: True)
    service, plan = beat(store, '1/0/0/0')
    assert plan['last_outcome'] == 'ENQUEUED' and service.controller.texts[0].startswith('这一拍掷到：歇着')


def test_what_waits_wakes_a_nothing_beat_only_when_an_hour_would_lose_it(store):
    from datetime import datetime, timezone
    from test_peer_lines import SCENE, with_line
    with_line(store)
    moment = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)
    for seq in range(1, 6):                     # five unseen asides: all still in the list next hour
        store.db.messages.insert_one({'_id': 'a%d' % seq, 'schema_version': 1, 'scene_id': SCENE, 'scene_seq': seq,
                                      'direction': 'inbound', 'text': '心跳 %d' % seq,
                                      'received_at': '2026-10-12T08:%02d:00+00:00' % seq,
                                      'event': {'raw': {'asuna_aside': True}}})
    assert dice.waiting(store, 'P1', moment) is False
    store.db.messages.insert_one({'_id': 'a6', 'schema_version': 1, 'scene_id': SCENE, 'scene_seq': 6,
                                  'direction': 'inbound', 'text': '心跳 6', 'received_at': '2026-10-12T08:06:00+00:00',
                                  'event': {'raw': {'asuna_aside': True}}})
    assert dice.waiting(store, 'P1', moment) is True, 'the list is full: one more would push the oldest out'


def test_each_outcome_opens_with_its_line_and_goes_where_it_belongs(store):
    service, _ = beat(store, '0/0/1/0')
    assert service.controller.offers[0][0] == 'self_development'
    assert service.controller.texts[0].startswith('这一拍掷到：自我开发（醒着的分布：歇着 0、做点有意思的 0、自我开发 1、自我评估 0）')
    store.db.plans.delete_many({})
    service, _ = beat(store, '0/0/0/1')
    assert service.controller.offers[-1][0] == 'presence' and service.controller.envelopes[-1] == {'dice': 'self_evaluation'}
    assert '照做、换一件、或者不理，都行' in service.controller.texts[-1]


def test_without_self_improvement_on_this_machine_its_weight_counts_as_zero(store):
    service = scheduler(store)
    store.config['persona_model']['heartbeat'].update(dice_awake='0/0/1/0')
    store.config['self_development'] = {'enabled': False}
    fire(service, service.ensure_presence())
    assert store.db.audit_events.find_one({'type': 'presence.rolled'})['payload']['outcome'] == 'interesting'


def test_only_the_programs_own_heartbeat_can_say_what_it_rolled(store):
    from asuna.coordinator import Coordinator
    from asuna.lanes import FakeLane
    from asuna.router import Router
    lane = FakeLane(store, [])
    router = Router(store, Coordinator(store, lane))
    seen = []
    router.coordinator.ingest = lambda event, **_: seen.append(event) or {'state': 'X'}
    router.receive({'event_id': 'c1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': 'hi', 'episode_kind': 'presence',
                    'dice': 'self_evaluation', 'channel': {'id': 'fixture'}})
    router.receive({'event_id': 'presence:x', 'scene_id': 'dm-a', 'person_id': 'A', 'text': 'beat',
                    'episode_kind': 'presence', 'dice': 'self_evaluation'})
    assert 'dice' not in seen[0] and seen[1]['dice'] == 'self_evaluation'


def test_self_evaluation_brings_her_day_as_raw_readings_at_home(store):
    from asuna.context import ContextBuilder
    from test_adr009_p2 import owner
    owner(store)
    store.db.messages.insert_one({'_id': 'out-1', 'schema_version': 1, 'scene_id': 'dm-a', 'direction': 'outbound',
                                  'phase': 'SPEAK', 'receipt_at': '2099-01-01T00:00:00+00:00'})
    event = {'event_id': 'presence:e1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': 'beat', 'episode_kind': 'presence'}
    _, plain, _ = ContextBuilder(store).prepare(event)
    assert 'self_review_from_program' not in plain
    _, rolled, _ = ContextBuilder(store).prepare({**event, 'event_id': 'presence:e2', 'dice': 'self_evaluation'})
    review = rolled['self_review_from_program']
    assert set(review) == {'said', 'tasks', 'refused', 'open', 'since_at', 'note'}
    assert review['said'][0]['lines'] >= 1 and review['said'][0]['last_at']
