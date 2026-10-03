"""Explicit teardown for databases owned by isolated tests and probes."""
import re

from pymongo import MongoClient
from .config import validate_database


def dispose_test_store(store):
    """Drop an owned test database even if its application client was closed."""
    config, name = store.config, store.name
    protected = {config['database'], config.get('legacy_database'), *config['allowed_databases']}
    if name in protected or not re.fullmatch(r'asuna_v2_test_[A-Za-z0-9_]+', name):
        raise ValueError('TEST_CLEANUP_TARGET_NOT_AUTHORIZED')
    validate_database(config, name)
    cleanup = MongoClient(config['mongo_uri'], serverSelectionTimeoutMS=5000,
                          connectTimeoutMS=5000, timeoutMS=10000)
    try:
        cleanup.drop_database(name)
    finally:
        cleanup.close()
        store.client.close()
