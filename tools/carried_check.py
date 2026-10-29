"""ADR-096's install checks, read only: what the turns carry is what carried() says, in numbers only.

Usage: python tools/carried_check.py [--config config/local.json] [--model <persona-model.json>]

Checks (carried.install_checks): the latest turn's system_ref section list equals carried() for its pair; each pair's
refusal gives carried()'s number for the pair it names (the write is only measured, never made); a write gets its
room line; every section whose inject and tier differ is said. Prints one line per check, PASS or FAIL, with the
numbers it saw; no section text, no headings. A home task's command gets the database from the Host (the
variables dbread reads); otherwise the checkout's config names it.
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from asuna import carried, memory_tiers       # noqa: E402
from asuna.dbread import ENV                  # noqa: E402
from asuna.state import Store                 # noqa: E402


class ReadOnly:
    """What carried() needs of a store, with no way to write: the owners' collections of a store on her database
    (her heads through records.heads, her tiers through memory_tiers)."""

    def __init__(self, store, config):
        self.store, self.config = store, config
        self.collection = store.collection

    def audit(self, *args, **kwargs):
        raise RuntimeError('carried_check reads only')


def her_store(config):
    """A store on the database the Host named for this command, else the one the checkout's config names."""
    uri, name = os.environ.get(ENV['uri']), os.environ.get(ENV['database'])
    if not (uri and name):
        from asuna.config import load
        local = load(ROOT / 'config' / 'local.json')
        uri, name = local['mongo_uri'], local['database']
    return Store({**config, 'mongo_uri': uri, 'database': name, 'allowed_databases': [name]}, name)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', default=str(ROOT / 'config' / 'local.json'),
                        help='settings with home_groups (default: the checkout\'s config/local.json, wherever it runs)')
    parser.add_argument('--model', help="the persona package's persona-model.json (its render keys)")
    args = parser.parse_args()
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    path = Path(args.config)
    config = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if args.model:
        config['persona_model'] = json.loads(Path(args.model).read_text(encoding='utf-8'))
    held = her_store(config)
    try:
        return _checks(ReadOnly(held, config), path)
    finally:
        held.close()


def _checks(store, path):
    personas = memory_tiers.personas(store)
    if len(personas) != 1:
        print('FAIL persona: %d personas have tier rows, expected one' % len(personas))
        return 1
    failed = 0
    if not path.exists():
        # Without the settings the home groups are unknown and their pair is never measured: say so, and not green.
        print('SKIP home_group_pair %s' % json.dumps({'config': str(path), 'found': False}, ensure_ascii=False))
        failed += 1
    for name, passed, seen in carried.install_checks(store, personas[0]):
        failed += not passed
        print('%s %s %s' % ('PASS' if passed else 'FAIL', name, json.dumps(seen, ensure_ascii=False)))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
