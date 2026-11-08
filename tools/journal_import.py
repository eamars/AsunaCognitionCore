"""ADR-117 L4's one-off: one of her working documents becomes a running record, one row per section.

Usage: python tools/journal_import.py <doc> [--config config/local.json] --dry-run   count only
       python tools/journal_import.py <doc> [--config config/local.json]             import it

A one-time import, run with her Host stopped: --dry-run first (it reads only, the Host may be up), then the import.
The import refuses while a Host for this database runs (JOURNAL_IMPORT_HOST_UP): when the lock file the Host holds
for its whole life on this machine (config.database_lock) cannot be taken, and while any database lease
(host_lease.holder, its own included) has not expired. A lease left by a Host that was just stopped expires within
host_lease.LEASE_SECONDS, so the import waits for it, up to WAIT_SECONDS, saying so; a lease renewed meanwhile is a
Host that runs. It holds that lock until it ends, so no Host starts meanwhile. It calls the running records' own import (documents.DocumentStore._journal_import): every section of the
document's current revision becomes a row, with the times its revisions give (first written, last changed); its tier
rows are made at hand with those times; the document's head goes last and its revisions stay as they were. Until the
head goes the document reads as before, so an import stopped halfway leaves it whole; run again, it makes no row twice
and finishes. A write of the document during the import keeps the head and the run exits 1; run again, it brings the
rows to the head's revision. Only a working document is imported. Prints counts only, never a heading or a text. The
persona is the config's `chat.persona`.
"""
import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from asuna import documents, host_lease          # noqa: E402
from asuna.config import database_lock, load     # noqa: E402
from asuna.queue import RuntimeLease             # noqa: E402
from asuna.records import heads                  # noqa: E402
from asuna.state import Store                    # noqa: E402

HOST_HERE = ('JOURNAL_IMPORT_HOST_UP: her Host for this database is running on this machine (it holds %s); '
             'stop it, then import')
HOST_RENEWED = ('JOURNAL_IMPORT_HOST_UP: the database lease (%s on %s) was renewed while this waited: a Host is '
                'running; stop it, then import')
HOST_LEASED = ('JOURNAL_IMPORT_HOST_UP: the database lease (%s on %s) had not expired after %d s of waiting (until %s '
               'UTC); stop that Host, then import')
WAIT_SECONDS, POLL_SECONDS = 120, 5


def counts(store, persona, slug):
    """What the document holds now: its head's sections, the rows already made, its revisions."""
    docs = documents.DocumentStore(store, persona)
    head = heads.head(store, docs.key(slug), ['revision_id'])
    content = (heads.revision(store, head['revision_id'], ['content']) or {}).get('content') or {} if head else {}
    sections = content.get('sections') or []
    made = {row['_id'] for row in documents.entries(store, persona, slug).rows(fields=['_id'])}
    return {'head': bool(head), 'kind': content.get('kind') if head else None, 'sections': len(sections),
            'rows': len(made),
            'rows_to_make': sum(1 for s in sections if docs._journal_entry_id(slug, s['sid']) not in made),
            'by_visibility': dict(Counter(s.get('visibility') or 'none' for s in sections)),
            'revisions': heads.history(store, docs.key(slug)).count()}


def host_stopped(config):
    """(the lock her Host holds while it runs, now held here, None) when no Host for this database runs; else
    (None, why). Any lease that has not expired, this deployment's own too, is waited for: a Host stopped a moment
    ago leaves one that expires within LEASE_SECONDS; one renewed meanwhile is a running Host."""
    path = database_lock(config)
    lock = RuntimeLease(path, timeout=2)
    try:
        lock.__enter__()
    except TimeoutError:
        return None, HOST_HERE % path.name
    first, until = host_lease.holder(config), time.monotonic() + WAIT_SECONDS
    held = first
    while held:
        if held['expires_at'] != first['expires_at']:
            why = HOST_RENEWED % (held['persona'], held['host'])
            break
        if held['expires_at'] is not None and held['expires_at'] < datetime.now(timezone.utc).replace(tzinfo=None):
            return lock, None
        if time.monotonic() >= until:
            why = HOST_LEASED % (held['persona'], held['host'], WAIT_SECONDS, held['expires_at'])
            break
        print('waiting for the database lease to expire (until %s UTC; up to %d s)' % (held['expires_at'], WAIT_SECONDS),
              file=sys.stderr, flush=True)
        time.sleep(POLL_SECONDS)
        held = host_lease.holder(config)
    else:
        return lock, None
    lock.__exit__(None, None, None)
    return None, why


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('doc', help='the document (its slug)')
    parser.add_argument('--config', default='config/local.json')
    parser.add_argument('--dry-run', action='store_true', help='count only: what the import would make')
    args = parser.parse_args()
    config = load(args.config)
    persona = (config.get('chat') or {}).get('persona')
    if not persona:
        sys.exit('JOURNAL_IMPORT_NO_PERSONA: the config names no chat.persona')
    lock, why = (None, None) if args.dry_run else host_stopped(config)
    if why:
        print(json.dumps({'dry_run': False, 'refused': why}, ensure_ascii=False))
        sys.exit(1)
    store = Store(config)
    try:
        before = counts(store, persona, args.doc)
        out = {'doc_found': before['head'] or bool(before['rows']), 'dry_run': args.dry_run, 'before': before}
        if before['head'] and before['kind'] != 'working':
            out['refused'] = 'JOURNAL_IMPORT_NOT_WORKING: only a working document becomes rows'
        elif not before['head']:
            out['refused'] = None if before['rows'] else 'JOURNAL_IMPORT_NOT_FOUND'     # rows already, or nothing
        elif not args.dry_run:
            if not documents.DocumentStore(store, persona)._journal_import(args.doc):
                # Written during the import: the head is kept, and a run again brings the rows to its revision.
                out.update(after=counts(store, persona, args.doc),
                           refused='JOURNAL_IMPORT_HEAD_CHANGED: the document was written during the import; its '
                                   'head is kept; run it again')
            else:
                after = counts(store, persona, args.doc)
                out.update(after=after, rows_equal_sections=after['rows'] == before['sections'],
                           revisions_kept=after['revisions'] == before['revisions'])
        print(json.dumps(out, ensure_ascii=False))
        if out.get('refused') or (out.get('after') and not (out['rows_equal_sections'] and out['revisions_kept']
                                                             and not out['after']['head'])):
            sys.exit(1)
    finally:
        store.close()
        if lock:
            lock.__exit__(None, None, None)


if __name__ == '__main__':
    main()
