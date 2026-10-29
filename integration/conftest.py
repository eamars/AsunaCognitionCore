"""What every integration test shares: a throwaway `asuna_v2_test_*` database on the server the checkout's
config/local.json names, reached through the store's adapter registry (`asuna.store.adapters`), and dropped at the
end, failures included.

`settings` (session): the registry's settings for that server, from the address in config/local.json and nothing else
of it; every test that takes it skips when no server is named or the server does not answer. `store`: a `Store` on a
database of its own (`asuna_v2_test_<test name>_<hex>`), every declared collection made, holding nothing a test does
not write itself. `world`: the same, holding the synthetic world (tests/fixtures/world.json: three people, four
conversations, twelve memories, three personas) and a turn's settings (the tracked example settings, the fixture
route's workspace, fixture models), for a test that runs her turns; in a module marked `world` (integration/world/),
`store` is that world. Every such store also has `raw`, the same database through the driver, for what a test writes
or reads beside the code under test. Each database is dropped when its test ends and its being gone is checked; a
workspace made for it is removed. A test here holds a few hundred synthetic records at most. Nothing here prints the
server's address.
"""
import contextlib
import json
import re
import secrets
import sys
from pathlib import Path

import pytest
from pymongo import MongoClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))         # the fixture world's helpers (fixture_grant, reply_parts)

from asuna import channel_kinds  # noqa: E402
from asuna.config import DATA, load  # noqa: E402
from asuna.state import Store  # noqa: E402
from asuna.store import adapters  # noqa: E402
from asuna.store.errors import StoreError  # noqa: E402
from asuna.testing import remove_workspace  # noqa: E402

LOCAL = ROOT / 'config' / 'local.json'
EXAMPLE = ROOT / 'config' / 'local.example.json'
WORLD = ROOT / 'tests' / 'fixtures' / 'world.json'
# The world's scenes and people are fixture ones; the places tests name (a QQ group, an agent line, a peer line) are
# their channel packages' kinds, every one of them loaded as a Host with all four would load them.
channel_kinds.load([{'python': ROOT / 'packages' / 'channels' / folder / 'python', 'module': module}
                    for folder, module in (('qq-bot', 'qq_bot'), ('agent-line', 'agent_line'),
                                           ('dsh-peer', 'dsh_peer'), ('napcat-qq', 'napcat_qq'))])


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


@contextlib.contextmanager
def throwaway_store(settings, label, config=None):
    """A Store on a throwaway database of its own, every declared collection made; dropped on exit, failures
    included, and checked gone."""
    _, live = _local()
    name = throwaway_name(label)
    assert name != live
    config = {**(config or {}), 'mongo_uri': settings['mongo_uri'], 'database': name, 'allowed_databases': []}
    opened = Store(config, name)
    client = MongoClient(settings['mongo_uri'], serverSelectionTimeoutMS=5000)
    opened.raw = client[name]
    try:
        opened.ensure()
        yield opened
    finally:
        client.close()
        opened.close()
        adapters.drop(settings, name)
        assert name not in adapters.module(settings).databases(settings), 'the test database is gone'


def pytest_configure(config):
    config.addinivalue_line('markers', 'world: in this test, `store` is the fixture world (the `world` fixture)')


@pytest.fixture
def store(settings, request):
    if request.node.get_closest_marker('world'):
        yield request.getfixturevalue('world')
        return
    with throwaway_store(settings, request.node.name) as opened:
        yield opened


def turn_settings(name):
    """A turn's settings for the fixture world: the tracked example settings, fixture models for both brains, a
    Host sandbox, and the fixture route's workspace for dm-a (the scene stays public)."""
    from fixture_grant import fixture_grant
    config = load(EXAMPLE, dsh_home=DATA / 'asuna-dsh')
    config['character_id'] = 'demo'
    for lane, modalities in (('character', ['text']), ('executor', ['text', 'image'])):
        config[lane] = {'model': 'fixture-' + lane, 'provider': 'fixture', 'max_tokens': 4096,
                        'context_window': 65536, 'input_modalities': modalities, 'token_counter': 'native-host'}
    config['_host_sandbox'] = {'available': True, 'reason': None}
    work = fixture_grant(config, name)
    return config, work


@pytest.fixture
def world(settings, request):
    from asuna import capabilities
    label = 'world_' + request.node.name
    config, work = turn_settings(throwaway_name(label))
    capabilities.forget()
    try:
        with throwaway_store(settings, label, config) as opened:
            opened.seed(WORLD)
            yield opened
    finally:
        remove_workspace(work)
