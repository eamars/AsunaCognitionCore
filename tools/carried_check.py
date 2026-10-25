"""ADR-096's install checks, read only: what the turns carry is what carried() says, in numbers only.

Usage: python tools/carried_check.py [--config config/local.json] [--model <persona-model.json>]

Checks (carried.install_checks): the latest turn's system_ref section list equals carried() for its pair; each pair's
refusal gives carried()'s number for the pair it names (the write is only measured, never made); a write gets its
room line; every section whose inject and tier differ is said. Prints one line per check, PASS or FAIL, with the
numbers it saw; no section text, no headings. A home task's command gets the database from the Host
(dbread.Reader.from_host); otherwise the checkout's config names it.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from asuna import carried                     # noqa: E402
from asuna.dbread import Reader               # noqa: E402


class ReadOnly:
    """What carried() needs of a store, with no way to write."""

    def __init__(self, db, config):
        self.db, self.config = db, config

    def head(self, entity, scope):
        head = self.db.state_heads.find_one({'_id': entity + '|' + scope})
        return (head, self.db.state_revisions.find_one({'_id': head['revision_id']})) if head else None

    def audit(self, *args, **kwargs):
        raise RuntimeError('carried_check reads only')


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
    reader = Reader.from_host()
    store = ReadOnly(reader.db, config)
    personas = reader.db.memory_tiers.distinct('persona', {'row': 'item'})
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
