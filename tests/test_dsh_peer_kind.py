"""The dsh channel kind (packages/channels/dsh-peer): id formats the core uses for a peer DSH conversation."""
from asuna import channel_kinds
from asuna.config import ROOT


def test_a_peer_conversation_has_dsh_ids():
    channel_kinds.load([{'python': ROOT / 'packages' / 'channels' / 'dsh-peer' / 'python', 'module': 'dsh_peer'}])
    kind = channel_kinds.of_channel('dsh')
    assert kind.TITLE == 'DSH' and kind.IMAGE_HOSTS == ()
    assert kind.person_id('peer') == 'dsh:peer' and kind.account_of('dsh:peer') == 'peer'
    assert kind.account_of('qq:12345') is None and kind.account_of('dsh:Not Valid') is None
    scene = kind.scene_id('home', 'dm', 'peer')
    assert scene == 'dsh:home:dm:peer' and kind.scene_parts(scene) == ('home', 'dm', 'peer')
    assert channel_kinds.of(scene) is kind and channel_kinds.of('dsh:peer') is kind
    assert not kind.INBOUND_MENTION.search('@peer hello')
    assert kind.test_guards({}) == [] if hasattr(kind, 'test_guards') else True
