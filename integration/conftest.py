"""What every integration test shares: a throwaway `asuna_v2_test_*` database on the server the checkout's
config/local.json names, reached through the store's adapter registry (`asuna.store.adapters`), and dropped at the
end, failures included.

`settings` (session): the registry's settings for that server, from the address in config/local.json and nothing else
of it; every test that takes it skips when no server is named or the server does not answer. `store`: a `Store` on a
database of its own (`asuna_v2_test_<test name>_<hex>`), every declared collection made, holding nothing a test does
not write itself; the database is dropped when the test ends, and its being gone is checked. A test here holds a few
hundred synthetic records at most. Nothing here prints the server's address.
"""
import json
import re
import secrets
from pathlib import Path

import pytest

from asuna.state import Store
from asuna.store import adapters
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
    return '%s%s_%s' % (adapters.TEST_PREFIX, re.sub(r'[^A-Za-z0-9]+', '_', label)[:40].strip('_'),
                        secrets.token_hex(6))


@pytest.fixture
def store(settings, request):
    _, live = _local()
    name = throwaway_name(request.node.name)
    assert name != live
    opened = Store({'mongo_uri': settings['mongo_uri'], 'database': name, 'allowed_databases': []}, name)
    try:
        opened.ensure()
        yield opened
    finally:
        opened.close()
        adapters.drop(settings, name)
        assert name not in adapters.module(settings).databases(settings), 'the test database is gone'
