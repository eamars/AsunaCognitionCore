"""The data child (data_children.py): `python -X utf8 -P -m asuna.data_worker <host pid>`. It runs the action brain's
history search and discussion digest on its own Store and Retrieval, so their work, however long, never holds the
worker's interpreter lock. It says it is ready, then answers one job at a time on stdout in media_children's frames;
stdout carries frames only.

- A job's payload (JSON): the tool, the task row, the tool's args, a copy of the worker's config, the database's name
  and the channel plugins the worker loaded. The child keeps one Store per database, its config replaced by each job's
  copy, and one Retrieval, built again when the database or the copy's embedding settings differ from those it was
  built with. Its query embeddings wait at most EMBED_SECONDS (EMBED_CONNECT_SECONDS to connect), as the memory
  indexer's do, so a slow endpoint falls back to lexical search within the job's deadline. The channel plugins are
  loaded once, and again when the list changes.
- The answer's payload (JSON, through the conversion the worker gives every tool result, `default=str`): the result,
  or a refusal of a known class (`refusal_class`) as its class and words, with the evidence records the job made;
  the worker records them. The child writes what the tools write (label rows, retrieval's audit), never evidence.
- An error of the child's own code is answered with `program` and the traceback's tail.
- It exits when its stdin closes or its Host's pid is gone, even in the middle of a job (media_worker._watch).

`answer` is one job; with no Host running (tools, offline checks, tests) data_children runs it in the calling process.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import traceback

from .media_children import read_frame, write_frame
from .media_worker import TRACE_CHARS, _watch

EMBED_SECONDS, EMBED_CONNECT_SECONDS = 10, 5


def refusal_class(exc):
    """The known refusal class an exception is, most specific first; None for any other."""
    from .state import Conflict, Denied
    for name, kind in (('Denied', Denied), ('Conflict', Conflict), ('PermissionError', PermissionError),
                       ('ValueError', ValueError)):
        if isinstance(exc, kind):
            return name
    return None


class Collected:
    """The evidence of one job, kept for the worker to record."""

    def __init__(self):
        self.records = []

    def record(self, kind, payload):
        self.records.append([kind, payload])
        return kind


class Services:
    """The child's Stores, Retrieval and channel plugins, kept from job to job."""

    def __init__(self):
        self.stores, self.retrieval, self.built_for, self.channels = {}, None, None, None
        self.evidence = Collected()

    def store(self, config, database):
        from .state import Store
        store = self.stores.get(database)
        if store is None:
            store = self.stores[database] = Store(config, database)
        store.config = config
        return store

    def retrieval_for(self, store, config):
        settings = [store.name, config.get('embedding')]
        if self.retrieval is None or self.built_for != settings:
            import httpx
            from .retrieval import Retrieval
            if self.retrieval is not None:
                self.retrieval.close()
            self.retrieval = Retrieval(store, self.evidence)
            self.retrieval.http.client.timeout = httpx.Timeout(EMBED_SECONDS, connect=EMBED_CONNECT_SECONDS)
            self.built_for = settings
        return self.retrieval

    def run(self, job):
        """The tool's result for one job (its refusals raised as the tool raises them)."""
        from . import channel_kinds
        from .discussion_digest import DIGEST_TOOL_NAME, DiscussionDigestService
        from .history_query import HISTORY_TOOL_NAME, HistoryQueryService
        if job['channels'] != self.channels:
            channel_kinds.load(job['channels'])
            self.channels = job['channels']
        store = self.store(job['config'], job['database'])
        retrieval = self.retrieval_for(store, job['config'])
        if job['tool'] == HISTORY_TOOL_NAME:
            return HistoryQueryService(store, retrieval).query_for_task(job['task'], job['args'])
        if job['tool'] == DIGEST_TOOL_NAME:
            return DiscussionDigestService(store, retrieval).digest_for_task(job['task'], job['args'])
        raise LookupError('not a data tool: %s' % str(job['tool'])[:60])

    def close(self):
        if self.retrieval is not None:
            self.retrieval.close()
        for store in self.stores.values():
            store.close()
        self.stores, self.retrieval = {}, None


def answer(services, data):
    """One job's answer frame (header, payload) from its payload; an error of this program raises."""
    job = json.loads(data.decode('utf-8'))
    try:
        try:
            body = {'result': services.run(job)}
        except Exception as exc:
            refused = refusal_class(exc)
            if refused is None:
                raise
            body = {'refused': refused, 'words': str(exc)}
        body['evidence'] = services.evidence.records
        return {'ok': True}, json.dumps(body, ensure_ascii=False, default=str).encode('utf-8')
    finally:
        services.evidence.records = []


def main(argv):
    out, inp = sys.stdout.buffer, sys.stdin.buffer
    sys.stdout = sys.stderr                       # a stray print never lands between frames
    try:
        host = int(argv[0])
        threading.Thread(target=_watch, args=(host,), name='host-watch', daemon=True).start()
        import importlib
        for name in ('state', 'retrieval', 'history_query', 'discussion_digest'):
            importlib.import_module('.' + name, __package__)       # before the ready frame: the first job imports none
        services = Services()
    except Exception as exc:                      # noqa: BLE001 the Host is told it did not start, with the class
        write_frame(out, {'ready': False, 'error': type(exc).__name__})
        return 1
    write_frame(out, {'ready': True, 'pid': os.getpid()})
    while True:
        try:
            _, data = read_frame(inp)
        except EOFError:
            return 0
        try:
            header, payload = answer(services, data)
        except Exception as exc:                  # noqa: BLE001 a fault of this program, with its class and trace
            header, payload = {'ok': False, 'program': True, 'error': '%s: %s' % (type(exc).__name__, str(exc)[:300]),
                               'trace': traceback.format_exc()[-TRACE_CHARS:]}, b''
        write_frame(out, header, payload)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
