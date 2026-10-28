"""The read-only check of one ADR-104 batch against a deployment's database, before the batch merges: numbers only,
never a record id or a value.

  python tools/adr104_equivalence.py b1b|b2|b3 [--config config/local.json] [--out <folder>] [--max-ms 2000]

Each batch: what the store's `ensure` would do there, as a dry run (collections it would create, indexes it would
make, retired indexes it would drop, indexes of a declared name that differ, validators), and for every field the
catalog declares in the batch's collections (b1b: all of them; b2: `host_leases` and `lane_faults`; b3: `scenes`),
its stored records by BSON type, the nulls, the records missing a required field and, for a vector, the lengths that
differ. b3 also runs its read cases: each read the batch moved, as the replaced code wrote it with pymongo and as the
owner (`records.scenes`) now answers it, on parameters sampled through the owner (at most 20 a case, at most 1,000
queries in all, serial, `--max-ms` each, three runs for the times): the same ids in the same order, the same records,
the same plan stages; numbers only.
Each query is read-only and bounded by `--max-ms`. The numbers go to `<out>/<batch>.json` (default
`<data>/private/adr104-evidence/<batch>/`) and to the console. Exit 0 when nothing would be created, made or refused,
every validator is the one ensure creates and every declared field holds only its kind (the retired indexes to drop
are reported: dropping them is the batch's change); 1 when something differs; 2 when a check could not run (a query
over its time limit, the server out of reach).
"""
from __future__ import annotations
import argparse
import json
import os
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


def kinds(db, collection, max_ms):
    """Per declared field: {bson type: records}, and the records whose vector length differs from the declared one."""
    fields = [f for f in collection.fields if f.path != '_id']
    if not fields:
        return {}
    project = {'_id': 0, **{'k%d' % n: {'$type': '$' + f.path} for n, f in enumerate(fields)}}
    for n, f in enumerate(fields):
        if f.kind == 'vector':
            project['d%d' % n] = {'$cond': [{'$isArray': '$' + f.path}, {'$size': '$' + f.path}, None]}
    rows = db[collection.name].aggregate([{'$project': project}, {'$group': {'_id': '$$ROOT', 'n': {'$sum': 1}}}],
                                         maxTimeMS=max_ms)
    found = {f.path: {'types': {}, 'other_length': 0} for f in fields}
    for row in rows:
        for n, f in enumerate(fields):
            kind = row['_id'].get('k%d' % n, 'missing')
            found[f.path]['types'][kind] = found[f.path]['types'].get(kind, 0) + row['n']
            length = row['_id'].get('d%d' % n)
            if f.kind == 'vector' and length is not None and length != f.dimensions:
                found[f.path]['other_length'] += row['n']
    return found


def differs(collection, counts):
    """The declared fields whose stored records the declaration refuses: another kind, null where not nullable, a
    required field missing, a vector of another length."""
    wrong = []
    for f in collection.fields:
        if f.path == '_id' or f.path not in counts:
            continue
        types = counts[f.path]['types']
        allowed = KINDS[f.kind] | {'missing'} | ({'null'} if f.nullable else set())
        if set(types) - allowed or (f.required and types.get('missing')) or counts[f.path]['other_length']:
            wrong.append(f.path)
    return wrong


# The collections whose declared fields each batch counts (None: every collection).
BATCHES = {'b1b': None, 'b2': ('host_leases', 'lane_faults'), 'b3': ('scenes',)}
QUERIES = 1000
RUNS = 3


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
    """The MongoDB adapter, keeping the last read it sent (to explain it)."""
    sent = None

    def get(self, coll, id, fields=None):
        self.sent = (coll, {'_id': id}, (), 0, 1, fields)
        return super().get(coll, id, fields)

    def find(self, coll, where, sort=(), skip=0, limit=None, fields=None):
        from asuna.store.mongodb import query
        self.sent = (coll, query(where), sort, skip, limit or 0, fields)
        return super().find(coll, where, sort, skip, limit, fields)


def _cases(db, store):
    """(name, old(param), new(param), parameters) for each read B3 moved, the old as the replaced code wrote it."""
    from asuna.records import scenes as owner
    rows = sorted(owner.all(store, fields=['_id', 'scope_key', 'policy_epoch', 'kind']), key=lambda r: r['_id'])
    ids, kinds = [r['_id'] for r in rows], ['group', 'dm']
    scopes = [r['scope_key'] for r in rows if isinstance(r.get('scope_key'), str)]
    pairs = [(r['scope_key'], r.get('policy_epoch')) for r in rows if isinstance(r.get('scope_key'), str)]
    batches = [ids[n:n + 5] for n in range(0, len(ids), 5)]
    scenes = db.scenes
    one = lambda filter, proj=None: ('find_one', filter, proj)
    many = lambda filter, proj=None: ('find', filter, proj)
    return [
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
    ], scenes


def _old(scenes, call):
    method, filter, proj = call
    if method == 'find_one':
        return scenes.find_one(filter, proj), scenes.find(filter, proj).limit(1)
    return list(scenes.find(filter, proj)), scenes.find(filter, proj)


