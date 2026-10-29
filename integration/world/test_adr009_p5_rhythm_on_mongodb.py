"""ADR-050 on MongoDB, kept by ADR-104 decision 9 (a break would leak private data): a memory built on anything said at
home cannot be made public."""
from datetime import datetime, timezone
import threading
import types

import pytest

from asuna.chat import SceneQueue
from asuna.schedule import ScheduleService
from asuna.state import Denied

from turn_parts import owner

pytestmark = pytest.mark.world                # `store` is the fixture world


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
                      **{k: v for k, v in payload.items() if k not in ('plan_id', 'every_seconds')}}
            if 'every_seconds' in payload:                # DSH stores an interval as everySeconds
                record['everySeconds'] = payload['every_seconds']
            self.events.append({'seq': len(self.events) + 1, 'data': {'operation': 'create', 'schedule': record}})
            return record
        if path == '/schedule/update':
            record = dict([e['data']['schedule'] for e in self.events
                           if e['data'].get('schedule', {}).get('id') == payload['id']][-1])
            change = payload.get('change')
            if change:                                    # DSH: exactly kind and its own selector
                selector = {'every': 'every_seconds', 'daily': 'daily', 'weekly': 'weekly', 'at': 'at'}.get(change['kind'])
                assert selector and set(change) == {'kind', selector}, change
                record.update({'everySeconds': change['every_seconds']} if change['kind'] == 'every'
                              else {selector: change[selector]}, kind=change['kind'])
            if payload.get('title'):
                record['title'] = payload['title']
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
        self.envelopes = []

    def offer_internal(self, kind, event_id, scene_id, person_id, text, **visit):
        self.offers.append((kind, event_id, scene_id, person_id))
        self.texts.append(text)
        self.envelopes.append(visit)

    def offer_self_development(self, event_id, *, text=None, **_):
        self.offers.append(('self_development', event_id, self.settings['scene_id'], self.settings['person_id']))
        self.texts.append(text)
        self.envelopes.append({})


def scheduler(store, rhythm=None):
    owner(store)
    store.config['persona_model'] = {'model_version': 1, 'persona': {'id': 'P1', 'display_name': 'x'},
        # The gates are under test here, not the die (ADR-058, test_heartbeat_dice.py): it always rolls interesting.
        'heartbeat': {'enabled': True, 'every_min': 30, 'min_gap_min': 20,
                      'dice_awake': '有趣 1', 'dice_asleep': '有趣 1'},
        'rhythm': rhythm or {},
        'memory': {'promotion': {'daily_quota': 2, 'min_roots': 2, 'min_dates': 2, 'window_days': 7}}}
    store.config['persona_runtime'] = {'P1': {'heartbeat_target': 'dm-a'}}
    service = ScheduleService.__new__(ScheduleService)
    service.store, service.lane, service.controller = store, NativeLane(), Controller()
    service.deliver_lock, service.rhythm_lock = threading.RLock(), threading.RLock()
    service.app = types.SimpleNamespace(config=store.config)
    return service


def test_a_memory_built_on_anything_said_at_home_cannot_be_made_public(store):
    """ADR-050: a public memory shows in every conversation, so every source must be from outside home."""
    from asuna.role_tools import promote
    from asuna import visibility
    scheduler(store)                                  # the persona model with a promotion quota
    ep = {'_id': 'ep-night', 'persona': 'P1', 'episode_kind': 'settlement', 'tool_calls': {}}
    for i, cls in ((1, visibility.PUBLIC), (2, visibility.OWNER_PRIVATE), (3, visibility.PUBLIC)):
        store.raw.episodes.insert_one({'_id': 'pe-%d' % i, 'schema_version': 1, 'scene_id': 'g-%d' % i,
                                      'source_event_id': 'in-p%d' % i, 'episode_kind': 'external',
                                      'manifest': {'session_class': cls}})
        store.raw.audit_events.insert_one({'_id': 'pctx-%d' % i, 'schema_version': 1, 'type': 'context.prepared',
                                          'stream_id': 'pe-%d' % i, 'occurred_at': '2026-10-0%dT12:00:00+00:00' % i})
    item = {'fact': '群里周五晚上常开黑', 'appraisal': '是他们固定的热闹', 'signal': '周五晚上可以聊游戏',
            'why': '两周都这样', 'visibility': 'public'}
    with pytest.raises(Denied, match='PROMOTION_NOT_PUBLIC'):
        promote(store, ep, {**item, 'source_ids': ['pe-1', 'pe-2']}, key='p1')
    kept = promote(store, ep, {**item, 'source_ids': ['pe-1', 'pe-3']}, key='p2')
    assert store.raw.memory_units.find_one({'_id': kept['memory_id']})['scope_key'] == 'global-safe'
    home = promote(store, ep, {**item, 'visibility': 'private', 'source_ids': ['pe-1', 'pe-2']}, key='p3')
    assert store.raw.memory_units.find_one({'_id': home['memory_id']})['scope_key'] != 'global-safe'


