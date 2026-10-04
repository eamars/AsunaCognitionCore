"""ADR-009 P5 MongoDB tests: T5.2 heartbeat gates and retiming, T5.3 settlement and promotion."""
from datetime import datetime, timezone
import threading
import types

import pytest

from asuna.chat import SceneQueue
from asuna.policy import PolicyStore
from asuna.schedule import ScheduleService
from asuna.state import Denied
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
        self.pending, self.active, self.active_task, self.offers = SceneQueue(), None, None, []

    def offer_internal(self, kind, event_id, scene_id, person_id, text):
        self.offers.append((kind, event_id, scene_id, person_id))


def scheduler(store, rhythm=None):
    owner(store)
    store.config['persona_model'] = {'model_version': 1, 'persona': {'id': 'P1', 'display_name': 'x'},
        'heartbeat': {'enabled': True, 'every_min': 30, 'min_gap_min': 20, 'skip_in_sleep': False},
        'rhythm': rhythm or {},
        'memory': {'promotion': {'daily_quota': 2, 'min_roots': 2, 'min_dates': 2, 'window_days': 7}},
        'policy_keys': {'heartbeat.every_min': {'type': 'integer', 'min': 1, 'max': 1440, 'what': '心跳间隔'}}}
    store.config['persona_runtime'] = {'P1': {'heartbeat_target': 'dm-a'}}
    service = ScheduleService.__new__(ScheduleService)
    service.store, service.lane, service.controller = store, NativeLane(), Controller()
    service.deliver_lock = threading.RLock()
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


