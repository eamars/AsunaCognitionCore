"""What `ensure` and `ensure_vectors` do on a real server, each on a throwaway `asuna_v2_test_*` database, dropped at
the end, failures included: the fault counts' TTL index as B1b's catalog makes it and as B2's drops it once
`lane_faults.forget_old` takes over; the old vector index still answering while its filter fields change; a new index
that is not ready yet answering False."""
import contextlib
import json
import random
import secrets
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pymongo import MongoClient
from pymongo.errors import PyMongoError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))

from asuna import lane_faults  # noqa: E402
from asuna.store import Checked, mongodb  # noqa: E402
from asuna.store.catalog import CATALOG, Catalog, Collection, Space, index  # noqa: E402
import store_contract  # noqa: E402

TTL = 'hour_at_1'


@pytest.fixture(scope='module')
def settings():
    path = ROOT / 'config' / 'local.json'
    if not path.exists():
        pytest.skip('no config/local.json: no MongoDB server named')
    config = json.loads(path.read_text(encoding='utf-8'))
    try:
        MongoClient(config['mongo_uri'], serverSelectionTimeoutMS=3000).admin.command('ping')
    except PyMongoError:
        pytest.skip('MongoDB is not reachable')
    return {'mongo_uri': config['mongo_uri']}


@contextlib.contextmanager
def throwaway(settings):
    name = 'asuna_v2_test_integration_' + secrets.token_hex(6)
    adapter = mongodb.open(settings, name)
    try:
        yield adapter
    finally:
        adapter.close()
        mongodb.drop(settings, name)
        assert name not in mongodb.databases(settings)


def b1b_lane_faults():
    """`lane_faults` as B1b's catalog declared it: today's indexes and the TTL index on the hour."""
    today = CATALOG.collection('lane_faults')
    return Collection('lane_faults', 'lane_faults', today.fields,
                      (*today.indexes, index(('hour_at', 1), expire_after=30 * 86400)), versioned=True)


def test_a_fresh_database_gets_todays_ttl_index_from_b1bs_catalog(settings):
    with throwaway(settings) as adapter:
        made = Checked(adapter, Catalog([b1b_lane_faults()])).ensure()
        assert TTL in made['lane_faults'].indexes_made
        info = adapter.db.lane_faults.index_information()[TTL]
        assert [tuple(key) for key in info['key']] == [('hour_at', 1)] and info['expireAfterSeconds'] == 30 * 86400


def test_b2s_ensure_drops_it_and_forget_old_takes_over(settings):
    with throwaway(settings) as adapter:
        Checked(adapter, Catalog([b1b_lane_faults()])).ensure()
        store = Checked(adapter, CATALOG)
        assert store.ensure(['lane_faults'])['lane_faults'].dropped == (TTL,)
        assert TTL not in adapter.db.lane_faults.index_information()
        assert store.ensure(['lane_faults'])['lane_faults'].dropped == ()
        now = datetime.now(timezone.utc)
        for error, moment in (('old', now - timedelta(days=lane_faults.KEEP_DAYS, hours=2)),
                              ('kept', now - timedelta(days=lane_faults.KEEP_DAYS - 1))):
            lane_faults.record(store, 'qq', 'inbound', 'post', error, moment=moment)
        assert [row['error'] for row in adapter.db.lane_faults.find()] == ['kept']


def _units(store, count=60):
    rng = random.Random(7)
    rows = [{'_id': 'u%03d' % n, 'embedding': [rng.uniform(-1, 1) for _ in range(store_contract.DIM)],
             'scope_key': 's%d' % (n % 3), 'policy_epoch': 1, 'status': 'active', 'kind': 'turn'}
            for n in range(count)]
    store.collection('units').insert(rows)
    return rows


def test_a_new_index_that_is_not_ready_answers_false(settings):
    with throwaway(settings) as adapter:
        store = Checked(adapter, store_contract.CATALOG)
        store.ensure(['units'])
        _units(store)
        assert store.ensure_vectors(store_contract.SPACE, timeout=0) is False


def test_the_old_index_answers_while_its_filter_fields_change(settings):
    small = Space(store_contract.SPACE.name, 'units', 'embedding', store_contract.DIM, ('scope_key',))
    with throwaway(settings) as adapter:
        store = Checked(adapter, store_contract.CATALOG)
        store.ensure(['units'])
        rows = _units(store)
        assert store.ensure_vectors(small, timeout=180)
        query = rows[0]['embedding']
        want = [i for i, _ in store_contract.brute(rows, query, lambda r: r['scope_key'] == 's1')[:5]]
        store.ensure_vectors(store_contract.SPACE, timeout=0)          # the new definition starts building
        assert [i for i, _ in store.nearest(small, query, 5, {'scope_key': 's1'})] == want
        until = time.monotonic() + 180
        while True:                                                     # then the new fields answer too
            try:
                got = store.nearest(store_contract.SPACE, query, 5, {'kind': 'turn', 'scope_key': 's1'})
                break
            except PyMongoError:
                if time.monotonic() > until:
                    raise
                time.sleep(1)
        assert [i for i, _ in got] == want
