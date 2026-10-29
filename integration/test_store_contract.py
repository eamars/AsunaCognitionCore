"""The store's contract (tests/store_contract.py) on the MongoDB adapter against a real server, and the cases only a
server can show: the races (R, real processes) and the differential (D: generated conditions answered by MongoDB and
by the in-memory adapter, order included).

Each case runs on a throwaway `asuna_v2_test_*` database of synthetic records, dropped at the end, failures included;
everything skips when no server is named or it cannot be reached. Nothing here prints the server's address.
"""
import contextlib
import json
import os
import random
import secrets
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st
from pymongo import MongoClient
from pymongo.errors import PyMongoError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))

from asuna.store import Checked, adapters, memory, mongodb  # noqa: E402
from asuna.store.words import (And, AnyOf, Contains, Each, Exists, Holds, HoldsAny, IsNull, NonEmpty,  # noqa: E402
                               NoneOf, Not, Or, Range, StartsWith)
import store_contract  # noqa: E402
from store_contract import CATALOG  # noqa: E402

globals().update({name: getattr(store_contract, name) for name in store_contract.__all__})   # its cases and fixtures
adapters.register(mongodb)
WORKER = Path(__file__).with_name('store_race_worker.py')


def _settings():
    path = ROOT / 'config' / 'local.json'
    if not path.exists():
        pytest.skip('no config/local.json: no MongoDB server named')
    config = json.loads(path.read_text(encoding='utf-8'))
    try:
        MongoClient(config['mongo_uri'], serverSelectionTimeoutMS=3000).admin.command('ping')
    except PyMongoError:
        pytest.skip('MongoDB is not reachable')
    return {'database_adapter': 'mongodb', 'mongo_uri': config['mongo_uri']}


@pytest.fixture(scope='session')
def server():
    return _settings()


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


# D: the differential.

TIMES = [datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=h) for h in range(4)]
NAMES = ['', 'a', 'A', 'ab', 'abc', 'b', 'B.x', 'é', '中', 'Ab']


def _records(seed=10428, count=200):
    """Synthetic records: missing fields, nulls, empty lists, many equal sort keys."""
    rng = random.Random(seed)
    rows = []
    for n in range(count):
        row = {'_id': 'd%03d' % n}
        for path, values in (('name', NAMES), ('n', [None, 0, 1, 1.0, 2, -3.5]), ('flag', [True, False]),
                             ('at', TIMES), ('note', [None, 'x', 'y']), ('rank', [0, 1, 2])):
            if rng.random() < 0.75:
                row[path] = rng.choice(values)
        if rng.random() < 0.8:
            row['tags'] = rng.sample(['x', 'y', 'z'], rng.randint(0, 3))
        if rng.random() < 0.6:
            row['meta'] = {k: v for k, v in (('kind', rng.choice([None, 'k1', 'k2'])), ('size', rng.randint(0, 3)))
                           if rng.random() < 0.7}
        if rng.random() < 0.6:
            row['sources'] = [{'scene_id': rng.choice(['s1', 's2']), 'seq': rng.randint(0, 2)}
                              for _ in range(rng.randint(0, 3))]
        rows.append(row)
    return rows


VALUE = {'name': st.sampled_from(NAMES[1:]), 'n': st.sampled_from([0, 1, 2.0, -3.5]), 'flag': st.booleans(),
         'at': st.sampled_from(TIMES), 'note': st.sampled_from(['x', 'y']), 'rank': st.sampled_from([0, 1, 2]),
         'meta.kind': st.sampled_from(['k1', 'k2']), 'meta.size': st.integers(0, 3)}
NULLABLE = ('n', 'note', 'meta.kind')
ORDERED = ('name', 'n', 'at', 'note', 'rank', 'meta.size')


def _word(path):
    value = VALUE[path]
    words = [value, value.map(Not), st.lists(value, max_size=3).map(AnyOf), st.lists(value, max_size=3).map(NoneOf),
             st.booleans().map(Exists)]
    if path in NULLABLE:
        words.append(st.just(IsNull()))
    if path in ORDERED:
        words.append(st.builds(lambda a, b: Range(gte=a, lt=b), value, value))
        words.append(value.map(lambda v: Range(gt=v)))
    if path in ('name', 'note'):
        words.append(st.sampled_from(['a', 'A', 'b', '.', 'x']).map(StartsWith))
        words.append(st.builds(Contains, st.sampled_from(['a', 'B', 'É', 'x']), st.booleans()))
    return st.one_of(words)


LEAF = st.one_of(
    st.just({}),
    *[_word(path).map(lambda w, p=path: {p: w}) for path in sorted(VALUE)],
    st.sampled_from(['x', 'y', 'z']).map(lambda v: {'tags': Holds(v)}),
    st.lists(st.sampled_from(['x', 'y', 'z']), max_size=2).map(lambda vs: {'tags': HoldsAny(vs)}),
    st.just({'tags': NonEmpty()}),
    st.builds(lambda s, q: {'sources': Each({'scene_id': s, 'seq': Range(gte=q)})}, st.sampled_from(['s1', 's2']),
              st.integers(0, 2)),
)
WHERE = st.recursive(LEAF, lambda inner: st.one_of(st.lists(inner, min_size=1, max_size=3).map(lambda b: Or(*b)),
                                                   st.lists(inner, max_size=3).map(lambda b: And(*b))), max_leaves=6)
SORT = st.sampled_from([(), (('rank', 1),), (('n', -1),), (('note', 1), ('at', -1)), (('name', 1),)])


@pytest.fixture(scope='module')
def both(server):
    with _throwaway(server) as (store, _):
        store.ensure(['things'])
        double = Checked(memory.MemoryAdapter(), CATALOG)
        double.ensure(['things'])
        rows = _records()
        store.collection('things').insert([dict(r) for r in rows])
        double.collection('things').insert([dict(r) for r in rows])
        yield store.collection('things'), double.collection('things')


@settings(max_examples=100, derandomize=True, database=None, deadline=None,
          suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow])
@given(where=WHERE, sort=SORT)
def test_D01_mongodb_answers_as_the_double(both, where, sort):
    mongo, double = both
    order = [*sort, ('_id', 1)]
    assert [r['_id'] for r in mongo.find(where, sort=order)] == [r['_id'] for r in double.find(where, sort=order)]
    assert mongo.count(where) == double.count(where)
