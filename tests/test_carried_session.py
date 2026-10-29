"""ADR-028: a conversation that no longer fits the model's window continues in a new session carrying its last
summary. These tests use an in-memory Mongo; they create no database."""
from types import SimpleNamespace

import pytest

from asuna.context_budget import CARRIED_CHARS, carried_block
from asuna.coordinator import Coordinator, SessionCarried
from asuna.records import episodes as episode_records


def test_the_carried_block_is_bounded_and_says_when_there_was_no_summary():
    assert carried_block('')['note'] and 'summary' not in carried_block('')
    long = carried_block('字' * (CARRIED_CHARS + 500))['summary']
    assert long.startswith('字' * CARRIED_CHARS) and '500' in long[CARRIED_CHARS:]


def test_the_coordinator_runs_a_carried_turn_once_more_and_says_why(monkeypatch):
    runs, updates, audits = [], [], []
    coordinator = Coordinator.__new__(Coordinator)
    episode = {'_id': 'ep', 'scope_key': 'scene:local', 'revision': 1}
    coordinator.store = SimpleNamespace(audit=lambda *args: audits.append(args))
    monkeypatch.setattr(episode_records, 'get', lambda store, episode_id, fields=None, **fence: episode)
    coordinator.character = SimpleNamespace()
    coordinator._update = lambda ep, **changes: updates.append(changes) or {**ep, **changes}

    def run(ep):
        runs.append(ep.get('resume_diagnostic'))
        if len(runs) == 1:
            raise SessionCarried('overflow', 'new-session')
        return {'state': 'COMMITTED'}
    coordinator._run_turn = run
    assert coordinator._turn(episode) == {'state': 'COMMITTED'}
    assert runs[0] is None and '新会话' in runs[1]
    assert audits[0][1] == 'turn.carried' and audits[0][2] == {'successor': 'new-session'}
    coordinator._run_turn = lambda ep: (_ for _ in ()).throw(SessionCarried('again', 'third'))
    with pytest.raises(SessionCarried):
        coordinator._turn(episode)


