"""On MongoDB: a turn lacking a field of the episodes' plain unique index is refused before anything is written, and a
whole one is written (ADR-104, design 3.5), on a throwaway `asuna_v2_test_*` database of synthetic records, dropped at
the end, failures included; skipped when no server is named or it cannot be reached. Nothing here prints the server's
address."""
import json
import secrets
from pathlib import Path

import pytest
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from asuna.store import Checked, adapters, mongodb
from asuna.store.catalog import CATALOG
from asuna.store.errors import RecordInvalid

ROOT = Path(__file__).resolve().parents[1]
adapters.register(mongodb)


@pytest.fixture
def episodes():
    path = ROOT / 'config' / 'local.json'
    if not path.exists():
        pytest.skip('no config/local.json: no MongoDB server named')
    config = json.loads(path.read_text(encoding='utf-8'))
    try:
        MongoClient(config['mongo_uri'], serverSelectionTimeoutMS=3000).admin.command('ping')
    except PyMongoError:
        pytest.skip('MongoDB is not reachable')
    settings = {'database_adapter': 'mongodb', 'mongo_uri': config['mongo_uri']}
    name = adapters.TEST_PREFIX + 'required_' + secrets.token_hex(6)
    adapter = adapters.open(settings, name)
    try:
        store = Checked(adapter, CATALOG)
        store.ensure(['episodes'])
        yield store.collection('episodes'), adapter, name
    finally:
        adapter.close()
        adapters.drop(settings, name)
        assert name not in mongodb.databases(settings)


@pytest.mark.parametrize('field', ['scene_id', 'source_event_id', 'episode_kind'])
def test_a_turn_lacking_a_unique_index_field_is_refused_on_mongodb(episodes, field):
    rows, adapter, name = episodes
    whole = {'_id': 'whole', 'schema_version': 1, 'revision': 1, 'scene_id': 'g', 'source_event_id': 'ev',
             'episode_kind': 'external'}
    with pytest.raises(RecordInvalid) as caught:
        rows.insert({key: value for key, value in whole.items() if key != field} | {'_id': 'lacking'})
    assert str(caught.value).startswith('RECORD_REQUIRED')
    assert rows.count() == 0, 'nothing reached the server'
    rows.insert(whole)
    assert rows.get('whole')[field] == whole[field]
