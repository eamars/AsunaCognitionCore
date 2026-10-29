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

An entry may carry the largest size the platform takes, in bytes: `file:4096` declares `file` with that limit
(`limit`). The names are kept as plain names; an entry whose limit is not a whole number is not declared.
"""
from __future__ import annotations

import logging
import re
import threading

from .state import now
from .records import artifacts as artifact_records

KIND = 'channel_capabilities'
LIMITED = re.compile(r'^([^:]+):(\d{1,20})$')
POINTERS = ('quote', 'quote_in', 'react', 'react_in', 'recall')
CHANGE = 'capability_change'
# What she does herself, in her words (ADR-079 §9.7): a change of one is told to each conversation once.
WORDS = {'quote': '引用', 'react': '点表情', 'recall': '撤回自己的话'}
CANNOT = '这条腿做不了%s'
BACK = '这条腿又能%s了'
log = logging.getLogger(__name__)

_lock = threading.Lock()
_known = {}                    # channel id -> the declared names, as last kept
_limits = {}                   # channel id -> {name: the largest size it takes, in bytes}, as last kept
_warned = set()                # channel ids whose missing pointer capabilities were logged this run


def _row_id(channel_id):
    return 'capabilities:' + channel_id


def split(supports):
    """(names, limits) of a declaration: `name` or `name:<bytes>`; an entry whose limit is not a whole number is
    left out."""
    names, limits = set(), {}
    for entry in supports or ():
        entry = str(entry or '')
        if not entry:
            continue
        if ':' not in entry:
            names.add(entry)
            continue
        found = LIMITED.match(entry)
        if found:
            names.add(found.group(1))
            limits[found.group(1)] = int(found.group(2))
    return tuple(sorted(names)), limits


def declared(store, channel_id, supports):
    """Keep what an adapter declared on a claim; write the row only when it changed. A pointer capability the adapter
    did not declare is logged once per run, naming the channel and the function."""
    names, limits = split(supports)
    with _lock:
        if _known.get(channel_id) == names and _limits.get(channel_id) == limits:
            return
        _known[channel_id] = names
        _limits[channel_id] = limits
        first = channel_id not in _warned
        _warned.add(channel_id)
    row = {'_id': _row_id(channel_id), 'kind': KIND, 'channel_id': channel_id, 'supports': list(names),
           **({'limits': limits} if limits else {}), 'declared_at': now(), 'schema_version': 1}
    prior = artifact_records.get(store, row['_id'], ['supports'])
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
    if artifact_records.get(store, row['_id'], ['_id']):
        artifact_records.replace(store, row)
        return
    try:
        artifact_records.insert(store, row)
    except Exception:                                        # noqa: BLE001 another claim wrote it first
        artifact_records.replace(store, row)


def change_line(store, scene):
    """The one line a conversation gets after its channel lost or regained a function she uses, at its next turn;
    None when there is none or it was shown here already."""
    channel_id = (scene or {}).get('channel_id')
    row = artifact_records.get(store, CHANGE + ':' + channel_id) if channel_id else None
    if not row or scene['_id'] in (row.get('shown') or ()):
        return None
    artifact_records.replace(store, {**row, 'shown': [*(row.get('shown') or ()), scene['_id']]})
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
    row = artifact_records.get(store, _row_id(channel_id), ['supports', 'limits']) or {}
    names = tuple(row.get('supports') or ())
    with _lock:
        _known.setdefault(channel_id, names)
        _limits.setdefault(channel_id, dict(row.get('limits') or {}))
    return names


def limit(store, channel_id, name):
    """The largest size in bytes a channel's adapter declared for one of its functions (`file:<bytes>`); None when
    it declared none."""
    if not channel_id:
        return None
    with _lock:
        known = channel_id in _limits
        value = (_limits.get(channel_id) or {}).get(name)
    if not known:
        supports(store, channel_id)
        with _lock:
            value = (_limits.get(channel_id) or {}).get(name)
    return value


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
        _limits.clear()
        _warned.clear()
