"""Where only speak speaks (role_tools.REPLY_REPLACES, owner 2026-10-19), a turn that does not call it says nothing. A
stay_silent call there runs as she meant it, the way an old name runs: it ends the turn, and its result says once that
not calling speak is enough. The tool list her conversation shows does not change (its prompt cache holds)."""
from asuna import role_tools


def test_the_host_lets_it_through_as_it_does_an_old_name():
    assert role_tools.aliases()['stay_silent'] == 'speak'
