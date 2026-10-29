"""The host lease and the lane fault counts against a real server: the unit run's own tests of them
(tests/test_host_lease.py, the lease's test in tests/test_host_stops.py, tests/test_lane_faults.py), which the
in-process stand-in cannot carry (the lease is written on the server's clock), each on a throwaway `asuna_v2_test_*`
database, dropped at the end, failures included."""
import json
import secrets
import sys
from pathlib import Path

import pytest
from pymongo import MongoClient
from pymongo.errors import PyMongoError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))

from asuna.state import Store  # noqa: E402
import test_host_lease  # noqa: E402
import test_host_stops  # noqa: E402
import test_lane_faults  # noqa: E402

for module in (test_host_lease, test_lane_faults):
    globals().update({name: getattr(module, name) for name in dir(module) if name.startswith('test_')})
test_a_lease_left_behind_is_found_and_a_clean_stop_leaves_none = (
    test_host_stops.test_a_lease_left_behind_is_found_and_a_clean_stop_leaves_none)


@pytest.fixture
def store():
    path = ROOT / 'config' / 'local.json'
    if not path.exists():
        pytest.skip('no config/local.json: no MongoDB server named')
    config = json.loads(path.read_text(encoding='utf-8'))
    try:
        MongoClient(config['mongo_uri'], serverSelectionTimeoutMS=3000).admin.command('ping')
    except PyMongoError:
        pytest.skip('MongoDB is not reachable')
    name = 'asuna_v2_test_integration_' + secrets.token_hex(6)
    opened = Store(config, name)
    try:
        opened.ensure()
        yield opened
    finally:
        opened.client.drop_database(name)
        assert name not in opened.client.list_database_names()
        opened.client.close()
