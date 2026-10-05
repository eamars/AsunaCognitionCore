"""ADR-009 P5 MongoDB tests: T5.2 heartbeat gates and retiming, T5.3 settlement and promotion;
ADR-012 M-A: the heartbeat belongs to the program, its pace to her."""
from datetime import datetime, timedelta, timezone
import threading
import types

import pytest

from asuna.chat import SceneQueue
from asuna.persona_model import PersonaModelError, neutral, validate
from asuna.policy import PolicyStore
from asuna.schedule import ScheduleService
from asuna.state import Denied, now
from test_adr009_p2 import owner


class NativeLane:
    scheduler_session = 's-p5'

    def __init__(self):
        self.events, self.calls, self.created = [], [], 0

    def schedule(self, path, payload=None):
        self.calls.append((path, payload))
        if path == '/schedule/events':
            return [dict(e) for e in self.events]
        if path == '/schedule/create':
            self.created += 1
            kind = next(k for k in ('every', 'daily', 'weekly', 'after') if k in payload or k + '_seconds' in payload)
            record = {'id': 'n%d' % self.created, 'prompt': 'ASUNA_PLAN:' + payload['plan_id'], 'kind': kind,
                      'scheduledAt': datetime.now(timezone.utc).isoformat(),
                      **{k: v for k, v in payload.items() if k != 'plan_id'}}
            self.events.append({'seq': len(self.events) + 1, 'data': {'operation': 'create', 'schedule': record}})
            return record
        if path == '/schedule/update':
            record = dict([e['data']['schedule'] for e in self.events
                           if e['data'].get('schedule', {}).get('id') == payload['id']][-1])
            record.update({k: v for k, v in payload['change'].items() if k != 'kind'}, kind=payload['change']['kind'])
            self.events.append({'seq': len(self.events) + 1, 'data': {'operation': 'update', 'schedule': record}})
            return record
        if path == '/schedule/delete':
            self.events.append({'seq': len(self.events) + 1, 'data': {'operation': 'delete', 'id': payload['id']}})
            return {'deleted': True}
        raise AssertionError(path)

    def fire(self, native_id):
        self.events.append({'seq': len(self.events) + 1, 'data': {'operation': 'dispatch', 'id': native_id}})
        return self.events[-1]['seq']


class Controller:
    def __init__(self):
        self.settings = {'persona': 'P1', 'scene_id': 'dm-a', 'person_id': 'A'}
        self.pending, self.active, self.active_task, self.offers, self.texts = SceneQueue(), None, None, [], []

    def offer_internal(self, kind, event_id, scene_id, person_id, text):
        self.offers.append((kind, event_id, scene_id, person_id))
        self.texts.append(text)


def scheduler(store, rhythm=None):
    owner(store)
    store.config['persona_model'] = {'model_version': 1, 'persona': {'id': 'P1', 'display_name': 'x'},
        'heartbeat': {'enabled': True, 'every_min': 30, 'min_gap_min': 20, 'skip_in_sleep': False},
        'rhythm': rhythm or {},
        'memory': {'promotion': {'daily_quota': 2, 'min_roots': 2, 'min_dates': 2, 'window_days': 7}}}
    store.config['persona_runtime'] = {'P1': {'heartbeat_target': 'dm-a'}}
    service = ScheduleService.__new__(ScheduleService)
    service.store, service.lane, service.controller = store, NativeLane(), Controller()
    service.deliver_lock, service.rhythm_lock = threading.RLock(), threading.RLock()
    service.app = types.SimpleNamespace(config=store.config)
    return service


def fire(service, plan):
    seq = service.lane.fire(plan['schedule_id'])
    service.deliver({'session': 's-p5', 'seq': seq, 'id': plan['schedule_id']})
    return service.store.db.plans.find_one({'_id': plan['_id']})


