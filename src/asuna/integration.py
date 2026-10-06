"""Owner-granted, fixed-network integration lifecycle; contains no platform protocol."""
from collections import deque
import copy
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
    {'name': 'integration_test', 'description': 'Owner integration grant only. Run argv against a frozen copy of the adapter in the development candidate, up to 60 seconds. Edit the adapter with the development tools (its channel project); RUNTIME_API.md describes the actual host contract. The run reaches the configured endpoints directly with the real settings, so a test run can really act on a platform: test with reads, and leave sending to the outbox and the published adapter. In argv, /app is the frozen adapter, /data its writable folder (separate from enabled service data) and /integration/config.json its settings (also in $ASUNA_INTEGRATION_CONFIG and $ASUNA_INTEGRATION_DATA); python3 is Python 3.12 on this machine. Return real stdout/stderr and exit code. Never infer platform delivery from process startup.', 'parameters': {'argv': {'type': 'array', 'items': {'type': 'string'}, 'required': True}, 'timeout': {'type': 'integer'}}},
    {'name': 'integration_start', 'description': 'Enable argv as a managed service from a frozen copy (/app) of the published adapter (development_publish of its channel project). Keeps running after the tool returns and restores the then-published adapter on host restart. /data persists. Unpublished edits never run here. Only use when the owner task asks for persistent operation. Return process state, not a platform acknowledgement.', 'parameters': {'argv': {'type': 'array', 'items': {'type': 'string'}, 'required': True}}},
    {'name': 'integration_stop', 'description': 'Stop the enabled integration and disable restart; retain files and logs.', 'parameters': {}},
    {'name': 'integration_status', 'description': 'Read actual managed process state and bounded stdout/stderr. Running is not connection or delivery success.', 'parameters': {}},
]
# 集成产物导入跟着同一道 owner 闸门走：只读配置里的端点，只写本次任务工作区。
INTEGRATION_TOOLS.append(IMPORT_TOOL)



def owner_dm(config, scene, person):
    """The owner's own direct chat on a platform: a dm route to the owner, and the owner speaking (canonical
    persons by configuration; a name never decides it)."""
    from . import scene_links
    owner = (config.get('chat') or {}).get('person_id')
    mapping = scene_links.canonical_map(config)
    if not owner or not person or mapping.get(person, person) != owner:
        return False
    for channel in (config.get('channels') or {}).values():
        for route in (channel.get('routes') or {}).values() if isinstance(channel, dict) else ():
            if (isinstance(route, dict) and route.get('scene_id') == scene and (route.get('target') or {}).get('type') == 'dm'
                    and route.get('person_id') and mapping.get(route['person_id'], route['person_id']) == owner):
                return True
    return False


def owner_profile(config, scene, person):
    """The owner's workspace grant: the owner in the local chat, or in their own platform DM (owner 2026-10-06).
    The profile itself stays bound to the local chat."""
    profile = config.get('integration', {})
    local = config.get('chat', {})
    here = (scene, person) == (local.get('scene_id'), local.get('person_id')) or owner_dm(config, scene, person)
    if profile.get('enabled') is not True or not here:
        raise Denied('INTEGRATION_OWNER_REQUIRED')
    if (local.get('scene_id'), local.get('person_id')) != (profile.get('scene_id'), profile.get('person_id')):
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


def direct(adapter, endpoints):
    """The run's view of its endpoints: each alias at the device's own address. The adapter settings name an
    endpoint by its local port (`port`, where relays once served it); those references become the device's address."""
    table = {e['name']: {'host': e['host'], 'port': e['target_port'], **({'tls': True} if e.get('tls') else {})}
             for e in endpoints}
    ports = {e['port']: e for e in endpoints}

    def address(match):
        e = ports.get(int(match.group(2)))
        return match.group(0) if e is None else match.group(1) + e['host'] + ':' + str(e['target_port'])

    def rewrite(value):
        if isinstance(value, dict):
            return {key: rewrite(item) for key, item in value.items()}
        if isinstance(value, list):
            return [rewrite(item) for item in value]
        if isinstance(value, str):
            return re.sub(r'(^|//|@)(?:127\.0\.0\.1|localhost):(\d+)', address, value)
        return value
    return rewrite(adapter), table


