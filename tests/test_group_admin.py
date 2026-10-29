"""Her place in a group and what she may do as an admin (group_admin.py), and the adapter's side of it."""
import sys

from asuna.channels import kept_raw
from asuna.config import ROOT
from test_people import GROUP

ADAPTER = ROOT / 'packages' / 'channels' / 'napcat-qq' / 'integration'
sys.path[:0] = [str(ADAPTER), str(ADAPTER / 'vendor')]          # as adapter.py sets it up
from qqadapter.outbound import Outbound            # noqa: E402
from qqadapter.selfrole import SelfRoles           # noqa: E402


def test_only_her_own_role_in_a_group_is_kept_from_raw():
    group = {'person_id': 'qq:20002', 'channel': {'sender_id': '20002', 'target': {'type': 'group', 'id': GROUP}}}
    assert kept_raw(group, {'asuna_self': {'role': 'admin', 'extra': 1}})['asuna_self'] == {'role': 'admin'}
    assert 'asuna_self' not in kept_raw(group, {'asuna_self': {'role': 'god'}})
    dm = {'person_id': 'qq:20002', 'channel': {'sender_id': '20002', 'target': {'type': 'dm', 'id': '20002'}}}
    assert 'asuna_self' not in kept_raw(dm, {'asuna_self': {'role': 'admin'}})


def test_the_adapter_maps_actions_to_napcat_calls_only():
    call = Outbound.admin_call
    group = {'type': 'group', 'id': '80000'}
    assert call({'target': group, 'admin': {'kind': 'mute', 'account': '20002', 'seconds': 600}}, '90000') == (
        'set_group_ban', {'group_id': 80000, 'user_id': 20002, 'duration': 600})
    assert call({'target': group, 'admin': {'kind': 'unmute', 'account': '20002'}}, '90000')[1]['duration'] == 0
    assert call({'target': group, 'admin': {'kind': 'kick', 'account': '20002'}}, '90000')[0] == 'set_group_kick'
    assert call({'target': group, 'admin': {'kind': 'recall', 'message_id': '7123'}}, '90000') == (
        'delete_msg', {'message_id': 7123})
    assert call({'target': group, 'admin': {'kind': 'kick', 'account': '90000'}}, '90000') == (None, 'bad_account')
    assert call({'target': group, 'admin': {'kind': 'mute', 'account': '20002', 'seconds': 5}}, '90000') == (None, 'bad_duration')
    # the ceiling she is allowed to ask for is the platform's own: 30 days passes, one minute more does not
    assert call({'target': group, 'admin': {'kind': 'mute', 'account': '20002', 'seconds': 2592000}}, '90000')[1][
        'duration'] == 2592000
    assert call({'target': group, 'admin': {'kind': 'mute', 'account': '20002', 'seconds': 2592060}}, '90000') == (
        None, 'bad_duration')
    assert call({'target': {'type': 'dm', 'id': '20002'}, 'admin': {'kind': 'kick', 'account': '20002'}}, '90000')[0] is None
    assert call({'target': group, 'admin': {'kind': 'set_group_admin', 'account': '20002'}}, '90000') == (None, 'unknown_admin_kind')


def test_the_adapter_reports_her_own_role_from_napcat():
    class Api:
        calls = 0

        def api_call(self, action, params, timeout=None):
            Api.calls += 1
            assert action == 'get_group_member_info' and params['user_id'] == 90000
            return {'retcode': 0, 'data': {'user_id': 90000, 'role': 'admin'}}
    roles = SelfRoles('90000')
    envelope = {'group_id': '80000', 'raw': {}}
    assert roles.attach(envelope, Api()) == 'admin' and envelope['raw']['asuna_self'] == {'role': 'admin'}
    roles.attach({'group_id': '80000', 'raw': {}}, Api())
    assert Api.calls == 1                                   # cached for the TTL


