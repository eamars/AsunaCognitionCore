"""The channel lanes' fault counts (ADR-095 step 1, lane_faults.py), where they are removed: old counts leave on the
next write, and a sweep that fails never changes what a post counted (each count written once, the failure in the
audit). On the unit run's store (conftest.py)."""
from datetime import datetime, timedelta, timezone

from asuna import audit, lane_faults
from asuna.store.errors import Unavailable

NOW = datetime.now(timezone.utc)
HOUR = lane_faults.hour_of(NOW)


def row(**over):
    return {'lane': 'inbound', 'stage': 'post', 'error': 'host_error:500', 'hour': HOUR, 'count': 1, **over}


def counts(store):
    return list(store.collection('lane_faults').find())


def test_a_failing_cleanup_never_changes_the_counts_answer(store, monkeypatch):
    def unavailable(store, now=None):
        raise Unavailable('DATABASE_UNAVAILABLE: cleanup')
    monkeypatch.setattr(lane_faults, 'forget_old', unavailable)
    assert lane_faults.receive(store, 'qq', {'counts': [row(count=2)]}) == {'status': 'recorded', 'rows': 1}
    lane_faults.record(store, 'qq', 'inbound', 'post', 'other')
    assert sorted((doc['error'], doc['count']) for doc in counts(store)) == [
        ('host_error:500', 2), ('other', 1)], 'each count written once, and nothing else in the counts'
    failed = sorted(audit.events(store, 'lane_faults.forget_failed').rows(), key=lambda e: e['payload']['path'])
    assert [(event['payload']['path'], event['payload']['error']) for event in failed] == [
        ('receive', 'DATABASE_UNAVAILABLE'), ('record', 'DATABASE_UNAVAILABLE')]
    cutoffs = [datetime.fromisoformat(event['payload']['cutoff']) for event in failed]
    assert all(abs(cutoff - (datetime.now(timezone.utc) - timedelta(days=lane_faults.KEEP_DAYS))) < timedelta(minutes=1)
               for cutoff in cutoffs)


def test_the_hosts_own_lanes_are_known_and_counted(store):
    """Every lane the Host counts in is in the list the readers know (the data child's, the tool watchdog's)."""
    from asuna import media_children
    for lane in (*media_children.FAULT_LANES.values(), 'tools'):
        assert lane in lane_faults.LANES
        lane_faults.record(store, 'host', lane, 'stage', 'error')
    assert sorted(doc['lane'] for doc in counts(store)) == sorted({*media_children.FAULT_LANES.values(), 'tools'})


def test_counts_leave_after_their_days_on_the_next_write(store):
    now = datetime.now(timezone.utc)
    lane_faults.record(store, 'qq', 'inbound', 'post', 'old', moment=now - timedelta(days=lane_faults.KEEP_DAYS, hours=2))
    lane_faults.record(store, 'qq', 'inbound', 'post', 'kept', moment=now - timedelta(days=lane_faults.KEEP_DAYS - 1))
    assert [doc['error'] for doc in counts(store)] == ['kept']
