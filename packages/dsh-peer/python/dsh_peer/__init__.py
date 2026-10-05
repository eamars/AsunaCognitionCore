"""Another DeepSeek Harness agent as an Asuna channel kind (asuna/channel_kinds.py).

The peer is an agent living in a session of another DSH Web server. Its replies arrive as direct messages in
one conversation; her answers leave through the outbox as prompts to that session. The bridge that carries
them runs in this package's own Host plugin (src/bridge.js); there is no sandboxed adapter.
"""
import re

KIND = 'dsh'                      # scene ids dsh:<home>:dm:<peer>; person ids dsh:<peer>
TITLE = 'DSH'                     # the sidebar workspace its conversations live in
IMAGE_HOSTS = ()                  # the bridge carries text only

ACCOUNT = re.compile(r'[a-z][a-z0-9-]{0,39}')
INBOUND_MENTION = re.compile(r'(?!)')        # a peer conversation has no @ mentions
SCENE = re.compile(r'dsh:([^:]+):(dm):(.+)')


def person_id(account):
    return KIND + ':' + str(account)


def account_of(person):
    """The account inside a dsh:<account> person id, else None."""
    head, _, account = str(person or '').partition(':')
    return account if head == KIND and ACCOUNT.fullmatch(account) else None


def scene_id(bot, kind, target):
    return '%s:%s:%s:%s' % (KIND, bot, kind, target)


def scene_parts(scene):
    """(home account, 'dm', peer) of a dsh scene id, else None."""
    match = SCENE.fullmatch(str(scene or ''))
    return match.groups() if match else None


def outbound_mention(account):
    return '@' + person_id(account)


def adapter_config(adapter, channel):
    """No sandboxed adapter serves this channel; nothing is derived."""
    return adapter


def strip_derived(adapter):
    return adapter
