"""QQ through the official QQ Bot open platform, as a channel kind of the Asuna core (asuna/channel_kinds.py).

The platform names people and groups by OpenIDs that belong to this one bot (never a QQ number), so this kind has
its own ids and runs beside the NapCat kind (`qq`) without sharing people with it. The bridge that speaks the
platform's gateway and OpenAPI runs in this package's own Host plugin (src/bridge.js); there is no sandboxed adapter.
"""
import re

KIND = 'qqbot'                    # scene ids qqbot:<appid>:<dm|group>:<openid>; person ids qqbot:<openid>
TITLE = 'QQ Bot'                  # the sidebar workspace its conversations live in
OPEN_ADMISSION = True             # its senders are strangers the deployment may admit (channelAdmission automatic)
# The hosts the platform delivers inbound pictures from (attachments[].url).
IMAGE_HOSTS = ('multimedia.nt.qq.com.cn', 'gchat.qpic.cn')
# She speaks here only through `speak`, in these parts (what the bridge sends: text, and a picture with or without
# words); the platform has no stickers, pokes or reactions for a bot. What else it carries is the bridge's declaration.
REPLY_PARTS = ('text', 'picture')

# An OpenID (a user's in a private chat, a member's or a group's in a group): letters and digits, longer than any
# QQ number, so a bare QQ number is never read as one.
ACCOUNT = re.compile(r'[0-9A-Za-z_-]{24,64}')
# The bridge writes a real @ in inbound text as @<openid>; her outbound @ reaches it as @qqbot:<openid>.
INBOUND_MENTION = re.compile(r'@([0-9A-Za-z_-]{24,64})')
SCENE = re.compile(r'qqbot:([^:]+):(dm|group):(.+)')


def person_id(account):
    return KIND + ':' + str(account)


def account_of(person):
    """The OpenID inside a qqbot:<openid> person id, else None."""
    head, _, account = str(person or '').partition(':')
    return account if head == KIND and ACCOUNT.fullmatch(account) else None


def scene_id(bot, kind, target):
    return '%s:%s:%s:%s' % (KIND, bot, kind, target)


def scene_parts(scene):
    """(bot AppID, 'dm' or 'group', target OpenID) of a qqbot scene id, else None."""
    match = SCENE.fullmatch(str(scene or ''))
    return match.groups() if match else None


def outbound_mention(account):
    return '@' + person_id(account)


def adapter_config(adapter, channel):
    """No sandboxed adapter serves this channel; nothing is derived."""
    return adapter


def strip_derived(adapter):
    return adapter
