"""QQ through NapCat, as a channel kind of the Asuna core (asuna/channel_kinds.py).

The core names no platform. Everything it needs to know about QQ ids, the adapter's text
conventions and the adapter's derived settings is here; the adapter itself is in ../../integration.
"""
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

KIND = 'qq'                       # scene ids qq:<bot>:<dm|group>:<target>; person ids qq:<account>
TITLE = 'QQ'                      # the sidebar workspace its conversations live in
# Only the media hosts this deployment has actually received QQ images from (stored inbound metadata):
# the NT media host, the group-picture CDN that older clients' pictures still come from, and the sticker
# shop host store stickers come from.
IMAGE_HOSTS = ('multimedia.nt.qq.com.cn', 'gchat.qpic.cn', 'gxh.vip.qq.com')
# The file hosts the 148 received files with a link were served from (gzc-, hkc-, tjc-, njc-, cqc-download.ftn.qq.com).
FILE_HOSTS = ('.ftn.qq.com',)
# The adapter's resident service: an enabled integration for this channel starts it by itself the first time.
SERVICE_ARGV = ('python3', '/app/adapter.py', '--service')
# QQ's own faces (小黄脸) by name -> id: the same table the adapter turns `[表情:名字]` into a face with.
_FACE_ROWS = json.loads(
    (Path(__file__).resolve().parents[2] / 'integration' / 'qqadapter' / 'faces.json').read_text(encoding='utf-8'))['faces']
FACES = {row['name']: row['id'] for row in _FACE_ROWS}
for _row in _FACE_ROWS:                # a renamed face keeps its old names (`aliases`) so they still pass the core's check
    for _alias in _row.get('aliases') or ():
        FACES.setdefault(_alias, _row['id'])
OPEN_ADMISSION = True             # its senders are strangers the deployment may admit (channelAdmission automatic)
REQUESTS = True                   # friend and group requests reach her home, which answers them (qqadapter/notices.py)
STICKERS = True                   # the adapter can send a sticker: a picture marked as one, or a store sticker
# What her reply is made of here (ADR-064 phase 2): she speaks only through `speak`, in these parts.
REPLY_PARTS = ('text', 'sticker', 'picture', 'file', 'poke', 'react', 'recall')
# QQ lets anyone take back their own message for two minutes (a group's owner or admin longer).
OWN_RECALL_SECONDS = 120


def sticker_of(item):
    """A media item stored before the adapter marked stickers (0.6): a store sticker comes from the shop
    host, a custom one is a picture with sub_type 1 (7 for the small named ones); a photo is 0."""
    if '//gxh.vip.qq.com/' in str(item.get('url') or ''):
        return 'market'
    return 'custom' if str(item.get('sub_type') or '').strip() in ('1', '7') else None


# QQ names a picture's file by the md5 of its bytes (checked on live stickers, 2026-10-06).
MD5_FILE = re.compile(r'([0-9A-Fa-f]{32})\.[A-Za-z0-9]{2,5}')


def sticker_md5(item):
    match = MD5_FILE.fullmatch(str(item.get('file') or '').strip())
    return match.group(1) if match else None


# A picture link from the NT media host carries a signature (`rkey`) that expires within minutes; the picture stays.
# The adapter posts NapCat's current keys under these names, and a stored link is signed again with the key of its
# kind before it is fetched (asuna/media_keys.py): appid 1407 group pictures, 1406 private ones.
SIGNED_HOST = 'multimedia.nt.qq.com.cn'
MEDIA_KEYS = {'1407': 'qq-group', '1406': 'qq-private'}
RKEY = re.compile(r'([?&]rkey=)([^&#]*)')
APPID = re.compile(r'[?&]appid=(\d+)')


def _signed(url):
    """The key name a signed link needs and its current signature, or None."""
    url = str(url or '')
    if urlsplit(url).hostname != SIGNED_HOST:
        return None
    appid, rkey = APPID.search(url), RKEY.search(url)
    name = MEDIA_KEYS.get(appid.group(1)) if appid else None
    return (name, rkey.group(2)) if name and rkey else None


def media_key_name(url):
    found = _signed(url)
    return found[0] if found else None


def media_key_in(url):
    """(name, key) a link that arrived minutes ago is signed with."""
    found = _signed(url)
    return found if found and found[1] else None


def sign_media(url, key):
    return RKEY.sub(lambda match: match.group(1) + key, str(url), count=1)


def media_refusal(status, detail):
    """What the media host's refusal means: 'expired' (the signature), 'gone' (the picture), or None."""
    if '-5503007' in detail or 'expired' in detail.lower():
        return 'expired'
    if status in (404, 410):
        return 'gone'
    return None


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
    """Fill the adapter's derived settings from the channel it serves (host token is set by the core). Who may speak is
    the core's to decide and the adapter asks it, so nothing of that is derived (ADR-107)."""
    adapter.setdefault('napcat', {})['account_id'] = channel['account_id']
    return adapter


def strip_derived(adapter):
    """Remove what adapter_config derives, so exported settings keep only what the owner set."""
    adapter.get('napcat', {}).pop('account_id', None)
    return adapter
