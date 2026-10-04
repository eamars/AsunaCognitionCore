"""Cleanup protects production names and covers failure before fixture yield."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from asuna.config import load
from asuna.state import Store
from asuna.testing import dispose_test_store


@pytest.mark.parametrize('name', ['admin', 'asuna_cognition_core_v2', 'asuna_v2_test_explicitly_allowed'])
def test_cleanup_rejects_protected_or_unrelated_database_before_connecting(name):
    config = {'database': 'asuna_cognition_core_v2', 'legacy_database': 'legacy',
              'allowed_databases': ['asuna_cognition_core_v2', 'asuna_v2_test_explicitly_allowed']}
    with patch('asuna.testing.MongoClient') as client:
        with pytest.raises(ValueError, match='TEST_CLEANUP_TARGET_NOT_AUTHORIZED'):
            dispose_test_store(SimpleNamespace(config=config, name=name))
        client.assert_not_called()


def test_fixture_drops_database_when_seed_fails_before_yield(monkeypatch):
    import conftest
    names = []
    def fail(store, *fixture):
        names.append(store.name)
        raise RuntimeError('deliberate seed failure')
    monkeypatch.setattr(Store, 'seed', fail)
    monkeypatch.delenv('ASUNA_TEST_EVIDENCE_ROOT', raising=False)
    with pytest.raises(RuntimeError, match='deliberate seed failure'):
        next(conftest.store.__wrapped__(SimpleNamespace()))
    assert len(names) == 1
    observer = Store(load(), names[0])
    try:
        assert names[0] not in observer.client.list_database_names()
    finally:
        observer.client.close()


def test_teardown_handles_an_application_that_already_closed_its_store(store):
    store.client.close()
