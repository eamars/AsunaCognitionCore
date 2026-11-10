"""A due plan that does not reach her is said to her (ADR-119 F10): a firing that fails on the worker's side marks
the plan's conversation and her next turn there reads one line; a firing DSH logged but never handed over is handed
on by the rhythm watch, once; the self-development plans carry the fields her plan view shows. The native scheduler is
the recording stand-in of test_plan_zone_service; the store is the in-memory database."""
import threading
from datetime import timedelta

import pytest

from asuna import faults, schedule, schedule_rules
from asuna.records import plans as plan_records
from asuna.records import scenes as scene_records
import test_plan_zone_service
from test_plan_zone_service import NOW, create


@pytest.fixture
def service(world, monkeypatch):
    made = test_plan_zone_service.service.__wrapped__(world, monkeypatch)
    made.deliver_lock, made.rhythm_lock = threading.RLock(), threading.RLock()
    return made


def audits(store, kind):
    return [row for row in store.collection('audit_events').find({'type': kind})]


def due(service, plan, seq, ago=0):
    """DSH logs a firing of the plan's native record, `ago` seconds before NOW."""
    native = service.lane.events and next(e['data']['schedule'] for e in service.lane.events
                                          if e['data'].get('operation') == 'create'
                                          and e['data']['schedule']['prompt'] == 'ASUNA_PLAN:' + plan['_id'])
    service.lane.events.append({'seq': seq, 'data': {'operation': 'dispatch', 'id': native['id'],
                                                     'acceptedAt': (NOW - timedelta(seconds=ago)).isoformat()}})
    return native


def stale(service, plan):
    """The conversation's policy moved on since the plan was made: its firing cannot run (SCHEDULE_POLICY_STALE)."""
    current = plan_records.get(service.store, plan['_id'])
    plan_records.save(service.store, {**current, 'policy_epoch': 0}, expected=current['revision'], stream=plan['_id'])


def fire(service, plan, seq):
    native = due(service, plan, seq)
    creates = service._grouped(service.lane.events)[0]
    service._deliver(seq, native['id'], creates)


def her_line(service):
    return faults.plan_line(service.store, scene_records.get(service.store, 'dm-a'),
                            schedule_rules.her_zone(service.store.config))


def told(service, shown):
    faults.told(service.store, {'_id': 'ep-next', 'scene_id': 'dm-a', 'scope_key': 'scene:dm-a',
                                'manifest': {'told': {'plan_fault': shown}}})


def shown_now(service):
    mark = scene_records.get(service.store, 'dm-a')['plan_fault']
    return {key: mark.get(key) for key in ('at', 'count', 'plans')}


def test_a_firing_that_fails_on_the_worker_side_is_said_once_where_she_reads(service):
    first, second = create(service, 'one', {'after_seconds': 600}), create(service, 'two', {'after_seconds': 900})
    stale(service, first)
    stale(service, second)
    assert her_line(service) is None
    fire(service, first, 10)
    line = her_line(service)
    assert '「look」' in line and '没排上' in line and 'SCHEDULE_POLICY_STALE' in line, line
    assert '这条不再响了' in line, 'a one-off that did not run does not fire again, and she is told so'
    assert '一共' not in line
    fire(service, second, 11)
    shown = shown_now(service)
    assert '一共 2 次' in her_line(service)
    told(service, shown)
    assert her_line(service) is None and 'plan_fault' not in scene_records.get(service.store, 'dm-a')
    assert sorted(row['stream_id'] for row in audits(service.store, 'schedule.fault_told')) == \
        sorted([first['_id'], second['_id']]), 'each plan she was told about keeps a line that she was'
    notes = list(service.store.collection('developer_inbox').find({}))
    assert len(notes) == 1 and notes[0].get('count', 1) >= 1, 'the developer has one note per cause a day'


def test_a_failure_while_she_reads_is_neither_lost_nor_counted_twice(service):
    first, second = create(service, 'one', {'after_seconds': 600}), create(service, 'two', {'after_seconds': 900})
    stale(service, first)
    stale(service, second)
    fire(service, first, 10)
    shown = shown_now(service)            # her turn read the line here
    fire(service, second, 11)             # and this failed before that turn committed
    told(service, shown)
    mark = scene_records.get(service.store, 'dm-a')['plan_fault']
    assert mark['count'] == 1 and list(mark['plans']) == [second['_id']]
    assert '一共' not in her_line(service)


def test_a_logged_firing_never_handed_over_is_handed_on_by_the_watch_once(service, monkeypatch):
    received = []
    service.controller = type('Controller', (), {'receive': lambda self, event: received.append(event)})()
    plan = create(service, 'late', {'after_seconds': 600})
    due(service, plan, 20, ago=60)
    service.hand_on_late()
    assert received == [], 'a firing a live callback may still bring is left to it'
    service.lane.events.pop()
    due(service, plan, 20, ago=schedule.HANDOFF_LATE_SECONDS + 60)
    service.hand_on_late()
    service.hand_on_late()
    assert len(received) == 1, 'handed on once, however often the watch looks'
    late = received[0]['handed_late']
    assert late['why'] == schedule.HANDOFF_UNSEEN and late['due'].startswith('2026-09-24T04:5')
    line = faults.late_line(schedule_rules.her_zone(service.store.config), late['due'], late['handed'], late['why'])
    assert '才交到你手上' in line and schedule.HANDOFF_UNSEEN in line, line
    assert len(audits(service.store, 'schedule.handoff_late')) == 1


def test_the_development_plans_carry_the_fields_her_plan_view_shows(service, monkeypatch):
    service.controller = type('Controller', (), {'settings': {'scene_id': 'dm-a', 'person_id': 'A'}})()
    service._ensure_development_plan('plan-dev', 3600, 'grow')
    plan = plan_records.get(service.store, 'plan-dev')
    assert plan['native_recurring'] is True and plan['next_fire_at'] == '2026-09-25T07:00:00+00:00'
    # A record from before: live, without the two fields; completed, its count not back-filled.
    plan_records.save(service.store, {**plan, 'native_recurring': None, 'next_fire_at': None},
                      expected=plan['revision'], stream='plan-dev')
    service._ensure_development_plan('plan-dev', 3600, 'grow')
    plan = plan_records.get(service.store, 'plan-dev')
    assert plan['native_recurring'] is True and plan['next_fire_at'] and plan['fire_count_since'] == NOW.isoformat()
    assert 'fire_count' not in plan
