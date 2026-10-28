"""The read-only check of one ADR-104 batch against a deployment's database, before the batch merges: numbers only,
never a record id or a value.

  python tools/adr104_equivalence.py b1b|b2|b3|b4|b5 [--config config/local.json] [--out <folder>] [--max-ms 2000]

Each batch: what the store's `ensure` would do there, as a dry run (collections it would create, indexes it would
make, retired indexes it would drop, indexes of a declared name that differ, validators), and for every field the
catalog declares in the batch's collections (b1b: all of them; b2: `host_leases` and `lane_faults`; b3: `scenes`;
b4: `messages`; b5: `episodes`, `sessions`, `sink_receipts`, `lane_receipts`), its stored records by BSON type, the
nulls, the records missing a required field and, for a vector, the lengths that differ; b4 and b5 also, per
collection (SIZED), the records of 512 KiB or more and those whose BSON and JSON sizes fall on different sides of
1 MiB. b3, b4 and b5 also run their read cases: each read the batch moved, as the replaced code wrote it with
pymongo and as the owner (`records.scenes`, `records.messages`, `records.episodes`, `records.sessions`,
`records.receipts`) now answers it, on parameters sampled through the
owners (at most 20 a case, at most 1,000 queries in all, serial, `--max-ms` each, three runs for the times): the same
ids in the same order, the same records (values in one order for a distinct), the same plan stages (a distinct or an
aggregate has no plan of its own to compare; the new plan is reported), and how many rows each side answered; per
declared field, the records whose value its declaration refuses; numbers only. The collections to create, the
indexes to make and the validators count for the collections the batch declares (the rest are reported apart); a
plan difference the lead accepted (ACCEPTED_PLAN_DIFFERENCES) is reported with its reason, recheck and times and
does not fail the run. The timing gate: a read case whose new p50 is more than SLOWER times its old p50 and more than
SLOWER_MS above it, and still past it when timed again (CONFIRM_RUNS runs of each side), fails the run, named with
both times and the new plan, unless the lead accepted it (ACCEPTED_SLOWDOWNS: the times when accepted, the reason,
when it is looked at again; each reported on every run); the cases watched under the threshold (WATCHED) are
reported beside their family with their times.
The field counts are many small reads (parts of at most PART_RECORDS records by `_id`, FIELDS_PER_READ fields
each), each bounded by `--max-ms` on the server; a read over its limit leaves its fields unchecked, named in the
report (exit 2). Each query is read-only and bounded by `--max-ms`. The numbers go to `<out>/<batch>.json` (default
`<data>/private/adr104-evidence/<batch>/`) and to the console. Exit 0 when nothing would be created, made or refused,
every validator is the one ensure creates and every declared field holds only its kind (the retired indexes to drop
are reported: dropping them is the batch's change); 1 when something differs; 2 when a check could not run (a query
over its time limit, the server out of reach).
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from pymongo import MongoClient  # noqa: E402
from pymongo.errors import ExecutionTimeout, PyMongoError  # noqa: E402

from asuna.store.catalog import CATALOG  # noqa: E402
from asuna.store.mongodb import MongoAdapter  # noqa: E402

KINDS = {'text': {'string'}, 'number': {'int', 'long', 'double', 'decimal'}, 'bool': {'bool'}, 'time': {'date'},
         'object': {'object'}, 'list': {'array'}, 'vector': {'array'}}


def dry_run(adapter):
    """{collection: plan and validator}; nothing is written."""
    return {c.name: {**adapter.plan(c), 'validator': adapter.validator(c)} for c in CATALOG.collections()}


def _bson_type(value):
    """A Python value's BSON type name, as `$type` names it."""
    from datetime import datetime
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'bool'
    if isinstance(value, int):
        return 'int' if -2 ** 31 <= value < 2 ** 31 else 'long'
    return {float: 'double', str: 'string', dict: 'object', list: 'array', datetime: 'date'}.get(type(value), 'other')


def _values_at(value, parts):
    """The values at a path, through the objects of lists on the way."""
    if not parts:
        yield value
    elif isinstance(value, dict):
        if parts[0] in value:
            yield from _values_at(value[parts[0]], parts[1:])
    elif isinstance(value, list):
        for item in value:
            yield from _values_at(item, parts)


def _list_root(collection, path):
    """The first declared list on a field's path (its records hold the field once per element), or None."""
    parts = path.split('.')
    for n in range(1, len(parts)):
        declared = collection.field('.'.join(parts[:n]))
        if declared is not None and declared.kind == 'list':
            return '.'.join(parts[:n])
    return None


# The field-kind counts are many small reads, never one scan of a whole collection: the records in parts of at most
# PART_RECORDS by `_id` (its index), a few fields at a time, each read bounded by `--max-ms` on the server.
PART_RECORDS = 20000
FIELDS_PER_READ = 10


def parts(db, name, max_ms, timings):
    """The `_id` bounds that cut a collection into parts of at most PART_RECORDS records: [(after, upto)], None
    standing for an open end. Each bound is one read of the `_id` index (the store's ids are text)."""
    import time as clock
    bounds, last = [], None
    while True:
        started = clock.perf_counter()
        try:
            found = list(db[name].find({'_id': {'$gt': last}} if last is not None else {}, {'_id': 1},
                                       sort=[('_id', 1)], skip=PART_RECORDS - 1, limit=1, max_time_ms=max_ms))
        finally:
            timings.append((clock.perf_counter() - started) * 1000)
        if not found:
            bounds.append((last, None))
            return bounds
        bounds.append((last, found[0]['_id']))
        last = found[0]['_id']


def _part(after, upto):
    bound = {**({'$gt': after} if after is not None else {}), **({'$lte': upto} if upto is not None else {})}
    return {'_id': bound} if bound else {}


def kinds(db, collection, max_ms, timings=None, unchecked=None):
    """Per declared field: {bson type: records}, the records whose vector length differs from the declared one, and
    for a list {element bson type: records}. A field inside the objects of a list is counted by the types of the
    values its records hold there (a record holding none counts as missing), read from the records holding the
    list. Read part by part and a few fields at a time (PART_RECORDS, FIELDS_PER_READ), each read bounded by
    `max_ms`; a read over its limit adds its fields to `unchecked` and the count goes on without it."""
    import time as clock
    timings = [] if timings is None else timings
    unchecked = set() if unchecked is None else unchecked
    fields = [f for f in collection.fields if f.path != '_id']
    if not fields:
        return {}
    found = {f.path: {'types': {}, 'other_length': 0, 'elements': {}} for f in fields}
    plain = [f for f in fields if _list_root(collection, f.path) is None]
    groups = [plain[n:n + FIELDS_PER_READ] for n in range(0, len(plain), FIELDS_PER_READ)]
    nested = {}
    for f in fields:
        root = _list_root(collection, f.path)
        if root is not None:
            nested.setdefault(root, []).append(f)
    try:
        cut = parts(db, collection.name, max_ms, timings)
    except ExecutionTimeout:                           # the parts' bounds could not be read: nothing is counted
        unchecked.update(f.path for f in fields)
        return found
    for after, upto in cut:
        where = _part(after, upto)
        for group in groups:
            project = {'_id': 0, **{'k%d' % n: {'$type': '$' + f.path} for n, f in enumerate(group)}}
            for n, f in enumerate(group):
                if f.kind == 'vector':
                    project['d%d' % n] = {'$cond': [{'$isArray': '$' + f.path}, {'$size': '$' + f.path}, None]}
                if f.kind == 'list':
                    project['e%d' % n] = {'$cond': [{'$isArray': '$' + f.path}, {'$setUnion': [
                        {'$map': {'input': '$' + f.path, 'in': {'$type': '$$this'}}}]}, []]}
            started = clock.perf_counter()
            try:
                rows = list(db[collection.name].aggregate(
                    [{'$match': where}, {'$project': project}, {'$group': {'_id': '$$ROOT', 'n': {'$sum': 1}}}],
                    maxTimeMS=max_ms))
            except ExecutionTimeout:
                unchecked.update(f.path for f in group)
                continue
            finally:
                timings.append((clock.perf_counter() - started) * 1000)
            for row in rows:
                for n, f in enumerate(group):
                    kind = row['_id'].get('k%d' % n, 'missing')
                    found[f.path]['types'][kind] = found[f.path]['types'].get(kind, 0) + row['n']
                    length = row['_id'].get('d%d' % n)
                    if f.kind == 'vector' and length is not None and length != f.dimensions:
                        found[f.path]['other_length'] += row['n']
                    for element in row['_id'].get('e%d' % n) or ():
                        found[f.path]['elements'][element] = found[f.path]['elements'].get(element, 0) + row['n']
        for root, inside in nested.items():
            started = clock.perf_counter()
            try:
                docs = list(db[collection.name].find({**where, root: {'$type': 'array'}}, {root: 1},
                                                     max_time_ms=max_ms))
            except ExecutionTimeout:
                unchecked.update(f.path for f in inside)
                continue
            finally:
                timings.append((clock.perf_counter() - started) * 1000)
            for doc in docs:
                for f in inside:
                    seen = {_bson_type(value) for value in _values_at(doc, f.path.split('.'))} or {'missing'}
                    for kind in seen:
                        found[f.path]['types'][kind] = found[f.path]['types'].get(kind, 0) + 1
                    if f.kind == 'list':
                        for value in _values_at(doc, f.path.split('.')):
                            for element in {_bson_type(item) for item in value} if isinstance(value, list) else ():
                                found[f.path]['elements'][element] = found[f.path]['elements'].get(element, 0) + 1
    return found


def differing(collection, counts):
    """Per declared field, the records whose value the declaration refuses (another kind, null where not
    nullable, a list element of another kind; a record holding several such counts once per kind), 0 for none."""
    out = {}
    for f in collection.fields:
        if f.path == '_id' or f.path not in counts:
            continue
        allowed = KINDS[f.kind] | {'missing'} | ({'null'} if f.nullable else set())
        wrong = sum(n for kind, n in counts[f.path]['types'].items() if kind not in allowed)
        if f.kind == 'list':
            wrong += sum(n for kind, n in (counts[f.path].get('elements') or {}).items() if kind not in KINDS[f.of])
        out[f.path] = wrong + counts[f.path]['other_length'] + (counts[f.path]['types'].get('missing', 0)
                                                                 if f.required else 0)
    return out


def differs(collection, counts):
    """The declared fields whose stored records the declaration refuses: another kind, null where not nullable, a
    required field missing, a vector of another length, a list holding an element of another kind."""
    wrong = []
    for f in collection.fields:
        if f.path == '_id' or f.path not in counts:
            continue
        types = counts[f.path]['types']
        allowed = KINDS[f.kind] | {'missing'} | ({'null'} if f.nullable else set())
        elements = set(counts[f.path].get('elements') or ()) - (KINDS[f.of] if f.kind == 'list' else set())
        if set(types) - allowed or (f.required and types.get('missing')) or counts[f.path]['other_length']                 or (f.kind == 'list' and elements):
            wrong.append(f.path)
    return wrong


# The collections whose declared fields each batch counts (None: every collection).
BATCHES = {'b1b': None, 'b2': ('host_leases', 'lane_faults'), 'b3': ('scenes',), 'b4': ('messages',),
           'b5': ('episodes', 'sessions', 'sink_receipts', 'lane_receipts')}
# The collections whose records' sizes each batch counts (512 KiB or more; BSON and JSON on different sides of 1 MiB).
SIZED = {'b4': ('messages',), 'b5': ('episodes', 'sessions', 'sink_receipts', 'lane_receipts')}
QUERIES = 1000
_ARCHIVED = {'reason': "the archived stream's old read left out `legacy` by an exclusion projection, which the store "
                       "does not have; the owner drops it after the read (accepted for B4, 2026-10-28)",
             'recheck': 'recheck not recorded'}
# Plan differences the lead accepted, by batch and case: reported with their reason and recheck, and their times,
# not counted against a clean run.
ACCEPTED_PLAN_DIFFERENCES = {'b4': {'search, archived lines': _ARCHIVED,
                                    'search, archived lines by person after both cursors': _ARCHIVED}}
# The timing gate: a read case whose new p50 is more than SLOWER times its old p50 and more than SLOWER_MS above it
# fails the run, unless the lead accepted it here, by batch and case: {'old_ms', 'new_ms' (the p50s as measured when
# accepted), 'reason', 'recheck' (when it is looked at again)}. Each accepted entry is reported on every run.
SLOWER, SLOWER_MS = 2.0, 5.0
# A case over the gate is timed again before it fails: CONFIRM_RUNS more runs of each side, alternating, on its first
# sample, within the query budget; the confirmation's p50s decide (a server's jitter of a few tens of ms on a read of
# one or two ms otherwise fails a run whose plans and records are the same, and passes the next).
CONFIRM_RUNS = 10
ACCEPTED_SLOWDOWNS = {}
# Cases under the threshold that are watched, by batch and case: reported on every run with their times now, beside
# the case they are of a family with, so they are seen, not passed silently.
WATCHED = {'b4': {'who wrote in these': {
    'family': 'who wrote here', 'old_ms': 12, 'new_ms': 19,
    'note': 'same family, under threshold: a values read grouped by presence, as "who wrote here" (293 ms against 9 '
            'before fa46c24132f6); measured at B4 old p50 ~12 ms, new ~19 ms, 1.55x'}}}
RUNS = 3
READ_CASES = ('b3', 'b4', 'b5')


def slower(old, new):
    """Whether a new p50 is past the timing gate: more than SLOWER times the old and more than SLOWER_MS above it."""
    return old is not None and new is not None and new > SLOWER * old and new - old > SLOWER_MS


def slowdowns(batch, cases):
    """(failing, accepted): the read cases past the timing gate (`slower`), by their confirmation's p50s when they
    were timed again (`confirm`), each (name, old p50, new p50, new plan); those the lead accepted
    (ACCEPTED_SLOWDOWNS) apart."""
    failing, accepted = [], []
    for name, case in cases.items():
        timing = case['confirm'] if (case.get('confirm') or {}).get('runs') else case
        old, new = timing.get('ms_old_p50'), timing.get('ms_new_p50')
        if not slower(old, new):
            continue
        found = (name, old, new, case.get('plan_new'))
        (accepted if name in ACCEPTED_SLOWDOWNS.get(batch, {}) else failing).append(found)
    return failing, accepted


def _stages(plan):
    """The stage names of a query plan, root first, with the index each scan uses."""
    out = []
    while plan:
        out.append(plan.get('stage', '?') + (':' + plan['indexName'] if plan.get('indexName') else ''))
        plan = plan.get('inputStage') or (plan.get('inputStages') or [None])[0]
    return out


