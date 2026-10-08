"""Explicit teardown for databases owned by isolated tests and probes."""
import re
import shutil

from pymongo import MongoClient
from .config import validate_database
from .queue import effects_lock_path
from .tasks import workspace_lock_path


def remove_lock_files(*paths):
    """Remove lock files a test or probe owned; one still held stays (Windows refuses to delete an open file)."""
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def remove_workspace(path):
    """A test workspace and the lease file a task run left for it."""
    shutil.rmtree(path, ignore_errors=True)
    remove_lock_files(workspace_lock_path(path))


def dispose_test_store(store):
    """Drop an owned test database even if its application client was closed."""
    config, name = store.config, store.name
    protected = {config['database'], *config['allowed_databases']}
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
    remove_lock_files(effects_lock_path(name))
