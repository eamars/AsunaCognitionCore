"""Current signatures for a platform's media links (ADR-035).

A platform may sign its media links with a key that expires within minutes while the picture itself stays. A stored
link is signed again with the current key of its kind just before it is fetched; the channel kind says which links
are signed, with which key name, and how to put a key in (channel_kinds.media_key_name, sign_media).

The current keys come from the channel adapter (``POST /v1/channels/<id>/media_keys``, names its kind declares in
MEDIA_KEYS, each with how many seconds it lasts) and, failing that, from a link that arrived in the last
LINK_KEY_SECONDS (``saw``, called as each inbound event is received). Keys are session secrets: they live only in this
process's memory, never in the database, the audit, a log or a reply. After a restart the adapter posts them again
within minutes.
"""
import threading
import time

from . import channel_kinds
from .vision import MEDIA_KEY

LINK_KEY_SECONDS = 300       # a link's own signature works about seven minutes after it arrives (measured)
MAX_KEYS = 8
KEY_CHARS = 1024
MIN_SECONDS, MAX_SECONDS = 60, 86400
MARGIN_SECONDS = 30          # a key this close to its end is not used

_lock = threading.Lock()
_keys = {}                   # name -> (key, monotonic deadline, 'adapter' | 'link')


def _put(name, key, seconds, source):
    with _lock:
        held = _keys.get(name)
        # A link's key never displaces the adapter's while the adapter's lasts.
        if source == 'link' and held and held[2] == 'adapter' and held[1] > time.monotonic():
            return
        _keys[name] = (key, time.monotonic() + seconds, source)


def receive(channel_id, body):
    """The adapter's current keys: {'keys': [{'name', 'key', 'seconds'}]}. The answer never repeats a key."""
    rows = body.get('keys')
    allowed = channel_kinds.media_key_names(channel_id)
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_KEYS:
        raise ValueError('MEDIA_KEYS_INVALID: keys 要是 1..%d 条的列表' % MAX_KEYS)
    for row in rows:
        name, key, seconds = (row or {}).get('name'), (row or {}).get('key'), (row or {}).get('seconds')
        if name not in allowed:
            raise ValueError('MEDIA_KEY_NAME_DENIED: %r 不是这个渠道声明的密钥（%s）' % (name, '、'.join(sorted(allowed)) or '没有'))
        if not isinstance(key, str) or not 1 <= len(key) <= KEY_CHARS or not key.isprintable() or '&' in key:
            raise ValueError('MEDIA_KEY_INVALID: %s 的 key 要是 1..%d 个可打印字符、不带 &' % (name, KEY_CHARS))
        if isinstance(seconds, bool) or not isinstance(seconds, int) or not MIN_SECONDS <= seconds <= MAX_SECONDS:
            raise ValueError('MEDIA_KEY_SECONDS_INVALID: %s 的 seconds 要是 %d..%d 的整数' % (name, MIN_SECONDS, MAX_SECONDS))
    for row in rows:
        _put(row['name'], row['key'], row['seconds'], 'adapter')
    return {'status': 'stored', 'names': sorted({row['name'] for row in rows})}


def saw(event):
    """An inbound event's media links: a signed one that just arrived carries a current key."""
    block = (event.get('raw') or {}).get(MEDIA_KEY)
    for item in (block.get('items') if isinstance(block, dict) else None) or ():
        found = channel_kinds.media_key_in(item.get('url')) if isinstance(item, dict) else None
        if found:
            _put(found[0], found[1], LINK_KEY_SECONDS, 'link')


def current(name):
    with _lock:
        held = _keys.get(name)
    return held[0] if held and held[1] - MARGIN_SECONDS > time.monotonic() else None


def sign(url):
    """(url, signature): signature None for a link that carries none, 'renewed' once signed with the current key,
    'unavailable' when no current key is known (the link goes out as stored)."""
    name = channel_kinds.media_key_name(url)
    if not name:
        return url, None
    key = current(name)
    return (channel_kinds.sign_media(url, key), 'renewed') if key else (url, 'unavailable')


def forget():
    """Tests: start from no keys."""
    with _lock:
        _keys.clear()
