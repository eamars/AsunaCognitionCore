"""tools/agent_line.py: what poll has confirmed is printed even when a later fetch fails (a Host restart cut a poll
after it confirmed her message, and the message was lost to the agent, 2026-10-13)."""
import sys

from asuna.config import ROOT

sys.path.insert(0, str(ROOT / 'tools'))
import agent_line  # noqa: E402


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
