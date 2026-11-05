"""ADR-117 L2b's one-off: the three stored fields a turn's blocks now read, filled on the rows written before them.

Usage: python tools/adr117_l2b_backfill.py <config> --dry-run        counts only; reads no tool record
       python tools/adr117_l2b_backfill.py <config> [--limit N]     fill (`--limit`: at most N tasks, a timed sample)

- a document's head: `kind`, from its current revision (documents.DocumentStore._commit writes it now);
- a task with a text report: `result.chars` and `result.pages`, with the function its finish uses (tasks.sized);
- a group: `name`, from its newest line that carries one (ingress writes it now).

A row that already has its field is left as it is, but a group whose stored name is not its newest named line's is
named again (the old worker's ingress does not keep it current between the two runs). Tasks are filled one at a time.
Run it in bulk while the old worker runs (a finished task never changes), then once more between its stop and the new
worker's start for what changed in between; a second run with nothing new changes nothing. Prints counts only, never
a text. The tool and its owner functions (`records.heads.backfill_kind`, `records.tasks.lacking_size` and
`backfill_size`, `records.scenes.backfill_name`) exist only for this landing and are deleted after its install.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from asuna.records import heads as head_records          # noqa: E402
from asuna.records import messages as message_records    # noqa: E402
from asuna.records import scenes as scene_records        # noqa: E402
from asuna.records import tasks as task_records          # noqa: E402
from asuna.tasks import FIRST_PAGE_CHARS, sized          # noqa: E402


def heads(store, dry_run):
    rows = head_records.with_prefix(store, 'doc:').rows(fields=['revision_id', 'kind'])
    missing = [row for row in rows if 'kind' not in row]
    counts = {'documents': len(rows), 'missing_kind': len(missing), 'revision_missing': 0, 'filled': 0}
    for row in [] if dry_run else missing:
        revision = head_records.revision(store, row['revision_id'], ['content.kind'])
        if not revision:
            counts['revision_missing'] += 1
            continue
        head_records.backfill_kind(store, row['_id'], (revision.get('content') or {}).get('kind'))
        counts['filled'] += 1
    return counts


def tasks(store, dry_run, limit):
    counts = {'lacking': 0, 'text_reports': 0, 'missing_chars': 0, 'missing_pages': 0, 'long': 0,
              'result_not_object': 0, 'filled': 0, 'left': 0}
    due = []
    for row in task_records.lacking_size(store).each(fields=['result']):
        counts['lacking'] += 1
        result = row.get('result')
        if result is not None and not isinstance(result, dict):
            counts['result_not_object'] += 1
            continue
        text = (result or {}).get('text')
        if not isinstance(text, str):
            continue
        counts['text_reports'] += 1
        counts['missing_chars'] += 'chars' not in result
        counts['missing_pages'] += 'pages' not in result
        counts['long'] += len(text) > FIRST_PAGE_CHARS
        due.append(row['_id'])
    for task_id in [] if dry_run else due[:limit]:
        row = task_records.get(store, task_id, ['result.text', 'intent_revision'])
        size = sized(store, row, row.get('result')) if row else None
        if isinstance(size, dict) and 'chars' in size:
            task_records.backfill_size(store, task_id, size['chars'], size['pages'])
            counts['filled'] += 1
    counts['left'] = len(due) - counts['filled']
    return counts


def scenes(store, dry_run):
    groups = scene_records.of_kind(store, 'group', fields=['_id', 'name'])
    counts = {'groups': len(groups), 'without_named_line': 0, 'missing_name': 0, 'differs': 0, 'filled': 0}
    for group in groups:
        line = message_records.lines(store, group['_id'], group_name=True, by='received_at').first(
            newest_first=True, fields=['event.raw.group_name'])
        if not line:
            counts['without_named_line'] += 1
            continue
        name = ((line.get('event') or {}).get('raw') or {}).get('group_name')
        if 'name' not in group:
            counts['missing_name'] += 1
        elif group['name'] != name:
            counts['differs'] += 1
        else:
            continue
        if not dry_run:
            scene_records.backfill_name(store, group['_id'], name)
            counts['filled'] += 1
    return counts


def run(store, *, dry_run=False, limit=None):
    started = time.monotonic()
    report = {'dry_run': dry_run, 'limit': limit, 'heads': heads(store, dry_run),
              'tasks': tasks(store, dry_run, limit), 'scenes': scenes(store, dry_run)}
    report['seconds'] = round(time.monotonic() - started, 2)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('config', help='the deployment config (config/local.json)')
    parser.add_argument('--dry-run', action='store_true', help='count only; no write, no tool record read')
    parser.add_argument('--limit', type=int, default=None, help='fill at most this many tasks')
    args = parser.parse_args()
    from asuna.config import load
    from asuna.state import Store
    store = Store(load(args.config))
    try:
        print(json.dumps(run(store, dry_run=args.dry_run, limit=args.limit)))
    finally:
        store.close()


if __name__ == '__main__':
    main()
