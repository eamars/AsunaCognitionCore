"""Replaceable RuntimeHost behind the existing local Web bridge.

The UI process owns the Web server and bridge. A fresh Python child owns each
RuntimeHost so a normal development publish can activate new Python source.
"""
from __future__ import annotations

import multiprocessing
from pathlib import Path
from queue import Queue, Empty
import threading
import uuid


class RuntimeUnavailable(RuntimeError):
    pass


def _run_host(connection, config, database, evidence_root):
    from .chat import local_settings
    from .evidence import Evidence
    from .host import RuntimeHost
    from .ui import Workbench
    from .ui_stream import UiStreamHub

    send_lock = threading.Lock()
    streams = UiStreamHub()
    def send(message):
        with send_lock:
            connection.send(message)

    try:
        evidence = Evidence(Path(evidence_root))
        evidence.record('host.start.started', {})
        with RuntimeHost(config, evidence, database, stream_observer=streams) as host:
            workbench = Workbench(host.app.store, local_settings(config), host.controller)
            workbench.host = host
            workbench.stream_hub = streams
            host.controller.emit = workbench.emit
            relay_stop = threading.Event()
            def relay():
                version = 0
                while not relay_stop.is_set():
                    current, events = streams.events_since(version)
                    for event in events:
                        send({'kind': 'stream', 'event': event})
                    version = current
                    streams.wait(version, .5)
            relay_thread = threading.Thread(target=relay, name='asuna-ui-stream-relay', daemon=True)
            send({'kind': 'ready'})
            relay_thread.start()
            try:
                while not host.shutdown_requested.is_set():
                    if not connection.poll(.2):
                        continue
                    message = connection.recv()
                    if message.get('kind') == 'stop':
                        host.shutdown_requested.set()
                        break
                    if message.get('kind') != 'request':
                        continue
                    request_id = message['id']
                    method = message['method']
                    try:
                        if method not in ('snapshot', 'command', 'trace_detail',
                                          'inspector_detail', 'provider_diagnostic'):
                            raise ValueError('UNKNOWN_UI_METHOD')
                        value = getattr(workbench, method)(*message['args'])
                        send({'kind': 'response', 'id': request_id, 'value': value})
                    except Exception as exc:
                        send({'kind': 'response', 'id': request_id,
                              'error': type(exc).__name__, 'message': str(exc)})
            finally:
                send({'kind': 'restarting' if host.restart_requested.is_set() else 'stopped'})
                relay_stop.set()
                relay_thread.join(timeout=2)
                if workbench.model_thread:
                    workbench.model_thread.join()
    except EOFError:
        pass
    except BaseException as exc:
        try:
            send({'kind': 'fatal', 'message': str(exc)})
        except (OSError, EOFError):
            pass
        raise
    finally:
        connection.close()


class RuntimeLink:
    def __init__(self, config, database, evidence_root, stream_hub):
        self.config, self.database = config, database
        self.evidence_root = Path(evidence_root)
        self.stream_hub = stream_hub
        self.ready = threading.Event()
        self.stopping = threading.Event()
        self.fatal = threading.Event()
        self.send_lock = threading.Lock()
        self.pending_lock = threading.Lock()
        self.pending = {}
        self.connection = None
        self.thread = threading.Thread(target=self._supervise, name='asuna-runtime-link', daemon=True)

    def start(self):
        self.thread.start()

    def _fail_pending(self):
        with self.pending_lock:
            pending, self.pending = self.pending, {}
        for reply in pending.values():
            reply.put({'error': 'RuntimeUnavailable', 'message': '宿主正在重启'})

    def _accept_stream(self, event):
        kind = event['kind']
        if kind == 'reset':
            self.stream_hub.reset()
        elif kind == 'start':
            self.stream_hub('start', event['id'], **{key: value for key, value in event.items()
                if key not in ('kind', 'id', 'sequence', 'createdAt', 'status')})
        elif kind == 'delta':
            self.stream_hub('text', event['id'], field=event['field'], text=event['text'])
        elif kind == 'end':
            self.stream_hub('end', event['id'], status=event['status'])

    def _supervise(self):
        context = multiprocessing.get_context('spawn')
        attempt = 0
        while not self.stopping.is_set():
            attempt += 1
            parent, child = context.Pipe()
            process = context.Process(target=_run_host, args=(child, self.config, self.database,
                str(self.evidence_root / f'runtime-{attempt:03d}')),
                name='asuna-runtime-host', daemon=True)
            self.connection = parent
            try:
                process.start()
            except BaseException:
                self.ready.clear()
                self.fatal.set()
                self._fail_pending()
                parent.close()
                child.close()
                return
            child.close()
            restarting = False
            try:
                while True:
                    try:
                        if not process.is_alive() and not parent.poll():
                            break
                    except (EOFError, OSError):
                        break
                    if self.stopping.is_set():
                        with self.send_lock:
                            try:
                                parent.send({'kind': 'stop'})
                            except (EOFError, OSError):
                                pass
                        break
                    try:
                        if not parent.poll(.2):
                            continue
                    except (EOFError, OSError):
                        break
                    try:
                        message = parent.recv()
                    except (EOFError, OSError):
                        break
                    kind = message.get('kind')
                    if kind == 'ready':
                        self.ready.set()
                        self.stream_hub.reset()
                    elif kind == 'stream':
                        self._accept_stream(message['event'])
                    elif kind == 'response':
                        with self.pending_lock:
                            reply = self.pending.pop(message['id'], None)
                        if reply:
                            reply.put(message)
                    elif kind in ('restarting', 'stopped', 'fatal'):
                        self.ready.clear()
                        self.stream_hub.reset()
                        self._fail_pending()
                        restarting = kind == 'restarting'
                        if kind == 'fatal':
                            self.fatal.set()
            finally:
                self.ready.clear()
                self.stream_hub.reset()
                self._fail_pending()
                parent.close()
                self.connection = None
                process.join()
            if not restarting and not self.stopping.is_set():
                self.fatal.set()
                return

    def call(self, method, *args):
        if not self.ready.is_set():
            raise RuntimeUnavailable('宿主正在重启')
        request_id = uuid.uuid4().hex
        reply = Queue(maxsize=1)
        with self.pending_lock:
            self.pending[request_id] = reply
        try:
            with self.send_lock:
                if not self.ready.is_set() or self.connection is None:
                    raise RuntimeUnavailable('宿主正在重启')
                self.connection.send({'kind': 'request', 'id': request_id,
                                      'method': method, 'args': args})
            try:
                result = reply.get(timeout=24)
            except Empty:
                raise RuntimeUnavailable('宿主读取超时') from None
            if 'error' in result:
                kind = result['error']
                error = result['message']
                if kind == 'Denied':
                    from .state import Denied
                    raise Denied(error)
                if kind == 'PermissionError':
                    raise PermissionError(error)
                if kind in ('ValueError', 'TypeError'):
                    raise ValueError(error)
                raise RuntimeUnavailable(error)
            return result['value']
        finally:
            with self.pending_lock:
                self.pending.pop(request_id, None)

    def stop(self):
        self.stopping.set()
        self.ready.clear()
        self.stream_hub.reset()
        self.thread.join(timeout=15)
# ADR-007 lifecycle acceptance publish marker.
