"""ADR-058: the heartbeat rolls a die before it reaches her. Nothing (no turn, unless an hour would lose something
only a heartbeat shows), interesting, self development, self evaluation, review the dice, reach out at home; awake and
asleep weights she sets by name; the roll is one line of text, reproducible from the beat, and recorded."""
import collections

import pytest

from asuna import dice
from test_adr009_p5_rhythm import fire, scheduler


def test_a_roll_follows_its_weights_is_the_same_for_the_same_beat_and_a_zero_never_comes():
    weights = dice.parse('歇着 40、有趣 35、自我评估 25')
    rolls = collections.Counter(dice.roll('beat-%d' % n, weights) for n in range(4000))
    assert rolls['self_development'] == 0
    assert all(abs(rolls[o] / 4000 - weights[o] / 100) < 0.03 for o in ('nothing', 'interesting', 'self_evaluation'))
    assert dice.roll('beat-7', weights) == dice.roll('beat-7', weights)
    assert weights['self_development'] == 0 and weights['reach_out'] == 0, 'a name left out weighs 0'
    assert dice.parse('歇着40,复盘 2/找人 5') == {**dict.fromkeys(dice.OUTCOMES, 0), 'nothing': 40, 'review_dice': 2,
                                                 'reach_out': 5}
    for bad in ('40/35/10/15', '歇着 0', '睡觉 10', '歇着 10、歇着 5', '歇着', None):
        with pytest.raises(ValueError):
            dice.parse(bad)


def beat(store, weights):
    service = scheduler(store)
    store.config['persona_model']['heartbeat'].update(dice_awake=weights, dice_asleep=weights)
    store.config['self_development'] = {'enabled': True}
    plan = service.ensure_presence()
    return service, fire(service, plan)


def test_nothing_does_not_reach_her_and_says_why_in_its_record(store):
    service, plan = beat(store, '歇着 1')
    assert plan['last_outcome'] == 'SKIPPED:DICE_NOTHING' and not service.controller.offers
    rolled = store.db.audit_events.find_one({'type': 'presence.rolled'})['payload']
    assert rolled['outcome'] == 'nothing' and rolled['reaches'] is False and rolled['period'] == 'awake'


def test_nothing_still_reaches_her_when_only_a_heartbeat_would_show_what_waits(store, monkeypatch):
    monkeypatch.setattr(dice, 'waiting', lambda *args: True)
    service, plan = beat(store, '歇着 1')
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
    service, _ = beat(store, '自我开发 1')
    assert service.controller.offers[0][0] == 'self_development'
    assert service.controller.texts[0].startswith('这一拍掷到：自我开发（醒着的分布：歇着 0、有趣 0、自我开发 1、自我评估 0、复盘 0、找人 0）')
    store.db.plans.delete_many({})
    service, _ = beat(store, '自我评估 1')
    assert service.controller.offers[-1][0] == 'presence' and service.controller.envelopes[-1] == {'dice': 'self_evaluation'}
    assert '照做、换一件、或者不理，都行' in service.controller.texts[-1]


def test_without_self_improvement_on_this_machine_its_weight_counts_as_zero(store):
    service = scheduler(store)
    store.config['persona_model']['heartbeat'].update(dice_awake='自我开发 1')
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


def test_reach_out_names_her_lines_and_weighs_nothing_without_one(store):
    service = scheduler(store)
    store.config['persona_model']['heartbeat'].update(dice_awake='找人 1', dice_asleep='找人 1')
    fire(service, service.ensure_presence())
    assert store.db.audit_events.find_one({'type': 'presence.rolled'})['payload']['outcome'] == 'interesting'
    from test_peer_lines import with_line
    with_line(store)
    store.db.plans.delete_many({})
    service, _ = beat(store, '找人 1')
    text = service.controller.texts[-1]
    assert text.startswith('这一拍掷到：找人') and 'pass_note' in text and service.controller.envelopes[-1] == {}


def at(store, stream, kind, when, payload):
    store.audit(stream, kind, payload, 'scene:local')
    row = store.db.audit_events.find_one({'stream_id': stream, 'type': kind}, sort=[('seq', -1)])
    store.db.audit_events.update_one({'_id': row['_id']}, {'$set': {'occurred_at': when}})


def rolled(store, when, outcome, occurrence, reaches=True):
    at(store, 'plan-p', 'presence.rolled', when, {'occurrence': occurrence, 'period': 'awake', 'outcome': outcome,
                                                  'weights': {}, 'reaches': reaches})


def test_review_brings_every_roll_since_her_last_review_with_what_each_beat_did(store):
    service, _ = beat(store, '复盘 1')
    assert service.controller.envelopes[-1] == {'dice': 'review_dice'}
    store.db.audit_events.delete_many({'type': 'presence.rolled'})
    rolled(store, '2099-01-01T01:00:00+00:00', 'review_dice', 'old-review')
    rolled(store, '2099-01-01T02:00:00+00:00', 'nothing', 'n1', reaches=False)
    rolled(store, '2099-01-01T03:00:00+00:00', 'interesting', 'i1')
    store.db.episodes.insert_one({'_id': 'ep-i1', 'schema_version': 1, 'scene_id': 'local',
                                  'source_event_id': 'presence:i1', 'episode_kind': 'presence',
                                  'silent_reason': '没什么想说的'})
    at(store, 'ep-i1', 'role_tool', '2099-01-01T03:01:00+00:00', {'call_id': 'c', 'tool': 'visit', 'result': 'ok'})
    rolled(store, '2099-01-01T04:00:00+00:00', 'review_dice', 'now')
    from datetime import datetime, timezone
    out = dice.review(store, 'P1', 'now', datetime(2099, 1, 1, 4, 0, tzinfo=timezone.utc))
    assert [(r['roll'], r['reached']) for r in out['rolls']] == [('歇着', '没叫你'), ('有趣', '叫了你')]
    assert out['rolls'][1]['tools'] == {'visit': 1} and out['rolls'][1]['quiet'] == '没什么想说的'
    assert out['counts'] == {'歇着': 1, '有趣': 1} and out['since_at'] == '2099-01-01T01:00:00+00:00'
    assert out['tables']['醒着'].startswith('歇着 ') and '找人' in out['tables']['睡着']


def test_set_policy_shows_the_whole_table_it_stored(store):
    from asuna import role_tools
    from asuna.coordinator import Coordinator
    from asuna.lanes import FakeLane
    from test_adr009_p2 import owner
    owner(store)
    tools = role_tools.RoleTools(Coordinator(store, FakeLane(store, [])))
    ep = {'_id': 'ep-home', 'persona': 'P1', 'scene_id': 'dm-a', 'scope_key': 'scene:dm-a', 'episode_kind': 'presence',
          'source_event_id': 'presence:x', 'manifest': {'session_class': 'owner_private'}}
    result, _ = tools.tool_set_policy(ep, 'c1', {'key': 'heartbeat.dice_awake', 'value': '歇着 50、有趣 50',
                                                 'reason': '先试试'})
    assert result['stored_table'] == '歇着 50、有趣 50、自我开发 0、自我评估 0、复盘 0、找人 0'
    with pytest.raises(role_tools.Refused, match='能写的名字'):
        tools.tool_set_policy(ep, 'c2', {'key': 'heartbeat.dice_awake', 'value': '睡觉 10', 'reason': '错名'})
