"""Owner-granted, fixed-network integration lifecycle; contains no platform protocol."""
from collections import deque
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import shutil
import subprocess
import threading
import uuid

from .config import DATA, ROOT, redact_text
from .evidence import canonical, sha
from .state import Denied
from .queue import RuntimeLease
from .integration_import import IMPORT_TOOL, IMPORT_TOOL_NAME

INTEGRATION_TOOLS = [
    {'name': 'integration_test', 'description': 'Owner integration grant only. Run argv against a frozen copy of the adapter in the development candidate at /app, up to 60 seconds. Edit the adapter with the development tools (its channel project); RUNTIME_API.md describes the actual host contract. Only configured endpoints are reachable. Read /integration/config.json for explicit connection settings; writable /data is separate from enabled service data. Return real stdout/stderr and exit code. Never infer platform delivery from process startup.', 'parameters': {'argv': {'type': 'array', 'items': {'type': 'string'}, 'required': True}, 'timeout': {'type': 'integer'}}},
    {'name': 'integration_start', 'description': 'Enable argv as a managed service from a frozen /app copy of the published adapter (development_publish of its channel project). Keeps running after the tool returns and restores the then-published adapter on host restart. /data persists. Unpublished edits never run here. Only use when the owner task asks for persistent operation. Return process state, not a platform acknowledgement.', 'parameters': {'argv': {'type': 'array', 'items': {'type': 'string'}, 'required': True}}},
    {'name': 'integration_stop', 'description': 'Stop the enabled integration and disable restart; retain files and logs.', 'parameters': {}},
    {'name': 'integration_status', 'description': 'Read actual managed process state and bounded stdout/stderr. Running is not connection or delivery success.', 'parameters': {}},
]
# 集成产物导入跟着同一道 owner 闸门走：只读配置里的端点，只写本次任务工作区。
INTEGRATION_TOOLS.append(IMPORT_TOOL)



def owner_profile(config, scene, person):
    profile = config.get('integration', {})
    local = config.get('chat', {})
    if profile.get('enabled') is not True or (scene, person) != (local.get('scene_id'), local.get('person_id')):
        raise Denied('INTEGRATION_OWNER_REQUIRED')
    if (scene, person) != (profile.get('scene_id'), profile.get('person_id')):
        raise Denied('INTEGRATION_PROFILE_BINDING_MISMATCH')
    return profile


def event_granted(config, event):
    if event.get('integration_profile') != 'owner':
        return False
    from . import sandbox_backend
    if not sandbox_backend.available(config):
        return False                      # the managed process only runs in the sandbox (ADR-010 D5)
    owner_profile(config, event['scene_id'], event['person_id'])
    return True


def linux(path, config=None):
    """A host path as the integration sandbox sees it."""
    from . import sandbox_backend
    return sandbox_backend.path(sandbox_backend.require(config if config is not None else {}), path)


def valid_argv(argv):
    if (not isinstance(argv, list) or not argv or len(argv) > 40
            or any(not isinstance(arg, str) or '\x00' in arg for arg in argv)
            or sum(map(len, argv)) > 16000):
        raise ValueError('INVALID_INTEGRATION_ARGV')
    return argv


