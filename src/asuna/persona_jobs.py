"""Persona jobs: run-to-completion programs a persona package declares (ADR-009 PERSONA_CONTRACT §7).

Transport is stdio JSONL — the pipe is the token, there is no network endpoint:
  host → job   {"kind":"start","run_id","persona","dry_run","args","sources":{id: mount},"out"}
  job  → host  {"id":n,"method":"…","args":{…}}      host → job {"id":n,"value":…} | {"id":n,"error":{code,detail}}
  job  → host  {"kind":"report","status":"ok|red|error","summary","items"}
  exit code    0 = ok, 1 = red, 2 = error
The sandbox launcher reuses the existing WSL bubblewrap environment with no
network, read-only job code and source roots, and a size-capped /out. Without
WSL/bubblewrap the feature reports "unavailable"; it never runs unsandboxed.
The direct launcher exists only for protocol tests.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import uuid
import zipfile

from .config import DATA
from .persona_data import DataError, PersonaDataAPI, persona_sources
from . import visibility

OUT_LIMIT = 64 * 1024 * 1024


def _wsl_path(path: Path) -> str:
    path = Path(path).resolve()
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


class SandboxLauncher:
    """WSL bubblewrap: --unshare-all (no network), ro job code and sources, rw /out only."""
    name = 'wsl-bubblewrap'

    @staticmethod
    def available():
        try:
            probe = subprocess.run(['wsl', '-d', 'Ubuntu', '--exec', 'sh', '-c', 'command -v bwrap && command -v python3'],
                                   capture_output=True, timeout=30)
            return probe.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def spawn(self, entry: Path, sources: dict, out: Path):
        mounts = []
        for root_id, path in sources.items():
            mounts += ['--ro-bind', _wsl_path(path), '/src/' + root_id]
        command = ['wsl', '-d', 'Ubuntu', '--exec', 'bwrap', '--unshare-all', '--die-with-parent', '--new-session',
                   '--ro-bind', '/usr', '/usr', '--symlink', 'usr/bin', '/bin', '--symlink', 'usr/lib', '/lib',
                   '--symlink', 'usr/lib64', '/lib64', '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
                   '--ro-bind', _wsl_path(entry.parent), '/job', *mounts, '--bind', _wsl_path(out), '/out',
                   '--chdir', '/job', '--clearenv', '--setenv', 'PATH', '/usr/bin:/bin', '--setenv', 'PYTHONIOENCODING', 'utf-8',
                   '/usr/bin/prlimit', '--as=1073741824', '--fsize=67108864', '--nofile=256', '--',   # personal-scan: ok (1 GiB, 64 MiB byte limits)
                   'python3', '-u', '/job/' + entry.name]
        mapped = {root_id: '/src/' + root_id for root_id in sources}
        return subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE), mapped, '/out'


class DirectLauncher:
    """Protocol tests only: no isolation at all, real host paths."""
    name = 'direct-unsandboxed'

    @staticmethod
    def available():
        return True

    def spawn(self, entry: Path, sources: dict, out: Path):
        import os
        env = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'}   # the protocol is UTF-8 JSONL
        process = subprocess.Popen([sys.executable, '-u', str(entry)], cwd=str(entry.parent), stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        return process, {root_id: str(path) for root_id, path in sources.items()}, str(out)


class JobRunner:
    def __init__(self, store, persona, *, retrieval=None, launcher=None):
        self.store, self.persona, self.retrieval = store, persona, retrieval
        self.launcher = launcher or SandboxLauncher()

    def job(self, job_id):
        for job in (self.store.config.get('persona_contribution') or {}).get('jobs') or []:
            if job['id'] == job_id:
                return job
        raise DataError('JOB_UNKNOWN', job_id)

    def run(self, job_id, *, dry_run=True, args=None):
        """Returns status, exit code, counts and the report artifact id — never an excerpt."""
        job = self.job(job_id)
        if not self.launcher.available():
            return {'status': 'unavailable', 'job': job_id, 'reason': 'sandbox (WSL + bubblewrap) not available'}
        configured = persona_sources(self.store.config, self.persona)
        missing = [root for root in job['sources'] if root not in configured]
        if missing:
            raise DataError('SOURCE_NOT_AUTHORIZED', ','.join(missing))
        run_id = 'job-' + uuid.uuid4().hex[:16]
        out = (DATA / 'persona-jobs' / run_id / 'out').resolve()
        out.mkdir(parents=True)
        api = PersonaDataAPI(self.store, self.persona, run_id=run_id, job_id=job_id, grants=job['grants'],
                             sources={root: configured[root]['state'] for root in job['sources']}, retrieval=self.retrieval)
        process, mounts, out_mount = self.launcher.spawn(Path(job['entry']), {root: Path(configured[root]['path'])
                                                                              for root in job['sources']}, out)
        self.store.audit('persona-job:' + run_id, 'persona_job.started', {'job': job_id, 'dry_run': dry_run,
                         'launcher': self.launcher.name}, visibility.owner_private_scope(self.persona))
        counts, report, deadline = {'requests': 0, 'errors': 0}, None, time.monotonic() + int(job['timeout_s'])
        killed = threading.Event()

        def watchdog():
            while process.poll() is None:
                if time.monotonic() > deadline or _size(out) >= OUT_LIMIT:
                    killed.set()
                    process.kill()
                    return
                time.sleep(0.2)

        threading.Thread(target=watchdog, daemon=True).start()
        stderr = []
        threading.Thread(target=lambda: stderr.append(process.stderr.read()), daemon=True).start()
        start = {'kind': 'start', 'run_id': run_id, 'persona': self.persona, 'dry_run': bool(dry_run),
                 'args': args or {}, 'sources': mounts, 'out': out_mount}
        try:
            process.stdin.write((json.dumps(start, ensure_ascii=False) + '\n').encode())
            process.stdin.flush()
            for raw in process.stdout:
                try:
                    message = json.loads(raw)
                except ValueError:
                    counts['errors'] += 1
                    continue
                if message.get('kind') == 'report':
                    report = message
                    continue
                counts['requests'] += 1
                request_args = dict(message.get('args') or {})
                if dry_run and message.get('method') in ('documents.upsert', 'documents.append', 'affect.import',
                                                         'memory.upsert', 'policy.set', 'artifacts.snapshot'):
                    request_args['dry_run'] = True       # a dry run never writes, whatever the job asks
                try:
                    reply = {'id': message.get('id'), 'value': api.dispatch(message.get('method'), request_args)}
                except Exception as exc:
                    counts['errors'] += 1
                    reply = {'id': message.get('id'), 'error': {'code': getattr(exc, 'code', type(exc).__name__),
                                                                'detail': str(exc)[:300]}}
                process.stdin.write((json.dumps(reply, ensure_ascii=False, default=str) + '\n').encode())
                process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        code = process.wait()
        if killed.is_set():
            status = 'error'
        else:
            status = {0: 'ok', 1: 'red'}.get(code, 'error')
        if report and not api.reports:
            api.dispatch('report.put', {'status': report.get('status', status), 'summary': report.get('summary', ''),
                                        'items': report.get('items') or []})
        if killed.is_set() or _size(out) >= OUT_LIMIT:   # the sandbox caps writes at the limit itself
            status = 'error'
            api.report_put({'status': 'error', 'summary': 'timeout or /out over limit', 'items': []})
        out_artifact = self._pack(out, run_id) if not killed.is_set() and any(out.iterdir()) else None
        shutil.rmtree(out.parent, ignore_errors=True)
        result = {'run_id': run_id, 'job': job_id, 'status': status, 'exit_code': code, 'dry_run': bool(dry_run),
                  'counts': counts, 'report_artifact_ids': [r['artifact_id'] for r in api.reports],
                  'out_artifact_id': out_artifact, 'launcher': self.launcher.name}
        self.store.audit('persona-job:' + run_id, 'persona_job.finished', {**result, 'stderr_tail': (b''.join(stderr)[-2000:]).decode('utf-8', 'replace')},
                         visibility.owner_private_scope(self.persona))
        return result

    def _pack(self, out, run_id):
        from .blobs import BlobStore
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(out.rglob('*')):
                if path.is_file():
                    archive.write(path, path.relative_to(out).as_posix())
        return BlobStore(self.store).put(buffer.getvalue(), visibility.owner_private_scope(self.persona),
                                         'persona_job_out', source_ids=[run_id])['artifact_id']


TOOL_FIELDS = ('run_id', 'job', 'status', 'exit_code', 'dry_run', 'counts', 'report_artifact_ids', 'reason')


def tool_result(result: dict) -> dict:
    """What the action brain may see of a run (§7.4): status, counts and artifact ids, never an excerpt."""
    return {k: result.get(k) for k in TOOL_FIELDS}


def _size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob('*') if p.is_file()) if path.exists() else 0
