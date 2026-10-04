"""History delta for one native role session (ADR-009 D-3).

A role session keeps its own transcript, so rows it has already been given, and
its own replies, need not be prepended again on every MONOLOGUE. The cursor lives
on the ``sessions`` row: ``history_hwm`` ({source scene id: scene_seq}),
``history_generation`` (the compaction generation the cursor was set under) and
``compaction_generation`` (the latest count of completed native compactions seen
in a stage result). When the two generations differ, the transcript may have been
summarized, so the cursor is dropped and the full window is given again.

Sessions without a cursor (first turn, or no session key) get the full window,
exactly as before.
"""
from __future__ import annotations

HISTORY_ONLY_PREFIX = 'history:'


def select(store, key, rows, own_scene, source_seq):
    """Return (rows to give, manifest). ``rows`` is the ordinary window, newest first."""
    cursor = store.db.sessions.find_one({'_id': key}) or {}
    generation = cursor.get('compaction_generation', 0)
    full = not cursor.get('history_hwm') or cursor.get('history_generation', 0) != generation
    hwm = {} if full else dict(cursor['history_hwm'])
    own = set()
    if not full:
        outbound = [row['episode_id'] for row in rows if row.get('direction') == 'outbound' and row.get('episode_id')]
        own = {ep['_id'] for ep in store.db.episodes.find({'_id': {'$in': outbound}, 'history_session': key}, {'_id': 1})}
    given, next_hwm = [], dict(hwm)
    for row in rows:
        scene = row.get('scene_id') or own_scene
        seq = row.get('scene_seq') or 0
        next_hwm[scene] = max(next_hwm.get(scene, -1), seq)
        if seq <= hwm.get(scene, -1) or (row.get('direction') == 'outbound' and row.get('episode_id') in own):
            continue
        given.append(row)
    if source_seq is not None:
        next_hwm[own_scene] = max(next_hwm.get(own_scene, -1), source_seq)
    return given, {'session': key, 'full_window': full, 'given': len(given), 'omitted': len(rows) - len(given),
                   'generation': generation, 'next_hwm': next_hwm}


def _write(store, key, values):
    row = store.db.sessions.find_one({'_id': key})
    if row:
        return store.put('sessions', {**row, **values}, expected=row['revision'], stream='history:' + key)
    if key.startswith(HISTORY_ONLY_PREFIX):
        # Lanes without a native session (tests, offline) keep the cursor on their own row.
        return store.put('sessions', {'_id': key, 'binding_key': key, 'history_only': True, **values}, stream=key)
    return None                         # a native row is created by its binding; never pre-create it


def advance(store, manifest):
    """After the stage that carried the history block: the session has now seen the window."""
    return _write(store, manifest['session'], {'history_hwm': manifest['next_hwm'],
                                               'history_generation': manifest['generation']})


def observe(store, key, generation):
    """Record the compaction count reported by a stage result (None: lane cannot tell)."""
    if generation is None:
        return None
    row = store.db.sessions.find_one({'_id': key}) or {}
    if row.get('compaction_generation', 0) == generation and row:
        return row
    return _write(store, key, {'compaction_generation': int(generation)})