def valid_argv(argv):
    if (not isinstance(argv, list) or not argv or len(argv) > 40
            or any(not isinstance(arg, str) or '\x00' in arg for arg in argv)
            or sum(map(len, argv)) > 16000):
        raise ValueError('INVALID_INTEGRATION_ARGV')
    return argv


def native_argv(argv, snapshot, data, config_path):
    """An adapter argv as this machine runs it: python3 is the worker's Python; /app, /data and
    /integration/config.json (how the adapter and its manual name them) are the run's own folders and file."""
    import sys
    names = {'/integration/config.json': Path(config_path), '/app': Path(snapshot), '/data': Path(data)}
    out = [sys.executable if argv[0] in ('python3', 'python', 'python3.exe', 'python.exe') else argv[0]]
    for arg in argv[1:]:
        for name, path in names.items():
            if arg == name or arg.startswith(name + '/'):
                arg = path.as_posix() + arg[len(name):]
                break
        out.append(arg)
    return out


class ManagedProcess:
    """One adapter (or trusted one-shot) process under the Host's sandbox (sandbox_backend.py): it may write only its
    data folder, and reaches its endpoints directly (owner 2026-10-06: no network rule). Its output is kept as logs."""
    def __init__(self, spec, directory, config):
        from . import sandbox_backend
        self.directory, self.config = directory, config
        self.logs = deque(maxlen=64)
        self.lock = threading.Lock()
        self.exit_code = None
        self.started = threading.Event()
        self.finished = threading.Event()
        self.stop_requested = False
        command = sandbox_backend.confine(config, spec['argv'], spec['data'])
        self.process = subprocess.Popen(command, cwd=spec['snapshot'], stdin=subprocess.DEVNULL,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        env=sandbox_backend.environment({'ASUNA_INTEGRATION_CONFIG': spec['config'],
                                                                         'ASUNA_INTEGRATION_DATA': spec['data'],
                                                                         'PYTHONUNBUFFERED': '1'}))
        self.started.set()
        self.reader = threading.Thread(target=self._stream, args=(self.process.stdout, 'stdout'), daemon=True)
        self.errors = threading.Thread(target=self._stream, args=(self.process.stderr, 'stderr'), daemon=True)
        self.reader.start(); self.errors.start()
        threading.Thread(target=self._wait, daemon=True).start()

    def _log(self, stream, text):
        with self.lock:
            self.logs.append({'stream': stream, 'text': text})
            # Bounded rolling raw evidence; kept only in ignored runtime storage.
            try:
                (self.directory/'logs.json').write_text(json.dumps(list(self.logs), ensure_ascii=False), encoding='utf-8')
            except OSError as exc:
                self.logs.append({'stream': 'supervisor_error', 'text': 'LOG_PERSISTENCE_FAILED: '+str(exc)})

    def _stream(self, pipe, name):
        while chunk := pipe.read1(4096):
            self._log(name, chunk.decode('utf-8', 'replace'))

    def _wait(self):
        code = self.process.wait()
        self.reader.join(5); self.errors.join(5)
        self.exit_code = code
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
                     'network': 'direct to the configured endpoints'}
        return value

    def stop(self):
        self.stop_requested = True
        try:
            self.process.kill()   # the Host sandbox's runner holds the command in a kill-on-close job
        except OSError:
            pass
        try:
            self.process.wait(timeout=12)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('INTEGRATION_STOP_UNCONFIRMED') from exc
        self.finished.wait(5)
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
        # The relay binds `port` inside the namespace (unprivileged); the device's own port is whatever it serves on (SSH 22, HTTPS 443).
        for key, low in (('port', 1024), ('target_port', 1)):
            if type(e[key]) is not int or not low <= e[key] <= 65535:
                raise ValueError('INVALID_INTEGRATION_PORT')
        if e['port'] in ports:
            raise ValueError('DUPLICATE_INTEGRATION_PORT')
        if any(type(e.get(key, False)) is not bool for key in ('read_only', 'tls')):
            raise ValueError('INVALID_INTEGRATION_ENDPOINT_OPTION')
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
        self.active, self.active_snapshot = None, None
        self.busy = set()                 # snapshots of trusted one-shot runs still in flight
        self.enabled_path = self.root/'enabled.json'
        self.fingerprint = sha(canonical(self.profile))
        self.restoration_error = None
        self.lease = RuntimeLease(self.root/'owner.lock')
        self.lease.__enter__()
        self._sweep_snapshots()
        try:
            from .config import RESOURCES
            manual = RESOURCES/'RUNTIME_API.md' if (RESOURCES/'RUNTIME_API.md').is_file() else ROOT/'RUNTIME_API.md'
            shutil.copyfile(manual, self.dev/'RUNTIME_API.md')
        except BaseException:
            self.lease.__exit__(None, None, None); self.lease = None
            raise

    def _sweep_snapshots(self):
        """Remove finished copies: keep only the one the service runs from and the one enabled for restart."""
        keep = {self.active_snapshot, *self.busy}
        try:
            keep.add(json.loads(self.enabled_path.read_text(encoding='utf-8')).get('snapshot'))
        except (OSError, ValueError):
            pass
        for entry in (self.root/'snapshots').glob('*'):
            if entry.name not in keep and re.fullmatch(r'[0-9a-f]{32}', entry.name):
                shutil.rmtree(entry, ignore_errors=True)

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
            self.active, self.active_snapshot = self._launch(snapshot, saved['argv'], 'service'), snapshot.name
            if applying and self.active.snapshot()['state'] != 'RUNNING':
                raise RuntimeError('INTEGRATION_SETTINGS_START_FAILED')
            self._enable(saved['argv'], snapshot, previous=saved.get('snapshot'))
        except Exception as exc:
            self.restoration_error = str(exc)
            if applying:
                raise
        finally:
            self._sweep_snapshots()

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

    def _launch(self, snapshot, argv, mode, only=None):
        argv = valid_argv(argv)
        directory = self.root/'runs'/uuid.uuid4().hex; directory.mkdir(parents=True)
        data = self.root/'service-data' if mode == 'service' else directory/'data'
        data.mkdir(exist_ok=True)
        adapter, endpoints = copy.deepcopy(self.profile.get('adapter_config', {})), self.endpoints
        if only is not None:
            # A trusted one-shot run that needs one service gets only that endpoint, and no adapter settings.
            adapter, endpoints = {}, [e for e in endpoints if e['name'] == only]
        adapter, table = direct(adapter, endpoints)
        config_path = directory/'config.json'
        config_path.write_text(json.dumps({'endpoints': table, 'adapter': adapter}), encoding='utf-8')
        spec = {'snapshot': str(snapshot), 'data': str(data), 'config': str(config_path),
                'argv': native_argv(argv, snapshot, data, config_path)}
        process = ManagedProcess(spec, directory, self.config)
        process.finished.wait(.3)
        return process

    def call(self, tool, args):
        with self.lock:
            if self.lease is None: raise RuntimeError('INTEGRATION_RUNNER_CLOSED')
            if tool == 'integration_test':
                timeout = args.get('timeout', 30)
                if type(timeout) is not int or not 1 <= timeout <= 60:
                    raise ValueError('INTEGRATION_TEST_TIMEOUT_RANGE_1_60')
                try:
                    process = self._launch(self._snapshot(), args['argv'], 'test')
                    expired = not process.finished.wait(timeout)
                    value = process.stop() if expired else process.snapshot()
                    return {**value, 'timed_out': expired}
                finally:
                    self._sweep_snapshots()
            if tool == 'integration_start':
                if self.active and not self.active.finished.is_set():
                    raise Denied('INTEGRATION_ALREADY_RUNNING_STOP_BEFORE_REPLACE')
                snapshot = self._snapshot(self.release())
                self.active, self.active_snapshot = self._launch(snapshot, args['argv'], 'service'), snapshot.name
                value = self.active.snapshot()
                if value['state'] == 'RUNNING':
                    previous = json.loads(self.enabled_path.read_text(encoding='utf-8')) if self.enabled_path.exists() else {}
                    self._enable(args['argv'], snapshot, previous=previous.get('snapshot'))
                self._sweep_snapshots()
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
        request = {'endpoint': endpoint['name'], 'path': path, 'limit': limit, 'timeout': timeout}
        report, body, failure = self._trusted_run('integration_fetch.py', request, timeout + 10, 'IMPORT_FETCH')
        if failure:
            return {'transport_error': failure}
        if report.get('status') != 200 or report.get('transport_error'):
            body = b''
        if len(body) != report.get('bytes') or hashlib.sha256(body).hexdigest() != report.get('sha256'):
            return {'transport_error': 'IMPORT_ARTIFACT_VERIFY_FAILED: reported %s bytes, read %s'
                    % (report.get('bytes'), len(body))}
        return {'status': report.get('status'), 'declared': report.get('declared'), 'body': body,
                'content_type': report.get('content_type'), 'location': report.get('location'),
                'transport_error': report.get('transport_error')}

    def generate_image(self, request):
        """One picture from the image endpoint (image_generation); only that relay is reachable.

        The runner lock covers the launch only: a generation can take minutes, and the integration tools,
        status and stop must not wait behind it.
        """
        from .image_generation import IMAGE_ENDPOINT
        if not any(e['name'] == IMAGE_ENDPOINT for e in self.endpoints):
            return {'transport_error': 'IMAGE_ENDPOINT_NOT_CONFIGURED'}
        report, body, failure = self._trusted_run('integration_image.py', {**request, 'endpoint': IMAGE_ENDPOINT},
                                                  request['timeout'] + 30, 'IMAGE', only=IMAGE_ENDPOINT)
        if failure:
            return {'transport_error': failure}
        if report.get('generated'):
            if len(body) != report.get('bytes') or hashlib.sha256(body).hexdigest() != report.get('sha256'):
                return {'transport_error': 'IMAGE_VERIFY_FAILED: reported %s bytes, read %s'
                        % (report.get('bytes'), len(body))}
        return {'report': report, 'body': body if report.get('generated') else b''}

    def _trusted_run(self, script, request, wait, label, only=None):
        """Run one of the platform's own scripts in a test-mode namespace: (report, artifact bytes, failure)."""
        source = self.root/'fetch'/uuid.uuid4().hex
        process = snapshot = None
        try:
            with self.lock:
                if self.lease is None: raise RuntimeError('INTEGRATION_RUNNER_CLOSED')
                source.mkdir(parents=True)
                shutil.copyfile(Path(__file__).with_name(script), source/script)
                snapshot = self._snapshot(source)
                self.busy.add(snapshot.name)
                process = self._launch(snapshot, ['python3', script, json.dumps(request)], 'test', only=only)
            expired = not process.finished.wait(wait)
            value = process.snapshot()
            if expired:
                try:
                    process.stop()
                except BaseException:
                    pass
                return None, b'', '%s_TIMEOUT: %ss' % (label, wait)
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
            if not isinstance(report, dict):
                return None, b'', '%s_REPORT_MISSING (exit %s): %s' % (label, value.get('exit_code'), (stdout + stderr)[-300:])
            artifact = process.directory/'data'/'artifact.bin'
            try:
                body = artifact.read_bytes() if artifact.exists() else b''
            except OSError as exc:
                return None, b'', '%s_ARTIFACT_READ_FAILED: %s' % (label, str(exc)[:200])
            return report, body, None
        except Exception as exc:
            return None, b'', (type(exc).__name__ + ': ' + str(exc))[:300]
        finally:
            shutil.rmtree(source, ignore_errors=True)
            if snapshot is not None:
                self.busy.discard(snapshot.name)
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
