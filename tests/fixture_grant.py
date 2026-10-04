"""Workspace grant for the fixture world: a channel route for dm-a/A (the scene stays public).

Workspace mode is the only task mode, so delegation needs a real grant. A route grant keeps
dm-a a public scene (it is not the owner's local scene) and replaces any channel routes that
a local configuration would bring into tests.
"""
from asuna.config import ROOT


def fixture_grant(config, name):
    work = ROOT / '.runtime/work' / name
    work.mkdir(parents=True, exist_ok=True)
    config['channels'] = {'fixture': {'token': 'f' * 32, 'account_id': 'fixture-bot', 'routes': {
        'dm-a': {'scene_id': 'dm-a', 'sender_id': 'A', 'person_id': 'A', 'target': {'type': 'dm', 'id': 'A'},
                 'workspace': str(work), 'read_only_paths': []}}}}
    return work


def returned(store, task, text, refs):
    """A task returned the way tasks.Executor returns it: natural language plus program-attached receipts."""
    from asuna.state import now
    current = store.db.tasks.find_one({'_id': task['_id']})
    result = {'task_id': task['_id'], 'intent_revision': current['intent_revision'], 'text': text,
              'finish_reason': 'stop', 'artifact_refs': list(refs), 'diagnostic': None,
              'facts': [{'text': text, 'evidence_refs': list(refs)}], 'uncertainties': []}
    return store.put('tasks', {**current, 'state': 'RETURNED', 'result': result, 'finished_at': now(),
                               'feedback_state': 'READY'}, expected=current['revision'], stream=task['_id'])
