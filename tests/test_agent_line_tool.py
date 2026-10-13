"""tools/agent_line.py: what poll has confirmed is printed even when a later fetch fails (a Host restart cut a poll
after it confirmed her message, and the message was lost to the agent, 2026-10-13)."""
import importlib.util
import sys

import pytest

from asuna.config import ROOT

# Loaded under its own name: `agent_line` is also the channel kind's module (packages/channels/agent-line).
spec = importlib.util.spec_from_file_location('agent_line_cli', ROOT / 'tools' / 'agent_line.py')
agent_line = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent_line)


def test_a_confirmed_message_survives_a_later_failed_fetch(monkeypatch):
    calls = []

    def call(line, method, path, body=None, timeout=None):
        calls.append((method, path))
        if method == 'POST':
            return {}
        if len(calls) == 1:
            return {'items': [{'publication_id': 'p1', 'attempt_id': 'a1', 'text': '她的话'}]}
        sys.exit('The Host does not answer')

    monkeypatch.setattr(agent_line, 'call', call)
    assert agent_line.poll({'url': 'http://example.invalid'}, 5) == (['她的话'], 'open', [])
    assert ('POST', '/outbox/p1/receipt') in calls


def test_send_answers_a_question_by_its_id(monkeypatch):
    sent = []
    monkeypatch.setattr(agent_line, 'call', lambda line, method, path, body=None, timeout=None: sent.append(body) or {})
    line = {'route_id': 'claude-code', 'account_id': 'home', 'sender_id': 'claude-code'}
    agent_line.send(line, '改这一行', 'q-1a2b3c4d')
    assert sent[-1]['raw'] == {'asuna_answer': {'question': 'q-1a2b3c4d'}}
    agent_line.send(line, '随便说说')
    assert 'raw' not in sent[-1]
    with pytest.raises(SystemExit, match='question id'):
        agent_line.send(line, 'x', 'not-an-id')