def reads(client, database, max_ms):
    """Each case's numbers: n, same, differing, plan stages and times, old against new; none are ids."""
    import statistics
    import time as clock
    from asuna.store import Checked
    old_db = client.get_database(database)
    adapter = _Recording(client, database)
    store = Checked(adapter, CATALOG)
    cases, scenes = _cases(old_db, store)
    per_case = max(1, min(20, (QUERIES - 2 * len(cases)) // (len(cases) * 2 * RUNS)))
    out, timed, explained = {}, 0, 0
    for name, old_call, new_call, params in cases:
        chosen = params[::max(1, len(params) // per_case)][:per_case] if params else []
        same = differing = plans_differ = 0
        times = {'old': [], 'new': []}
        old_plan = new_plan = None
        for param in chosen:
            results = {}
            for _ in range(RUNS):
                started = clock.perf_counter()
                old_value, old_cursor = _old(scenes, old_call(param))
                times['old'].append((clock.perf_counter() - started) * 1000)
                started = clock.perf_counter()
                new_value = new_call(param)
                times['new'].append((clock.perf_counter() - started) * 1000)
                timed += 2
                results = {'old': _plain(old_value), 'new': _plain(new_value)}
            if results['old'] == results['new']:
                same += 1
            else:
                differing += 1
            if old_plan is None or new_plan is None or param is chosen[-1]:
                coll, filter, sort, skip, limit, fields = adapter.sent
                new_cursor = adapter.db[coll].find(filter, {f: 1 for f in fields} if fields else None,
                                                   sort=list(sort) or None, skip=skip, limit=limit)
                old_plan = _stages(old_cursor.explain()['queryPlanner']['winningPlan'])
                new_plan = _stages(new_cursor.explain()['queryPlanner']['winningPlan'])
                explained += 2
                plans_differ += old_plan != new_plan
        pct = lambda values, q: round(statistics.quantiles(values, n=20)[q], 2) if len(values) > 1 else (
            round(values[0], 2) if values else None)
        out[name] = {'n': len(chosen), 'same': same, 'differing': differing, 'plans_differ': plans_differ,
                     'plan_old': old_plan, 'plan_new': new_plan,
                     'ms_old_p50': pct(times['old'], 9), 'ms_old_p95': pct(times['old'], 18),
                     'ms_new_p50': pct(times['new'], 9), 'ms_new_p95': pct(times['new'], 18)}
    samples = sum(case['n'] for case in out.values())
    # What was run: the one sampling read, each case's samples x 2 sides x RUNS timed runs, 2 explains per explained
    # sample.
    return out, {'sampling': 1, 'samples': samples, 'timed': timed, 'explain': explained,
                 'total': 1 + timed + explained, 'counted_as': 'sampling + samples x 2 sides x %d runs + explain' % RUNS}



def check(batch, settings, database, out, max_ms):
    client = MongoClient(settings['mongo_uri'], serverSelectionTimeoutMS=5000, connectTimeoutMS=5000,
                         **({'timeoutMS': max_ms} if batch == 'b3' else {}))
    # Nothing is written: ensure is planned, not run, and every read is read-only.
    report, unchecked = {'mode': 'dry_run', 'database_collections': len(CATALOG.names())}, []
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
            try:
                counts = kinds(adapter.db, collection, max_ms)
            except ExecutionTimeout:
                unchecked.append(collection.name)
                continue
            report['fields'][collection.name] = counts
            report['fields_differ'] += [[collection.name, path] for path in differs(collection, counts)]
        if batch == 'b3':
            report['reads'], report['queries'] = reads(client, database, max_ms)
    except ExecutionTimeout:
        print('UNCHECKED, a read case over the time limit')
        return 2
    except PyMongoError as error:
        print('ADR104_CHECK_UNREACHABLE: %s' % type(error).__name__)
        return 2
    finally:
        client.close()
    report['unchecked'] = unchecked
    totals = {key: sum(1 if key == 'create' and plan['create'] else len(plan[key]) if key != 'create' else 0
                       for plan in plans.values()) for key in ('create', 'make', 'drop', 'conflicts')}
    validators = {}
    for plan in plans.values():
        validators[plan['validator']] = validators.get(plan['validator'], 0) + 1
    report['totals'], report['validators'] = totals, validators
    out.mkdir(parents=True, exist_ok=True)
    (out / (batch + '.json')).write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print('ensure, dry run: collections to create %(create)d, indexes to make %(make)d, to drop %(drop)d, '
          'conflicting %(conflicts)d' % totals)
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
            print('%s.%s: %s%s' % (name, path, shown, ', other length %d' % seen['other_length']
                                   if seen['other_length'] else ''))
    for name, path in report['fields_differ']:
        print('differs from its declaration: %s.%s' % (name, path))
    for name in unchecked:
        print('UNCHECKED, over the time limit: %s' % name)
    for name, case in (report.get('reads') or {}).items():
        print('read %s: n %d, same %d, differing %d, plans differing %d (%s | %s), ms old p50 %s p95 %s, new p50 %s p95 %s'
              % (name, case['n'], case['same'], case['differing'], case['plans_differ'],
                 ' > '.join(case['plan_old'] or []), ' > '.join(case['plan_new'] or []),
                 case['ms_old_p50'], case['ms_old_p95'], case['ms_new_p50'], case['ms_new_p95']))
    if 'queries' in report:
        q = report['queries']
        print('queries: %d (sampling %d, timed %d = %d samples x 2 sides x %d runs, explain %d)'
              % (q['total'], q['sampling'], q['timed'], q['samples'], RUNS, q['explain']))
    print('numbers written to %s' % (out / (batch + '.json')))
    if unchecked:
        return 2
    clean = (not (totals['create'] or totals['make'] or totals['conflicts'])
             and set(validators) <= {'same', 'not declared'} and not report['fields_differ']
             and not any(case['differing'] or case['plans_differ'] for case in (report.get('reads') or {}).values()))
    return 0 if clean else 1


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
