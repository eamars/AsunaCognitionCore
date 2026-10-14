"""Her plan list shows the time a plan was armed for (Xiaoman's report 2026-10-11): an "after N seconds" plan used to
be recomputed from the moment of reading, so its due time moved later at every look."""
from datetime import datetime, timedelta, timezone

from asuna import schedule_rules

ZONE = {'tz': timezone.utc, 'name': 'UTC', 'zone_unavailable': None}
ARMED = datetime(2026, 10, 11, 5, 11, 20, tzinfo=timezone.utc)


def test_an_after_plan_keeps_the_time_it_was_armed_for():
    due = ARMED + timedelta(seconds=1800)
    plan = {'_id': 'p', 'intent': '看一眼', 'status': 'ACTIVE', 'rule': {'after_seconds': 1800},
            'next_fire_at': due.isoformat(timespec='seconds')}
    for later in (0, 480, 720):
        row = schedule_rules.project(plan, ZONE, ARMED + timedelta(seconds=later))
        assert row['next_fire_at'] == due.isoformat(timespec='seconds')
    # a native time written with Z reads the same
    assert schedule_rules.project({**plan, 'next_fire_at': '2026-10-11T05:41:20Z'}, ZONE, ARMED)['next_fire_at'] \
        == due.isoformat(timespec='seconds')
    # without a stored time (an old record) it is still computed
    assert schedule_rules.project({**plan, 'next_fire_at': None}, ZONE, ARMED)['next_fire_at'] == due.isoformat(timespec='seconds')


def test_a_rules_local_time_reads_the_same_as_its_next_firing():
    """A rule's `at` is her local wall time: shown with its zone, the edge reads it as that time, not as UTC."""
    from zoneinfo import ZoneInfo
    from asuna import local_time
    zone = {'tz': ZoneInfo('Pacific/Auckland'), 'name': 'Pacific/Auckland', 'zone_unavailable': None}
    plan = {'_id': 'p', 'intent': 'x', 'status': 'ACTIVE', 'rule': {'at': '2026-10-14T21:30'},
            'next_fire_at': '2026-10-14T08:30:00+00:00'}
    shown = local_time.for_model(schedule_rules.project(plan, zone, datetime(2026, 10, 14, 1, tzinfo=timezone.utc)), zone)
    fire = local_time.face(datetime(2026, 10, 14, 8, 30, tzinfo=timezone.utc), zone['tz'])
    assert 'rule' not in shown and shown['next_fire_at'] == fire and shown['description'] == '一次性：' + fire
