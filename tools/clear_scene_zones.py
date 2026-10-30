"""ADR-106's one-off: take the time zone off every conversation that still carries one.

Usage: python tools/clear_scene_zones.py [--config config/local.json]           count only (dry run)
       python tools/clear_scene_zones.py [--config config/local.json] --apply   clear them

Prints counts only, never a zone. Nothing reads the stored value any more, so the order against the install does not
matter; a second run changes none. The tool and `records/scenes.py:clear_timezones` are deleted in the commit after
the landing is verified.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from asuna.config import load           # noqa: E402
from asuna.records import scenes        # noqa: E402
from asuna.state import Store           # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', default='config/local.json')
    parser.add_argument('--apply', action='store_true', help='clear them (without it: count only)')
    args = parser.parse_args()
    store = Store(load(args.config))
    try:
        before = scenes.timezones(store)
        changed = scenes.clear_timezones(store) if args.apply else 0
        print(json.dumps({'applied': args.apply, 'carrying_before': before, 'cleared': changed,
                          'carrying_after': scenes.timezones(store)}))
    finally:
        store.close()


if __name__ == '__main__':
    main()
