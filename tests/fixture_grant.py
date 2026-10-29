"""Workspace grant for the fixture world: a channel route for dm-a/A (the scene stays public).

Workspace mode is the only task mode, so delegation needs a real grant. A route grant keeps
dm-a a public scene (it is not the owner's local scene) and replaces any channel routes that
a local configuration would bring into tests.
"""
from asuna.config import DATA


def fixture_grant(config, name):
    work = DATA / 'work' / name
    work.mkdir(parents=True, exist_ok=True)
    config['channels'] = {'fixture': {'token': 'f' * 32, 'account_id': 'fixture-bot', 'routes': {
        'dm-a': {'scene_id': 'dm-a', 'sender_id': 'A', 'person_id': 'A', 'target': {'type': 'dm', 'id': 'A'},
                 'workspace': str(work), 'read_only_paths': []}}}}
    return work
