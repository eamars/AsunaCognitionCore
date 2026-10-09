"""Coding agents on this machine as an Asuna channel kind (asuna/channel_kinds.py).

Each agent (Claude Code, or another) has one direct line: it posts with the channel API and polls her answers
from the outbox itself (tools/agent_line.py). Nothing runs in the Host for it but this kind.
"""
import re

KIND = 'agent'                    # scene ids agent:<home>:dm:<agent>; person ids agent:<agent>
TITLE = 'Agent'                   # the sidebar workspace its conversations live in
IMAGE_HOSTS = ()                  # text only
TEXT_ONLY = True
PEER_LINE = True                  # she can open/close each line herself (asuna/lines.py)
HOME = True                       # a trusted home conversation (owner_private), like the DSH peer line
ROUTE_KEYS = True                 # each route has a key of its own that opens only that line (channels.route_key)

ACCOUNT = re.compile(r'[a-z][a-z0-9-]{0,39}')
INBOUND_MENTION = re.compile(r'(?!)')        # a direct line has no @ mentions
SCENE = re.compile(r'agent:([^:]+):(dm):(.+)')


def person_id(account):
    return KIND + ':' + str(account)


def account_of(person):
    """The account inside an agent:<account> person id, else None."""
    head, _, account = str(person or '').partition(':')
    return account if head == KIND and ACCOUNT.fullmatch(account) else None


def scene_id(bot, kind, target):
    return '%s:%s:%s:%s' % (KIND, bot, kind, target)


def scene_parts(scene):
    """(home account, 'dm', agent) of an agent scene id, else None."""
    match = SCENE.fullmatch(str(scene or ''))
    return match.groups() if match else None


def outbound_mention(account):
    return '@' + person_id(account)


def adapter_config(adapter, channel):
    """No sandboxed adapter serves this channel; nothing is derived."""
    return adapter


def strip_derived(adapter):
    return adapter
