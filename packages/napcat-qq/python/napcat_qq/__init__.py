"""QQ through NapCat, as a channel kind of the Asuna core (asuna/channel_kinds.py).

The core names no platform. Everything it needs to know about QQ ids, the adapter's text
conventions and the adapter's derived settings is here; the adapter itself is in ../../integration.
"""
import json
from pathlib import Path
import re

KIND = 'qq'                       # scene ids qq:<bot>:<dm|group>:<target>; person ids qq:<account>
TITLE = 'QQ'                      # the sidebar workspace its conversations live in
# Only the media hosts this deployment has actually received QQ images from (stored inbound metadata):
# the NT media host, the group-picture CDN that older clients' pictures still come from, and the sticker
# shop host store stickers come from.
IMAGE_HOSTS = ('multimedia.nt.qq.com.cn', 'gchat.qpic.cn', 'gxh.vip.qq.com')
# QQ's own faces (小黄脸) by name -> id: the same table the adapter turns `[表情:名字]` into a face with.
FACES = {row['name']: row['id'] for row in json.loads(
    (Path(__file__).resolve().parents[2] / 'integration' / 'qqadapter' / 'faces.json').read_text(encoding='utf-8'))['faces']}
STICKERS = True                   # the adapter can send a sticker: a picture marked as one, or a store sticker


def sticker_of(item):
    """A media item stored before the adapter marked stickers (0.6): a store sticker comes from the shop
    host, a custom one is a picture with sub_type 1 (7 for the small named ones); a photo is 0."""
    if '//gxh.vip.qq.com/' in str(item.get('url') or ''):
        return 'market'
    return 'custom' if str(item.get('sub_type') or '').strip() in ('1', '7') else None

ACCOUNT = re.compile(r'[0-9]{4,20}')
# The adapter writes a real @ in inbound text as @<account>; her outbound @ reaches it as @qq:<account>.
INBOUND_MENTION = re.compile(r'@(\d{5,12})')
SCENE = re.compile(r'qq:([^:]+):(dm|group):(.+)')


def person_id(account):
    return KIND + ':' + str(account)


def account_of(person):
    """The account inside a qq:<account> person id, else None."""
    head, _, account = str(person or '').partition(':')
    return account if head == KIND and ACCOUNT.fullmatch(account) else None


def scene_id(bot, kind, target):
    return '%s:%s:%s:%s' % (KIND, bot, kind, target)


def scene_parts(scene):
    """(bot account, 'dm' or 'group', target) of a QQ scene id, else None."""
    match = SCENE.fullmatch(str(scene or ''))
    return match.groups() if match else None


def outbound_mention(account):
    return '@' + person_id(account)


def adapter_config(adapter, channel):
    """Fill the adapter's derived settings from the channel it serves (host token is set by the core)."""
    adapter.setdefault('napcat', {})['account_id'] = channel['account_id']
    adapter.update(admission=channel['admission'], blocked_senders=channel.get('blocked_senders', []),
                   blocked_groups=channel.get('blocked_groups', []))
    adapter['routes'], adapter['allowed_private_user_ids'], adapter['allowed_group_ids'] = {}, [], []
    for route_id, route in channel.get('routes', {}).items():
        target = route['target']
        if target['type'] == 'dm':
            adapter['allowed_private_user_ids'].append(target['id'])
            adapter['routes'][route_id] = {'message_type': 'private', 'sender_id': route['sender_id'], 'target': target}
        elif target['type'] == 'group':
            adapter['allowed_group_ids'].append(target['id'])
            adapter['routes'][route_id] = {'message_type': 'group', 'allowed_sender_ids': list(route['members']),
                                           'target': target}
        else:
            raise ValueError('INVALID_CHANNEL_TARGET')
    return adapter


def strip_derived(adapter):
    """Remove what adapter_config derives, so exported settings keep only what the owner set."""
    for key in ('routes', 'allowed_private_user_ids', 'allowed_group_ids', 'admission',
                'blocked_senders', 'blocked_groups'):
        adapter.pop(key, None)
    adapter.get('napcat', {}).pop('account_id', None)
    return adapter
