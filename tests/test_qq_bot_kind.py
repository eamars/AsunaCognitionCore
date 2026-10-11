"""The qqbot channel kind (packages/channels/qq-bot): OpenID ids beside the NapCat kind, and the core reading them as
it reads QQ numbers (ADR-046)."""
from asuna import channel_kinds
from asuna.config import ROOT
from asuna.group_members import _member
from asuna.peer_context import snapshot_event

channel_kinds.load([{'python': ROOT / 'packages' / 'channels' / 'qq-bot' / 'python', 'module': 'qq_bot'},
                    {'python': ROOT / 'packages' / 'channels' / 'napcat-qq' / 'python', 'module': 'napcat_qq'}])
APP, USER, GROUP = '1000000001', 'E4F4AEA33253A2797FB897C50B81D7ED', '0B1C2D3E4F5A6B7C8D9E0F1A2B3C4D5E'


def test_a_bot_conversation_has_openid_ids_apart_from_qq_numbers():
    kind = channel_kinds.of_channel('qqbot')
    assert kind.person_id(USER) == 'qqbot:' + USER and kind.account_of('qqbot:' + USER) == USER
    assert kind.account_of('qq:12345') is None and kind.account_of('qqbot:12345') is None
    scene = kind.scene_id(APP, 'group', GROUP)
    assert kind.scene_parts(scene) == (APP, 'group', GROUP) and channel_kinds.of(scene) is kind
    assert kind.INBOUND_MENTION.search('@%s 你好' % USER).group(1) == USER
    # A bare QQ number is a person of the NapCat kind only; a bare OpenID one of this kind only.
    assert channel_kinds.person_ids('12345') == ['qq:12345']
    assert channel_kinds.person_ids(USER) == ['qqbot:' + USER]


def test_a_group_senders_profile_is_kept_with_a_32_character_group_id():
    event = {'event_id': 'channel-x', 'scene_id': 'qqbot:%s:group:%s' % (APP, GROUP), 'person_id': 'qqbot:' + USER,
             'channel': {'id': 'qqbot', 'sender_id': USER, 'target': {'type': 'group', 'id': GROUP}},
             'raw': {'asuna_peer': {'person_id': 'qqbot:' + USER, 'account_id': USER, 'scene': 'group:' + GROUP,
                                    'group_id': GROUP, 'display': '群友', 'nickname': '群友', 'source': 'event_sender',
                                    'verified': True}}}
    profile = snapshot_event(event)
    assert profile and profile['group_id'] == GROUP and profile['scene'] == 'group:' + GROUP
    event['raw']['asuna_peer']['group_id'] = GROUP[:-1] + 'F'
    assert snapshot_event(event) is None


def test_a_member_list_takes_the_ids_its_kind_names():
    assert _member({'user_id': USER}, channel_kinds.of_channel('qqbot').ACCOUNT)['user_id'] == USER
    assert _member({'user_id': USER}, channel_kinds.of_channel('qq').ACCOUNT) is None
    assert _member({'user_id': '12345'}, channel_kinds.of_channel('qq').ACCOUNT)['user_id'] == '12345'
