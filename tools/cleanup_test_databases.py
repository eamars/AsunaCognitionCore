"""Inventory or remove only explicitly inventoried Asuna test databases."""
import argparse
import json
import re
from pathlib import Path

from pymongo import MongoClient
from asuna.config import load, validate_database


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    config = load()
    protected = {config['database'], config.get('legacy_database'), *config['allowed_databases'], 'admin', 'local', 'config'}
    client = MongoClient(config['mongo_uri'], serverSelectionTimeoutMS=5000, connectTimeoutMS=5000)
    try:
        before = set(client.list_database_names())
        if not args.apply:
            data = {'protected': sorted(n for n in protected if n), 'database_count': len(before),
                    'test_databases': sorted(n for n in before if n.startswith('asuna_v2_test_') and n not in protected),
                    'other_databases': sorted(n for n in before if not n.startswith('asuna_v2_test_') or n in protected)}
            args.inventory.parent.mkdir(parents=True, exist_ok=True)
            args.inventory.write_text(json.dumps(data, indent=2), encoding='utf-8')
            print(json.dumps({'test_databases': len(data['test_databases']), 'inventory': str(args.inventory)}))
            return
        data = json.loads(args.inventory.read_text(encoding='utf-8'))
        targets = data['test_databases']
        # Validate the whole concrete manifest before the first mutation. New
        # databases appearing after inventory are never added to this operation.
        for name in targets:
            if name in protected or not re.fullmatch(r'asuna_v2_test_[A-Za-z0-9_]+', name):
                raise ValueError('TEST_CLEANUP_TARGET_NOT_AUTHORIZED')
            validate_database(config, name)
        dropped = []
        try:
            for name in targets:
                if name not in before:
                    continue
                client.drop_database(name)
                dropped.append(name)
                if len(dropped) % 10 == 0:
                    print(json.dumps({'dropped': len(dropped), 'total': len(targets)}), flush=True)
        finally:
            after = set(client.list_database_names())
            result = {'dropped': dropped, 'remaining_targets': sorted(set(targets) & after),
                      'remaining_test_databases': sorted(n for n in after if n.startswith('asuna_v2_test_')),
                      'other_databases_preserved': sorted(before - set(targets)) == sorted(after - set(targets)),
                      'database_count_after': len(after)}
            args.inventory.with_name('result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
            print(json.dumps({key: len(value) if key == 'dropped' else value for key, value in result.items()}))
    finally:
        client.close()


if __name__ == '__main__':
    main()