def test_T5_2_heartbeat_gates_and_retime_in_place(store):
    service = scheduler(store)
    plan = service.ensure_presence()
    assert plan['kind'] == 'presence' and plan['rule'] == {'every_seconds': 1800}
    service.controller.pending.put(({'scene_id': 'dm-a'}, 'queued'))
    busy = fire(service, plan)
    assert busy['last_outcome'] == 'SKIPPED:BUSY' and not service.controller.offers
    service.controller.pending.get_nowait()
    service.controller.pending.task_done()
    ran = fire(service, plan)
    assert ran['last_outcome'] == 'ENQUEUED' and service.controller.offers[0][0] == 'presence'
    gap = fire(service, plan)
    assert gap['last_outcome'] == 'SKIPPED:MIN_GAP' and len(service.controller.offers) == 1
    assert store.db.audit_events.count_documents({'stream_id': plan['_id'], 'type': 'presence.skipped'}) == 2
    PolicyStore(store, 'P1', store.config['persona_model']).set(
        [{'key': 'heartbeat.every_min', 'value': 45, 'what': '心跳间隔'}], base_revision_id=None, reason='慢一点',
        author='character', mutation_id='t52-retime')
    retimed = service.ensure_presence()
    paths = [path for path, _ in service.lane.calls]
    assert retimed['schedule_id'] == plan['schedule_id'] and retimed['rule'] == {'every_seconds': 2700}
    assert '/schedule/update' in paths and '/schedule/delete' not in paths and service.lane.created == 1
    store.config['persona_runtime'] = {'P1': {'heartbeat_target': 'g1'}}
    with pytest.raises(Denied, match='PRESENCE_TARGET_NOT_OWNER_PRIVATE'):
        service.ensure_presence()


def set_policy(store, key, value):
    policy = PolicyStore(store, 'P1', store.config['persona_model'])
    policy.set([{'key': key, 'value': value, 'what': key}], base_revision_id=policy.read()[0], reason='test',
               author='character', mutation_id='policy-%s-%s' % (key, value))


def test_her_heartbeat_pace_is_bounded_and_only_the_owner_turns_it_off(store):
    service = scheduler(store)
    model = store.config['persona_model']
    for value in (14, 241):
        with pytest.raises(ValueError, match='POLICY_VALUE_RANGE'):
            PolicyStore(store, 'P1', model).validate([{'key': 'heartbeat.every_min', 'value': value, 'what': 'x'}])
    # heartbeat.enabled is the owner's: a package cannot hand it to her as a policy key.
    declared = {**neutral('p1', 'x'), 'policy_keys': {'heartbeat.enabled': {'type': 'boolean', 'what': '开关'}}}
    with pytest.raises(PersonaModelError, match='may not declare core keys: heartbeat.enabled'):
        validate(declared, 'p1')
    with pytest.raises(Denied, match='POLICY_KEY_UNDECLARED'):
        PolicyStore(store, 'P1', declared).validate([{'key': 'heartbeat.enabled', 'value': False, 'what': '关掉'}])
    assert service.ensure_presence()['rule'] == {'every_seconds': 1800}
    store.config['persona_model'] = {**model, 'heartbeat': {**model['heartbeat'], 'every_min': 5}}
    assert service.ensure_presence()['rule'] == {'every_seconds': 900}       # an out-of-range default is clamped


def test_the_heartbeat_waits_for_her_turns_and_her_pause_ends_by_itself(store):
    service = scheduler(store)
    plan = service.ensure_presence()
    set_policy(store, 'heartbeat.min_gap_min', 0)
    service.controller.active_task = 'task-running'           # the action brain at work does not make her busy
    assert fire(service, plan)['last_outcome'] == 'ENQUEUED'
    service.controller.active_task = None
    assert service.pause_presence(60)
    assert fire(service, plan)['last_outcome'] == 'SKIPPED:PAUSED'
    store.db.plans.update_one({'_id': plan['_id']}, {'$set': {'paused_until': '2000-01-01T00:00:00+00:00'}})
    assert fire(service, plan)['last_outcome'] == 'ENQUEUED'   # the pause ran out; nobody had to resume it
    beats = store.db.plans.find_one({'_id': plan['_id']})['beats']
    assert beats['count'] == 2
    store.db.plans.update_one({'_id': plan['_id']}, {'$set': {'beats': {**beats, 'count': 24}}})
    assert fire(service, plan)['last_outcome'] == 'SKIPPED:DAILY_BUDGET'
    assert len(service.controller.offers) == 2
    assert 'set_policy' in service.controller.texts[0] and 'heartbeat.pause_min' in service.controller.texts[0]


