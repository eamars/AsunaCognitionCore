"""The store's contract (store_contract.py) on the MongoDB adapter against a real server, and the cases only a server
can show: the races (R, real processes).

Each case runs on a throwaway `asuna_v2_test_*` database of synthetic records, dropped at the end, failures included;
everything skips when no server is named or it cannot be reached (conftest.py). Nothing here prints the server's
address.
"""
import contextlib
import json
import os
import secrets
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from asuna.store import Checked, adapters, mongodb
import store_contract
from store_contract import CATALOG

globals().update({name: getattr(store_contract, name) for name in store_contract.__all__})   # its cases and fixtures
ROOT = Path(__file__).resolve().parents[1]
WORKER = Path(__file__).with_name('store_race_worker.py')


@pytest.fixture(scope='session')
def server(settings):
    return {'database_adapter': 'mongodb', **settings}


@contextlib.contextmanager
def _throwaway(settings):
    name = adapters.TEST_PREFIX + 'contract_' + secrets.token_hex(6)
    adapter = adapters.open(settings, name)
    try:
        yield Checked(adapter, CATALOG), name
    finally:
        adapter.close()
        adapters.drop(settings, name)
        assert name not in mongodb.databases(settings)


@pytest.fixture(scope='session')
def open_store(server):
    @contextlib.contextmanager
    def opened():
        with _throwaway(server) as (store, _):
            yield store
    return opened


# R: races, each between real processes on one throwaway database.

def _race(settings, race, name, workers):
    start = time.time() + 3
    env = {**os.environ, 'ASUNA_RACE_SETTINGS': json.dumps(settings), 'PYTHONPATH': str(ROOT / 'src')}
    running = [subprocess.Popen([sys.executable, str(WORKER), race, name, str(start), str(n)], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for n in range(workers)]
    results = []
    for process in running:
        out, err = process.communicate(timeout=180)
        assert process.returncode == 0, err[-800:]
        results.append(json.loads(out.strip().splitlines()[-1]))
    return results


def test_R01_the_counter_across_four_processes(server):
    with _throwaway(server) as (store, name):
        store.ensure()
        store.collection('things').insert({'_id': 'counter', 'rank': 0})
        got = [n for part in _race(server, 'counter', name, 4) for n in part]
        assert sorted(got) == list(range(1, 201))


def test_R02_six_claimers_never_take_one_item_twice(server):
    with _throwaway(server) as (store, name):
        store.ensure()
        store.collection('keyed').insert([{'_id': 'q%02d' % n, 'platform': 'p', 'account': str(n), 'state': 'queued',
                                           'order': n} for n in range(60)])
        got = [item for part in _race(server, 'claim', name, 6) for item in part]
        assert sorted(got) == ['q%02d' % n for n in range(60)]


def test_R03_two_holders_of_an_expired_lease_one_wins(server):
    with _throwaway(server) as (store, name):
        store.ensure()
        store.collection('leases').insert({'_id': 'host', 'instance': 'gone',
                                           'expires_at': datetime.now(timezone.utc) - timedelta(minutes=5)})
        got = sorted(outcome for part in _race(server, 'lease', name, 2) for outcome in part)
        assert got == ['refused', 'taken']
        assert store.collection('leases').get('host')['instance'].startswith('holder-')


def test_R04_two_writers_at_one_revision_one_writes(server):
    with _throwaway(server) as (store, name):
        store.ensure()
        store.collection('keyed').insert({'_id': 'k', 'platform': 'p', 'account': '1', 'revision': 1})
        got = [written for part in _race(server, 'revision', name, 2) for written in part]
        assert sorted(got) == [False, True]
        assert store.collection('keyed').get('k')['revision'] == 2