def _plain(value):
    """A record as compared: times as UTC without a zone (the old client reads them naive, the adapter aware)."""
    from datetime import timezone
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if hasattr(value, 'tzinfo') and getattr(value, 'tzinfo', None) is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


class _Recording(MongoAdapter):
    """The MongoDB adapter, keeping the last read it sent (to explain it): (collection, filter, sort, skip, limit,
    fields)."""
    sent = None

    def get(self, coll, id, fields=None):
        self.sent = (coll, {'_id': id}, (), 0, 1, fields)
        return super().get(coll, id, fields)

    def find(self, coll, where, sort=(), skip=0, limit=None, fields=None):
        from asuna.store.mongodb import query
        self.sent = (coll, query(where), sort, skip, limit or 0, fields)
        return super().find(coll, where, sort, skip, limit, fields)

    def count(self, coll, where, limit=None):
        from asuna.store.mongodb import query
        self.sent = (coll, query(where), (), 0, 0, None)
        return super().count(coll, where, limit)

    def group(self, coll, where, by, *args, **kwargs):
        from asuna.store.mongodb import query
        self.sent = (coll, query(where), (), 0, 0, None)
        return super().group(coll, where, by, *args, **kwargs)


def _cases_b3(store):
    """(name, old(param), new(param), parameters, compare) for each read B3 moved, the old as the replaced code
    wrote it."""
    from asuna.records import scenes as owner
    rows = sorted(owner.all(store, fields=['_id', 'scope_key', 'policy_epoch', 'kind']), key=lambda r: r['_id'])
    ids, kinds = [r['_id'] for r in rows], ['group', 'dm']
    scopes = [r['scope_key'] for r in rows if isinstance(r.get('scope_key'), str)]
    pairs = [(r['scope_key'], r.get('policy_epoch')) for r in rows if isinstance(r.get('scope_key'), str)]
    batches = [ids[n:n + 5] for n in range(0, len(ids), 5)]
    one = lambda filter, proj=None: ('find_one', 'scenes', filter, proj, None)
    many = lambda filter, proj=None: ('find', 'scenes', filter, proj, None, 0)
    return [(name, old, new, params, 'value') for name, old, new, params in [
        ('get', lambda i: one({'_id': i}), lambda i: owner.get(store, i), ids),
        ('get fields', lambda i: one({'_id': i}, {'kind': 1}), lambda i: owner.get(store, i, fields=['kind']), ids),
        ('by_scope', lambda s: one({'scope_key': s}), lambda s: owner.by_scope(store, s), scopes),
        ('by_scope group fields', lambda s: one({'scope_key': s, 'kind': 'group'}, {'scope_key': 1, 'policy_epoch': 1}),
         lambda s: owner.by_scope(store, s, kind='group', fields=['scope_key', 'policy_epoch']), scopes),
        ('by_scope epoch', lambda p: one({'scope_key': p[0], 'policy_epoch': p[1]}),
         lambda p: owner.by_scope(store, p[0], epoch=p[1]), pairs),
        ('of_kind fields', lambda k: many({'kind': k}, {'scope_key': 1, 'policy_epoch': 1, 'kind': 1, 'channel_id': 1}),
         lambda k: owner.of_kind(store, k, fields=['scope_key', 'policy_epoch', 'kind', 'channel_id']), kinds),
        ('of_kind besides', lambda i: many({'kind': 'group', '_id': {'$ne': i}}, {'scope_key': 1, 'policy_epoch': 1, 'kind': 1}),
         lambda i: owner.of_kind(store, 'group', besides=i, fields=['scope_key', 'policy_epoch', 'kind']), ids),
        ('of_kind whole', lambda k: many({'kind': k}), lambda k: owner.of_kind(store, k), kinds),
        ('many fields', lambda b: many({'_id': {'$in': b}}, {'kind': 1}), lambda b: owner.many(store, b, fields=['kind']),
         batches),
        ('many group', lambda b: many({'_id': {'$in': b}, 'kind': 'group'}), lambda b: owner.many(store, b, kind='group'),
         batches),
        ('in_scopes', lambda b: many({'scope_key': {'$in': b}}, {'scope_key': 1, 'sequence': 1}),
         lambda b: owner.in_scopes(store, b, fields=['scope_key', 'sequence']),
         [scopes[n:n + 5] for n in range(0, len(scopes), 5)]),
        ('all fields', lambda _: many({}, {'_id': 1, 'kind': 1}), lambda _: owner.all(store, fields=['_id', 'kind']), [None]),
        ('condense_wanted', lambda _: many({'condense_wanted': {'$exists': True}, 'kind': 'group'}),
         lambda _: owner.condense_wanted(store), [None]),
        ('channel_scenes', lambda k: one({'kind': k, 'channel_id': {'$exists': True}}, {'_id': 1}),
         lambda k: owner.channel_scenes(store, k), kinds),
    ]]


def _old(db, call):
    """An old read as the replaced code made it: (its answer, a cursor of the same query to explain, or None when the
    form has no plan of its own to compare: distinct, an aggregate). A call is ('find_one', coll, filter, projection,
    sort), ('find', coll, filter, projection, sort, limit), ('count', coll, filter, limit), ('distinct', coll, field,
    filter), ('aggregate', coll, pipeline), or a function of the database doing several (its last query explained)."""
    if callable(call):
        return call(db)
    method, coll = call[0], db[call[1]]
    if method == 'find_one':
        _, _, filter, proj, sort = call
        return coll.find_one(filter, proj, sort=sort), coll.find(filter, proj, sort=sort).limit(1)
    if method == 'find':
        _, _, filter, proj, sort, limit = call
        return list(coll.find(filter, proj, sort=sort, limit=limit)), coll.find(filter, proj, sort=sort, limit=limit)
    if method == 'count':
        _, _, filter, limit = call
        return coll.count_documents(filter, **({'limit': limit} if limit else {})), coll.find(filter)
    if method == 'distinct':
        _, _, field, filter = call
        return coll.distinct(field, filter), None
    _, _, pipeline = call
    return list(coll.aggregate(pipeline)), None


def _compared(value, how):
    """A read's answer as compared: records as they are (times without a zone), values in one order."""
    value = _plain(value)
    if how == 'values':
        return sorted(value, key=repr)
    return value