class ManagedProcess:
    def __init__(self, spec, directory, config):
        self.directory, self.config = directory, config
        self.logs = deque(maxlen=64)
        self.lock = threading.Lock()
        self.exit_code = None
        self.started = threading.Event()
        self.finished = threading.Event()
        self.stop_requested = False
        from . import sandbox_backend
        sandbox = sandbox_backend.require(config)
        self.process = subprocess.Popen(
            [*sandbox_backend.prefix(sandbox), 'python3', sandbox_backend.path(sandbox, Path(__file__).with_name('integration_worker.py'))],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', errors='replace')
        self.process.stdin.write(json.dumps(spec)+'\n'); self.process.stdin.flush()
        self.reader = threading.Thread(target=self._read, daemon=True); self.reader.start()
        self.errors = threading.Thread(target=self._errors, daemon=True); self.errors.start()

    def _log(self, stream, text):
        with self.lock:
            self.logs.append({'stream': stream, 'text': text})
            # Bounded rolling raw evidence; kept only in ignored runtime storage.
            try:
                (self.directory/'logs.json').write_text(json.dumps(list(self.logs), ensure_ascii=False), encoding='utf-8')
            except OSError as exc:
                self.logs.append({'stream': 'supervisor_error', 'text': 'LOG_PERSISTENCE_FAILED: '+str(exc)})

    def _errors(self):
        while text := self.process.stderr.read(4096):
            self._log('supervisor_stderr', text)

    def _read(self):
        try:
            for line in self.process.stdout:
                value = json.loads(line)
                if value['type'] == 'started':
                    self.started.set()
                elif value['type'] == 'log':
                    self._log(value['stream'], value['text'])
                elif value['type'] == 'exit':
                    self.exit_code = value['exit_code']
            code = self.process.wait()
            if self.exit_code is None:
                self.exit_code = code if code else -1
        except Exception as exc:
            self._log('supervisor_error', str(exc))
            self.exit_code = -1
            self.process.stdin.close()
        finally:
            self.finished.set()

    def snapshot(self):
        with self.lock:
            # Reassemble each stream before redaction: a credential may span
            # multiple pipe reads. Raw chunks remain only in private runtime logs.
            streams = {}
            for entry in self.logs:
                streams.setdefault(entry['stream'], []).append(entry['text'])
            value = {'state': ('STOPPED' if self.stop_requested else 'EXITED') if self.process.poll() is not None else
                     'RUNNING' if self.started.is_set() else 'STARTING',
                     'exit_code': self.exit_code,
                     'logs': [{'stream': name, 'text': redact_text(''.join(parts), self.config)} for name, parts in streams.items()],
                     'run_id': self.directory.name,
                     'network': 'private namespace; configured TCP relays only'}
        return value

    def stop(self):
        self.stop_requested = True
        try:
            self.process.stdin.close()  # Supervisor EOF kills the whole namespace.
        except OSError:
            pass
        try:
            self.process.wait(timeout=12)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('INTEGRATION_STOP_UNCONFIRMED') from exc
        self.reader.join(2)
        self.errors.join(2)
        return self.snapshot()


def validate_profile(config):
    """Shared startup/settings validation with no process, lease or filesystem writes."""
    local = config['chat']
    profile = owner_profile(config, local['scene_id'], local['person_id'])
    endpoints = profile.get('endpoints', [])
    if not isinstance(endpoints, list) or len(endpoints) > 8:
        raise ValueError('INTEGRATION_ENDPOINT_LIMIT')
    names, ports = set(), set()
    for e in endpoints:
        if not re.fullmatch(r'[a-z][a-z0-9_-]{0,30}', e['name']) or e['name'] in names:
            raise ValueError('INVALID_INTEGRATION_ENDPOINT_NAME')
        ip = ipaddress.ip_address(e['host'])
        if not (ip.is_private or ip.is_loopback) or ip.is_unspecified or ip.is_multicast:
            raise ValueError('INTEGRATION_ENDPOINT_MUST_BE_EXPLICIT_LOCAL_IP')
        for key in ('port', 'target_port'):
            if type(e[key]) is not int or not 1024 <= e[key] <= 65535:
                raise ValueError('INVALID_INTEGRATION_PORT')
        if e['port'] in ports:
            raise ValueError('DUPLICATE_INTEGRATION_PORT')
        names.add(e['name']); ports.add(e['port'])
    return profile


class IntegrationRunner:
    def __init__(self, config, *, root=None):
        self.config = config
        self.profile = validate_profile(config)
        self.endpoints = self.profile.get('endpoints', [])
        self.root = Path(root).resolve() if root else DATA/'integration/owner'
        if not self.root.is_relative_to(DATA/'integration'):
            raise Denied('INTEGRATION_ROOT_DENIED')
        selected = config.get('_integration_project')
        self.dev = Path(selected).resolve() if selected else self.root/'development'
        if selected and not self.dev.is_relative_to(DATA/'work/self-development'):
            raise Denied('INTEGRATION_PROJECT_NOT_AUTHORIZED')
        self.dev.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.active = None
        self.enabled_path = self.root/'enabled.json'
        self.fingerprint = sha(canonical(self.profile))
        self.restoration_error = None
        self.lease = RuntimeLease(self.root/'owner.lock')
        self.lease.__enter__()
        try:
            from .config import RESOURCES
            manual = RESOURCES/'RUNTIME_API.md' if (RESOURCES/'RUNTIME_API.md').is_file() else ROOT/'RUNTIME_API.md'
            shutil.copyfile(manual, self.dev/'RUNTIME_API.md')
        except BaseException:
            self.lease.__exit__(None, None, None); self.lease = None
            raise

    def restore(self):
        if not self.enabled_path.exists():
            return
        saved = json.loads(self.enabled_path.read_text(encoding='utf-8'))
        if not saved.get('enabled'):
            return
        applying = self.config.get('_native_apply_integrations', False)
        if saved.get('profile') != self.fingerprint and not applying:
            self.restoration_error = 'PROFILE_CHANGED_RESTART_REQUIRES_EXPLICIT_START'
            return
        try:
            # The published adapter as of this start, never unpublished files in the development tree.
            snapshot = self._snapshot(self.release())
            self.active = self._launch(snapshot, saved['argv'], 'service')
            if applying and self.active.snapshot()['state'] != 'RUNNING':
                raise RuntimeError('INTEGRATION_SETTINGS_START_FAILED')
            self._enable(saved['argv'], snapshot, previous=saved.get('snapshot'))
        except Exception as exc:
            self.restoration_error = str(exc)
            if applying:
                raise

    def release(self):
        """The published adapter: the only code a managed service runs (ADR-011 §5.2, one publish path)."""
        value = self.config.get('_native_integration_release')
        if not value or not Path(value).is_dir():
            raise Denied('INTEGRATION_RELEASE_UNAVAILABLE: publish the channel project first')
        return Path(value)

    def _enable(self, argv, snapshot, previous=None):
        saved = {'enabled': True, 'snapshot': snapshot.name, 'argv': argv, 'profile': self.fingerprint}
        temporary = self.enabled_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(saved), encoding='utf-8'); temporary.replace(self.enabled_path)
        self.restoration_error = None
        if previous and previous != snapshot.name and re.fullmatch(r'[0-9a-f]{32}', previous):
            shutil.rmtree(self.root/'snapshots'/previous, ignore_errors=True)

    def _snapshot(self, source_root=None):
        source_root = source_root or self.dev
        destination = self.root/'snapshots'/uuid.uuid4().hex
        destination.mkdir(parents=True)
        count = total = 0
        for source in source_root.rglob('*'):
            # The development namespace cannot mutate files during this locked copy.
            if source.is_symlink() or source.is_junction() or not source.resolve().is_relative_to(source_root.resolve()):
                raise Denied('INTEGRATION_SNAPSHOT_LINK_DENIED')
            target = destination/source.relative_to(source_root)
            if source.is_dir():
                target.mkdir()
            elif source.is_file():
                count += 1; total += source.stat().st_size
                if count > 2000 or total > 64*1024*1024:
                    raise ValueError('INTEGRATION_SNAPSHOT_LIMIT')
                shutil.copyfile(source, target)
            else:
                raise Denied('INTEGRATION_SNAPSHOT_SPECIAL_FILE_DENIED')
        return destination

    def _launch(self, snapshot, argv, mode):
        argv = valid_argv(argv)
        directory = self.root/'runs'/uuid.uuid4().hex; directory.mkdir(parents=True)
        data = self.root/'service-data' if mode == 'service' else directory/'data'
        data.mkdir(exist_ok=True)
        connection = {'endpoints': {e['name']: {'host': '127.0.0.1', 'port': e['port']} for e in self.endpoints},
                      'adapter': self.profile.get('adapter_config', {})}
        config_path = directory/'config.json'; config_path.write_text(json.dumps(connection), encoding='utf-8')
        spec = {'snapshot': linux(snapshot, self.config), 'data': linux(data, self.config), 'config': linux(config_path, self.config),
                'argv': argv, 'endpoints': self.endpoints}
        process = ManagedProcess(spec, directory, self.config)
        if not process.started.wait(8):
            process.stop()
            raise RuntimeError('INTEGRATION_LAUNCH_FAILED: '+json.dumps(process.snapshot()))
        process.finished.wait(.3)
        return process

    def call(self, tool, args):
        with self.lock:
            if self.lease is None: raise RuntimeError('INTEGRATION_RUNNER_CLOSED')
            if tool == 'integration_test':
                timeout = args.get('timeout', 30)
                if type(timeout) is not int or not 1 <= timeout <= 60:
                    raise ValueError('INTEGRATION_TEST_TIMEOUT_RANGE_1_60')
                process = self._launch(self._snapshot(), args['argv'], 'test')
                expired = not process.finished.wait(timeout)
                value = process.stop() if expired else process.snapshot()
                return {**value, 'timed_out': expired}
            if tool == 'integration_start':
                if self.active and not self.active.finished.is_set():
                    raise Denied('INTEGRATION_ALREADY_RUNNING_STOP_BEFORE_REPLACE')
                snapshot = self._snapshot(self.release())
                self.active = self._launch(snapshot, args['argv'], 'service')
                value = self.active.snapshot()
                if value['state'] == 'RUNNING':
                    previous = json.loads(self.enabled_path.read_text(encoding='utf-8')) if self.enabled_path.exists() else {}
                    self._enable(args['argv'], snapshot, previous=previous.get('snapshot'))
                return value
            if tool == 'integration_stop':
                self.enabled_path.write_text('{"enabled":false}', encoding='utf-8')
                return self.active.stop() if self.active else self.status()
            if tool == 'integration_status':
                return self.status()
            raise ValueError('UNKNOWN_INTEGRATION_TOOL')

    def import_artifact(self, args, *, workspace, protected=(), register=None):
        """Read one artifact from a configured endpoint; the platform writes it into the task workspace.

        ``register`` is the host-side image registration hook (see integration_import); the task's
        scope is bound by the caller, never by tool arguments.
        """
        from .integration_import import import_artifact
        with self.lock:
            if self.lease is None: raise RuntimeError('INTEGRATION_RUNNER_CLOSED')
            return import_artifact(args, endpoints=self.endpoints, workspace=workspace,
                                   fetch=self._fetch_artifact, protected=protected, register=register)

    def _fetch_artifact(self, endpoint, path, limit, timeout=20):
        """One managed-namespace GET: only that endpoint's configured relay is reachable, never a URL."""
        source = self.root/'fetch'/uuid.uuid4().hex
        source.mkdir(parents=True)
        process = snapshot = None
        try:
            shutil.copyfile(Path(__file__).with_name('integration_fetch.py'), source/'integration_fetch.py')
            request = json.dumps({'endpoint': endpoint['name'], 'path': path, 'limit': limit, 'timeout': timeout})
            snapshot = self._snapshot(source)
            process = self._launch(snapshot, ['python3', 'integration_fetch.py', request], 'test')
            expired = not process.finished.wait(timeout + 10)
            value = process.snapshot()
            if expired:
                try:
                    process.stop()
                except BaseException:
                    pass
            streams = {}
            for entry in value['logs']:
                streams.setdefault(entry['stream'], []).append(entry['text'])
            stdout = ''.join(streams.get('stdout', [])); stderr = ''.join(streams.get('stderr', []))
            report = None
            for line in reversed(stdout.splitlines()):
                try:
                    report = json.loads(line); break
                except ValueError:
                    continue
            if expired:
                return {'transport_error': 'IMPORT_FETCH_TIMEOUT: %ss' % timeout}
            if report is None:
                return {'transport_error': 'IMPORT_FETCH_REPORT_MISSING (exit %s): %s'
                        % (value.get('exit_code'), (stdout + stderr)[-300:])}
            body = b''
            if report.get('status') == 200 and not report.get('transport_error'):
                try:
                    body = (process.directory/'data'/'artifact.bin').read_bytes()
                except OSError as exc:
                    return {'transport_error': 'IMPORT_ARTIFACT_READ_FAILED: ' + str(exc)[:200]}
            if len(body) != report.get('bytes') or hashlib.sha256(body).hexdigest() != report.get('sha256'):
                return {'transport_error': 'IMPORT_ARTIFACT_VERIFY_FAILED: reported %s bytes, read %s'
                        % (report.get('bytes'), len(body))}
            return {'status': report.get('status'), 'declared': report.get('declared'), 'body': body,
                    'content_type': report.get('content_type'), 'location': report.get('location'),
                    'transport_error': report.get('transport_error')}
        except Exception as exc:
            return {'transport_error': (type(exc).__name__ + ': ' + str(exc))[:300]}
        finally:
            shutil.rmtree(source, ignore_errors=True)
            if snapshot is not None:
                shutil.rmtree(snapshot, ignore_errors=True)
            if process is not None:
                try:
                    (process.directory/'data'/'artifact.bin').unlink(missing_ok=True)
                except OSError:
                    pass

    def status(self):
        value = self.active.snapshot() if self.active else {'state': 'STOPPED', 'logs': []}
        if self.restoration_error:
            value['error'] = self.restoration_error
        return value

    def close(self):
        with self.lock:
            if self.lease is None: return
            if self.active:
                self.active.stop()  # Keep enabled.json so an explicit start survives host restart.
            self.lease.__exit__(None, None, None); self.lease = None
