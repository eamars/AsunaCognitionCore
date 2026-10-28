"""The store's contract (store_contract.py) in the unit run, on two adapters: `[memory]`, the in-memory adapter, the
reference of the meaning table; and `[stand-in]`, the MongoDB adapter over the unit run's in-process stand-in. A case
the stand-in answers otherwise is listed in harness_skips.txt by its `[stand-in]` id only (the collection refuses a
line that would skip a `[memory]` case); the integration run on MongoDB decides it. Here too the cases only the
in-memory adapter has: its shuffled ties (O05) and its injected clock.

Ties are shuffled with one seed per run, printed with every failure; `ASUNA_STORE_SEED=<seed>` repeats a run's order.
"""
import contextlib
import os
import random
import uuid
from datetime import datetime, timedelta, timezone

import pymongo
import pytest

from asuna.store import Checked, adapters, memory
from asuna.store.mongodb import MongoAdapter
from asuna.store.words import Now, Range, Set
import conftest
import store_contract
from store_contract import CATALOG

globals().update({name: getattr(store_contract, name) for name in store_contract.__all__})   # its cases and fixtures
SEED = int(os.environ.get('ASUNA_STORE_SEED') or random.SystemRandom().randrange(2 ** 32))
adapters.register(memory)


@pytest.fixture(scope='session', params=['memory', 'stand-in'])
def adapter(request):
    """Which adapter the contract runs on: the in-memory reference, or the MongoDB adapter over the stand-in."""
    return request.param


@pytest.fixture(scope='session')
def open_store(adapter):
    client = None
    if adapter == 'stand-in':
        client = pymongo.MongoClient(conftest.NO_SERVER)
        assert getattr(client, 'unit_run', False), 'the stand-in is not loaded: this run could reach a server'

    @contextlib.contextmanager
    def opened():
        name = 'asuna_v2_test_contract_' + uuid.uuid4().hex[:12]
        if client is not None:
            try:
                yield Checked(MongoAdapter(client, name), CATALOG)
            finally:
                client.drop_database(name)
            return
        print('in-memory adapter, tie seed %d (ASUNA_STORE_SEED=%d repeats it)' % (SEED, SEED))
        try:
            yield Checked(adapters.open({'database_adapter': 'memory', 'seed': SEED}, name), CATALOG)
        finally:
            adapters.drop({'database_adapter': 'memory'}, name)
            assert name not in memory.databases({})
    yield opened
    if client is not None:
        client.close()


class _Item:
    def __init__(self, nodeid, adapter=None):
        self.nodeid, self.marks = nodeid, []
        if adapter:
            self.callspec = type('Callspec', (), {'params': {'adapter': adapter}})()

    def add_marker(self, mark):
        self.marks.append(mark)


def test_a_skip_line_skips_only_the_test_it_equals_and_never_the_reference():
    case = 'tests/test_store_contract.py::TestW::test_W01_x'
    items = [_Item(case + '[memory]', 'memory'), _Item(case + '[stand-in]', 'stand-in'),
             _Item('tests/test_other.py::test_once')]
    conftest.apply_harness_skips({case + '[stand-in]': 'x'}, items, whole=True)
    assert [bool(item.marks) for item in items] == [False, True, False]
    with pytest.raises(pytest.UsageError, match='HARNESS_SKIP_HITS_THE_REFERENCE'):
        conftest.apply_harness_skips({case + '[memory]': 'x'}, items, whole=True)
    for nothing in (case, 'tests/test_other.py::test_gone'):
        with pytest.raises(pytest.UsageError, match='HARNESS_SKIP_NOT_A_TEST'):
            conftest.apply_harness_skips({nothing: 'x'}, items, whole=True)


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
