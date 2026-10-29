"""ADR-020 M1 on MongoDB: one running Host per database, across machines; a restart of the same deployment never
waits; the next start finds a lease the old one left behind (a Host taken away from outside). On a throwaway
database (conftest.py)."""
import time
from datetime import datetime, timedelta, timezone

import pytest

from asuna.host_lease import COLLECTION, LEASE_SECONDS, DatabaseLease, host_id, mark_planned
from asuna.state import Denied
from asuna.store.words import Set


def lease(store, folder, **kw):
    return DatabaseLease({'mongo_uri': store.config['mongo_uri'], 'database': store.name}, root=folder, **kw)


def test_another_deployment_is_refused_and_the_same_one_takes_over(store, tmp_path):
    here, there = tmp_path / 'here', tmp_path / 'there'
    with lease(store, here, persona='p-one'):
        with pytest.raises(Denied, match='DATABASE_IN_USE: p-one on '):
            lease(store, there, persona='p-two').acquire()
        again = lease(store, here).acquire()           # a replaced worker or recreated container: same host id
        again.adapter.close()
    assert store.collection(COLLECTION).count() == 0, 'released on exit'
    with lease(store, there):                          # free again
        pass
    assert host_id(here) == host_id(here) != host_id(there)


def test_a_lease_left_by_a_crash_expires(store, tmp_path):
    crashed = lease(store, tmp_path / 'crashed').acquire()          # never released: the process died
    crashed.adapter.close()
    with pytest.raises(Denied, match='DATABASE_IN_USE'):
        lease(store, tmp_path / 'other').acquire()
    store.collection(COLLECTION).update({'_id': 'host'}, Set({'expires_at': datetime(2000, 1, 1, tzinfo=timezone.utc)}))
    with lease(store, tmp_path / 'other', persona='next') as taken:
        assert store.collection(COLLECTION).get('host')['instance'] == taken.me


def test_the_lease_is_renewed_while_the_host_runs(store, tmp_path):
    with lease(store, tmp_path / 'x', renew_seconds=0.2):
        first = store.collection(COLLECTION).get('host')['expires_at']
        time.sleep(1.2)
        assert store.collection(COLLECTION).get('host')['expires_at'] > first


def test_a_lease_left_behind_is_found_and_a_clean_stop_leaves_none(store, tmp_path):
    with lease(store, tmp_path / 'h') as clean:
        assert clean.left_behind is None
    with lease(store, tmp_path / 'h') as again:
        assert again.left_behind is None, 'a clean stop deleted the lease'
    killed = lease(store, tmp_path / 'h').acquire()                 # dies without releasing
    killed.adapter.close()
    # The lease hands its times on in UTC without a zone (host_lease._utc); the store's read carries the zone.
    held = store.collection(COLLECTION).get('host')['expires_at'].replace(tzinfo=None)
    with lease(store, tmp_path / 'h') as next_start:
        assert next_start.left_behind == held - timedelta(seconds=LEASE_SECONDS) and not next_start.planned
    killed = lease(store, tmp_path / 'h').acquire()
    killed.adapter.close()
    assert mark_planned({'mongo_uri': store.config['mongo_uri'], 'database': store.name}, 'developer')
    with lease(store, tmp_path / 'h') as after_deploy:
        assert after_deploy.planned, 'a deploy marked its restart before killing the Host'
        assert 'planned_stop' not in store.collection(COLLECTION).get('host'), 'the new Host starts unmarked'
