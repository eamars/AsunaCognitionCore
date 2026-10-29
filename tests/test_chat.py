"""Her local chat: what a failure says in its diagnostics never carries a credential of the settings."""
from asuna.chat import redact


def test_diagnostics_redact_credentials():
    config = {'mongo_uri': 'mongodb://user:secret@127.0.0.1', 'embedding': {'api_key': 'sensitive-key'}}
    result = redact('failure mongodb://user:secret@127.0.0.1 sensitive-key original-error', config)
    assert 'secret' not in result and 'sensitive-key' not in result
    assert 'original-error' in result
