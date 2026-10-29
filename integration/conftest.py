"""What every integration test shares: one throwaway `asuna_v2_test_*` database per test module, on the server the
checkout's config/local.json names, reached through the store's adapter registry (`asuna.store.adapters`), and
dropped when the module ends, failures included. An integration test checks only that the MongoDB adapter keeps the
interface's promises on a real server, with a few synthetic records a case, so it never loads the server.

`settings` (session): the registry's settings for that server, from the address in config/local.json and nothing else
of it; every test that takes it skips when no server is named or the server does not answer. `database` (module):
(the module's database name, the driver's handle on it). `emptied(settings, database)`: the shared layer over the
module's database with every collection dropped first (their indexes with them). `store`: a `Store` on the module's
database, emptied the same way, every declared collection made. Nothing here prints the server's address.
"""
import contextlib
import json
import re
import secrets
from pathlib import Path

import pytest
from pymongo import MongoClient

from asuna.state import Store
from asuna.store import Checked, adapters
from asuna.store.catalog import CATALOG
from asuna.store.errors import StoreError

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / 'config' / 'local.json'


def _local():
    if not LOCAL.exists():
        pytest.skip('no config/local.json: no MongoDB server named')
    config = json.loads(LOCAL.read_text(encoding='utf-8'))
    return config['mongo_uri'], config.get('database')


@pytest.fixture(scope='session')
def settings():
    uri, _ = _local()
    found = {'mongo_uri': uri}
    probe = adapters.open(found, adapters.TEST_PREFIX + 'ping')
    try:
        probe.ping()
    except (StoreError, OSError):
        pytest.skip('the MongoDB server named in config/local.json does not answer')
    finally:
        probe.close()
    return found


def throwaway_name(label):
    """A fresh test database name: the registry's test prefix, a label, and random hex."""
    return '%s%s_%s' % (adapters.TEST_PREFIX, re.sub(r'[^A-Za-z0-9]+', '_', label)[:30].strip('_'),
                        secrets.token_hex(6))


@pytest.fixture(scope='module')
def database(settings, request):
    _, live = _local()
    name = throwaway_name(request.module.__name__.rsplit('.', 1)[-1])
    assert name != live
    client = MongoClient(settings['mongo_uri'], serverSelectionTimeoutMS=5000)
    try:
        yield name, client[name]
    finally:
        client.close()
        adapters.drop(settings, name)
        assert name not in adapters.module(settings).databases(settings), 'the test database is gone'


def _drop_collections(handle):
    for collection in handle.list_collection_names():
        handle.drop_collection(collection)


@contextlib.contextmanager
def emptied(settings, database, catalog=CATALOG):
    """The shared layer over the module's database, every collection dropped first; its adapter closed on exit."""
    name, handle = database
    _drop_collections(handle)
    adapter = adapters.open(settings, name)
    try:
        yield Checked(adapter, catalog)
    finally:
        adapter.close()


@pytest.fixture
def store(settings, database):
    name, handle = database
    _drop_collections(handle)
    opened = Store({'mongo_uri': settings['mongo_uri'], 'database': name, 'allowed_databases': []}, name)
    try:
        opened.ensure()
        yield opened
    finally:
        opened.close()