def test_any_home_turn_counts_for_the_gap_and_only_news_for_her_lifts_it(store):
    service = scheduler(store)
    store.config['channels'] = {'qq': {'routes': {'r1': {'scene_id': 'g1', 'target': {'type': 'group', 'id': 'x'}}}}}
    plan = service.ensure_presence()
    store.db.plans.insert_one({'_id': 'plan-asuna-settlement', 'schema_version': 1, 'kind': 'settlement',
                               'scene_id': 'dm-a', 'last_outcome': 'ENQUEUED', 'last_occurrence_at': now()})
    assert fire(service, plan)['last_outcome'] == 'SKIPPED:MIN_GAP'     # she just had her settlement turn
    store.db.messages.insert_one({'_id': 'm-quiet', 'schema_version': 1, 'scene_id': 'g1', 'direction': 'inbound',
                                  'received_at': now(), 'processing_outcome': 'RECORDED_NO_WAKE'})
    assert fire(service, plan)['last_outcome'] == 'SKIPPED:MIN_GAP'     # group talk that did not wake her
    store.db.messages.insert_one({'_id': 'm-called', 'schema_version': 1, 'scene_id': 'g1', 'direction': 'inbound',
                                  'received_at': now()})
    assert fire(service, plan)['last_outcome'] == 'ENQUEUED'            # someone in a group reached her
    store.db.plans.update_one({'_id': 'plan-asuna-settlement'}, {'$set': {'last_outcome': 'SKIPPED:ALREADY_SETTLED'}})
    assert fire(service, plan)['last_outcome'] == 'SKIPPED:MIN_GAP'
    store.db.tasks.insert_one({'_id': 'task-done', 'schema_version': 1, 'finished_at': now()})
    assert fire(service, plan)['last_outcome'] == 'ENQUEUED'            # one of her tasks finished


def test_a_silent_heartbeat_is_rebuilt_once_and_she_is_told_once(store):
    service = scheduler(store)
    plan = service.ensure_presence()
    assert service.watch_rhythm() is None                               # just armed
    long_ago = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    store.db.plans.update_one({'_id': plan['_id']}, {'$set': {'last_occurrence_at': long_ago}})
    assert service.watch_rhythm() == 'REBUILT'
    rebuilt = store.db.plans.find_one({'_id': plan['_id']})
    assert rebuilt['status'] == 'ACTIVE' and rebuilt['schedule_id'] != plan['schedule_id']
    assert ('/schedule/delete', {'id': plan['schedule_id']}) in service.lane.calls
    assert service.watch_rhythm() is None                               # one rebuild for one silence
    assert store.db.audit_events.count_documents({'stream_id': plan['_id'], 'type': 'rhythm.heartbeat_missed'}) == 1
    assert fire(service, rebuilt)['last_outcome'] == 'ENQUEUED' and '断过一次' in service.controller.texts[-1]
    store.db.plans.update_one({'_id': plan['_id']}, {'$set': {'last_presence_at': long_ago}})
    assert fire(service, rebuilt)['last_outcome'] == 'ENQUEUED' and '断过一次' not in service.controller.texts[-1]
    store.db.plans.update_one({'_id': plan['_id']}, {'$set': {'status': 'CANCELLED'}})
    assert service.watch_rhythm() is None                               # the owner turned it off: nothing to keep


