"""What a channel's running adapter says it carries (ADR-079 §9.7).

An adapter declares it on every outbox claim (`?supports=`); the program keeps the last declaration per channel, in
`artifacts` (kind `channel_capabilities`), so it holds across restarts before the first claim. What she reads and the
tools she gets follow it, never the adapter's software: a function not declared is not carried, and is hidden.

The pointer family (quote, reply, reaction, recall):
  quote      her line can quote another
  quote_in   it passes on what others quote
  react      she can react to a line
  react_in   it passes on reactions
  recall     it carries recalls

When a channel stops or starts carrying a function she uses herself (quote, react, recall), each of its
conversations gets one program line at its next turn, naming the leg as the cause (her words).
"""
from __future__ import annotations

import logging
import threading

from .state import now

KIND = 'channel_capabilities'
POINTERS = ('quote', 'quote_in', 'react', 'react_in', 'recall')
CHANGE = 'capability_change'
# What she does herself, in her words (ADR-079 §9.7): a change of one is told to each conversation once.
WORDS = {'quote': '引用', 'react': '点表情', 'recall': '撤回自己的话'}
CANNOT = '这条腿做不了%s'
BACK = '这条腿又能%s了'
log = logging.getLogger(__name__)

_lock = threading.Lock()
_known = {}                    # channel id -> the declared names, as last kept
_warned = set()                # channel ids whose missing pointer capabilities were logged this run


def _row_id(channel_id):
    return 'capabilities:' + channel_id


def declared(store, channel_id, supports):
    """Keep what an adapter declared on a claim; write the row only when it changed. A pointer capability the adapter
    did not declare is logged once per run, naming the channel and the function."""
    names = tuple(sorted({str(name) for name in supports or () if name}))
    with _lock:
        if _known.get(channel_id) == names:
            return
        _known[channel_id] = names
        first = channel_id not in _warned
        _warned.add(channel_id)
    row = {'_id': _row_id(channel_id), 'kind': KIND, 'channel_id': channel_id, 'supports': list(names),
           'declared_at': now(), 'schema_version': 1}
    prior = store.db.artifacts.find_one({'_id': row['_id']}, {'supports': 1})
    _write(store, row)
    if prior is not None:
        lost = [name for name in WORDS if name in prior.get('supports', ()) and name not in names]
        gained = [name for name in WORDS if name not in prior.get('supports', ()) and name in names]
        if lost or gained:
            # The latest change stands; each conversation of the channel reads it once (change_line).
            _write(store, {'_id': CHANGE + ':' + channel_id, 'kind': CHANGE, 'channel_id': channel_id, 'lost': lost,
                           'gained': gained, 'at': now(), 'shown': [], 'schema_version': 1})
    missing = [name for name in POINTERS if name not in names]
    if missing and first:
        log.info('channel %s does not declare %s: hidden from her there', channel_id, ', '.join(missing))


def _write(store, row):
    if store.db.artifacts.find_one({'_id': row['_id']}, {'_id': 1}):
        store.db.artifacts.replace_one({'_id': row['_id']}, row)
        return
    try:
        store.db.artifacts.insert_one(row)
    except Exception:                                        # noqa: BLE001 another claim wrote it first
        store.db.artifacts.replace_one({'_id': row['_id']}, row)


def change_line(store, scene):
    """The one line a conversation gets after its channel lost or regained a function she uses, at its next turn;
    None when there is none or it was shown here already."""
    channel_id = (scene or {}).get('channel_id')
    row = store.db.artifacts.find_one({'_id': CHANGE + ':' + channel_id}) if channel_id else None
    if not row or scene['_id'] in (row.get('shown') or ()):
        return None
    store.db.artifacts.replace_one({'_id': row['_id']}, {**row, 'shown': [*(row.get('shown') or ()), scene['_id']]})
    said = []
    if row.get('lost'):
        said.append(CANNOT % '、'.join(WORDS[name] for name in row['lost']))
    if row.get('gained'):
        said.append(BACK % '、'.join(WORDS[name] for name in row['gained']))
    return '；'.join(said) + '。'


def supports(store, channel_id):
    """The names a channel's adapter last declared; empty when it never did."""
    if not channel_id:
        return ()
    with _lock:
        if channel_id in _known:
            return _known[channel_id]
    row = store.db.artifacts.find_one({'_id': _row_id(channel_id)}, {'supports': 1}) or {}
    names = tuple(row.get('supports') or ())
    with _lock:
        _known.setdefault(channel_id, names)
    return names


def carries(store, scene, *names):
    """Whether the scene's channel declares any of these."""
    channel_id = (scene or {}).get('channel_id')
    have = supports(store, channel_id)
    return any(name in have for name in names)


def numbered(store, scene):
    """Lines there show their number: the channel carries quotes, out or in (ADR-079 §9.2)."""
    return carries(store, scene, 'quote', 'quote_in')


def forget():
    with _lock:
        _known.clear()
        _warned.clear()
