"""Cleanup protects production names and covers failure before fixture yield."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from asuna.testing import dispose_test_store


@pytest.mark.parametrize('name', ['admin', 'asuna_cognition_core_v2', 'asuna_v2_test_explicitly_allowed'])
def test_cleanup_rejects_protected_or_unrelated_database_before_connecting(name):
    config = {'database': 'asuna_cognition_core_v2', 'legacy_database': 'legacy',
              'allowed_databases': ['asuna_cognition_core_v2', 'asuna_v2_test_explicitly_allowed']}
    with patch('asuna.store.adapters.drop') as drop:
        with pytest.raises(ValueError, match='TEST_CLEANUP_TARGET_NOT_AUTHORIZED'):
            dispose_test_store(SimpleNamespace(config=config, name=name))
        drop.assert_not_called()


