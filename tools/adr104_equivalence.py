"""The read-only check of one ADR-104 batch against a deployment's database, before the batch merges: numbers only,
never a record id or a value.

  python tools/adr104_equivalence.py b1b|b2 [--config config/local.json] [--out <folder>] [--max-ms 2000]

Each batch: what the store's `ensure` would do there, as a dry run (collections it would create, indexes it would
make, retired indexes it would drop, indexes of a declared name that differ, validators), and for every field the
catalog declares in the batch's collections (b1b: all of them; b2: `host_leases` and `lane_faults`), its stored
records by BSON type, the nulls, the records missing a required field and, for a vector, the lengths that differ.
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
BATCHES = {'b1b': None, 'b2': ('host_leases', 'lane_faults')}


def check(batch, settings, database, out, max_ms):
    client = MongoClient(settings['mongo_uri'], serverSelectionTimeoutMS=5000, connectTimeoutMS=5000)
    report, unchecked = {'database_collections': len(CATALOG.names())}, []
    try:
        adapter = MongoAdapter(client, database)
        plans = dry_run(adapter)
        report['ensure'] = {name: {k: (len(v) if isinstance(v, list) else v) for k, v in plan.items()}
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
    print('numbers written to %s' % (out / (batch + '.json')))
    if unchecked:
        return 2
    clean = (not (totals['create'] or totals['make'] or totals['conflicts'])
             and set(validators) <= {'same', 'not declared'} and not report['fields_differ'])
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
