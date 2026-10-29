"""Her own line taken back (her ask, the owner's yes, 2026-10-18): `speak`'s `recall` part names her line by its
number with a reason. Still queued, it is cancelled and never leaves; delivered within the platform's window, the
adapter recalls it; later, it is refused with what she can do instead; what came of it is in her history either way."""
import sys

from asuna.config import ROOT


def test_napcat_takes_back_her_own_message_with_delete_msg():
    adapter = ROOT / 'packages' / 'channels' / 'napcat-qq' / 'integration'
    sys.path[:0] = [str(adapter), str(adapter / 'vendor')]
    from qqadapter.outbound import Outbound
    call = Outbound.action_call({'target': {'type': 'group', 'id': '80000'},
                                 'action': {'kind': 'recall', 'message_id': '12345', 'line': 'mine-1'}})
    assert call == ('delete_msg', {'message_id': 12345})