def _amount(value):
    """How much a read answered: rows or values in a list, a record as one, a count as itself."""
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return 1
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def reads(client, database, max_ms, batch, config):
    """Each case's numbers: n, same, differing, plan stages and times, old against new; none are ids. A case whose
    old form has no plan to compare (a distinct, an aggregate) reports the new plan only."""
    import statistics
    import time as clock
    from asuna.store import Checked
    old_db = client.get_database(database)
    adapter = _Recording(client, database)
    store = Checked(adapter, CATALOG)
    cases, sampling = (_cases_b3(store), 1) if batch == 'b3' else {'b4': _cases_b4, 'b5': _cases_b5}[batch](
        store, config)
    per_case = max(1, min(20, (QUERIES - sampling - 2 * len(cases)) // (len(cases) * 2 * RUNS)))
    out, timed, explained, confirmed = {}, 0, 0, 0
    for name, old_call, new_call, params, how in cases:
        chosen = params[::max(1, len(params) // per_case)][:per_case] if params else []
        same = differing = plans_differ = rows_old = rows_new = 0
        times = {'old': [], 'new': []}
        old_plan = new_plan = None
        compared = True
        for param in chosen:
            results = {}
            for _ in range(RUNS):
                started = clock.perf_counter()
                old_value, old_cursor = _old(old_db, old_call(param))
                times['old'].append((clock.perf_counter() - started) * 1000)
                started = clock.perf_counter()
                new_value = new_call(param)
                times['new'].append((clock.perf_counter() - started) * 1000)
                timed += 2
                results = {'old': _compared(old_value, how), 'new': _compared(new_value, how)}
            rows_old, rows_new = rows_old + _amount(old_value), rows_new + _amount(new_value)
            if results['old'] == results['new']:
                same += 1
            else:
                differing += 1
            if old_plan is None or new_plan is None or param is chosen[-1]:
                coll, filter, sort, skip, limit, fields = adapter.sent
                new_cursor = adapter.db[coll].find(filter, {f: 1 for f in fields} if fields else None,
                                                   sort=list(sort) or None, skip=skip, limit=limit)
                new_plan = _stages(new_cursor.explain()['queryPlanner']['winningPlan'])
                explained += 1
                if old_cursor is None:
                    compared = False
                else:
                    old_plan = _stages(old_cursor.explain()['queryPlanner']['winningPlan'])
                    explained += 1
                    plans_differ += old_plan != new_plan
        pct = lambda values, q: round(statistics.quantiles(values, n=20)[q], 2) if len(values) > 1 else (
            round(values[0], 2) if values else None)
        out[name] = {'n': len(chosen), 'same': same, 'differing': differing, 'plans_differ': plans_differ,
                     'rows_old': rows_old, 'rows_new': rows_new,
                     'plan_accepted': name in ACCEPTED_PLAN_DIFFERENCES.get(batch, {}),
                     'plans_compared': compared, 'plan_old': old_plan, 'plan_new': new_plan,
                     'ms_old_p50': pct(times['old'], 9), 'ms_old_p95': pct(times['old'], 18),
                     'ms_new_p50': pct(times['new'], 9), 'ms_new_p95': pct(times['new'], 18)}
        if slower(out[name]['ms_old_p50'], out[name]['ms_new_p50']) and chosen:
            if sampling + timed + confirmed + explained + 2 * CONFIRM_RUNS > QUERIES:
                out[name]['confirm'] = {'runs': 0, 'why': 'over the query budget: not timed again'}
                continue
            again = {'old': [], 'new': []}
            for _ in range(CONFIRM_RUNS):
                started = clock.perf_counter()
                _old(old_db, old_call(chosen[0]))
                again['old'].append((clock.perf_counter() - started) * 1000)
                started = clock.perf_counter()
                new_call(chosen[0])
                again['new'].append((clock.perf_counter() - started) * 1000)
            confirmed += 2 * CONFIRM_RUNS
            out[name]['confirm'] = {'runs': CONFIRM_RUNS, 'ms_old_p50': round(statistics.median(again['old']), 2),
                                    'ms_new_p50': round(statistics.median(again['new']), 2)}
    samples = sum(case['n'] for case in out.values())
    # What was run: the sampling reads, each case's samples x 2 sides x RUNS timed runs, the confirmations of cases
    # over the timing gate, and the explains (two per explained sample, one where the old form has no plan of its own).
    return out, {'sampling': sampling, 'samples': samples, 'timed': timed, 'confirmed': confirmed,
                 'explain': explained, 'total': sampling + timed + confirmed + explained,
                 'counted_as': 'sampling + samples x 2 sides x %d runs + confirmations + explain' % RUNS}


PROGRAM_AUTHOR = 'asuna:internal'                       # ingress.PROGRAM_AUTHOR as the replaced code named it
NOT_CORE_NOTICE = {'author': {'$ne': PROGRAM_AUTHOR}}   # ingress.NOT_CORE_NOTICE
SAID = [{'direction': 'inbound'}, {'direction': 'outbound', 'delivery_state': 'DELIVERED'}]   # the outbound form
SAID_DELIVERED = [{'direction': 'inbound'}, {'delivery_state': 'DELIVERED'}]                  # the delivered form
POINTABLE = {'$or': [{'direction': 'inbound', 'event.raw.asuna_notice': {'$exists': False}, **NOT_CORE_NOTICE},
                     {'direction': 'outbound', 'delivery_state': 'DELIVERED'}]}              # people.People.POINTABLE
RELATED = {'text': 1, 'author': 1, 'direction': 1, 'scene_seq': 1, 'delivery_state': 1, 'platform_reply_to': 1,
           'event.group_context': 1, 'episode_id': 1, 'occurred_at': 1, 'receipt_at': 1, 'received_at': 1}
HISTORY = {'text': 1, 'author': 1, 'direction': 1, 'delivery_state': 1, 'platform_event_id': 1, 'platform_reply_to': 1,
           'event.group_context': 1, 'scene_seq': 1, 'episode_id': 1, 'received_at': 1, 'receipt_at': 1,
           'attachment': 1, 'attachment_skipped': 1, 'occurred_at': 1, 'event.raw.asuna_catchup': 1,
           'platform_receipt.response.verification': 1, 'event.raw.asuna_notice': 1, 'recalled_at': 1}
THREAD = {'_id': 1, 'text': 1, 'author': 1, 'direction': 1, 'phase': 1, 'delivery_state': 1, 'occurred_at': 1,
          'receipt_at': 1, 'receipt': 1, 'scene_seq': 1, 'scene_id': 1, 'policy_epoch': 1, 'reply_to': 1,
          'event.group_context': 1, 'event.raw.asuna_peer': 1, 'event.channel': 1}           # discussion_digest
SAMPLED = ['_id', 'scene_id', 'policy_epoch', 'scene_seq', 'direction', 'author', 'episode_id', 'received_at',
           'receipt_at', 'channel_id', 'target', 'receipt', 'segment_index', 'text', 'event.event_id',
           'event.channel.platform_event_id', 'platform_message_id', 'event.group_context.topic_id',
           'event.raw.asuna_peer.display', 'event.raw.asuna_forward']


def _old_receipt(parts, refs, query=None, case=True, author=None, person=None, authors=None):
    """history_query's receipt stream as the replaced code built it (outbound_fallback_filter, person_clause,
    scene_id_clause): its filter and sort."""
    ids = list(dict.fromkeys(parts['scene_ids']))
    flt = {'scene_id': ids[0]} if len(ids) == 1 else {'scene_id': {'$in': ids}}
    flt.update({'policy_epoch': parts['epoch'], 'direction': 'outbound', 'phase': 'SPEAK',
                'delivery_state': 'DELIVERED', 'receipt': {'$in': sorted(refs)}, 'receipt_at': {'$exists': False}})
    if author:
        flt['author'] = author
    if query:
        flt['text'] = {'$regex': re.escape(query), **({} if case else {'$options': 'i'})}
    clause = _old_clause(person, authors)
    if clause:
        flt['$and'] = [dict(clause)]
    return flt, [('scene_seq', -1), ('scene_id', -1)]


def _old_streams(parts, query, window, pairs, case=True, author=None, person=None, authors=None, archived=False):
    """history_query's in-line streams as the replaced code built them (message_filters, then search_messages
    appending each stream's cursor to its condition list): {stream: (filter, sort)}. The archived stream copied the
    people's stream and so shared its condition list: with a person filter it also holds the people's cursor (the
    known defect B4 keeps)."""
    ids = list(dict.fromkeys(parts['scene_ids']))
    base = {'scene_id': ids[0]} if len(ids) == 1 else {'scene_id': {'$in': ids}}
    base['policy_epoch'] = parts['epoch']
    if author:
        base['author'] = author
    bounds = {op: value for op, value in zip(('$gte', '$lte'), window or ()) if value}
    pattern = {'$regex': re.escape(query), **({} if case else {'$options': 'i'})} if query else None
    inbound = dict(base, direction='inbound')
    outbound = dict(base, direction='outbound', phase='SPEAK', delivery_state='DELIVERED')
    if bounds:
        inbound['occurred_at'] = dict(bounds)
        outbound['receipt_at'] = dict(bounds)
    if pattern is not None:
        inbound['$or'] = [{'text': dict(pattern)}, {'event.raw.asuna_forward.nodes.text': dict(pattern)}]
        outbound['text'] = dict(pattern)
    clause = _old_clause(person, authors)
    if clause:
        inbound['$and'] = [dict(clause)]
        outbound['$and'] = [dict(clause)]
    streams = [('inbound', 'occurred_at', inbound), ('outbound', 'receipt_at', outbound)]
    if archived:
        archive = {**inbound, 'scene_id': {'$in': ['archive:' + sid for sid in parts['scene_ids']]},
                   'direction': 'archived', 'deletion_id': {'$exists': False}}
        if bounds:
            archive['occurred_at'] = {op: _archive_stamp(value) for op, value in bounds.items()}
        streams.append(('archived', 'occurred_at', archive))
    for key, field, flt in streams:
        pair = pairs.get(key)
        if pair:
            at, seq = pair[0], pair[1]
            clauses = [{field: {'$lt': at}}, {field: at, 'scene_seq': {'$lt': seq}}]
            if len(pair) > 2:
                clauses.append({field: at, 'scene_seq': seq, 'scene_id': {'$lt': pair[2]}})
            flt.setdefault('$and', []).append({'$or': clauses})
    return {key: (flt, [(field, -1), ('scene_seq', -1), ('scene_id', -1)]) for key, field, flt in streams}


def _old_clause(person, authors):
    """history_query.person_filter as the replaced code wrote it."""
    if authors is not None:
        return {'author': {'$in': list(authors)}}
    return {'$or': [{key: value} for key in ('author', 'event.raw.asuna_peer.person_id', 'event.raw.asuna_peer.card',
                                             'event.raw.asuna_peer.nickname', 'event.raw.asuna_peer.display',
                                             'event.raw.asuna_peer.aliases') for value in sorted(person)]}         if person else None


def _archive_stamp(value):
    """history_query._archive_stamp."""
    from datetime import datetime, timezone
    try:
        date = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return str(value)
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    return date.astimezone(timezone.utc).isoformat(timespec='microseconds')


def _days_before(stamp, days):
    """An ISO time `days` before another, in the form the core writes (or the same text when it is no time)."""
    from datetime import datetime, timedelta, timezone
    try:
        moment = datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
    except ValueError:
        return stamp
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (moment - timedelta(days=days)).isoformat()


def _sample_b4(store, config):
    """What the cases read with, through the owners: the conversations, and the newest lines of up to 20 of them."""
    from asuna.records import messages as owner, scenes as scene_owner
    scenes = sorted(scene_owner.all(store, fields=['_id', 'policy_epoch', 'kind', 'scope_key', 'summary_start_seq']),
                    key=lambda row: row['_id'])
    places, tried = [], 0
    for scene in scenes:
        if len(places) >= 20 or tried >= 60:
            break
        tried += 1
        rows = owner.lines(store, scene['_id']).rows(newest_first=True, limit=4, fields=SAMPLED)
        if rows and isinstance(scene.get('policy_epoch'), int):
            places.append((scene, rows))
    return scenes, places, tried


def _cases_b4(store, config):
    """(name, old(param), new(param), parameters, compare) for each read B4 moved, the old as the replaced code wrote
    it; parameters sampled through the owners, synthetic values where her lines hold none (both sides then read
    nothing, and the plans are still compared)."""
    from asuna.records import messages as owner
    me = config.get('character_id') or (config.get('chat') or {}).get('persona', 'character')
    boss = (config.get('chat') or {}).get('person_id') or 'nobody'
    scenes, places, tried = _sample_b4(store, config)
    lines = [(scene, row) for scene, rows in places for row in rows]
    first = [(scene, rows[0]) for scene, rows in places]                       # each conversation's newest line
    oldest = [(scene, rows[-1]) for scene, rows in places]                     # its 4th newest: a short window
    s = lambda pair: pair[0]['_id']
    e = lambda pair: pair[0]['policy_epoch']
    q = lambda pair: pair[1].get('scene_seq') or 0
    t = lambda pair: pair[1].get('received_at') or '9999'
    ids = [row['_id'] for _, row in lines]
    batches = [ids[n:n + 5] for n in range(0, len(ids), 5)]
    by_scene = [(scene, [row['_id'] for row in rows]) for scene, rows in places]
    inbound = [(scene, row) for scene, row in lines if row.get('direction') == 'inbound']
    outbound = [(scene, row) for scene, row in lines if row.get('direction') == 'outbound']
    outbound = [(scene, row) for scene, row in outbound if isinstance(row.get('episode_id'), str)]
    episodes = list(dict.fromkeys(row['episode_id'] for _, row in outbound))
    parts_of = [(scene, row) for scene, row in outbound if isinstance(row.get('segment_index'), int)] or outbound
    authors = [(scene, row['author']) for scene, row in inbound if isinstance(row.get('author'), str)]
    topics = [(scene, ((row.get('event') or {}).get('group_context') or {}).get('topic_id') or 'topic-none')
              for scene, row in inbound]
    events = [(scene, (row.get('event') or {}).get('event_id') or 'event-none') for scene, row in inbound]
    platform = [(scene, ((row.get('event') or {}).get('channel') or {}).get('platform_event_id')
                 or row.get('platform_message_id') or 'platform-none') for scene, row in lines]
    names = [(scene, ((row.get('event') or {}).get('raw') or {}).get('asuna_peer', {}).get('display') or 'name-none')
             for scene, row in inbound]
    refs = [(scene, next((block.get('ref') for block in (((row.get('event') or {}).get('raw') or {})
                                                         .get('asuna_forward') or []) if isinstance(block, dict)),
                         'forward-none')) for scene, row in inbound]
    channels = [(row['_id'], row['channel_id']) for _, row in outbound if isinstance(row.get('channel_id'), str)]
    targets = [(row['channel_id'], row['target']) for _, row in outbound
               if isinstance(row.get('channel_id'), str) and isinstance(row.get('target'), dict)]
    receipts = [(scene, row['receipt']) for scene, row in outbound if isinstance(row.get('receipt'), str)]
    newest = max((t(pair) for pair in first if t(pair) != '9999'), default='9999')
    recent = _days_before(newest, 2)                                           # two days before the newest line
    words = [(scene, row['text'][:2]) for scene, row in lines if isinstance(row.get('text'), str) and row['text']]
    home = (config.get('chat') or {}).get('scene_id') or 'home-none'
    routes = sorted({route['scene_id'] for channel in (config.get('channels') or {}).values()
                     for route in (channel.get('routes') or {}).values() if route.get('scene_id')} | {home})
    archived = []                                  # archived lines of up to 3 conversations, through the owner
    for pair in first[:3]:
        tried += 1
        rows = owner.search(store, [s(pair)], e(pair), 'archived', limit=4)
        if len(rows) >= 2:
            cursor = lambda row: [row.get('occurred_at'), row.get('scene_seq'), row.get('scene_id')]
            # her search by the person these archived lines' authors resolved to, its page after the newest one; the
            # people's cursor at the next one cuts the archived stream too (the defect B4 keeps)
            archived.append((pair, sorted({row['author'] for row in rows if isinstance(row.get('author'), str)}),
                             cursor(rows[1]), cursor(rows[0])))
    sources = lambda pair: [{'scene_id': s(pair), 'policy_epoch': e(pair)}]
    message_query = lambda pair: {'$and': [{'$or': sources(pair)}, NOT_CORE_NOTICE, {'$or': list(SAID)}]}
    parts = lambda pair: {'scene_ids': [s(pair)], 'epoch': e(pair)}
    window = lambda pair: (t(pair)[:10] + 'T00:00:00Z', '9999-12-31T23:59:59Z')
    one = lambda filter, proj=None, sort=None: ('find_one', 'messages', filter, proj, sort)
    many = lambda filter, proj=None, sort=None, limit=0: ('find', 'messages', filter, proj, sort, limit)
    count = lambda filter, limit=0: ('count', 'messages', filter, limit)
    distinct = lambda field, filter: ('distinct', 'messages', field, filter)
    desc = [('scene_seq', -1)]
    asc = [('scene_seq', 1)]

    def quoted_old(pair, mine):
        """notices.fill: hers by its message id however old, else anyone's within the time."""
        def run(db):
            fields = {'_id': 1, 'text': 1, 'author': 1, 'direction': 1, 'scene_seq': 1}
            flt = {'scene_id': s(pair), 'direction': 'outbound', 'platform_message_id': pair[1]}
            row = db.messages.find_one(flt, fields, sort=desc) if mine else None
            cursor = db.messages.find(flt, fields, sort=desc).limit(1)
            if row:
                return row, cursor
            flt = {'scene_id': s(pair), '$or': [
                {'direction': 'inbound', 'event.channel.platform_event_id': pair[1], 'received_at': {'$gte': recent}},
                {'direction': 'outbound', 'platform_message_id': pair[1], 'receipt_at': {'$gte': recent}}]}
            return db.messages.find_one(flt, fields, sort=desc), db.messages.find(flt, fields, sort=desc).limit(1)
        return run

    def excluded_old(pair):
        """discussion_digest._excluded_counts: speech not delivered, then lines that are not speech."""
        def run(db):
            base = {'scene_id': s(pair), 'policy_epoch': e(pair), 'direction': 'outbound'}
            first = dict(base, phase='SPEAK', delivery_state={'$ne': 'DELIVERED'})
            second = dict(base, phase={'$ne': 'SPEAK'})
            return [db.messages.count_documents(first), db.messages.count_documents(second)], db.messages.find(second)
        return run

    def page_old(pair, search=None):
        """native_api.page's aggregate on the source lines (its excerpt as compared)."""
        def run(db):
            query = message_query(pair)
            if search:
                query = {'$and': [query, {'text': {'$regex': re.escape(search), '$options': 'i'}}]}
            rows = list(db.messages.aggregate([{'$match': query}, {'$sort': {'occurred_at': -1, '_id': -1}},
                                               {'$skip': 0}, {'$limit': 25}, {'$project': {
                                                   'excerpt': {'$substrCP': [{'$ifNull': ['$text', '']}, 0, 200]}}}]))
            return [(row['_id'], row['excerpt']) for row in rows], db.messages.find(query, {'text': 1}, sort=[
                ('occurred_at', -1), ('_id', -1)], limit=25)
        return run

    def page_new(pair, search=None):
        rows = owner.said_in_sources(store, sources(pair), search=search).rows(newest_first=True, limit=25,
                                                                              fields=['text'])
        return [(row['_id'], (row.get('text') if isinstance(row.get('text'), str) else '')[:200]) for row in rows]

    def search_case(stream, text=False, person=False, cursor=False):
        def params(pair):
            word = next((w for scene, w in words if scene is pair[0]), None) if text else None
            who = ([pair[1].get('author')] if pair[1].get('author') else ['nobody']) if person else None
            after = [t(pair), q(pair), s(pair)] if cursor else None
            return pair, word, who, after

        def old(param):
            pair, word, who, after = param
            flt, sort = _old_streams(parts(pair), word, window(pair), {stream: after}, person=who,
                                     archived=stream == 'archived')[stream]
            return many(flt, {'legacy': 0} if stream == 'archived' else None, sort, 26)

        def new(param):
            pair, word, who, after = param
            return owner.search(store, [s(pair)], e(pair), stream, text=word, person=who,
                                window=window(pair) if stream != 'archived' else tuple(
                                    _archive_stamp(v) for v in window(pair)), after=after, limit=26)
        return old, new, [params(pair) for pair in first]

    cases = [
        # single lines
        ('get', lambda i: one({'_id': i}), lambda i: owner.get(store, i), ids, 'value'),
        ('get fields', lambda i: one({'_id': i}, {'author': 1, 'direction': 1}),
         lambda i: owner.get(store, i, fields=['author', 'direction']), ids, 'value'),
        ('get fenced to scene, scope, epoch', lambda p: one({'_id': p[1]['_id'], 'scene_id': s(p),
                                                            'scope_key': p[0].get('scope_key'),
                                                            'policy_epoch': e(p)}),
         lambda p: owner.get(store, p[1]['_id'], scene=s(p), scope=p[0].get('scope_key'), epoch=e(p)), lines, 'value'),
        ('get inbound in scene', lambda p: one({'_id': p[1]['_id'], 'scene_id': s(p), 'direction': 'inbound'}),
         lambda p: owner.get(store, p[1]['_id'], scene=s(p), direction='inbound'), lines, 'value'),
        ('get in scene fields', lambda p: one({'_id': p[1]['_id'], 'scene_id': s(p)},
                                              {'author': 1, 'text': 1, 'direction': 1, 'scene_seq': 1}),
         lambda p: owner.get(store, p[1]['_id'], scene=s(p), fields=['author', 'text', 'direction', 'scene_seq']),
         lines, 'value'),
        ('get in scene and epoch', lambda p: one({'_id': p[1]['_id'], 'scene_id': s(p), 'policy_epoch': e(p)}),
         lambda p: owner.get(store, p[1]['_id'], scene=s(p), epoch=e(p)), lines, 'value'),
        ('get outbound fields', lambda i: one({'_id': i, 'direction': 'outbound'}, {'monologue_refs': 1}),
         lambda i: owner.get(store, i, fields=['monologue_refs'], direction='outbound'), ids, 'value'),
        ('get on a channel', lambda c: one({'_id': c[0], 'channel_id': c[1]}, {'target': 1}),
         lambda c: owner.get(store, c[0], fields=['target'], channel=c[1]), channels or [('none', 'none')], 'value'),
        ('get from a channel', lambda i: one({'_id': i, 'event.channel': {'$exists': True}}),
         lambda i: owner.get(store, i, from_channel=True), ids, 'value'),
        ('many fields', lambda b: many({'_id': {'$in': b}}, {'author': 1}),
         lambda b: owner.many(store, b).rows(fields=['author']), batches, 'value'),
        ('many in scene and epoch', lambda p: many({'_id': {'$in': p[1]}, 'scene_id': p[0]['_id'],
                                                    'policy_epoch': p[0]['policy_epoch']}, RELATED),
         lambda p: owner.many(store, p[1], scene=p[0]['_id'], epoch=p[0]['policy_epoch']).rows(fields=list(RELATED)),
         by_scene, 'value'),
        ('many since', lambda b: many({'_id': {'$in': b}, 'received_at': {'$gte': recent}}, {'scene_seq': 1}),
         lambda b: owner.many(store, b, since=recent).rows(fields=['scene_seq']), batches, 'value'),
        ('many linkage (digest)', lambda p: many({'_id': {'$in': sorted(set(p[1]))}, 'scene_id': p[0]['_id'],
                                                  'policy_epoch': p[0]['policy_epoch']},
                                                 {'_id': 1, 'reply_to': 1, 'author': 1, 'direction': 1,
                                                  'event.group_context': 1, 'event.raw.asuna_peer': 1,
                                                  'event.channel': 1}),
         lambda p: owner.many(store, p[1], scenes=[p[0]['_id']], epoch=p[0]['policy_epoch']).rows(
             fields=['_id', 'reply_to', 'author', 'direction', 'event.group_context', 'event.raw.asuna_peer',
                     'event.channel']), by_scene, 'value'),
        ('at', lambda p: one({'scene_id': s(p), 'scene_seq': q(p)}, {'received_at': 1, 'receipt_at': 1}),
         lambda p: owner.at(store, s(p), q(p), fields=['received_at', 'receipt_at']), lines, 'value'),
        ('at hers', lambda p: one({'scene_id': s(p), 'scene_seq': q(p), 'direction': 'outbound', 'author': me}),
         lambda p: owner.at(store, s(p), q(p), direction='outbound', author=me), lines, 'value'),
        ('of_event', lambda p: one({'scene_id': s(p), 'policy_epoch': e(p), 'event.event_id': p[1]}, {'_id': 1}),
         lambda p: owner.of_event(store, s(p), e(p), p[1], fields=['_id']), events, 'value'),
        ('of_platform_event', lambda p: many({'platform_event_id': p[1]}, {'scope_key': 1, 'deletion_id': 1}),
         lambda p: owner.of_platform_event(store, p[1], fields=['scope_key', 'deletion_id']), platform, 'value'),
        ('referenced', lambda p: one({'scene_id': s(p), 'policy_epoch': e(p), '$or': [
            {'_id': p[1]['_id']}, {'event.channel.platform_event_id': p[1]['_id']},
            {'platform_message_id': p[1]['_id']}]}, {'author': 1, 'scene_seq': 1, 'direction': 1, 'summary_batch_id': 1}),
         lambda p: owner.referenced(store, s(p), e(p), p[1]['_id'],
                                    fields=['author', 'scene_seq', 'direction', 'summary_batch_id']), lines, 'value'),
        ('by_platform_id', lambda p: many({'scene_id': s(p), 'policy_epoch': e(p), '$or': [
            {'direction': 'inbound', 'event.channel.platform_event_id': p[1]},
            {'direction': 'outbound', 'platform_message_id': p[1], 'delivery_state': 'DELIVERED', 'author': me}]}),
         lambda p: owner.by_platform_id(store, s(p), e(p), platform_id=p[1], author=me).rows(), platform, 'value'),
        ('quoted, hers first', lambda p: quoted_old(p, True), lambda p: owner.quoted(store, s(p), p[1], mine=True,
                                                                                     since=recent), platform, 'value'),
        # what people saw (her turn context reads these)
        ('said, attend window', lambda p: many({'scene_id': s(p), 'policy_epoch': e(p), 'scene_seq': {'$lte': q(p)},
                                                '$or': SAID}, {'_id': 1, 'author': 1, 'text': 1, 'direction': 1,
                                                               'scene_seq': 1, 'received_at': 1}, desc, 40),
         lambda p: owner.said(store, s(p), e(p), upto=q(p)).rows(
             newest_first=True, limit=40, fields=['_id', 'author', 'text', 'direction', 'scene_seq', 'received_at']),
         first, 'value'),
        ('said, linked history', lambda p: many({'scene_id': s(p), 'policy_epoch': e(p), '$or': SAID_DELIVERED},
                                                HISTORY, desc, 12),
         lambda p: owner.said(store, s(p), e(p)).rows(newest_first=True, limit=12, fields=list(HISTORY)),
         first, 'value'),
        ('turn context: history', lambda p: many({'scene_id': s(p), 'policy_epoch': e(p), '$or': [
            {'direction': 'inbound', 'scene_seq': {'$lt': q(p)}}, {'delivery_state': 'DELIVERED'}]}, HISTORY, desc,
            40 if p[0].get('kind') == 'group' else 12),
         lambda p: owner.said(store, s(p), e(p), heard_before=q(p)).rows(
             newest_first=True, limit=40 if p[0].get('kind') == 'group' else 12, fields=list(HISTORY)),
         first, 'value'),
        ('turn context: topic thread', lambda p: many({'scene_id': s(p), 'policy_epoch': e(p),
                                                       'event.group_context.topic_id': p[1], '$or': SAID_DELIVERED},
                                                      RELATED, desc, 12),
         lambda p: owner.said(store, s(p), e(p), topic=p[1]).rows(newest_first=True, limit=12, fields=list(RELATED)),
         topics, 'value'),
        ('said, not yet summarised', lambda p: many({'scene_id': s(p), 'policy_epoch': e(p),
                                                     'scene_seq': {'$gt': p[0].get('summary_start_seq') or 0},
                                                     'summary_batch_id': {'$exists': False}, **NOT_CORE_NOTICE,
                                                     '$or': SAID}, None, asc, 24),
         lambda p: owner.said(store, s(p), e(p), people_only=True, after=p[0].get('summary_start_seq') or 0,
                              unsummarised=True).rows(limit=24), first, 'value'),
        ('said, people only, whole conversation', lambda p: many({'scene_id': s(p), **NOT_CORE_NOTICE,
                                                                  '$or': SAID_DELIVERED}, {'_id': 1}, asc),
         lambda p: owner.said(store, s(p), people_only=True).rows(fields=['_id']), first[:3], 'value'),
        ('said, after a line', lambda p: many({'scene_id': s(p), 'policy_epoch': e(p), 'scene_seq': {'$gt': q(p)},
                                               '$or': SAID_DELIVERED}, None, asc, 30),
         lambda p: owner.said(store, s(p), e(p), after=q(p)).rows(limit=30), oldest, 'value'),
        ('said, around a line', lambda p: many({'scene_id': s(p), 'policy_epoch': e(p),
                                                'scene_seq': {'$gte': q(p) - 2, '$lte': q(p) + 2},
                                                '$or': SAID_DELIVERED},
                                               {'text': 1, 'author': 1, 'direction': 1, 'scene_seq': 1}, asc),
         lambda p: owner.said(store, s(p), e(p), from_seq=q(p) - 2, upto=q(p) + 2).rows(
             fields=['text', 'author', 'direction', 'scene_seq']), oldest, 'value'),
        ('said, proactive rhythm', lambda p: many({'scene_id': s(p), 'policy_epoch': e(p), '$or': SAID},
                                                  {'scene_seq': 1, 'direction': 1, 'author': 1, 'occurred_at': 1},
                                                  desc, 120),
         lambda p: owner.said(store, s(p), e(p)).rows(newest_first=True, limit=120,
                                                      fields=['scene_seq', 'direction', 'author', 'occurred_at']),
         first, 'value'),
        ('said across (home experience)', lambda _: many({'$or': [
            {'scene_id': {'$in': [home]}, 'direction': 'inbound'},
            {'scene_id': {'$in': routes}, 'delivery_state': 'DELIVERED'}]},
            {'scene_id': 1, 'author': 1, 'direction': 1, 'text': 1, 'received_at': 1, 'delivery_state': 1},
            [('received_at', -1)], 20),
         lambda _: owner.said_across(store, [home], routes).rows(
             newest_first=True, limit=20,
             fields=['scene_id', 'author', 'direction', 'text', 'received_at', 'delivery_state']), [None], 'value'),
        ('web page source lines', lambda p: page_old(p), lambda p: page_new(p), first, 'value'),
        ('web page source lines, searched', lambda p: page_old(p[0], p[1]), lambda p: page_new(p[0], p[1]),
         [(pair, word) for pair in first for scene, word in words if scene is pair[0]][:20], 'value'),
        ('web page source line', lambda p: one({**message_query(p), '_id': p[1]['_id']},
                                               {'text': 1, 'author': 1, 'scene_id': 1, 'occurred_at': 1}),
         lambda p: owner.said_in_sources(store, sources(p), line=p[1]['_id'], by=None).first(
             fields=['text', 'author', 'scene_id', 'occurred_at']), lines, 'value'),
        ('web page sources by ids', lambda p: many({**message_query((p[0], None)), '_id': {'$in': p[1]}},
                                                   {'text': 1, 'author': 1, 'scene_id': 1, 'occurred_at': 1},
                                                   [('occurred_at', 1), ('_id', 1)], 12),
         lambda p: owner.said_in_sources(store, [{'scene_id': p[0]['_id'], 'policy_epoch': p[0]['policy_epoch']}],
                                         lines=p[1]).rows(limit=12, fields=['text', 'author', 'scene_id',
                                                                            'occurred_at']),
         by_scene, 'value'),
        ('pointable, the turn\'s line', lambda p: one({'_id': p[1]['_id'], 'scene_id': s(p), **POINTABLE}),
         lambda p: owner.pointable(store, s(p), line=p[1]['_id'], by=None).first(), lines, 'value'),
        ('pointable, at a position', lambda p: one({'scene_id': s(p), 'scene_seq': q(p), **POINTABLE}),
         lambda p: owner.pointable(store, s(p), seq=q(p), by=None).first(), lines, 'value'),
        ('pointable, recent', lambda p: many({'scene_id': s(p), **POINTABLE},
                                             {'text': 1, 'author': 1, 'direction': 1, 'scene_seq': 1}, desc, 6),
         lambda p: owner.pointable(store, s(p)).rows(newest_first=True, limit=6,
                                                     fields=['text', 'author', 'direction', 'scene_seq']),
         first, 'value'),
        # a conversation's lines
        ('lines, the newest position', lambda p: one({'scene_id': s(p)}, {'scene_seq': 1}, desc),
         lambda p: owner.lines(store, s(p)).first(newest_first=True, fields=['scene_seq']), first, 'value'),
        ('lines after a position', lambda p: many({'scene_id': s(p), 'scene_seq': {'$gt': q(p)}},
                                                  {'text': 1, 'direction': 1, 'scene_seq': 1}, asc),
         lambda p: owner.lines(store, s(p), after=q(p)).rows(fields=['text', 'direction', 'scene_seq']), oldest,
         'value'),
        ('lines between positions', lambda p: many({'scene_id': s(p), 'scene_seq': {'$gte': q(p), '$lte': q(p) + 3}},
                                                   None, asc),
         lambda p: owner.lines(store, s(p), from_seq=q(p), upto=q(p) + 3).rows(), oldest, 'value'),
        ('lines live up to a position', lambda p: many({'scene_id': s(p), 'policy_epoch': e(p),
                                                        'scene_seq': {'$lte': q(p)},
                                                        '$or': [{'direction': 'inbound'}, {'direction': 'outbound'}]},
                                                       {'scene_seq': 1, 'direction': 1, 'author': 1, 'text': 1}, desc,
                                                       12),
         lambda p: owner.lines(store, s(p), e(p), live=True, upto=q(p)).rows(
             newest_first=True, limit=12, fields=['scene_seq', 'direction', 'author', 'text']), first, 'value'),
        ('lines with the group name', lambda p: one({'scene_id': s(p), 'event.raw.group_name': {'$exists': True}},
                                                    {'event.raw.group_name': 1}, [('received_at', -1)]),
         lambda p: owner.lines(store, s(p), group_name=True, by='received_at').first(
             newest_first=True, fields=['event.raw.group_name']), first, 'value'),
        ('woken after a position', lambda p: one({'scene_id': s(p), 'scene_seq': {'$gt': q(p)},
                                                  'event.group_context.wake_reason': 'awaited_answer'}, {'_id': 1}),
         lambda p: owner.woken(store, s(p), 'awaited_answer', after=q(p)), oldest, 'value'),
        # what people wrote
        ('inbound since, counted', lambda p: count({'scene_id': s(p), 'direction': 'inbound',
                                                    'received_at': {'$gte': t(p)}}),
         lambda p: owner.inbound(store, s(p), since=t(p)).count(), oldest, 'value'),
        ('inbound, the newest by time', lambda p: one({'scene_id': s(p), 'direction': 'inbound'}, {'received_at': 1},
                                                      [('received_at', -1)]),
         lambda p: owner.inbound(store, s(p), by='received_at').first(newest_first=True, fields=['received_at']),
         first, 'value'),
        ('inbound since', lambda p: many({'scene_id': s(p), 'direction': 'inbound', 'received_at': {'$gte': t(p)}},
                                         {'author': 1, 'text': 1, 'received_at': 1}),
         lambda p: owner.inbound(store, s(p), since=t(p), by=None).rows(fields=['author', 'text', 'received_at']),
         oldest, 'value'),
        ('inbound elsewhere since', lambda p: many({'scene_id': {'$ne': s(p)}, 'direction': 'inbound',
                                                    'received_at': {'$gte': newest}},
                                                   {'scene_id': 1, 'author': 1, 'text': 1}),
         lambda p: owner.inbound(store, besides=s(p), since=newest, by=None).rows(
             fields=['scene_id', 'author', 'text']), first, 'value'),
        ('inbound by others since', lambda p: many({'scene_id': s(p), 'direction': 'inbound', 'author': {'$ne': me},
                                                    'received_at': {'$gte': t(p)}},
                                                   {'text': 1, 'author': 1, 'received_at': 1}),
         lambda p: owner.inbound(store, s(p), not_author=me, since=t(p), by=None).rows(
             fields=['text', 'author', 'received_at']), oldest, 'value'),
        ('turn context: queued after the line', lambda p: many({'scene_id': s(p), 'direction': 'inbound',
                                                                'scene_seq': {'$gte': q(p)}}, {'platform_event_id': 1}),
         lambda p: owner.inbound(store, s(p), from_seq=q(p), by=None).rows(fields=['platform_event_id']), oldest,
         'value'),
        ('turn context: later lines, not notices', lambda p: many({'scene_id': s(p), 'direction': 'inbound',
                                                                   'event.raw.asuna_notice': {'$exists': False},
                                                                   'scene_seq': {'$gt': q(p)}}, {'scene_seq': 1}, asc),
         lambda p: owner.inbound(store, s(p), after=q(p), no_notice=True).rows(fields=['scene_seq']), oldest,
         'value'),
        ('turn context: the speaker\'s tail', lambda p: many({'scene_id': s(p), 'policy_epoch': e(p),
                                                              'author': p[1]['author'], 'direction': 'inbound',
                                                              'scene_seq': {'$lt': q(p)}},
                                                             {'text': 1, 'author': 1, 'scene_seq': 1}, desc, 3),
         lambda p: owner.inbound(store, s(p), e(p), author=p[1]['author'], before=q(p)).rows(
             newest_first=True, limit=3, fields=['text', 'author', 'scene_seq']),
         [pair for pair in inbound if isinstance(pair[1].get('author'), str)], 'value'),
        ('inbound by the owner, the newest', lambda _: many({'direction': 'inbound', 'author': boss},
                                                            {'received_at': 1}, [('received_at', -1)], 1),
         lambda _: owner.inbound(store, author=boss, by='received_at').rows(newest_first=True, limit=1,
                                                                            fields=['received_at']), [None], 'value'),
        ('inbound by authors, counted', lambda p: count({'author': {'$in': [p[1]]}, 'direction': 'inbound'}, 60),
         lambda p: owner.inbound(store, authors=[p[1]]).count(limit=60), authors, 'value'),
        ('inbound in a window, counted', lambda p: count({'scene_id': s(p), 'direction': 'inbound',
                                                          'scene_seq': {'$gt': q(p) - 5, '$lte': q(p)}}, 50),
         lambda p: owner.inbound(store, s(p), after=q(p) - 5, upto=q(p)).count(limit=50), first, 'value'),
        ('inbound carrying a forward', lambda p: one({'scene_id': s(p), 'direction': 'inbound',
                                                      'event.raw.asuna_forward.ref': p[1]}, None,
                                                     [('received_at', -1)]),
         lambda p: owner.inbound(store, s(p), forward=p[1], by='received_at').first(newest_first=True), refs, 'value'),
        ('inbound with a peer card', lambda p: one({'scene_id': s(p), 'author': p[1], 'direction': 'inbound',
                                                    'event.raw.asuna_peer': {'$exists': True}}, None,
                                                   [('received_at', -1)]),
         lambda p: owner.inbound(store, s(p), author=p[1], peer=True, by='received_at').first(newest_first=True),
         authors, 'value'),
        ('inbound by a peer\'s name', lambda p: many({'scene_id': s(p), 'direction': 'inbound', '$or': [
            {'event.raw.asuna_peer.' + field: p[1]} for field in ('card', 'nickname', 'display', 'aliases')]},
            {'author': 1, 'scene_id': 1, 'received_at': 1}, None, 200),
         lambda p: owner.inbound(store, s(p), peer_named=p[1], by=None).rows(
             limit=200, fields=['author', 'scene_id', 'received_at']), names, 'value'),
        ('inbound pictures before a line', lambda p: many({'scene_id': s(p), 'direction': 'inbound',
                                                           'policy_epoch': e(p),
                                                           'scene_seq': {'$lt': q(p), '$gte': q(p) - 6},
                                                           'event.raw.asuna_media': {'$exists': True}}, None, desc),
         lambda p: owner.inbound(store, s(p), e(p), before=q(p), from_seq=q(p) - 6, media=True).rows(
             newest_first=True), first, 'value'),
        ('inbound pictures since', lambda p: many({'scene_id': s(p), 'policy_epoch': e(p), 'direction': 'inbound',
                                                   'received_at': {'$gte': t(p)},
                                                   'event.raw.asuna_media': {'$exists': True}},
                                                  {'_id': 1, 'scene_seq': 1}, desc),
         lambda p: owner.inbound(store, s(p), e(p), since=t(p), media=True).rows(newest_first=True,
                                                                                 fields=['_id', 'scene_seq']),
         oldest, 'value'),
        ('inbound in an epoch, newest', lambda p: many({'scene_id': s(p), 'policy_epoch': e(p),
                                                        'direction': 'inbound'}, {'_id': 1, 'scene_seq': 1}, desc, 50),
         lambda p: owner.inbound(store, s(p), e(p)).rows(newest_first=True, limit=50, fields=['_id', 'scene_seq']),
         first, 'value'),
        ('inbound news since', lambda _: one({'scene_id': {'$in': routes}, 'direction': 'inbound',
                                              'received_at': {'$gt': recent},
                                              'processing_outcome': {'$ne': 'RECORDED_NO_WAKE'}}, {'_id': 1}),
         lambda _: owner.inbound(store, scenes=routes, since_after=recent, not_outcome='RECORDED_NO_WAKE',
                                 by=None).first(fields=['_id']), [None], 'value'),
        ('inbound by people since, in an epoch', lambda p: many({'scene_id': s(p), 'policy_epoch': e(p),
                                                                 'direction': 'inbound',
                                                                 'received_at': {'$gte': t(p)}, **NOT_CORE_NOTICE},
                                                                {'author': 1}),
         lambda p: owner.inbound(store, s(p), e(p), people_only=True, since=t(p), by=None).rows(fields=['author']),
         oldest, 'value'),
        ('inbound, the newest by position', lambda p: many({'scene_id': s(p), 'direction': 'inbound'},
                                                           {'received_at': 1}, desc, 1),
         lambda p: owner.inbound(store, s(p)).rows(newest_first=True, limit=1, fields=['received_at']), first,
         'value'),
        ('inbound calling her after a line', lambda p: one({'scene_id': s(p), 'direction': 'inbound',
                                                            **NOT_CORE_NOTICE, 'scene_seq': {'$gt': q(p)},
                                                            'event.group_context.wake_reason': {'$in': [
                                                                'mentioned_account', 'reply_to_character',
                                                                'name_called']}}, {'_id': 1}),
         lambda p: owner.inbound(store, s(p), people_only=True, after=q(p),
                                 wakes=('mentioned_account', 'reply_to_character', 'name_called'),
                                 by=None).first(fields=['_id']), oldest, 'value'),
        ('inbound waiting behind a turn', lambda p: many({'scene_id': s(p), 'direction': 'inbound', **NOT_CORE_NOTICE,
                                                          'scene_seq': {'$gt': q(p)},
                                                          'event.group_context.wake_reason': {'$in': [
                                                              'mentioned_account', 'reply_to_character',
                                                              'catchup_mention']}}, {'author': 1}, asc, 32),
         lambda p: owner.inbound(store, s(p), people_only=True, after=q(p),
                                 wakes=('mentioned_account', 'reply_to_character', 'catchup_mention')).rows(
             limit=32, fields=['author']), oldest, 'value'),
        ('inbound by people after a line', lambda p: one({'scene_id': s(p), 'direction': 'inbound', **NOT_CORE_NOTICE,
                                                          'scene_seq': {'$gt': q(p)}}, {'_id': 1}),
         lambda p: owner.inbound(store, s(p), people_only=True, after=q(p), by=None).first(fields=['_id']), oldest,
         'value'),
        ('inbound by someone after a line', lambda p: one({'scene_id': s(p), 'direction': 'inbound',
                                                           'scene_seq': {'$gt': q(p) - 3},
                                                           'author': {'$in': [p[1]['author']]}}, {'_id': 1}),
         lambda p: owner.inbound(store, s(p), after=q(p) - 3, people_only=True, authors=[p[1]['author']],
                                 by=None).first(fields=['_id']),
         [pair for pair in inbound if isinstance(pair[1].get('author'), str)], 'value'),
        ('inbound answering her wait', lambda p: one({'scene_id': s(p), 'direction': 'inbound', 'author': p[1],
                                                      'scene_seq': {'$gt': 0},
                                                      'event.group_context.wake_reason': 'question_wait'},
                                                     {'_id': 1}),
         lambda p: owner.inbound(store, s(p), author=p[1], after=0, wake='question_wait', by=None).first(
             fields=['_id']), authors, 'value'),
        ('inbound answering her question', lambda p: many({'scene_id': s(p), 'direction': 'inbound', **NOT_CORE_NOTICE,
                                                           'scene_seq': {'$gt': q(p)}, '$or': [
                                                               {'event.group_context.reply_message_id': {'$in': [
                                                                   p[1]['_id']]}},
                                                               {'event.group_context.wake_reason': 'question_wait'},
                                                               {'event.raw.asuna_notice.kind': 'reaction',
                                                                'event.raw.asuna_notice.line.message_id': {
                                                                    '$in': ['platform-none']}}]}, None, asc),
         lambda p: owner.inbound(store, s(p), people_only=True, after=q(p),
                                 answers_to=([p[1]['_id']], ['platform-none'])).rows(), oldest, 'value'),
        ('inbound marked as an answer', lambda p: many({'scene_id': s(p), 'direction': 'inbound', **NOT_CORE_NOTICE,
                                                        'event.raw.asuna_aside': {'$ne': True},
                                                        'event.raw.asuna_answer.question': 'q-none'}, None, asc),
         lambda p: owner.inbound(store, s(p), people_only=True, asides=False, answers_question='q-none').rows(),
         first, 'value'),
        ('inbound first after her line, unmarked', lambda p: one({'scene_id': s(p), 'direction': 'inbound',
                                                                  **NOT_CORE_NOTICE,
                                                                  'event.raw.asuna_aside': {'$ne': True},
                                                                  'scene_seq': {'$gt': q(p)},
                                                                  'event.raw.asuna_answer': {'$exists': False}},
                                                                 None, asc),
         lambda p: owner.inbound(store, s(p), people_only=True, asides=False, after=q(p),
                                 no_answer_mark=True).first(), oldest, 'value'),
        ('inbound asides, counted', lambda p: count({'scene_id': s(p), 'direction': 'inbound',
                                                     'event.raw.asuna_aside': True, 'scene_seq': {'$gt': q(p)}}),
         lambda p: owner.inbound(store, s(p), asides=True, after=q(p)).count(), oldest, 'value'),
        ('inbound since, newest first', lambda p: many({'scene_id': s(p), 'direction': 'inbound',
                                                        'received_at': {'$gte': t(p)}}, {'text': 1}, desc, 10000),
         lambda p: owner.inbound(store, s(p), since=t(p)).rows(newest_first=True, limit=10000, fields=['text']),
         oldest, 'value'),
        ('inbound conversations since', lambda _: distinct('scene_id', {'direction': 'inbound',
                                                                        'received_at': {'$gte': recent}}),
         lambda _: owner.inbound(store, since=recent).values('scene_id'), [None], 'values'),
        ('inbound by people, by when said', lambda p: many({'scene_id': s(p), 'direction': 'inbound',
                                                            **NOT_CORE_NOTICE}, {'author': 1, 'occurred_at': 1},
                                                           [('occurred_at', -1)], 2000),
         lambda p: owner.inbound(store, s(p), people_only=True, by='occurred_at').rows(
             newest_first=True, limit=2000, fields=['author', 'occurred_at']), first[:5], 'value'),
        ('inbound with the group\'s name', lambda p: one({'scene_id': s(p), 'direction': 'inbound',
                                                          'event.raw.group_name': {'$exists': True}},
                                                         {'event.raw.group_name': 1, 'event.raw.asuna_peer': 1},
                                                         [('received_at', -1)]),
         lambda p: owner.inbound(store, s(p), group_name=True, by='received_at').first(
             newest_first=True, fields=['event.raw.group_name', 'event.raw.asuna_peer']), first, 'value'),
        ('inbound with a peer\'s shown name', lambda p: one({'scene_id': s(p), 'direction': 'inbound',
                                                             'event.raw.asuna_peer.display': {'$exists': True}},
                                                            {'event.raw.group_name': 1, 'event.raw.asuna_peer': 1},
                                                            [('received_at', -1)]),
         lambda p: owner.inbound(store, s(p), peer_display=True, by='received_at').first(
             newest_first=True, fields=['event.raw.group_name', 'event.raw.asuna_peer']), first, 'value'),
        ('mentions since', lambda p: many({'scene_id': s(p), 'received_at': {'$gte': t(p)},
                                           'event.group_context.mentioned_account_ids.0': {'$exists': True}},
                                          {'event.group_context.mentioned_account_ids': 1}),
         lambda p: owner.mentions(store, s(p), t(p)).rows(fields=['event.group_context.mentioned_account_ids']),
         oldest, 'value'),
        # her lines
        ('spoken, her newest in an epoch', lambda p: one({'scene_id': s(p), 'policy_epoch': e(p),
                                                          'direction': 'outbound', 'delivery_state': 'DELIVERED',
                                                          'author': me}, None, desc),
         lambda p: owner.spoken(store, s(p), e(p), author=me).first(newest_first=True), first, 'value'),
        ('turn context: her newest', lambda p: many({'scene_id': s(p), 'direction': 'outbound', 'author': me,
                                                     'delivery_state': 'DELIVERED'}, {'scene_seq': 1}, desc, 1),
         lambda p: owner.spoken(store, s(p), author=me).rows(newest_first=True, limit=1, fields=['scene_seq']),
         first, 'value'),
        ('turn context: her recent phrasing', lambda p: many({'scene_id': s(p), 'direction': 'outbound',
                                                              'delivery_state': 'DELIVERED'}, {'text': 1}, desc, 20),
         lambda p: owner.spoken(store, s(p)).rows(newest_first=True, limit=20, fields=['text']), first, 'value'),
        ('spoken, all of a conversation', lambda p: many({'scene_id': s(p), 'direction': 'outbound',
                                                          'delivery_state': 'DELIVERED'}, {'_id': 1}, asc),
         lambda p: owner.spoken(store, s(p)).rows(fields=['_id']), first[:3], 'value'),
        ('spoken with a receipt, the newest', lambda p: one({'scene_id': s(p), 'direction': 'outbound',
                                                             'delivery_state': 'DELIVERED',
                                                             'receipt_at': {'$exists': True}}, {'receipt_at': 1},
                                                            [('receipt_at', -1)]),
         lambda p: owner.spoken(store, s(p), with_receipt=True, by='receipt_at').first(
             newest_first=True, fields=['receipt_at']), first, 'value'),
        ('spoken since a receipt, counted', lambda p: count({'scene_id': s(p), 'direction': 'outbound',
                                                             'delivery_state': 'DELIVERED',
                                                             'receipt_at': {'$gte': recent}}),
         lambda p: owner.spoken(store, s(p), receipt_since=recent).count(), first, 'value'),
        ('spoken elsewhere since', lambda _: many({'direction': 'outbound', 'author': me, 'delivery_state': 'DELIVERED',
                                                   'receipt_at': {'$gte': recent}, 'scene_id': {'$nin': [home]}},
                                                  {'scene_id': 1, 'receipt_at': 1}),
         lambda _: owner.spoken(store, author=me, receipt_since=recent, not_in=[home], by=None).rows(
             fields=['scene_id', 'receipt_at']), [None], 'value'),
        ('her speech since', lambda _: many({'direction': 'outbound', 'phase': 'SPEAK', 'receipt_at': {'$gte': recent}},
                                            {'scene_id': 1, 'receipt_at': 1}, [('receipt_at', 1)]),
         lambda _: owner.spoken(store, delivered=False, speech=True, receipt_since=recent, by='receipt_at').rows(
             fields=['scene_id', 'receipt_at']), [None], 'value'),
        ('her speech, the newest', lambda p: one({'scene_id': s(p), 'direction': 'outbound', 'phase': 'SPEAK'},
                                                 {'scene_seq': 1}, desc),
         lambda p: owner.spoken(store, s(p), delivered=False, speech=True).first(newest_first=True,
                                                                                 fields=['scene_seq']),
         first, 'value'),
        ('spoken since, newest first', lambda p: many({'scene_id': s(p), 'direction': 'outbound',
                                                       'delivery_state': 'DELIVERED', 'author': me,
                                                       'receipt_at': {'$gte': recent}},
                                                      {'text': 1, 'episode_id': 1, 'scene_seq': 1}, desc),
         lambda p: owner.spoken(store, s(p), author=me, receipt_since=recent).rows(
             newest_first=True, fields=['text', 'episode_id', 'scene_seq']), first, 'value'),
        ('turn context: undelivered', lambda p: many({'scene_id': s(p), 'direction': 'outbound', 'delivery_state': {
            '$in': ['READY', 'QUEUED_EXTERNAL', 'SENDING', 'FAILED', 'UNKNOWN']}},
            {'text': 1, 'delivery_state': 1, 'author': 1}, desc, 4),
         lambda p: owner.outgoing(store, s(p), ['READY', 'QUEUED_EXTERNAL', 'SENDING', 'FAILED', 'UNKNOWN']).rows(
             newest_first=True, limit=4, fields=['text', 'delivery_state', 'author']), first, 'value'),
        # one turn's lines
        ('turn speech', lambda ep: many({'episode_id': ep, 'phase': 'SPEAK'},
                                        {'segment_index': 1, 'not_before': 1, 'text': 1}),
         lambda ep: owner.turn_parts(store, ep, by=None).rows(fields=['segment_index', 'not_before', 'text']),
         episodes, 'value'),
        ('turn delivered in its scene', lambda p: many({'episode_id': p[1].get('episode_id'), 'scene_id': s(p),
                                                        'direction': 'outbound', 'phase': 'SPEAK',
                                                        'delivery_state': 'DELIVERED'}, None, asc),
         lambda p: owner.turn_parts(store, p[1].get('episode_id'), scene=s(p), outbound=True, delivered=True).rows(),
         outbound, 'value'),
        ('turn outbound in order', lambda ep: many({'episode_id': ep, 'direction': 'outbound', 'phase': 'SPEAK'},
                                                   {'text': 1, 'delivery_state': 1, 'scene_seq': 1}, asc),
         lambda ep: owner.turn_parts(store, ep, outbound=True).rows(fields=['text', 'delivery_state', 'scene_seq']),
         episodes, 'value'),
        ('turn outbound, counted', lambda ep: count({'episode_id': ep, 'direction': 'outbound', 'phase': 'SPEAK'}),
         lambda ep: owner.turn_parts(store, ep, outbound=True).count(), episodes, 'value'),
        ('turn parts ready', lambda ep: many({'episode_id': ep, 'reply_part': True, 'delivery_state': 'READY'}, None,
                                             [('segment_index', 1)]),
         lambda ep: owner.turn_parts(store, ep, speech=False, state='READY', reply_parts=True,
                                     by='segment_index').rows(), episodes, 'value'),
        ('turn parts that left', lambda ep: many({'episode_id': ep, 'phase': 'SPEAK', 'reply_part': True,
                                                  'delivery_state': {'$nin': ['FAILED', 'CANCELLED_AFTER_FAILURE',
                                                                              'CANCELLED_BY_HER']}},
                                                 {'text': 1, 'sticker': 1, 'attachment': 1, 'action': 1, 'file': 1}),
         lambda ep: owner.turn_parts(store, ep, reply_parts=True, not_states=(
             'FAILED', 'CANCELLED_AFTER_FAILURE', 'CANCELLED_BY_HER'), by=None).rows(
             fields=['text', 'sticker', 'attachment', 'action', 'file']), episodes, 'value'),
        ('turn parts after a segment', lambda p: many({'episode_id': p[1].get('episode_id'), 'phase': 'SPEAK',
                                                       'segment_index': {'$gt': p[1].get('segment_index') or 0},
                                                       'delivery_state': {'$in': ['READY', 'QUEUED_EXTERNAL']}}),
         lambda p: owner.turn_parts(store, p[1].get('episode_id'), after_segment=p[1].get('segment_index') or 0,
                                    states=['READY', 'QUEUED_EXTERNAL'], by=None).rows(), parts_of, 'value'),
        ('turn parts before a segment', lambda p: many({'episode_id': p[1].get('episode_id'), 'phase': 'SPEAK',
                                                        'segment_index': {'$lt': p[1].get('segment_index') or 1},
                                                        'delivery_state': {'$nin': ['DELIVERED', 'CANCELLED_BY_HER']}},
                                                       {'delivery_state': 1, 'file': 1}),
         lambda p: owner.turn_parts(store, p[1].get('episode_id'), before_segment=p[1].get('segment_index') or 1,
                                    not_states=('DELIVERED', 'CANCELLED_BY_HER'), by=None).rows(
             fields=['delivery_state', 'file']), parts_of, 'value'),
        ('her first line of a turn', lambda p: one({'scene_id': s(p), 'episode_id': p[1].get('episode_id'),
                                                    'direction': 'outbound', 'phase': 'SPEAK'}, None, asc),
         lambda p: owner.turn_parts(store, p[1].get('episode_id'), scene=s(p), outbound=True).first(), outbound,
         'value'),
        ('unsettled, counted', lambda _: count({'direction': 'outbound', 'delivery_state': {
            '$in': ['QUEUED_EXTERNAL', 'SENDING']}}), lambda _: owner.unsettled(store), [None], 'value'),
        # a channel's outbox and the Host's inputs
        ('queued on a channel', lambda c: many({'channel_id': c[0], 'delivery_state': 'QUEUED_EXTERNAL'}),
         lambda c: owner.queued(store, c[0]).rows(), targets or [('none', {})], 'value'),
        ('queued chat on a route', lambda c: many({'channel_id': c[0], 'delivery_state': 'QUEUED_EXTERNAL',
                                                   'file': {'$exists': False}, 'target.type': c[1].get('type'),
                                                   'target.id': c[1].get('id')}),
         lambda c: owner.queued(store, c[0], files=False, target=c[1]).rows(),
         [c for c in targets if isinstance(c[1].get('type'), str) and isinstance(c[1].get('id'), str)]
         or [('none', {'type': 'dm', 'id': 'none'})], 'value'),
        ('conversations with a chat line out', lambda c: distinct('scene_id', {
            'channel_id': c[0], 'delivery_state': 'SENDING', 'file': {'$exists': False},
            'claimed_at': {'$gte': recent}}),
         lambda c: owner.in_flight_scenes(store, c[0], recent), targets or [('none', {})], 'values'),
        ('left sending', lambda _: many({'channel_id': {'$exists': True}, 'delivery_state': 'SENDING'}),
         lambda _: owner.sending(store).rows(), [None], 'value'),
        ('the Host\'s inputs in states', lambda _: many({'host_managed': True, 'ingress_state': {
            '$in': ['ACCEPTED', 'PROCESSING', 'FAILED']}}, None, [('received_at', 1)]),
         lambda _: owner.ingress(store, ['ACCEPTED', 'PROCESSING', 'FAILED']).rows(), [None], 'value'),
        ('channel inputs since', lambda _: many({'host_managed': True, 'received_at': {'$gte': newest},
                                                 'event.channel': {'$exists': True}}, None, [('received_at', 1)]),
         lambda _: owner.channel_inbound(store, newest).rows(), [None], 'value'),
        ('errands since, counted', lambda _: count({'event.visit.intent': 'errand', 'received_at': {'$gte': recent}}),
         lambda _: owner.visits(store, 'errand', since=recent).count(), [None], 'value'),
        ('errands, the newest', lambda _: many({'event.visit.intent': 'errand'},
                                               {'scene_id': 1, 'received_at': 1, 'event.event_id': 1},
                                               [('received_at', -1)], 5),
         lambda _: owner.visits(store, 'errand').rows(newest_first=True, limit=5,
                                                      fields=['scene_id', 'received_at', 'event.event_id']),
         [None], 'value'),
        ('errand results not yet told', lambda p: many({'adapter_id': 'visit', 'scene_id': s(p),
                                                        'platform_event_id': {'$type': 'string',
                                                                              '$regex': '^visit:errand:'},
                                                        'ingress_state': 'COMPLETE',
                                                        'errand_told': {'$exists': False}},
                                                       {'episode_id': 1, 'received_at': 1}, [('received_at', 1)]),
         lambda p: owner.errand_results(store, s(p)).rows(fields=['episode_id', 'received_at']), first, 'value'),
        # values
        ('pictures lines name', lambda _: distinct('attachment.artifact_id',
                                                   {'attachment.artifact_id': {'$exists': True}}),
         lambda _: owner.artifact_refs(store, 'attachment'), [None], 'values'),
        ('files on their way', lambda _: distinct('file.artifact_id', {'file.artifact_id': {'$exists': True},
                                                                       'delivery_state': {'$in': [
                                                                           'READY', 'QUEUED_EXTERNAL', 'SENDING']}}),
         lambda _: owner.artifact_refs(store, 'file', states=('READY', 'QUEUED_EXTERNAL', 'SENDING')), [None],
         'values'),
        ('who wrote here', lambda p: distinct('author', {'scene_id': s(p), 'direction': 'inbound'}),
         lambda p: owner.authors(store, s(p), direction='inbound'), first, 'values'),
        ('who wrote in these', lambda b: distinct('author', {'scene_id': {'$in': b}}),
         lambda b: owner.authors(store, scenes=b), [[pair[0]['_id'] for pair in first][n:n + 3]
                                                   for n in range(0, len(first), 3)], 'values'),
        ('archived authors by name', lambda p: distinct('author', {
            'scene_id': {'$in': ['archive:' + s(p)]}, 'direction': 'archived', 'policy_epoch': e(p),
            'deletion_id': {'$exists': False}, '$or': [{'author': {'$in': ['nobody']}},
                                                       {'historical_display_name': 'name-none'}]}),
         lambda p: owner.authors(store, scenes=['archive:' + s(p)], epoch=e(p), direction='archived', live_only=True,
                                 among=['nobody'], named='name-none'), first, 'values'),
        # history search and the digest
        ('search, people\'s lines', *search_case('inbound'), 'value'),
        ('search, people\'s lines by text', *search_case('inbound', text=True), 'value'),
        ('search, people\'s lines by person, after a cursor', *search_case('inbound', person=True, cursor=True),
         'value'),
        ('search, archived lines by person after both cursors',
         lambda p: many(_old_streams(parts(p[0]), None, None, {'inbound': p[2], 'archived': p[3]}, authors=p[1],
                                     archived=True)['archived'][0], {'legacy': 0},
                        [('occurred_at', -1), ('scene_seq', -1), ('scene_id', -1)], 26),
         lambda p: owner.search(store, [s(p[0])], e(p[0]), 'archived', authors=p[1], after=p[3], after_too=p[2],
                                limit=26), archived, 'value'),
        ('search, her lines', *search_case('outbound'), 'value'),
        ('search, her lines by text, after a cursor', *search_case('outbound', text=True, cursor=True), 'value'),
        ('search, archived lines', *search_case('archived'), 'value'),
        ('search, her lines by receipt', lambda p: many(*_old_receipt(parts(p[0]), {p[1]})[:1], None,
                                                        _old_receipt(parts(p[0]), {p[1]})[1]),
         lambda p: owner.search(store, [s(p[0])], e(p[0]), 'receipt', receipts={p[1]}),
         [((scene, None), ref) for scene, ref in receipts] or [(first[0], 'receipt-none')] if first else [], 'value'),
        ('digest thread', lambda p: many({'scene_id': p[0]['_id'], 'policy_epoch': p[0]['policy_epoch'], '$or': [
            {'event.group_context.reply_message_id': {'$in': sorted(set(p[1]))}},
            {'reply_to': {'$in': sorted(set(p[1]))}}, {'_id': {'$in': sorted(set(p[1]))}}]}, THREAD),
         lambda p: owner.thread(store, [p[0]['_id']], p[0]['policy_epoch'], replying_to=p[1], ids=p[1],
                                fields=list(THREAD)), by_scene, 'value'),
        ('digest left out and not speech, counted', lambda p: excluded_old(p),
         lambda p: [owner.excluded(store, [s(p)], e(p))[key] for key in ('undelivered_outbound', 'non_speak_outbound')],
         first, 'value'),
    ]
    return [case for case in cases if case[3]], 1 + tried


TURN = ['_id', 'scene_id', 'source_event_id', 'episode_kind', 'persona', 'person_id', 'scope_key', 'policy_epoch',
        'native_session_id', 'state']
BINDING = ['_id', 'scene_id', 'persona', 'policy_epoch', 'character_context', 'lane', 'scope_key', 'person_id',
           'broker_session', 'parent_session_id', 'task_id', 'successor_id', 'main_conversation', 'native_host']
TURN_KINDS = ('external', 'task_feedback', 'self_development', 'consult', 'visit', 'settlement')
PUBLISH = 'self_development_publish'
ANSWERED = ['COMMITTED', 'WAITING_TASK']                              # familiarity's and notes.FINISHED's states
RUNNING = ['PREPARED', 'TURN', 'SPEAK_ACCEPTED']                     # coordinator.recover
AT_WORK = ['ATTENDING', 'PREPARED', 'TURN', 'SPEAK_ACCEPTED']        # schedule.night_stage_busy


def _sample_b5(store):
    """What the cases read with, through the owners: turns of each kind, the native sessions, the sink receipts of
    her publications and some others, and the lane receipts of those sessions."""
    from asuna.records import episodes as turns, receipts, sessions
    found = {'turns': [], 'reads': 0}
    for kind in TURN_KINDS:
        found['turns'] += turns.of_kind(store, kind).rows(limit=6, fields=TURN)
        found['reads'] += 1
    found['bindings'] = sessions.native(store).rows(limit=60, fields=BINDING)
    found['publications'] = receipts.sink_of_kind(store, PUBLISH).rows(limit=12, fields=['_id', 'state', 'project'])
    found['sinks'] = receipts.sinks(store).rows(limit=12, fields=['_id', 'received_at', 'kind'])
    found['lanes'] = receipts.lane_of_sessions(store, [row['_id'] for row in found['bindings']])[:12]
    found['reads'] += 4
    return found


def _cases_b5(store, config):
    """(name, old(param), new(param), parameters, compare) for each read B5 moved, the old as the replaced code wrote
    it; parameters sampled through the owners, synthetic values where her records hold none (both sides then read
    nothing, and the plans are still compared)."""
    from asuna.records import episodes as turns, receipts, sessions
    got = _sample_b5(store)
    rows, bindings = got['turns'], got['bindings']
    ids = [row['_id'] for row in rows] or ['turn-none']
    batches = [ids[n:n + 5] for n in range(0, len(ids), 5)]
    persons = [[row['person_id']] for row in rows if isinstance(row.get('person_id'), str)] or [['person-none']]
    sources = [row for row in rows if isinstance(row.get('source_event_id'), str)]
    feedback = [row for row in sources if row.get('episode_kind') == 'task_feedback'] or sources
    scopes = sorted({row['scope_key'] for row in rows if isinstance(row.get('scope_key'), str)}) or ['scope-none']
    fenced = [row for row in rows if all(isinstance(row.get(key), str) for key in (
        'native_session_id', 'scope_key', 'scene_id', 'person_id', 'persona')) and isinstance(row.get('policy_epoch'), int)]
    personas = [row for row in rows if isinstance(row.get('persona'), str)]
    scenes = sorted({row['scene_id'] for row in rows if isinstance(row.get('scene_id'), str)})
    session_ids = [row['_id'] for row in bindings] or ['session-none']
    session_batches = [session_ids[n:n + 5] for n in range(0, len(session_ids), 5)]
    main = [row for row in bindings if row.get('main_conversation') and isinstance(row.get('scene_id'), str)]
    plain = [row for row in main if row.get('character_context') is None] or [
        {'scene_id': 'scene-none', 'persona': 'persona-none', 'policy_epoch': 1, 'character_context': None}]
    contexts = [row for row in main if isinstance(row.get('character_context'), str)] or [
        {'scene_id': 'scene-none', 'persona': 'persona-none', 'policy_epoch': 1, 'character_context': 'context-none'}]
    actions = [row for row in bindings if row.get('lane') == 'executor' and all(
        isinstance(row.get(key), str) for key in ('broker_session', 'parent_session_id', 'scene_id', 'scope_key',
                                                  'person_id', 'persona'))] or [
        {'broker_session': 'broker-none', 'parent_session_id': 'parent-none', 'scene_id': 'scene-none',
         'scope_key': 'scope-none', 'policy_epoch': 1, 'person_id': 'person-none', 'persona': 'persona-none',
         'task_id': 'task-none'}]
    local = (config.get('chat') or {}).get('scene_id') or 'local-none'
    publications = got['publications']
    projects = sorted({row['project'] for row in publications if isinstance(row.get('project'), str)}) or ['core']
    sink_ids = [row['_id'] for row in got['sinks'] + publications] or ['sink-none']
    stamps = sorted({row['received_at'] for row in got['sinks'] if isinstance(row.get('received_at'), str)}) or [
        '2026-01-01T00:00:00+00:00']
    lane_ids = [row['_id'] for row in got['lanes']] or ['lane-none']
    one = lambda coll, filter, proj=None, sort=None: ('find_one', coll, filter, proj, sort)
    many = lambda coll, filter, proj=None, sort=None, limit=0: ('find', coll, filter, proj, sort, limit)
    count = lambda coll, filter, limit=0: ('count', coll, filter, limit)
    fields = lambda *names: {name: 1 for name in names}
    E, S, L, K = 'episodes', 'sessions', 'lane_receipts', 'sink_receipts'

    def chain(row):
        return dict(broker=row['broker_session'], parents=[row['parent_session_id']], scene=row['scene_id'],
                    scope=row['scope_key'], epoch=row.get('policy_epoch'), person=row['person_id'],
                    persona=row['persona'])

    def action(row, task=False):
        flt = {'native_host': True, 'lane': 'executor', 'broker_session': row['broker_session'],
               'parent_session_id': {'$in': [row['parent_session_id']]}, 'scene_id': row['scene_id'],
               'scope_key': row['scope_key'], 'policy_epoch': row.get('policy_epoch'), 'person_id': row['person_id'],
               'persona': row['persona']}
        return {**flt, 'task_id': row.get('task_id') or 'task-none'} if task else flt

    newest = [('binding_updated_at', -1), ('_id', -1)]
    cases = [
        # episodes
        ('turn by id', lambda i: one(E, {'_id': i}), lambda i: turns.get(store, i), ids, 'value'),
        ('turn by id, fields', lambda i: one(E, {'_id': i}, fields('scene_id', 'scope_key', 'policy_epoch', 'person_id')),
         lambda i: turns.get(store, i, fields=['scene_id', 'scope_key', 'policy_epoch', 'person_id']), ids, 'value'),
        ('turn by id, nested fields', lambda i: one(E, {'_id': i}, fields(
            'persona', 'scene_id', 'manifest.session_class', 'manifest.carried', 'context.memories')),
         lambda i: turns.get(store, i, fields=['persona', 'scene_id', 'manifest.session_class', 'manifest.carried',
                                                'context.memories']), ids, 'value'),
        ('a carried turn of a persona', lambda r: one(E, {'_id': r['_id'], 'persona': r['persona'],
                                                          'system_ref.carried': {'$exists': True}}, fields('system_ref')),
         lambda r: turns.get(store, r['_id'], fields=['system_ref'], persona=r['persona'], carried=True), personas,
         'value'),
        ('a turn within the snapshot\'s fence', lambda r: one(E, {
            'native_session_id': r['native_session_id'], 'scope_key': r['scope_key'], 'scene_id': r['scene_id'],
            'person_id': r['person_id'], 'policy_epoch': r['policy_epoch'], 'persona': r['persona'], '_id': r['_id']},
            fields('context', 'manifest', 'monologue_refs', 'understanding_seen')),
         lambda r: turns.get(store, r['_id'], ['context', 'manifest', 'monologue_refs', 'understanding_seen'],
                             session=r['native_session_id'], scope=r['scope_key'], scene=r['scene_id'],
                             person=r['person_id'], epoch=r['policy_epoch'], persona=r['persona']), fenced, 'value'),
        ('turns by ids, fields', lambda b: many(E, {'_id': {'$in': b}}, fields('scene_id')),
         lambda b: turns.many(store, b).rows(fields=['scene_id']), batches, 'value'),
        ('a finished turn among ids', lambda b: one(E, {'_id': {'$in': b}, 'state': {'$in': ANSWERED}}, fields('_id')),
         lambda b: turns.many(store, b, states=ANSWERED).first(fields=['_id']), batches, 'value'),
        ('finished turns among ids, counted', lambda b: count(E, {'_id': {'$in': b}, 'state': {'$in': ANSWERED}}),
         lambda b: turns.many(store, b, states=ANSWERED).count(), batches, 'value'),
        ('the turn of a source', lambda r: one(E, {'source_event_id': r['source_event_id']}, fields('silent_reason')),
         lambda r: turns.of_source(store, r['source_event_id'], fields=['silent_reason']), sources, 'value'),
        ('the feedback turn of a result', lambda r: one(E, {'source_event_id': r['source_event_id'],
                                                            'episode_kind': 'task_feedback'}),
         lambda r: turns.of_source(store, r['source_event_id'], kind='task_feedback'), feedback, 'value'),
        ('the feedback turn of a result here', lambda r: one(E, {'scene_id': r['scene_id'],
                                                                 'source_event_id': r['source_event_id'],
                                                                 'episode_kind': 'task_feedback'}),
         lambda r: turns.of_source(store, r['source_event_id'], kind='task_feedback', scene=r['scene_id']), feedback,
         'value'),
        ('settlement turns', lambda _: many(E, {'episode_kind': 'settlement'}, fields('_id')),
         lambda _: turns.of_kind(store, 'settlement').rows(fields=['_id']), [None], 'value'),
        ('outside turns in groups', lambda b: many(E, {'episode_kind': 'external', 'scene_id': {'$in': b}},
                                                   fields('scene_id', 'native_session_id')),
         lambda b: turns.of_kind(store, 'external', scenes=b).rows(fields=['scene_id', 'native_session_id']),
         [scenes[n:n + 5] for n in range(0, len(scenes), 5)] or [['scene-none']], 'value'),
        ('turns to recover', lambda _: many(E, {'state': {'$in': RUNNING}, 'episode_kind': {'$ne': 'consult'}}),
         lambda _: turns.open(store, RUNNING, not_kind='consult').rows(), [None], 'value'),
        ('a self-development turn at work', lambda _: one(E, {'episode_kind': 'self_development',
                                                              'state': {'$in': AT_WORK}}, fields('_id')),
         lambda _: turns.open(store, AT_WORK, kind='self_development').first(fields=['_id']), [None], 'value'),
        ('turns answered with words, counted', lambda p: count(E, {'person_id': {'$in': p}, 'state': {'$in': ANSWERED},
                                                                   'speech': {'$exists': True}}, 15),
         lambda p: turns.answered(store, p, limit=15), persons, 'value'),
        ('turns of a scope', lambda s: many(E, {'scope_key': s}, fields('_id')),
         lambda s: turns.of_scope(store, s, fields=['_id']), scopes, 'value'),
        # sessions
        ('session by id', lambda i: one(S, {'_id': i}), lambda i: sessions.get(store, i), session_ids, 'value'),
        ('session by id, fields', lambda i: one(S, {'_id': i}, fields('errand', 'reflection')),
         lambda i: sessions.get(store, i, fields=['errand', 'reflection']), session_ids, 'value'),
        ('native session by id', lambda i: one(S, {'_id': i, 'native_host': True}),
         lambda i: sessions.get(store, i, native=True), session_ids, 'value'),
        ('native sessions', lambda _: many(S, {'native_host': True}), lambda _: sessions.native(store).rows(), [None],
         'value'),
        ('native sessions by ids', lambda b: many(S, {'_id': {'$in': b}, 'native_host': True}),
         lambda b: sessions.native(store, b).rows(), session_batches, 'value'),
        ('platform conversations among sessions', lambda b: many(S, {'_id': {'$in': b}, 'native_host': True,
                                                                     'lane': 'character', 'scene_id': {'$ne': local}},
                                                                 fields('scene_id')),
         lambda b: sessions.native(store, b, lane='character', besides_scene=local).rows(fields=['scene_id']),
         session_batches, 'value'),
        ('sessions continuing these', lambda b: many(S, {'successor_id': {'$in': b}}, fields('_id')),
         lambda b: sessions.successors(store, b).rows(fields=['_id']), session_batches, 'value'),
        ('the main session, no character context', lambda r: one(S, {
            'native_host': True, 'main_conversation': True, 'scene_id': r['scene_id'], 'persona': r['persona'],
            'policy_epoch': r.get('policy_epoch'), 'character_context': None}),
         lambda r: sessions.main(store, r['scene_id'], persona=r['persona'], epoch=r.get('policy_epoch'), context=None),
         plain, 'value'),
        ('the main session, a character context', lambda r: one(S, {
            'native_host': True, 'main_conversation': True, 'scene_id': r['scene_id'], 'persona': r['persona'],
            'policy_epoch': r.get('policy_epoch'), 'character_context': r['character_context']}),
         lambda r: sessions.main(store, r['scene_id'], persona=r['persona'], epoch=r.get('policy_epoch'),
                                 context=r['character_context']), contexts, 'value'),
        ('the main character session of a conversation', lambda r: one(S, {
            'scene_id': r['scene_id'], 'lane': 'character', 'native_host': True, 'main_conversation': True}),
         lambda r: sessions.main(store, r['scene_id'], lane='character'), main or plain, 'value'),
        ('the titled main session', lambda r: one(S, {'scene_id': r['scene_id'], 'main_conversation': True,
                                                      'native_title': {'$exists': True}}, fields('native_title')),
         lambda r: sessions.titled(store, r['scene_id'], fields=['native_title']), main or plain, 'value'),
        ('a task\'s action session', lambda r: one(S, action(r, task=True), None, newest),
         lambda r: sessions.of_task(store, **chain(r), task=r.get('task_id') or 'task-none'), actions, 'value'),
        ('a binding\'s newest action session', lambda r: one(S, action(r), None, newest),
         lambda r: sessions.of_task(store, **chain(r)), actions, 'value'),
        ('sessions of a scope', lambda s: many(S, {'scope_key': s}), lambda s: sessions.of_scope(store, s), scopes,
         'value'),
        # receipts
        ('lane receipt by id', lambda i: one(L, {'_id': i}), lambda i: receipts.lane_get(store, i), lane_ids, 'value'),
        ('lane receipts of sessions', lambda b: many(L, {'session_id': {'$in': b}}),
         lambda b: receipts.lane_of_sessions(store, b), session_batches, 'value'),
        ('sink receipt by id', lambda i: one(K, {'_id': i}), lambda i: receipts.sink_get(store, i), sink_ids, 'value'),
        ('sink receipts by ids', lambda b: many(K, {'_id': {'$in': b}}), lambda b: receipts.sinks(store, b).rows(),
         [sink_ids[n:n + 5] for n in range(0, len(sink_ids), 5)], 'value'),
        ('sink receipts, counted', lambda _: count(K, {}), lambda _: receipts.sinks(store).count(), [None], 'value'),
        ('a core publication applied', lambda _: one(K, {'kind': PUBLISH, 'state': 'APPLIED', 'project': 'core'}),
         lambda _: receipts.sink_of_kind(store, PUBLISH, state='APPLIED', project='core').first(), [None], 'value'),
        ('publications applied or active', lambda _: many(K, {'kind': PUBLISH, 'state': {'$in': ['APPLIED', 'ACTIVE']}}),
         lambda _: receipts.sink_of_kind(store, PUBLISH, states=['APPLIED', 'ACTIVE']).rows(), [None], 'value'),
        ('the newest publications', lambda _: many(K, {'kind': PUBLISH}, fields(
            'project', 'state', 'changed_files', 'deleted_files', 'published_at', 'activated_at', 'task_id'),
            [('published_at', -1)], 5),
         lambda _: receipts.sink_of_kind(store, PUBLISH, by='published_at').rows(
             newest_first=True, limit=5, fields=['project', 'state', 'changed_files', 'deleted_files', 'published_at',
                                                 'activated_at', 'task_id']), [None], 'value'),
        ('a publication still applied', lambda _: one(K, {'kind': PUBLISH, 'state': 'APPLIED'}, fields('_id')),
         lambda _: receipts.sink_of_kind(store, PUBLISH, state='APPLIED').first(fields=['_id']), [None], 'value'),
        ('publications waiting for a restart', lambda _: many(K, {'kind': PUBLISH, 'state': 'HOST_RESTART_REQUIRED'},
                                                              fields('project', 'published_at'),
                                                              [('published_at', 1)]),
         lambda _: receipts.sink_of_kind(store, PUBLISH, state='HOST_RESTART_REQUIRED', by='published_at').rows(
             fields=['project', 'published_at']), [None], 'value'),
        ('a project\'s earlier publications', lambda p: many(K, {
            'kind': PUBLISH, 'project': p[0], 'state': {'$in': ['APPLIED', 'HOST_RESTART_REQUIRED']},
            '_id': {'$ne': p[1]}}),
         lambda p: receipts.sink_of_kind(store, PUBLISH, project=p[0], states=['APPLIED', 'HOST_RESTART_REQUIRED'],
                                         besides=p[1]).rows(), [(p, sink_ids[0]) for p in projects], 'value'),
        ('receipts in a window', lambda w: many(K, {'received_at': {'$gte': w, '$lte': '9999-12-31T23:59:59Z'}}, None,
                                                [('received_at', -1), ('_id', -1)], 200),
         lambda w: receipts.sink_window(store, gte=w, lte='9999-12-31T23:59:59Z').rows(newest_first=True, limit=200),
         [stamp[:10] for stamp in stamps], 'value'),
        ('receipts before a cursor', lambda w: many(K, {'received_at': {'$lt': w}}, None,
                                                    [('received_at', -1), ('_id', -1)], 200),
         lambda w: receipts.sink_window(store, lt=w).rows(newest_first=True, limit=200), stamps, 'value'),
    ]
    return [case for case in cases if case[3]], got['reads']


def sizes(db, collection, max_ms, timings=None):
    """The records of 512 KiB or more by their BSON size, and of those the ones whose BSON and JSON sizes (the
    in-memory adapter's measure) fall on different sides of the store's 1 MiB limit; read part by part like the
    kinds. None when a read is over its limit."""
    import time as clock
    from asuna.store.words import MAX_RECORD_BYTES, record_bytes
    timings = [] if timings is None else timings
    large = []
    try:
        cut = parts(db, collection, max_ms, timings)
    except ExecutionTimeout:
        return None
    for after, upto in cut:
        started = clock.perf_counter()
        try:
            large += [row['_id'] for row in db[collection].aggregate(
                [{'$match': _part(after, upto)}, {'$project': {'s': {'$bsonSize': '$$ROOT'}}},
                 {'$match': {'s': {'$gte': MAX_RECORD_BYTES // 2}}}, {'$project': {'_id': 1}}], maxTimeMS=max_ms)]
        except ExecutionTimeout:
            return None
        finally:
            timings.append((clock.perf_counter() - started) * 1000)
    differ = 0
    for key in large:
        doc = db[collection].find_one({'_id': key}, max_time_ms=max_ms)
        if doc is not None:
            bson = MongoAdapter.measure(None, doc)
            differ += (bson > MAX_RECORD_BYTES) != (record_bytes(doc) > MAX_RECORD_BYTES)
    return {'large': len(large), 'sides_differ': differ}


def check(batch, settings, database, out, max_ms):
    client = MongoClient(settings['mongo_uri'], serverSelectionTimeoutMS=5000, connectTimeoutMS=5000,
                         **({'timeoutMS': max_ms} if batch in READ_CASES else {}))
    # The field counts' own client: no client-side time limit, only each read's `maxTimeMS` on the server, so a read
    # over its limit is the server's refusal of that read (its fields unchecked), never a connection timing out.
    counting = MongoClient(settings['mongo_uri'], serverSelectionTimeoutMS=5000, connectTimeoutMS=5000,
                           socketTimeoutMS=max_ms + 30000)
    # Nothing is written: ensure is planned, not run, and every read is read-only.
    report, unchecked = {'mode': 'dry_run', 'database_collections': len(CATALOG.names())}, []
    timings, unchecked_fields = [], {}
    try:
        adapter = MongoAdapter(client, database)
        plans = dry_run(adapter)
        report['ensure'] = {name: {'create': plan['create'], 'make': plan['make'], 'drop': plan['drop'],
                                   'conflicts': [index for index, _ in plan['conflicts']],
                                   'validator': plan['validator']}
                            for name, plan in plans.items()}
        report['conflicts'] = [[name, index] for name, plan in plans.items() for index, _ in plan['conflicts']]
        report['fields'], report['fields_differ'] = {}, []
        for collection in CATALOG.collections():
            if BATCHES[batch] is not None and collection.name not in BATCHES[batch]:
                continue
            missed = set()
            try:
                counts = kinds(counting.get_database(database), collection, max_ms, timings, missed)
            except ExecutionTimeout:
                unchecked.append(collection.name)
                continue
            if missed:
                unchecked_fields[collection.name] = sorted(missed)
            report['fields'][collection.name] = counts
            report['fields_differ'] += [[collection.name, path] for path in differs(collection, counts)]
            report.setdefault('fields_differing_records', {})[collection.name] = differing(collection, counts)
        for name in SIZED.get(batch, ()):
            report.setdefault('sizes', {})[name] = sizes(counting.get_database(database), name, max_ms, timings)
            if report['sizes'][name] is None:
                unchecked.append(name + ' sizes')
        ordered = sorted(timings)
        report['field_reads'] = {'reads': len(ordered), 'records_a_read': PART_RECORDS, 'fields_a_read': FIELDS_PER_READ,
                                 **({'ms_p50': round(ordered[len(ordered) // 2], 1),
                                     'ms_p95': round(ordered[int(len(ordered) * .95)], 1),
                                     'ms_max': round(ordered[-1], 1)} if ordered else {})}
        if batch in READ_CASES:
            report['reads'], report['queries'] = reads(client, database, max_ms, batch, settings)
            failing, accepted = slowdowns(batch, report['reads'])
            report['slowdowns'] = {'failing': failing, 'accepted': accepted,
                                   'rule': 'new p50 > %g x old and > %g ms above it' % (SLOWER, SLOWER_MS)}
    except ExecutionTimeout:
        print('UNCHECKED, a read case over the time limit')
        return 2
    except PyMongoError as error:
        print('ADR104_CHECK_UNREACHABLE: %s' % type(error).__name__)
        return 2
    finally:
        client.close()
        counting.close()
    report['unchecked'], report['unchecked_fields'] = unchecked, unchecked_fields
    # The collections to create, the indexes to make and the validators count for the collections the batch
    # declares (b1b: all); the drops and conflicts for every collection. The others are reported apart.
    ours = {name for name in plans if BATCHES[batch] is None or name in BATCHES[batch]}
    count = lambda key, names: sum(int(bool(plans[n]['create'])) if key == 'create' else len(plans[n][key])
                                   for n in names)
    totals = {'create': count('create', ours), 'make': count('make', ours), 'drop': count('drop', plans),
              'conflicts': count('conflicts', plans)}
    validators = {}
    for name in ours:
        validators[plans[name]['validator']] = validators.get(plans[name]['validator'], 0) + 1
    report['totals'], report['validators'] = totals, validators
    report['outside_batch'] = {'create': count('create', set(plans) - ours), 'make': count('make', set(plans) - ours)}
    out.mkdir(parents=True, exist_ok=True)
    (out / (batch + '.json')).write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print('ensure, dry run: collections to create %(create)d, indexes to make %(make)d, to drop %(drop)d, '
          'conflicting %(conflicts)d' % totals)
    if BATCHES[batch] is not None:
        print('(create and make count the collections the batch declares; elsewhere: to create %(create)d, '
              'to make %(make)d)'
              % report['outside_batch'])
    print('validators: ' + ', '.join('%s %d' % item for item in sorted(validators.items())))
    for what in ('make', 'drop'):
        for name, plan in sorted(report['ensure'].items()):
            for index in plan[what]:
                print('to %s: %s.%s' % (what, name, index))
    for name, plan in sorted(report['ensure'].items()):
        if plan['create']:
            print('to create: %s' % name)
    for name, index in report['conflicts']:
        print('conflict: %s.%s' % (name, index))
    for name, counts in sorted(report['fields'].items()):
        for path, seen in sorted(counts.items()):
            shown = ', '.join('%s %d' % item for item in sorted(seen['types'].items()))
            elements = ', '.join('%s %d' % item for item in sorted((seen.get('elements') or {}).items()))
            print('%s.%s: %s%s%s' % (name, path, shown, ', other length %d' % seen['other_length']
                                     if seen['other_length'] else '', '; elements: ' + elements if elements else ''))
    for name, path in report['fields_differ']:
        print('differs from its declaration: %s.%s (%d records)'
              % (name, path, report['fields_differing_records'][name][path]))
    for name in unchecked:
        print('UNCHECKED, over the time limit: %s' % name)
    for name, paths in sorted(unchecked_fields.items()):
        print('UNCHECKED, a read over the time limit: %s fields %s' % (name, ', '.join(paths)))
    if report.get('field_reads', {}).get('reads'):
        print('field counts: %(reads)d reads of at most %(records_a_read)d records and %(fields_a_read)d fields, '
              'ms p50 %(ms_p50)s p95 %(ms_p95)s max %(ms_max)s' % report['field_reads'])
    for name, size in sorted((report.get('sizes') or {}).items()):
        if size:
            print('%s: records of 512 KiB or more by BSON: %d; on different sides of 1 MiB by BSON and JSON: %d'
                  % (name, size['large'], size['sides_differ']))
    for name, case in (report.get('reads') or {}).items():
        print('read %s: n %d, same %d, differing %d, rows old %d new %d, plans differing %d%s (%s | %s), ms old p50 %s '
              'p95 %s, new p50 %s p95 %s'
              % (name, case['n'], case['same'], case['differing'], case.get('rows_old', 0), case.get('rows_new', 0),
                 case['plans_differ'], ', accepted' if case.get('plan_accepted') and case['plans_differ'] else '',
                 ' > '.join(case['plan_old'] or ['no plan of its own']) if case.get('plans_compared', True)
                 else 'old: no plan of its own', ' > '.join(case['plan_new'] or []),
                 case['ms_old_p50'], case['ms_old_p95'], case['ms_new_p50'], case['ms_new_p95']))
    for name, entry in sorted(ACCEPTED_PLAN_DIFFERENCES.get(batch, {}).items()):
        print('accepted plan difference: %s: %s; %s' % (name, entry['reason'], entry['recheck']))
    if 'slowdowns' in report:
        print('timing gate (%s):' % report['slowdowns']['rule'])
        for name, old, new, plan in report['slowdowns']['failing']:
            first, again = report['reads'][name], report['reads'][name].get('confirm') or {}
            print('SLOWER, fails the run: %s: old p50 %s ms, new p50 %s ms (%s), new plan %s'
                  % (name, old, new, 'timed again %d runs; first old %s, new %s' % (
                      again['runs'], first['ms_old_p50'], first['ms_new_p50']) if again.get('runs')
                     else again.get('why', 'not timed again'), ' > '.join(plan or [])))
        for name, case in sorted(report['reads'].items()):
            again = case.get('confirm') or {}
            if again.get('runs') and name not in {row[0] for row in report['slowdowns']['failing']}:
                print('timed again, under the gate: %s: first old p50 %s, new %s; %d runs: old %s, new %s'
                      % (name, case['ms_old_p50'], case['ms_new_p50'], again['runs'], again['ms_old_p50'],
                         again['ms_new_p50']))
        for name, entry in sorted(ACCEPTED_SLOWDOWNS.get(batch, {}).items()):
            now = report['reads'].get(name, {})
            print('accepted slowdown: %s: old p50 %s ms, new p50 %s ms when accepted (now old %s, new %s); %s; %s'
                  % (name, entry['old_ms'], entry['new_ms'], now.get('ms_old_p50'), now.get('ms_new_p50'),
                     entry['reason'], entry['recheck']))
        for name, entry in sorted(WATCHED.get(batch, {}).items()):
            now, family = report['reads'].get(name, {}), report['reads'].get(entry['family'], {})
            print('watched: %s, beside %s: %s; now old p50 %s ms, new p50 %s ms (%s: old %s, new %s)'
                  % (name, entry['family'], entry['note'], now.get('ms_old_p50'), now.get('ms_new_p50'),
                     entry['family'], family.get('ms_old_p50'), family.get('ms_new_p50')))
        if not report['slowdowns']['failing']:
            print('timing gate: no read case slower past the threshold')
    if 'queries' in report:
        q = report['queries']
        print('queries: %d (sampling %d, timed %d = %d samples x 2 sides x %d runs, timed again %d, explain %d)'
              % (q['total'], q['sampling'], q['timed'], q['samples'], RUNS, q.get('confirmed', 0), q['explain']))
    print('numbers written to %s' % (out / (batch + '.json')))
    if unchecked or unchecked_fields:
        return 2
    return 0 if clean(report, totals, validators) else 1


def clean(report, totals, validators):
    """Whether a checked run found nothing: no collection to create, no index to make, no conflict, every validator
    the one ensure creates, every declared field holding only its kind, no record on different sides of 1 MiB, no
    read case slower past the timing gate, and every read case the same, its plan too (or accepted)."""
    return (not (totals['create'] or totals['make'] or totals['conflicts'])
            and set(validators) <= {'same', 'not declared'} and not report['fields_differ']
            and not any((size or {}).get('sides_differ') for size in (report.get('sizes') or {}).values())
            and not (report.get('slowdowns') or {}).get('failing')
            and not any(case['differing'] or (case['plans_differ'] and not case.get('plan_accepted'))
                        for case in (report.get('reads') or {}).values()))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('batch', choices=sorted(BATCHES))
    parser.add_argument('--config', default=str(ROOT / 'config' / 'local.json'))
    parser.add_argument('--out')
    parser.add_argument('--max-ms', type=int, default=2000)
    args = parser.parse_args(argv)
    try:
        config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        print('ADR104_CHECK_CONFIG: %s' % type(error).__name__)
        return 2
    data = Path(os.environ.get('ASUNA_DATA_ROOT') or ROOT / '.runtime')
    out = Path(args.out) if args.out else data / 'private' / 'adr104-evidence' / args.batch
    return check(args.batch, config, config['database'], out, args.max_ms)


if __name__ == '__main__':
    sys.exit(main())
