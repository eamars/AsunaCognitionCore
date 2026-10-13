"""ADR-062 phase 1: the shadow pilot's daily reading, in counts only (no text, no headings, no queries).

Usage: python tools/memory_pilot_report.py [--since 2026-10-14] [--config config/local.json]
       python tools/memory_pilot_report.py --drop     removes everything the pilot wrote (one collection)
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from asuna import memory_pilot          # noqa: E402
from asuna.config import load           # noqa: E402
from asuna.state import Store           # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', default='config/local.json')
    parser.add_argument('--since', help='ISO date or time (UTC) of the first row to count')
    parser.add_argument('--drop', action='store_true', help='drop the pilot collection and its index')
    args = parser.parse_args()
    config = load(args.config)
    store = Store(config)
    try:
        if args.drop:
            store.db[memory_pilot.COLLECTION].drop()
            print(json.dumps({'dropped': memory_pilot.COLLECTION}))
            return
        print(json.dumps(memory_pilot.report(store, config.get('timezone') or 'UTC', args.since),
                         ensure_ascii=False, indent=1))
    finally:
        store.client.close()


if __name__ == '__main__':
    main()
