"""ADR-020 M1 on MongoDB: the host lease's claim is atomic on the server, with each lease on a client of its own. While
one deployment holds it another is refused and the same one takes it over; a lease left by a crash is taken by the
next holder once it expires. On the module's throwaway database (conftest.py)."""
from datetime import datetime, timezone

import pytest

from asuna.host_lease import COLLECTION, DatabaseLease
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


def test_a_lease_left_by_a_crash_expires(store, tmp_path):
    crashed = lease(store, tmp_path / 'crashed').acquire()          # never released: the process died
    crashed.adapter.close()
    with pytest.raises(Denied, match='DATABASE_IN_USE'):
        lease(store, tmp_path / 'other').acquire()
    store.collection(COLLECTION).update({'_id': 'host'}, Set({'expires_at': datetime(2000, 1, 1, tzinfo=timezone.utc)}))
    with lease(store, tmp_path / 'other', persona='next') as taken:
        assert store.collection(COLLECTION).get('host')['instance'] == taken.me
