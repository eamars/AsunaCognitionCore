"""The worker's request pipe from the Host (native_worker.serve): a child process never reads it, and one bad line
does not end the worker. 2026-10-06: a sandbox command's wsl inherited the worker's stdin, relayed part of a Host
request into Linux, and the cut remainder ended the read loop; the Host restarted the worker mid-task."""
import io
import json
import subprocess

from asuna import sandbox as sandbox_module
from asuna import sandbox_backend
from asuna.native_worker import serve
from asuna.sandbox import Sandbox


class Dispatcher:
    def __init__(self):
        self.handled = []

    def handle(self, request):
        self.handled.append(request)


def test_a_bad_line_is_recorded_and_skipped_and_the_worker_keeps_reading():
    records, dispatcher = [], Dispatcher()
    lines = io.StringIO('{"id": 1, "method": "status"}\n'
                        'd": 2, "method": "tool", "args": {"secret": "s3cret"}}\n'      # the cut remainder
                        '[1, 2]\n'
                        '{"id": 3, "method": "status"}\n')
    serve(lines, dispatcher, lambda kind, payload: records.append((kind, payload)))
    assert [request['id'] for request in dispatcher.handled] == [1, 3]
    assert [kind for kind, _ in records] == ['host.input_rejected', 'host.input_rejected', 'host.input_closed']
    assert 's3cret' not in json.dumps(records) and records[0][1]['chars'] > 0     # never the line itself


def test_a_sandbox_command_never_inherits_the_workers_stdin(tmp_path, monkeypatch):
    seen = {}

    def run(command, **options):
        seen.update(options)
        return subprocess.CompletedProcess(command, 0, json.dumps(
            {'exit_code': 0, 'stdout': '', 'stderr': '', 'output_limit': False, 'timed_out': False}), '')
    monkeypatch.setattr(sandbox_module, 'DATA', tmp_path)
    monkeypatch.setattr(sandbox_backend, 'require', lambda config: {'backend': 'wsl-bwrap', 'distro': 'Ubuntu'})
    monkeypatch.setattr(sandbox_module.subprocess, 'run', run)
    Sandbox(tmp_path / 'work' / 't1').run(['ls'])
    assert seen['stdin'] is subprocess.DEVNULL


def test_the_wsl_probe_never_inherits_the_workers_stdin(monkeypatch):
    seen = {}

    def run(command, **options):
        seen.update(options)
        return subprocess.CompletedProcess(command, 0, b'', b'')
    monkeypatch.setattr(sandbox_backend.subprocess, 'run', run)
    monkeypatch.setattr(sandbox_backend.os, 'name', 'nt')
    monkeypatch.setattr(sandbox_backend, '_PROBES', {})
    sandbox_backend._probe_wsl('Probe-Distro')
    assert seen['stdin'] is subprocess.DEVNULL
