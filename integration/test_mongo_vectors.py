"""The MongoDB adapter's vector search against a real server: `Store.ensure_vectors` and `Store.nearest` on a throwaway
`asuna_v2_test_*` database of 301 synthetic records, dropped at the end, failures included. It checks that the
adapter meets the interface, not the server's capacity: one small index, a few hundred queries."""
import json
import math
import random
import secrets
import time
from pathlib import Path

import pytest
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from asuna.state import Space, Store

ROOT = Path(__file__).resolve().parents[1]
DIM = 16
SPACE = Space(name='integration_vectors', collection='units', path='embedding', dimensions=DIM,
              fields=('scope_key', 'policy_epoch', 'status', 'kind'))
CASES = [
    ('no filter', {}, lambda r: True),
    ('value', {'status': 'active'}, lambda r: r['status'] == 'active'),
    ('list', {'scope_key': ['s1', 's3']}, lambda r: r['scope_key'] in ('s1', 's3')),
    ('pairs', {('scope_key', 'policy_epoch'): [('s0', 1), ('s2', 1), ('s4', 2)], 'status': 'active'},
     lambda r: (r['scope_key'], r['policy_epoch']) in {('s0', 1), ('s2', 1), ('s4', 2)} and r['status'] == 'active'),
    ('pairs and kind', {('scope_key', 'policy_epoch'): [('s1', 2), ('s3', 2)], 'kind': 'monologue'},
     lambda r: (r['scope_key'], r['policy_epoch']) in {('s1', 2), ('s3', 2)} and r['kind'] == 'monologue'),
]


def unit(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


def brute(rows, vector, keep):
    q = unit(vector)
    scored = [(row['_id'], sum(a * b for a, b in zip(q, unit(row['embedding'])))) for row in rows if keep(row)]
    return sorted(scored, key=lambda hit: (-hit[1], hit[0]))


@pytest.fixture(scope='module')
def world():
    path = ROOT / 'config' / 'local.json'
    if not path.exists():
        pytest.skip('no config/local.json: no MongoDB server named')
    config = json.loads(path.read_text(encoding='utf-8'))
    try:
        MongoClient(config['mongo_uri'], serverSelectionTimeoutMS=3000).admin.command('ping')
    except PyMongoError:
        pytest.skip('MongoDB is not reachable')
    name = 'asuna_v2_test_integration_' + secrets.token_hex(6)
    store = Store(config, name)
    rng = random.Random(10428)
    rows = [{'_id': 'u%03d' % n, 'embedding': [rng.uniform(-1, 1) for _ in range(DIM)], 'scope_key': 's%d' % (n % 5),
             'policy_epoch': 1 + n % 2, 'status': 'active' if n % 7 else 'forgotten',
             'kind': 'monologue' if n % 3 == 0 else 'turn'} for n in range(300)]
    rows.append(dict(rows[10], _id='u999'))         # an identical vector: a tie
    try:
        store.db.units.insert_many([dict(r) for r in rows])
        # Made first with fewer filter fields, so the next ensure_vectors has to bring it up to the space's.
        assert store.ensure_vectors(Space(SPACE.name, SPACE.collection, SPACE.path, DIM, ('scope_key',)), timeout=120)
        assert store.ensure_vectors(SPACE, timeout=180)
        until = time.monotonic() + 120              # an updated index may serve its old definition for a moment
        while True:
            try:
                store.nearest(SPACE, rows[0]['embedding'], 3, {'kind': 'turn'})
                break
            except PyMongoError:
                if time.monotonic() > until:
                    raise
                time.sleep(1)
        yield store, rows, [rows[10]['embedding']] + [[rng.uniform(-1, 1) for _ in range(DIM)] for _ in range(9)]
    finally:
        store.client.drop_database(name)
        assert name not in store.client.list_database_names()
        store.client.close()


def test_the_index_is_brought_up_to_the_space(world):
    store, _, _ = world
    index = list(store.db.units.list_search_indexes(SPACE.name))[0]
    assert {f['path'] for f in index['latestDefinition']['fields'] if f['type'] == 'filter'} == set(SPACE.fields)


@pytest.mark.parametrize('label,where,keep', CASES, ids=[c[0] for c in CASES])
@pytest.mark.parametrize('k', (1, 12, 24))
def test_nearest_is_exact_cosine(world, label, where, keep, k):
    store, rows, queries = world
    for q in queries:
        got, everything = store.nearest(SPACE, q, k, where), brute(rows, q, keep)
        want = everything[:k]
        assert len(got) == len(want) and all(abs(a - b) < 1e-4 for (_, a), (_, b) in zip(got, want))
        last = want[-1][1]
        tied = {i for i, s in everything if abs(s - last) < 1e-4}
        # Above the k-th score the same records in id order; at it, any of the records tied there.
        assert all(g == w if s > last + 1e-4 else g in tied for (g, _), (w, s) in zip(got, want))


def test_ties_come_in_id_order(world):
    store, rows, _ = world
    assert [i for i, _ in store.nearest(SPACE, rows[10]['embedding'], 2, {})] == ['u010', 'u999']


def test_empty_any_of_matches_nothing_and_bad_queries_are_refused(world):
    store, _, queries = world
    assert store.nearest(SPACE, queries[1], 5, {('scope_key', 'policy_epoch'): []}) == []
    for where, vector, k in (({'body': 'x'}, queries[1], 5), ({}, queries[1][:3], 5), ({}, [0.0] * DIM, 5),
                             ({}, queries[1], 0), ({}, queries[1], 101)):
        with pytest.raises(ValueError):
            store.nearest(SPACE, vector, k, where)
