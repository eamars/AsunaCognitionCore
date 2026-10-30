"""The plan service applies the decisions of `schedule_rules` (ADR-106) to real plan rows: what create stores, what a
retry does, and what an update does to a plan written on another clock. The native scheduler is a recording stand-in;
the store is the in-memory database."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from asuna import schedule, schedule_rules
from asuna.records import plans as plan_records
from asuna.schedule import ScheduleService

ZONE = 'Europe/Berlin'            # personal-scan: ok (unrelated demo DST zone)
OTHER = 'Etc/GMT-9'
NOW = datetime(2026, 9, 24, 5, 0, tzinfo=timezone.utc)      # 07:00 in ZONE on a Thursday


class NativeStandIn:
    """Records what the service asks DSH's scheduler for, and answers like it."""
    scheduler_session = 'session-1'

    def __init__(self):
        self.events, self.calls = [], []

    def schedule(self, path, payload=None):
        self.calls.append((path, payload))
        if path == '/schedule/events':
            return list(self.events)
        if path == '/schedule/create':
            kind = next((k for k in ('daily', 'weekly', 'every_seconds', 'after_seconds') if k in payload))
            record = {'id': 'native-%d' % len(self.events), 'prompt': 'ASUNA_PLAN:' + payload['plan_id'],
                      'kind': {'every_seconds': 'every', 'after_seconds': 'after'}.get(kind, kind),
                      'scheduledAt': '2026-09-25T07:00:00+00:00'}
            self.events.append({'data': {'operation': 'create', 'schedule': record}})
            return record
        if path == '/schedule/update':
            return {'id': payload['id'], 'kind': (payload.get('change') or {}).get('kind', 'daily'),
                    'scheduledAt': '2026-09-25T07:00:00+00:00'}
        return {}


@pytest.fixture
def service(world, monkeypatch):
    world.config['timezone'] = ZONE
    monkeypatch.setattr(schedule, 'now', lambda: NOW.isoformat())
    made = ScheduleService.__new__(ScheduleService)
    made.app, made.store, made.lane = SimpleNamespace(config=world.config, store=world), world, NativeStandIn()
    return made


def turn(call):
    return {'_id': 'ep-' + call, 'scene_id': 'dm-a', 'person_id': 'A', 'scope_key': 'scene:dm-a', 'policy_epoch': 1}


def create(service, call, spec):
    return service.create(turn(call), {'intent': 'look', **spec}, plan_id='plan-' + call)


def test_create_stores_a_zone_only_for_a_daily_plan_and_pins_an_appointment(service):
    clock = create(service, 'clock', {'clock': {'time': '09:00'}})
    assert clock['timezone'] == ZONE and 'tz_source' not in clock
    assert service.lane.calls[-1][1]['daily'] == {'time': '09:00:00', 'time_zone': ZONE}, 'DSH holds the same zone'
    appointment = create(service, 'at', {'at': '2026-09-25T20:00'})
    assert appointment['rule'] == {'at': '2026-09-25T18:00+00:00', 'at_utc': True} and 'timezone' not in appointment
    assert service.lane.calls[-1][1].keys() >= {'after_seconds'}, 'the native timer is relative, with no zone'
    after = create(service, 'after', {'after_seconds': 600})
    assert 'timezone' not in after and 'tz_source' not in after


def test_a_retried_create_is_the_same_plan_not_a_conflict(service):
    first = create(service, 'again', {'at': '2026-09-25T20:00'})
    natives = len(service.lane.events)
    second = create(service, 'again', {'at': '2026-09-25T20:00'})
    assert second['_id'] == first['_id'] and second['rule'] == first['rule'] and len(service.lane.events) == natives


def old_plan(service, **fields):
    """A daily plan from before: written on another clock, armed natively in that zone."""
    plan = create(service, 'old', {'clock': {'time': '09:00'}})
    current = plan_records.get(service.store, plan['_id'])
    return plan_records.save(service.store, {**current, 'timezone': OTHER, **fields}, expected=current['revision'],
                             stream=plan['_id'])


def update(service, plan, spec):
    return service.update(turn('update'), plan['_id'], spec)


def test_restating_the_same_time_puts_an_old_plan_on_her_clock(service):
    plan = old_plan(service)
    moved = update(service, plan, {'schedule': {'clock': {'time': '09:00'}}})
    assert moved['timezone'] == ZONE and moved['last_update']['from_timezone'] == OTHER
    assert moved['plan_version'] == plan['plan_version'] + 1
    path, payload = service.lane.calls[-1]
    assert path == '/schedule/update' and payload['change']['daily']['time_zone'] == ZONE, 'DSH is moved too'
    assert 'tz_source' not in moved
    note = schedule_rules.moved_note(moved, schedule_rules.her_zone(service.store.config))
    assert note and '比你的钟快 7 小时' in note, note
    again = update(service, moved, {'schedule': {'clock': {'time': '09:00'}}})
    assert again['plan_version'] == moved['plan_version'] and 'last_update' not in again, \
        'saying it again changes nothing and does not report the move a second time'


def test_restating_the_time_of_a_plan_already_on_her_clock_changes_nothing(service):
    plan = create(service, 'mine', {'clock': {'time': '09:00'}})
    calls = len(service.lane.calls)
    same = update(service, plan, {'schedule': {'clock': {'time': '09:00'}}})
    assert same['plan_version'] == plan['plan_version'] and len(service.lane.calls) == calls
    assert 'last_update' not in same, 'an earlier move is not reported again'


def test_new_wording_alone_keeps_the_plan_where_it_is(service):
    plan = old_plan(service)
    worded = update(service, plan, {'intent': 'look at the door'})
    assert worded['timezone'] == OTHER and worded['rule'] == plan['rule'] and worded['intent'] == 'look at the door'
    assert worded['next_fire_at'] == '2026-09-25T00:00:00+00:00', '09:00 on the plan\'s own clock, not on hers'
    assert 'from_timezone' not in worded['last_update']
    assert service.lane.calls[-1][1].get('change') is None, 'the native record keeps its timing; only its title follows'


def test_a_new_timing_on_a_plan_of_no_wall_zone_stores_no_zone(service):
    plan = old_plan(service)
    moved = update(service, plan, {'schedule': {'after_seconds': 900}})
    assert 'timezone' not in moved and moved['rule'] == {'after_seconds': 900}
    assert moved['last_update']['from_timezone'] == OTHER, 'it was written on another clock, and says so'


def test_a_daily_plan_is_armed_again_by_the_clock_it_was_written_on(service):
    plan = old_plan(service, native_recurring=False)
    service._rearm(plan['_id'])
    path, payload = service.lane.calls[-1]
    assert path == '/schedule/create' and payload['after_seconds'] == 19 * 3600, \
        '09:00 at its own clock is 19 hours after NOW; on hers it would be 26'
