"""The store's contract (store_contract.py) on the in-memory adapter, and the cases only the in-memory adapter has:
its shuffled ties (O05) and its injected clock.

Ties are shuffled with one seed per run, printed with every failure; `ASUNA_STORE_SEED=<seed>` repeats a run's order.
"""
import contextlib
import os
import random
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from asuna.store import Checked, adapters, memory
from asuna.store.words import Now, Range, Set
import store_contract
from store_contract import CATALOG

globals().update({name: getattr(store_contract, name) for name in store_contract.__all__})   # its cases and fixtures
SEED = int(os.environ.get('ASUNA_STORE_SEED') or random.SystemRandom().randrange(2 ** 32))
adapters.register(memory)


@pytest.fixture(scope='session')
def open_store():
    @contextlib.contextmanager
    def opened():
        name = 'asuna_v2_test_contract_' + uuid.uuid4().hex[:12]
        print('in-memory adapter, tie seed %d (ASUNA_STORE_SEED=%d repeats it)' % (SEED, SEED))
        try:
            yield Checked(adapters.open({'database_adapter': 'memory', 'seed': SEED}, name), CATALOG)
        finally:
            adapters.drop({'database_adapter': 'memory'}, name)
            assert name not in memory.databases({})
    return opened


def test_O05_the_double_shuffles_ties_and_its_seed_repeats_them():
    def order(seed):
        store = Checked(memory.MemoryAdapter(seed=seed), CATALOG)
        store.ensure()
        store.collection('things').insert([{'_id': 't%02d' % n, 'rank': 1} for n in range(30)])
        return [row['_id'] for row in store.collection('things').find({}, sort=[('rank', 1)])]
    assert order(1) == order(1) and order(2) == order(2)
    assert order(1) != order(2) and sorted(order(1)) == sorted(order(2))


def test_the_double_reads_now_from_its_injected_clock():
    moment = [datetime(2026, 5, 6, 7, 8, 9, tzinfo=timezone.utc)]
    store = Checked(memory.MemoryAdapter(clock=lambda: moment[0], seed=SEED), CATALOG)
    store.ensure()
    leases = store.collection('leases')
    leases.insert({'_id': 'host', 'instance': 'a', 'since': Now(), 'expires_at': Now(30)})
    assert leases.get('host')['expires_at'] == moment[0] + timedelta(seconds=30)
    take = Set({'instance': 'b', 'since': Now()})
    assert leases.update({'_id': 'host', 'expires_at': Range(lt=Now())}, take).matched == 0
    moment[0] += timedelta(seconds=31)
    assert leases.update({'_id': 'host', 'expires_at': Range(lt=Now())}, take).matched == 1
    assert leases.get('host')['since'] == moment[0] and leases.get('host')['instance'] == 'b'
