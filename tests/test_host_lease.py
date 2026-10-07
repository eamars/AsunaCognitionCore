"""ADR-020 M1: one running Host per database, across machines; a restart of the same deployment never waits."""
import datetime

import pytest

from asuna.host_lease import COLLECTION, DatabaseLease, host_id
from asuna.state import Denied


def lease(store, folder, **kw):
    return DatabaseLease({'mongo_uri': store.config['mongo_uri'], 'database': store.name}, root=folder, **kw)


def test_another_deployment_is_refused_and_the_same_one_takes_over(store, tmp_path):
    here, there = tmp_path / 'here', tmp_path / 'there'
    with lease(store, here, persona='kazusa'):
        with pytest.raises(Denied, match='DATABASE_IN_USE: kazusa on '):
            lease(store, there, persona='xiaoman').acquire()
        again = lease(store, here).acquire()           # a replaced worker or recreated container: same host id
        again.client.close()
    assert store.db[COLLECTION].count_documents({}) == 0, 'released on exit'
    with lease(store, there):                          # free again
        pass
    assert host_id(here) == host_id(here) != host_id(there)


def test_a_lease_left_by_a_crash_expires(store, tmp_path):
    crashed = lease(store, tmp_path / 'crashed').acquire()          # never released: the process died
    crashed.client.close()
    with pytest.raises(Denied, match='DATABASE_IN_USE'):
        lease(store, tmp_path / 'other').acquire()
    store.db[COLLECTION].update_one({'_id': 'host'}, {'$set': {'expires_at': datetime.datetime(2000, 1, 1)}})
    with lease(store, tmp_path / 'other', persona='next') as taken:
        assert store.db[COLLECTION].find_one({'_id': 'host'})['instance'] == taken.me


def test_the_lease_is_renewed_while_the_host_runs(store, tmp_path):
    with lease(store, tmp_path / 'x', renew_seconds=0.2):
        first = store.db[COLLECTION].find_one({'_id': 'host'})['expires_at']
        import time
        time.sleep(1.2)
        assert store.db[COLLECTION].find_one({'_id': 'host'})['expires_at'] > first
