"""ADR-120 landing 2's one-off: a picture or file she sent before the landing becomes the conversation's own it was sent
into, as a message written since makes it (coordinator.queue_reply).

Usage: python tools/adr120_shared_scopes_backfill.py <config> --dry-run     counts only; writes nothing
       python tools/adr120_shared_scopes_backfill.py <config>               share

For every line of hers that carries a stored picture (`attachment`, not a sticker) or file (`file`), the artifact gains
the line's conversation in `shared_scopes` (own_files.share: one set-add; a row already of that conversation, a
sticker, or one already shared there is left as it is). It plans from the database each time, so a run stopped anywhere
is finished by running it again, and a second run changes nothing. Prints counts only, never an id or a name. Run it
between her Host's stop and the new worker's start. It exists only for this landing and is deleted after its install.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from asuna import own_files                              # noqa: E402
from asuna.records import artifacts as artifact_records  # noqa: E402
from asuna.records import messages as message_records    # noqa: E402


def run(store, *, dry_run=False):
    started = time.monotonic()
    counts = {'lines': 0, 'stickers': 0, 'pairs': 0, 'artifact_missing': 0, 'own_already': 0, 'shared_already': 0,
              'to_share': 0, 'shared': 0}
    pairs = set()
    for line in message_records.carrying(store).each(fields=['scope_key', 'sticker', 'attachment', 'file']):
        counts['lines'] += 1
        if isinstance(line.get('sticker'), dict):
            counts['stickers'] += 1
            continue
        carried = (line.get('attachment') or line.get('file') or {}).get('artifact_id')
        if isinstance(carried, str) and isinstance(line.get('scope_key'), str):
            pairs.add((carried, line['scope_key']))
    counts['pairs'] = len(pairs)
    for artifact_id, scope in sorted(pairs):
        row = artifact_records.get(store, artifact_id, ['scope_key', 'shared_scopes'])
        if not row:
            counts['artifact_missing'] += 1
        elif row.get('scope_key') in (scope, own_files.STICKERS):
            counts['own_already'] += 1
        elif scope in (row.get('shared_scopes') or ()):
            counts['shared_already'] += 1
        else:
            counts['to_share'] += 1
            if not dry_run:
                counts['shared'] += bool(own_files.share(store, artifact_id, scope))
    return {'dry_run': dry_run, **counts, 'seconds': round(time.monotonic() - started, 2)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('config', help='the deployment config (config/local.json)')
    parser.add_argument('--dry-run', action='store_true', help='count only; write nothing')
    args = parser.parse_args()
    from asuna.config import load
    from asuna.state import Store
    store = Store(load(args.config))
    try:
        report = run(store, dry_run=args.dry_run)
        print(json.dumps(report))
    finally:
        store.close()
    # Its job: every pair it found to share was shared (a dry run shares nothing by design).
    sys.exit(0 if args.dry_run or report['shared'] == report['to_share'] else 1)


if __name__ == '__main__':
    main()
