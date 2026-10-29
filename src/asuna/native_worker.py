"""Private business worker for the DSH Host plugin; no model or Web runtime.

The existing Coordinator prepares a stage and consumes its real result on its
queue thread. A NativeLane yields that request across stdio, releasing the Host
hook to run the native loop. It never calls an agent or waits inside its loop.
"""
from __future__ import annotations

import argparse
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import ExitStack, nullcontext
import json
from pathlib import Path
from queue import Queue, Empty
import re
import shutil
import sys
import threading
import time
import uuid

from . import clock
from . import sandbox_backend, channel_kinds, errands
from .application import Application
from .host import RuntimeHost
from .config import DATA, ROOT, database_lock, redact_text
from .evidence import Evidence, sha
from .lanes import LaneResult
from .grants import workspace_grant
from .people import People
from .skills import skill_directories
from .state import Denied, now, Conflict
from .queue import RuntimeLease
from .records import scenes as scene_records
from .records import messages as message_records
from .records import episodes as episode_records
from .records import receipts as receipt_records
from .records import sessions as session_records
from .records import plans as plan_records
from .records import artifacts as artifact_records
from .records import people as people_records
from .records import tasks as task_records


KEPT_HOST_REPORTS = 5     # this start's evidence and the starts just before it
KEPT_HOST_RECORDS = 3000  # within one start, the newest records only: a busy hour writes about a thousand
EFFECTS_WAIT_SECONDS = 1.0  # a task stage's wait for the effects lock this long or longer is recorded


def prune_host_reports():
    """Each worker start writes its evidence to a new reports folder; only the newest few are kept."""
    starts = sorted((DATA / 'reports').glob('native-host-*'), key=lambda path: path.stat().st_mtime, reverse=True)
    for old in starts[KEPT_HOST_REPORTS:]:
        shutil.rmtree(old, ignore_errors=True)


def read_persona(config, persona):
    """A persona package's model as the worker takes it, validated (jsonschema); raises PersonaModelError or
    PERSONA_STATE_ID_MISMATCH and changes nothing. A publication is read this way before it is selected (persona.check)."""
    from .persona_model import load as load_model, neutral
    if config['chat']['persona'] != persona['id']:
        raise ValueError('PERSONA_STATE_ID_MISMATCH')
    return (load_model(persona['model'], persona['id']) if persona.get('model')
            else neutral(persona['id'], persona['display_name']))


def take_persona(config, persona):
    """The persona package as the worker reads it: at its start and after each persona publication, so what a
    publication reports ACTIVE is what her turns use. The model is validated before anything changes."""
    model = read_persona(config, persona)
    config['chat'] = {**config['chat'], 'display_name': persona['display_name']}
    config['character_id'] = persona['character_id']
    config['persona_contribution'] = persona
    config['persona_model'] = model


def gate_session_id(binding, operation):
    """A fresh gate session for each question, its repairs included: the material is complete every time, so the
    gate keeps no history and never compacts (attend.py)."""
    base = re.sub(r':fix-\d+$', '', operation)
    return 'asuna-attend-' + sha((binding + ':' + base).encode())[:32]


class ContextOverflow(RuntimeError):
    """A stage of her conversation was refused because the session no longer fits the model's window, after DSH's own
    overflow compaction (ADR-028). `carry` is what the plugin read from the session: its last summary."""
    def __init__(self, message, carry, session_id):
        super().__init__(message)
        self.carry, self.session_id = carry, session_id


class ModeChanged(RuntimeError):
    """Her conversation's session was opened with the other source of her thoughts (ADR-099): DSH keeps a session's
    first tools and system text at the head of every request, so it is carried to a new session instead."""
    def __init__(self, session_id):
        super().__init__('THOUGHTS_MODE_CHANGED')
        self.session_id = session_id


# What a turn says when it runs again in the session that replaced one opened with the other source of her thoughts.
MODE_CARRY_NOTE = '设置改了，这个对话换到新会话，这一回合在新会话里重新开始'


class NativeLane:
    composes_context = True     # the plugin composes a role notice from structured context
    def __init__(self, worker, config, store, evidence, lane='character', *args):
        self.worker, self.store, self.lane = worker, store, lane
        # The relevance gate (attend) is her own judgment: it uses the character route, at a low effort (index.js).
        route = {'character': 'character', 'appraiser': 'appraiser', 'attend': 'character'}.get(lane, 'action')
        self.model = {**config['character' if lane in ('character', 'attend') else 'executor'],
                      **config.get('_native_routes', {}).get(route, {})}
        self.lock = threading.RLock()

    def child_title(self, task, role_id, ep):
        """A child session's title: content only (her task's title, or the conversation it serves), since DSH
        shows a stored title as it is and UI words must follow the viewer's language (ADR-011 §2.8)."""
        if self.lane == 'executor' and task:
            return ' '.join(str(task.get('title') or task.get('goal') or task['_id']).split())[:48]
        if self.lane in ('summary', 'attend'):
            role = session_records.get(self.store, role_id, fields=['native_title']) or {}
            return role.get('native_title') or ep['scene_id']
        return None

    def generate(self, binding, operation, phase, text, system, tools=None, handler=None, **kwargs):
        """One stage of a native turn. A character turn exposes `tools`: each call she makes reaches
        `handler` on this thread (role_tools.py) while the turn waits for its result."""
        try:
            try:
                return self._generate(binding, operation, phase, text, system, tools, handler, **kwargs)
            except ModeChanged as exc:
                successor = self.worker.carry_session(exc.session_id, {'summary': '', 'why': 'thoughts'})
                if not successor:
                    # Not a main conversation (an errand's copy, a reflection), or a carry not yet delivered: it goes
                    # on in its session, which records the mode it now runs in.
                    return self._generate(binding, operation, phase, text, system, tools, handler, mode_kept=True,
                                          **kwargs)
                from .coordinator import SessionCarried
                raise SessionCarried(str(exc), successor, MODE_CARRY_NOTE) from exc
        except ContextOverflow as exc:
            successor = self.worker.carry_session(exc.session_id, exc.carry) if self.lane == 'character' else None
            if not successor:
                raise
            from .coordinator import SessionCarried
            raise SessionCarried(str(exc), successor) from exc

    def _generate(self, binding, operation, phase, text, system, tools, handler, mode_kept=False, **kwargs):
        with self.lock:
            prior = receipt_records.lane_get(self.store, operation)
            if prior and prior.get('native_host'):
                # A completed stage is final: its receipt answers a repeat without reopening the stage.
                return LaneResult(**{k: v for k, v in prior['result'].items() if k in LaneResult.__dataclass_fields__})
            if not self.worker.navigation_ready.wait(self.store.config['workflow_timeout_seconds']):
                raise RuntimeError('NATIVE_NAVIGATION_NOT_READY')
            task = None
            # A repair (answers.py) is the same stage asked again in the same session: parse its base operation.
            base = re.sub(r':fix-\d+$', '', operation)
            if self.lane == 'summary':
                scene = scene_records.by_scope(self.store, kwargs['scope_key'], epoch=kwargs['policy_epoch'])
                if not scene:
                    raise Denied('SUMMARY_SCENE_STALE')
                person = scene['members'][0]
                scene_records.authorize(self.store, scene['_id'], person)
                ep = {'_id': base, 'scene_id': scene['_id'], 'person_id': person,
                      'scope_key': scene['scope_key'], 'policy_epoch': scene['policy_epoch'],
                      'character_context': scene.get('character_context'),
                      'persona': self.store.config['chat']['persona']}
                ep['native_session_id'] = self.worker.resolve_role_session(ep)
            elif self.lane == 'executor' or phase == 'CONSULT':
                task_id = base.split(':execute:', 1)[0].split(':consult:', 1)[0]
                task = task_records.get(self.store, task_id)
                if not task:
                    raise Denied('STALE_TASK_FENCE')
                if self.lane == 'executor':
                    if base.split(':execute:', 1)[1].split(':', 1)[0] != str(task['intent_revision']):
                        raise Denied('STALE_TASK_FENCE')
                else:
                    artifact = artifact_records.get(self.store, base.split(':consult:',1)[1], task=task_id,
                                                    revision=task['intent_revision'])
                    if not artifact:
                        raise Denied('STALE_TASK_FENCE')
                # The turn the task works for: on an errand, the home turn that sent it (errands.home_turn).
                from . import errands
                ep = errands.home_turn(self.store, episode_records.get(self.store, task['episode_id']))
                if ep and self.lane == 'executor' and task.get('native_session_id'):
                    # The action brain works for its task: the task's place, requester and conversation, which for
                    # one begun on an errand are home's, not the errand turn's (coordinator.delegate).
                    home = session_records.get(self.store, task['native_session_id'], fields=['character_context'])
                    ep = {**ep, 'scene_id': task['scene_id'], 'person_id': task['requester_id'],
                          'scope_key': task['scope_key'], 'policy_epoch': task['policy_epoch'],
                          'native_session_id': task['native_session_id'],
                          'character_context': (home or {}).get('character_context', ep.get('character_context'))}
            else:
                ep = episode_records.get(self.store, base.split(':', 1)[0])
            if not ep:
                raise ValueError('NATIVE_EPISODE_BINDING_REQUIRED')
            role_id = ep.get('native_session_id')
            if not role_id:
                raise ValueError('NATIVE_ROLE_SESSION_REQUIRED')
            role_id = self.worker.continued_session(role_id)
            context = ep.get('character_context')
            if role_id != ep['native_session_id']:
                # A conversation that continued in another session (ADR-028) keeps that session's own context.
                context = (session_records.get(self.store, role_id) or {}).get('character_context', context)
            parent_id = role_id
            if self.lane == 'executor':
                native_id = self.worker.action_session_id(binding, role_id, ep, task)
                # A task begun before its conversation continued elsewhere keeps the parent it was started under.
                parent_id = (session_records.get(self.store, native_id) or {}).get('parent_session_id') or role_id
            elif self.lane == 'summary':
                native_id = 'asuna-summary-' + sha((binding + ':' + base).encode())[:32]
            elif self.lane == 'appraiser':
                native_id = 'asuna-appraiser-' + ep['persona']
            elif self.lane == 'attend':
                native_id = gate_session_id(binding, operation)
            else:
                native_id = role_id
            if self.lane == 'appraiser':
                # One tool-free appraiser session per persona, owned by the local operator scene;
                # each request carries only that episode's own visible material.
                local = self.store.config['chat']
                owner = scene_records.authorize(self.store, local['scene_id'], local['person_id'])
                grant, ep = local, {**ep, 'scene_id': owner['_id'], 'person_id': local['person_id'],
                                    'scope_key': owner['scope_key'], 'policy_epoch': owner['policy_epoch']}
            else:
                grant = workspace_grant(self.store.config, ep['scene_id'], ep['person_id'])
            platform = channel_kinds.of(ep['scene_id'])
            cwd = (self.worker.channel_workspace(platform) if self.lane in ('character', 'attend') and platform
                   else str(Path(grant['workspace']).resolve()))
            mode = None
            if self.lane == 'character':
                from .role_tools import thinking_mode
                mode = 'thinking' if thinking_mode(self.store.config) else 'tool'
                opened = session_records.get(self.store, native_id, fields=['thoughts'])
                # A session from before ADR-099 was opened in tool mode.
                if opened and (opened.get('thoughts') or 'tool') != mode and not mode_kept:
                    raise ModeChanged(native_id)
            record = self.worker.bind_session(native_id, {
                **({'thoughts': mode} if mode else {}),
                'lane': self.lane, 'scene_id': ep['scene_id'], 'person_id': ep['person_id'],
                'scope_key': ep['scope_key'], 'policy_epoch': ep['policy_epoch'],
                'character_context': context,
                'persona': ep['persona'], 'cwd': cwd,
                'role_session_id': parent_id, 'task_id': task['_id'] if task else None,
                'parent_session_id': parent_id if self.lane != 'character' else None,
                'broker_session': 's-' + sha(binding.encode())[:40],
                **({'execution_binding': binding} if self.lane == 'executor' else {}),
                'allowed_capabilities': task['allowed_capabilities'] if self.lane == 'executor' else [],
                **({'capability_refusals': self.worker.refusals_for(task)} if self.lane == 'executor' else {}),
                'system_sha256': sha(system.encode()),
                'skill_directories': [str(path) for path in skill_directories(self.store.config, ep['scene_id'], ep['person_id'],
                                                                              self.store)],
            })
            carried = record.get('carry') if self.lane == 'character' and 'context' in kwargs else None
            if carried and not carried.get('delivered'):
                # The first notice in a session that replaced one that no longer fit (ADR-028), once.
                from .context_budget import carried_block
                kwargs = {**kwargs, 'context': {'carried_from_program': carried_block(carried.get('summary'),
                                                                                      carried.get('why')),
                                                **kwargs['context']}}
            else:
                carried = None
            scene_kind = (scene_records.get(self.store, ep['scene_id'], fields=['kind']) or {}).get('kind')
            request = {'kind': 'stage', 'token': operation, 'session_id': native_id, 'scene_kind': scene_kind,
                       'lane': self.lane, 'phase': phase, 'text': text, 'system': system,
                       'episode_id': ep['_id'], 'binding': record, 'title': self.child_title(task, role_id, ep),
                       **({'tools': list(tools)} if tools is not None else {}),
                       **({'trigger': kwargs['trigger']} if kwargs.get('trigger') else {}),
                       **({'context': kwargs['context'], 'tail': kwargs['tail'], 'ceiling': kwargs.get('ceiling')}
                          if 'context' in kwargs else {}),
                       **({'pictures': kwargs['pictures']} if kwargs.get('pictures') else {})}
            if self.lane == 'executor' and task:
                request['task'] = {'_id': task['_id'], 'thread': task.get('thread') or task['_id'],
                                   'title': task.get('title') or task.get('goal'),
                                   'parent_session_id': record['parent_session_id'],
                                   # the route this job runs on (ADR-075): 高's only while it has not fallen
                                   'tier': 'high' if (task.get('tier') or {}).get('ran') == '高' else 'low'}
            if self.lane == 'character':
                source = message_records.get(self.store, 'in-' + ep['_id'])
                if source and source.get('event', {}).get('channel'):
                    request['channel_input'] = self.worker.channel_input(source)
            future = Future()
            future.asuna_lane = self.lane
            future.asuna_task = task
            future.asuna_calls = Queue()
            future.asuna_handler = handler
            future.add_done_callback(lambda _: future.asuna_calls.put(None))
            future.asuna_session_id = native_id
            future.asuna_binding = record
            future.asuna_broker_session = record['broker_session'] + ':' + sha(operation.encode())[:16]
            self.worker.register_stage(operation, future, task)
            try:
                self.worker.emit(request)
                try:
                    value = self.wait(future, self.store.config['workflow_timeout_seconds'])
                except TimeoutError:
                    # Stop the native run this stage waited for: nothing reads its result any more, its tools
                    # are already refused, and a continuation of the same task would meet it still running.
                    self.worker.emit({'kind': 'task_fenced', 'token': operation, 'session_id': native_id,
                                      'reason': 'STAGE_TIMEOUT'})
                    raise
                result = LaneResult(**value)
                # The receipt keeps the full result (the stage's single durable copy on the worker side);
                # the audit records only its hash (state.commit over 16 KB, phase.output).
                receipt_records.save_lane(self.store, {
                    '_id': operation, 'native_host': True, 'native_session_id': native_id,
                    'scope_key': ep['scope_key'], 'result': vars(result)}, stream=operation)
                if carried:
                    row = session_records.get(self.store, native_id)
                    session_records.save(self.store, {**row, 'carry': {**row['carry'], 'delivered': operation}},
                                   expected=row['revision'], stream='native-binding:' + native_id)
                return result
            finally:
                with self.worker.pending_lock:
                    self.worker.pending.pop(operation, None)
                if self.lane == 'executor':
                    self.worker.app.broker.bindings.pop(future.asuna_broker_session, None)

    def turn_done(self, ep):
        """Her turn has no further stage (coordinator._turn): the plugin ends the native turn."""
        if self.lane == 'character' and ep.get('native_session_id'):
            session_id = self.worker.continued_session(ep['native_session_id'])
            # An errand's copy and a reflection's session are retired once their turn ends (ADR-066, ADR-072):
            # archived, out of the session list.
            done = self.worker.side_session(session_id)
            self.worker.emit({'kind': 'turn_done', 'session_id': session_id, 'episode_id': ep['_id'],
                              **({'retire': True} if done else {})})
            if done:
                row = session_records.get(self.store, session_id)
                session_records.save(self.store, {**row, 'retired': True}, expected=row['revision'],
                               stream='native-binding:' + session_id)

    @staticmethod
    def wait(future, timeout):
        """The stage's result; her tool calls in the meantime run here, one at a time, in call order."""
        deadline = time.monotonic() + timeout
        while not future.done():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('NATIVE_STAGE_TIMEOUT')
            try:
                item = future.asuna_calls.get(timeout=min(remaining, 1))
            except Empty:
                continue
            if item is None:
                continue
            call, reply = item
            try:
                if not future.asuna_handler:
                    raise Denied('ROLE_TOOLS_NOT_EXPOSED')
                # ADR-099: the thinking her first call of a stage came with, recorded as her thought before it runs.
                extra = {'thinking': call['thinking']} if 'thinking' in call else {}
                reply.set_result(future.asuna_handler(call['call_id'], call['tool'], call.get('args') or {}, **extra))
            except BaseException as exc:
                reply.set_exception(exc)
        while True:                      # calls that arrived as the turn ended get a plain answer
            try:
                item = future.asuna_calls.get_nowait()
            except Empty:
                break
            if item is not None:
                item[1].set_exception(Denied('NATIVE_TURN_ENDED'))
        return future.result()

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class BusinessWorker:
    def __init__(self):
        self.stack = ExitStack()
        self.pending = {}
        self.pending_lock = threading.Lock()
        self.output_lock = threading.Lock()
        self.emit_timing = threading.local()      # this thread's last emit: the output lock's wait, the write (seconds)
        self.navigation_ready = threading.Event()
        self.app = None
        self.controller = None
        self.host = None
        self.host_pending = {}
        self.folded_stop = False        # a lease left behind was folded into the plugin's open span (ADR-101)
        self.stopping = threading.Event()
        self.carry_lock = threading.Lock()

    def register_stage(self, operation, future, task):
        """Admit a stage: the Host is not reconfiguring, its task (if any) is still valid, and the operation runs
        once. A task's stage waits for the effects lock first and takes the ingress fence only for the check, so
        no inbound line waits behind a tool call that holds the effects lock. A wait of EFFECTS_WAIT_SECONDS or
        more is recorded (`host.effects_lock_wait`) once the stage is past it; a failure to record is not the
        stage's."""
        effects = self.app.service.lock if task else nullcontext()
        holder = getattr(effects, 'holder', None)
        asked, waited = time.monotonic(), None
        try:
            with effects:
                waited = time.monotonic() - asked
                with self.controller.ingress_lock, self.pending_lock:
                    if self.controller.reconfiguring:
                        raise RuntimeError('HOST_RECONFIGURING')
                    if task:
                        self.app.service.valid(task)
                    if operation in self.pending:
                        raise RuntimeError('NATIVE_OPERATION_ALREADY_RUNNING')
                    self.pending[operation] = future
        finally:
            if task and waited is not None and waited >= EFFECTS_WAIT_SECONDS:
                try:
                    self.app.evidence.record('host.effects_lock_wait', {
                        'seconds': round(waited, 3), 'lane': getattr(future, 'asuna_lane', None),
                        **({'holder': holder} if holder else {})})
                except Exception:
                    pass

    def host_call(self, method, args, timeout=120):
        """A request the Host answers; `timeout` is how long to wait for it, which must cover any time the request
        itself is allowed to take there."""
        request_id = uuid.uuid4().hex
        future = Future()
        with self.pending_lock:
            self.host_pending[request_id] = future
        self.emit({'kind': 'host_request', 'request_id': request_id, 'method': method, 'args': args})
        try:
            return future.result(timeout=timeout)
        finally:
            with self.pending_lock:
                self.host_pending.pop(request_id, None)

    def emit(self, value):
        line = json.dumps(value, ensure_ascii=False, default=str) + '\n'
        mark = time.monotonic()
        with self.output_lock:
            waited, mark = time.monotonic() - mark, time.monotonic()
            sys.stdout.write(line)
            sys.stdout.flush()
            self.emit_timing.output_lock_wait, self.emit_timing.output_write = waited, time.monotonic() - mark

    def initialize(self, persona, skill_directories=None, routes=None, models=None, integration_project=None, native_sessions=None,
                   deployment=None, secrets=None, admission='explicit', apply_integrations=False,
                   schedule=True, channels=None, sandbox=None, ui_titles=None, action_idle_minutes=None,
                   action_high_idle_minutes=None, media=None, checkout=None, dsh_home=None):
        # Worker initialization is managed by the native Host.
        if self.app:
            return self.status()
        from .schedule import set_titles
        set_titles(ui_titles)            # her rhythm tasks' names, before the scheduler first reconciles them
        # Channel plugins (e.g. @asuna/napcat-qq) bring their platform's id formats before any route is read.
        channel_kinds.load(channels)
        from .native_settings import runtime_settings
        # The profile's settings are the only source (ADR-010 D3): no local configuration file is read.
        if not deployment:
            raise ValueError('NATIVE_DEPLOYMENT_REQUIRED')
        config = runtime_settings(deployment, secrets or {}, models, admission, create_dirs=True, persona=persona['id'])
        # ADR-098: the table of this machine's roots, built at every start and handed to the plugin with this answer;
        # without one (a filesystem or drive root) her lanes do not run.
        from . import local_roots
        roots = local_roots.attach(checkout, dsh_home)
        # One Host per database: two Hosts may never run the same business queue
        # or publish the same scene concurrently.
        self.stack.enter_context(RuntimeLease(database_lock(config)))
        # The same across machines: a lease in the database itself (ADR-020).
        from .host_lease import DatabaseLease
        lease = self.stack.enter_context(DatabaseLease(config, persona=persona['id']))
        # Existing state identity wins. Package defaults seed only absent heads. An invalid model keeps Core inert.
        take_persona(config, persona)
        config['_skill_directories'] = skill_directories or persona.get('skill_directories', [])
        config['_native_routes'] = routes or {}
        # Voice to text and video decoding, each on unless the profile's settings turn it off (ADR-095 §5.3.1).
        config['media'] = {kind: bool((media or {}).get(kind, True)) for kind in ('voice', 'video')}
        if action_idle_minutes:
            config['action_idle_minutes'] = action_idle_minutes
        # ADR-075: her action brain has a 高 only when the owner configured its route; its idle minutes are its own.
        from . import action_tiers
        action_tiers.CONFIGURED = bool((routes or {}).get('actionHigh'))
        action_tiers.REST = None
        if action_high_idle_minutes:
            config['action_high_idle_minutes'] = action_high_idle_minutes
        for lane, key in (('character', 'character'), ('action', 'executor')):
            if models and lane in models:
                config[key] = {**config[key], **models[lane]}
        config['_integration_project'] = integration_project
        # Commands run under the Host's own sandbox (sandbox_backend.py): the Host says whether it can confine, and
        # wraps each command on request.
        config['_host_sandbox'] = sandbox or {'available': False, 'reason': 'the Host did not offer its sandbox'}
        sandbox_backend.attach(lambda argv, root: self.host_call('sandbox', {'argv': argv, 'root': root})['argv'])
        # Her credentials live in DSH's credential store; the Host reads and writes them on request (credentials.py).
        from . import credentials
        credentials.attach(lambda args: self.host_call('credentials', args))
        from . import svg_render
        svg_render.attach(lambda args: self.host_call('render_svg', args))
        from . import focus
        focus.attach(self.retitle_scene)
        config['_native_apply_integrations'] = apply_integrations
        # The installed adapter release belongs to the channel plugin that ships it.
        releases = [entry['integration_release'] for entry in channels or () if entry.get('integration_release')]
        if releases:
            config['_native_integration_release'] = releases[0]
        evidence = Evidence(DATA / 'reports' / ('native-host-' + uuid.uuid4().hex[:10]), keep=KEPT_HOST_RECORDS,
                            pinned=('runtime.ready',))   # the supervisor's proof that this start came up
        prune_host_reports()
        def configure(host):
            self.app, self.controller = host.app, host.controller
            if lease.left_behind:                  # the last Host did not stop by itself (host_stops)
                from . import host_stops
                # ADR-101: the plugin's open span, read from the data folder (the worker never writes it).
                self.folded_stop = host_stops.left_behind(self.app.store, lease, host_stops.open_span())
            self.navigation = self.prepare_navigation(native_sessions or [])
            self.projection_start = artifact_records.get(self.app.store, 'native-channel-projection')
            if not self.projection_start:
                self.projection_start = artifact_records.save(self.app.store, {'_id': 'native-channel-projection',
                    'kind': 'native-channel-projection', 'since': now(), 'scope_key': 'operator'}, stream='native-channel-projection')
            self.controller.on_input_received = self.project_input
            self.controller.on_episode_finished = self.episode_finished
            self.app.coordinator.native_session_resolver = self.resolve_role_session
            self.app.coordinator.on_collab = self.collab
            self.app.coordinator.on_action_message = self.action_message
            self.app.service.on_fenced = self.task_fenced
            self.app.service.on_collab = self.collab
        self.host = self.stack.enter_context(RuntimeHost(
            config, evidence, lane_factory=lambda *a: NativeLane(self, *a),
            schedule_lane=NativeScheduleLane(self, config) if schedule else False, configure_controller=configure,
            development_factory=lambda c,s: NativeDevelopmentBridge(self,c,s), awaits_activation=True))
        self.watch = threading.Thread(target=self.watch_host, name='native-lifecycle', daemon=True)
        self.watch.start()
        threading.Thread(target=self.audit_retention, name='audit-retention', daemon=True).start()
        from .grants import home_workspaces
        # The Host makes her working copy in each (working-copy.js, ADR-065).
        return {**self.status(), 'navigation': self.navigation, 'home_workspaces': home_workspaces(self.app.config),
                'roots': roots, 'roots_refused': local_roots.REFUSED, 'folded_stop': self.folded_stop}

    def prepare_navigation(self, native_sessions):
        """Bind real native conversations; the Host owns their logs and workspaces."""
        from .channels import route_members
        store, config = self.app.store, self.app.config
        known = {row['id']: row for row in native_sessions}
        local = config['chat']
        Path(local['workspace']).mkdir(parents=True, exist_ok=True)
        name = local.get('display_name') or local['persona']          # from the persona package, never hard-coded
        scenes = [(local['scene_id'], local['person_id'], 'Local', name)]
        for channel in config.get('channels', {}).values():
            for route in channel.get('routes', {}).values():
                if route['target']['type'] == 'group' and route['target']['id'] in channel.get('blocked_groups', []):
                    continue
                members = [grant for sender, grant in route_members(route).items()
                           if sender not in channel.get('blocked_senders', [])]
                platform = channel_kinds.of(route['scene_id'])
                if not members or not platform:
                    continue
                scenes.append((route['scene_id'], members[0]['person_id'], platform.TITLE, self.channel_title(route)))
        bindings = session_records.native(store).rows()
        first = not any(row.get('navigation_version') == 1 for row in bindings)
        entries, retire = [], set()
        for scene_id, person, workspace, title in scenes:
            scene = scene_records.authorize(store, scene_id, person)
            scene_bindings = [row for row in bindings if row.get('lane') == 'character' and not row.get('errand')
                              and row['scene_id'] == scene_id and row['persona'] == local['persona']]
            candidates = [row for row in scene_bindings
                          if row.get('character_context', scene.get('character_context')) == scene.get('character_context')
                          and row.get('policy_epoch') == scene['policy_epoch'] and row['_id'] in known]
            candidates.sort(key=lambda row: (bool(row.get('main_conversation')),
                                             known[row['_id']]['createdAt']), reverse=True)
            source = candidates[0] if candidates else None
            session_id = (source['_id'] if workspace == 'Local' and source else self.role_session_id({
                'scene_id': scene_id, 'persona': local['persona'], 'policy_epoch': scene['policy_epoch'],
                'character_context': scene.get('character_context')}))
            prior = session_records.get(store, session_id)
            cwd = (str(Path(local['workspace']).resolve()) if workspace == 'Local'
                   else self.channel_workspace(channel_kinds.of(scene_id)))
            actor = source['person_id'] if source and source['person_id'] in scene['members'] else person
            values = {**(prior or {}), 'lane': 'character', 'scene_id': scene_id, 'person_id': actor,
                      'scope_key': scene['scope_key'], 'policy_epoch': scene['policy_epoch'],
                      'character_context': scene.get('character_context'),
                      'persona': local['persona'], 'cwd': cwd, 'role_session_id': session_id,
                      'main_conversation': True, 'retired': False, 'native_title': title,
                      'previous_native_title': prior.get('native_title') if prior else None,
                      'source_session_id': prior.get('source_session_id') if prior else
                          source['_id'] if source and source['_id'] != session_id else None}
            record = self.bind_session(session_id, values)
            entries.append({'session_id': session_id, 'workspace': workspace, 'binding': record})
            for old in scene_bindings:
                if old['_id'] == session_id:
                    continue
                # Later native New Sessions are intentional. Retire only an
                # earlier main binding, or histories in the initial migration.
                if not first and not old.get('main_conversation'):
                    continue
                retire.add(old['_id'])
                updated = {**old, 'main_conversation': False, 'retired': True}
                if old in candidates:
                    updated['successor_id'] = session_id
                else:
                    # An authorization/context change must not redirect old
                    # tasks or import their native transcript into a new scope.
                    updated.pop('successor_id', None)
                session_records.save(store, updated, expected=old['revision'], stream='native-binding:' + old['_id'])
        primary = {entry['session_id'] for entry in entries}
        for old in bindings:
            if old.get('main_conversation') and old['_id'] not in primary and old['_id'] not in retire:
                retire.add(old['_id'])
                session_records.save(store, {**old, 'main_conversation': False, 'retired': True},
                          expected=old['revision'], stream='native-binding:' + old['_id'])
        # The initial operator-requested cleanup archives old native logs; it
        # never deletes messages or alters immutable session headers.
        if first:
            retire.update(row['id'] for row in native_sessions
                          if row['id'] not in primary and row.get('agentPreset') != 'asuna-scheduler')
        return {'entries': entries, 'archive_ids': sorted(retire), 'first': first,
                'workspaces': {**{kind.TITLE: self.channel_workspace(kind) for kind in channel_kinds.kinds()},
                               'Local': str(Path(local['workspace']).resolve())}}

    @staticmethod
    def channel_workspace(platform):
        """The shared native workspace of one platform's conversations (<data>/work/<kind>)."""
        directory = (DATA / 'work' / platform.KIND).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        return str(directory)

    @staticmethod
    def role_session_id(ep):
        key = json.dumps([ep['scene_id'], ep['persona'], ep['policy_epoch'],
                          ep.get('character_context')], sort_keys=True)
        return 'asuna-role-' + sha(key.encode())[:32]

    def continued_session(self, session_id):
        """The session a conversation continues in now: its successors followed to the last one."""
        seen = {session_id}
        while True:
            successor = (session_records.get(self.app.store, session_id, fields=['successor_id']) or {}).get('successor_id')
            if not successor or successor in seen:
                return session_id
            seen.add(successor)
            session_id = successor

    def earlier_sessions(self, session_id):
        """This session and every session it continued from (their successors lead to it)."""
        chain, frontier = [session_id], [session_id]
        while frontier:
            rows = session_records.successors(self.app.store, frontier).rows(fields=['_id'])
            frontier = [row['_id'] for row in rows if row['_id'] not in chain]
            chain += frontier
        return chain

    def carry_session(self, session_id, carry):
        """Her conversation no longer fits the model's window (ADR-028), or was opened with the other source of her
        thoughts (`carry['why']` 'thoughts', ADR-099): the scene continues in a new session that carries the old
        one's last summary, and the old binding names it as successor. The Host prepares the new
        session and archives the old one. Returns the new session id, or None when this session is not a main
        conversation or is itself a carried session whose first notice never got through (no loop)."""
        from .role_tools import thinking_mode
        store = self.app.store
        with self.carry_lock:
            old = session_records.get(store, session_id, native=True)
            if not old or old.get('lane') != 'character':
                return None
            if old.get('successor_id'):
                return self.continued_session(session_id)
            if not old.get('main_conversation') or (old.get('carry') and not old['carry'].get('delivered')):
                return None
            scene = scene_records.authorize(store, old['scene_id'], old['person_id'])
            context = 'carried-' + uuid.uuid4().hex[:16]
            # $set, not a whole-document write: ingress increments the scene's sequence concurrently.
            scene_records.set_character_context(store, scene['_id'], context)
            successor = self.role_session_id({'scene_id': scene['_id'], 'persona': old['persona'],
                                              'policy_epoch': scene['policy_epoch'], 'character_context': context})
            summary = str((carry or {}).get('summary') or '').strip()
            record = self.bind_session(successor, {
                **{key: old[key] for key in ('lane', 'scene_id', 'person_id', 'scope_key', 'persona', 'cwd', 'native_title')},
                'policy_epoch': scene['policy_epoch'], 'character_context': context, 'role_session_id': successor,
                'main_conversation': True, 'retired': False, 'navigation_version': 1,
                'previous_native_title': None, 'source_session_id': None,
                'thoughts': 'thinking' if thinking_mode(store.config) else 'tool',     # ADR-099: opened in this mode
                'carry': {'from_session_id': session_id, 'summary': summary, 'delivered': None,
                          **({'why': carry['why']} if (carry or {}).get('why') else {})}})
            # The old binding keeps an explicit context: a row without one would match any context at navigation.
            session_records.save(store, {**old, 'character_context': old.get('character_context'), 'main_conversation': False,
                                   'retired': True, 'successor_id': successor},
                      expected=old['revision'], stream='native-binding:' + session_id)
            store.audit(session_id, 'native.context.carried', {
                'from_session_id': session_id, 'successor_id': successor, 'scene_id': scene['_id'],
                'summary_chars': len(summary), **({'why': carry['why']} if (carry or {}).get('why') else {})},
                scene['scope_key'])
            platform = channel_kinds.of(scene['_id'])
            workspace = platform.TITLE if platform else 'Local'
            self.host_call('carry_session', {'session_id': session_id, 'plan': {
                'first': False, 'archive_ids': [], 'workspaces': {workspace: record['cwd']},
                'entries': [{'session_id': successor, 'workspace': workspace, 'binding': record}]}})
            return successor

    def action_session_id(self, binding, role_id, ep, task):
        """One native context per authorized execution binding, including old logs."""
        binds = {'broker': 's-' + sha(binding.encode())[:40], 'parents': self.earlier_sessions(role_id),
                 'scene': ep['scene_id'], 'scope': ep['scope_key'], 'epoch': ep['policy_epoch'],
                 'person': ep['person_id'], 'persona': ep['persona']}
        # Prefer the immediately preceding task's source when importing an old
        # operation-scoped binding. Do not import another actor or policy epoch.
        prior = None
        for task_id in (task['_id'], task.get('continues_task_id')):
            if task_id:
                prior = session_records.of_task(self.app.store, **binds, task=task_id)
                if prior: break
        if not prior:
            prior = session_records.of_task(self.app.store, **binds)
        if prior:
            return prior['_id']
        identity = json.dumps([binding, role_id, ep['scene_id'], ep['scope_key'],
                               ep['policy_epoch'], ep['person_id'], ep['persona']], sort_keys=True)
        return 'asuna-action-' + sha(identity.encode())[:32]

    def audit_retention(self):
        """ADR-074: the audit, bounded by time and by size, is pruned once at start and then daily; stored pictures
        are swept by their life cycle (media_life) on the same beat, the days she carried are counted
        (carried.count_days) and the shadow pilot's old turn rows go (memory_pilot.prune)."""
        from .audit import prune
        while True:
            try:
                self.app.evidence.record('audit.pruned', {'deleted': prune(self.app.store)})     # 0 too: it ran
            except Exception as exc:
                self.app.evidence.record('audit.prune_failed', {'error': redact_text(str(exc), self.app.config)[:300]})
            try:
                # Stored pictures and files live by media_life.POLICY: expired copies, unlisted candidates and the
                # bytes of files past their days go.
                from . import media_life
                removed = media_life.sweep(self.app.store)
                if media_life.worth_recording(removed):
                    self.app.evidence.record('media.swept', removed)
            except Exception as exc:
                self.app.evidence.record('media.sweep_failed', {'error': redact_text(str(exc), self.app.config)[:300]})
            try:
                # ADR-096: what she carried, per section × place × day (carried_counts, 30 days), and the closed
                # shadow pilot's turn rows past 30 days.
                from . import carried, memory_pilot
                persona = (self.app.config.get('chat') or {}).get('persona')
                counted = carried.count_days(self.app.store, persona) if persona else {}
                self.app.evidence.record('carried.counted', {**counted,
                                                             'pilot_rows_deleted': memory_pilot.prune(self.app.store)})
            except Exception as exc:
                self.app.evidence.record('carried.count_failed', {'error': redact_text(str(exc), self.app.config)[:300]})
            if self.stopping.wait(24 * 3600):
                return

    def watch_host(self):
        while not self.stopping.wait(.5):
            if self.host.restart_requested.is_set():
                self.emit({'kind': 'restart_requested', 'reason': 'published-worker'})
                return

    def resolve_role_session(self, ep):
        """Bind trusted, normalized ingress; old transcripts stay read-only."""
        if not self.navigation_ready.wait(self.app.config['workflow_timeout_seconds']):
            raise RuntimeError('NATIVE_NAVIGATION_NOT_READY')
        store = self.app.store
        if ep.get('task_id'):
            task = task_records.get(store, ep['task_id'])
            original = episode_records.get(store, task['episode_id']) if task else None
            if original and self.carried(original.get('native_session_id'), ep):
                return self.continued_session(original['native_session_id'])
        source = message_records.get(store, 'in-' + ep['_id']) or {}
        plan_id = source.get('event', {}).get('scheduled_plan_id')
        plan = plan_records.get(store, plan_id) if plan_id else None
        original = episode_records.get(store, plan.get('source_episode_id')) if plan else None
        # A plan or a task begun on an errand or in a reflection comes back to the conversation itself, never to the
        # side session.
        if original and self.carried(original.get('native_session_id'), ep):
            return self.continued_session(original['native_session_id'])
        primary = session_records.main(store, ep['scene_id'], persona=ep['persona'], epoch=ep['policy_epoch'],
                                       context=ep.get('character_context'))
        session_id = primary['_id'] if primary else self.role_session_id(ep)
        if errands.is_errand_visit(source.get('event')):
            return self.errand_session(ep, session_id)
        from . import self_review
        prepared = ep.get('context') if 'context' in ep else (episode_records.get(store, ep['_id'], fields=['context'])
                                                               or {}).get('context')
        if self_review.reflecting(prepared):
            return self.reflection_session(ep, session_id)
        store.audit(ep['_id'], 'native.context.bound', {
            'native_session_id': session_id, 'legacy_history': 'read-only',
            'context': 'new native conversation; no tool or message replay'}, ep['scope_key'])
        return session_id

    def carried(self, session_id, ep):
        """Whether a turn that follows another (a task's, a plan's) continues that turn's session: only a conversation
        of its own place. A task begun on one line whose turn comes home runs in the home conversation; binding it to
        the other line's session would be refused (NATIVE_BINDING_IDENTITY_CHANGED)."""
        if not session_id or self.side_session(session_id):
            return False
        row = session_records.get(self.app.store, session_id, fields=['scene_id']) or {}
        return row.get('scene_id') in (None, ep['scene_id'])

    def side_session(self, session_id):
        """Whether this session is an errand's copy of a conversation (ADR-066) or a reflection's own (ADR-072): a
        one-turn session, retired once that turn ends, that later turns never take for the conversation."""
        row = session_records.get(self.app.store, session_id, fields=['errand', 'reflection']) or {}
        return bool(row.get('errand') or row.get('reflection'))

    def reflection_session(self, ep, home_id):
        """A reflection turn's own session (ADR-072): it starts empty, so its readings (her reviews) never enter the
        home conversation's context; what she does there lasts through her tools. Owner 2026-10-16: more tokens for her
        reflection are fine, none of them in her regular turns."""
        from . import self_review
        store = self.app.store
        session_id = self_review.reflection_session_id(ep['_id'])
        if session_records.get(store, session_id):
            return session_id
        scene = scene_records.authorize(store, ep['scene_id'], ep['person_id'])
        home = session_records.get(store, home_id) or {}
        cwd = home.get('cwd') or str(Path(workspace_grant(self.app.config, scene['_id'], ep['person_id'])['workspace']).resolve())
        self.bind_session(session_id, {
            'lane': 'character', 'scene_id': scene['_id'], 'person_id': ep['person_id'],
            'scope_key': scene['scope_key'], 'policy_epoch': scene['policy_epoch'],
            'character_context': ep.get('character_context'), 'persona': ep['persona'], 'cwd': cwd,
            'role_session_id': session_id, 'main_conversation': False, 'retired': False,
            'reflection': {'episode_id': ep['_id'], 'home_session_id': home_id}})
        store.audit(ep['_id'], 'reflection.session', {'session_id': session_id, 'home_session_id': home_id},
                    scene['scope_key'])
        return session_id

    def errand_session(self, ep, source_id):
        """The errand's own session (ADR-066): the Host copies the destination's conversation at its last completed
        turn, so the turn resumes from its cached prefix. Where it cannot (no completed turn, too near compaction, or
        the copy fails) the session starts empty (`forked` false), and the turn's notice carries the conversation's
        recent lines, none of them shown there yet."""
        store = self.app.store
        session_id = errands.session_id(ep['_id'])
        if session_records.get(store, session_id):
            return session_id
        scene = scene_records.authorize(store, ep['scene_id'], ep['person_id'])
        source = session_records.get(store, source_id) or {}
        platform = channel_kinds.of(scene['_id'])
        cwd = source.get('cwd') or (self.channel_workspace(platform) if platform
                                    else str(Path(workspace_grant(self.app.config, scene['_id'], ep['person_id'])['workspace']).resolve()))
        try:
            made = self.host_call('errand_session', {'session_id': session_id, 'source_session_id': source_id,
                                                     'scene_id': scene['_id'], 'cwd': cwd}) or {}
        except Exception as exc:                        # the errand still runs, in an empty session
            made = {'forked': False, 'reason': str(exc)[:200]}
        carried = {'episode_id': ep['_id'], 'source_session_id': source_id, 'forked': bool(made.get('forked')),
                   **({'reason': str(made['reason'])[:200]} if made.get('reason') else {})}
        self.bind_session(session_id, {
            'lane': 'character', 'scene_id': scene['_id'], 'person_id': ep['person_id'],
            'scope_key': scene['scope_key'], 'policy_epoch': scene['policy_epoch'],
            'character_context': ep.get('character_context'), 'persona': ep['persona'], 'cwd': cwd,
            'role_session_id': session_id, 'main_conversation': False, 'retired': False, 'errand': carried})
        store.audit(ep['_id'], 'errand.session', {'session_id': session_id, **carried}, scene['scope_key'])
        return session_id

    def status(self):
        integration = self.host.integration.status() if self.host and self.host.integration else {'state': 'DISABLED'}
        wanted = self.app and (self.app.config.get('integration') or {}).get('enabled')
        if wanted and not (self.host and self.host.integration) and not sandbox_backend.available(self.app.config):
            integration['error'] = 'no sandbox: ' + str(sandbox_backend.chosen(self.app.config)['reason'])
        return {'ready': bool(self.app), 'persona': self.app.config['chat']['persona'] if self.app else None,
                'workspace': self.app.config['chat']['workspace'] if self.app else None,
                'transport': 'stdio', 'model_runtime': 'dsh-host',
                'channels_active': bool(self.host and getattr(self.host, 'channel_server', None)),
                'channel_titles': [kind.TITLE for kind in channel_kinds.kinds()],
                'schedules_active': bool(self.host and getattr(self.host, 'schedule', None)),
                'integration_active': integration['state'] == 'RUNNING',
                'integration_state': integration['state'], 'integration_error': integration.get('error'),
                'sandbox': ({k: v for k, v in sandbox_backend.chosen(self.app.config).items() if k != 'distro'}
                            if self.app else None),
                'database': 'connected' if self.app else 'unavailable',
                'self_source': 'mongo' if self.app else None,      # a code: the settings card words it
                'active_role': self.controller.active if self.controller else None,
                'queued_inputs': self.controller.pending.qsize() if self.controller else 0,
                'queued_tasks': self.controller.task_queue.qsize() if self.controller else 0,
                'active_task': self.controller.active_task if self.controller else None}

    def refusals_for(self, task):
        """For the plugin's guard (ADR-053): the broker's sentence for each action tool this task was not given."""
        from .tasks import capability_refusal, ToolBroker
        names = [spec['name'] for spec in ToolBroker.catalogue()]
        return {name: capability_refusal(self.app.store, task, name) for name in names
                if name not in task['allowed_capabilities']}

    def joined_line(self, session):
        """The scene of a home line the owner joins (ADR-051) whose live character session this is, else None."""
        if not session or session.get('lane') != 'character' or session.get('successor_id') or session.get('retired') \
                or not session.get('cwd') or not channel_kinds.owner_joins(session.get('scene_id')):
            return None
        scene = scene_records.get(self.app.store, session['scene_id'], fields=['members']) or {}
        return session['scene_id'] if self.app.config['chat']['person_id'] in scene.get('members', ()) else None

    @staticmethod
    def read_only_note(platform):
        return {'key': 'read_only', **({'platform': platform.TITLE} if platform else {})}

    def bind_session(self, session_id, values):
        prior = session_records.get(self.app.store, session_id)
        identity = ('lane', 'scene_id', 'persona', 'cwd')
        if values['lane'] not in ('character', 'attend'):       # a group's sessions serve everyone in it
            identity += ('person_id',)
        if prior and any(prior.get(k) != values.get(k) for k in identity):
            raise Denied('NATIVE_BINDING_IDENTITY_CHANGED')
        scene = scene_records.authorize(self.app.store, values['scene_id'], values['person_id'])
        if scene['policy_epoch'] != values['policy_epoch']:
            raise Denied('NATIVE_SESSION_EPOCH_CHANGED')
        # Bindings keep a hash of the stage system prompt, never its full text.
        kept = {k: v for k, v in (prior or {}).items() if k != 'system'}
        return session_records.save(self.app.store, {
            **kept, **values, '_id': session_id, 'native_host': True,
            'binding_key': 'native-host:' + session_id,
            'binding_updated_at': now(),
        }, expected=prior['revision'] if prior else None, stream='native-binding:' + session_id)

    def session(self, session_id):
        record = session_records.get(self.app.store, session_id, native=True)
        if not record:
            raise Denied('NATIVE_SESSION_NOT_BOUND')
        scene = scene_records.authorize(self.app.store, record['scene_id'], record['person_id'])
        if scene['policy_epoch'] != record['policy_epoch']:
            raise Denied('NATIVE_SESSION_EPOCH_CHANGED')
        return record

    def task_fenced(self, task, reason):
        with self.pending_lock:
            pending=[(token,future) for token,future in self.pending.items()
                if (bound:=getattr(future,'asuna_task',None)) and bound['_id']==task['_id']
                and bound['intent_revision']<task['intent_revision'] and not future.done()]
            for _,future in pending:
                future.set_exception(Denied('STALE_TASK_FENCE'))
        for token,future in pending:
            self.emit({'kind':'task_fenced','token':token,'session_id':future.asuna_session_id,
                'task_id':task['_id'],'intent_revision':task['intent_revision'],'reason':reason})

    def parent_session(self, task):
        """Her role session the task belongs to: where its collaboration thread is drawn."""
        if task.get('native_session_id'):
            return self.continued_session(task['native_session_id'])
        original = episode_records.get(self.app.store, task['episode_id'], fields=['native_session_id']) or {}
        return self.continued_session(original['native_session_id']) if original.get('native_session_id') else None

    def collab(self, task, entry):
        """One entry of the two brains' thread (ADR-011 §7.1); the plugin appends it to her conversation."""
        session_id = self.parent_session(task)
        if session_id:
            # The tier a job was given and the one that ran it (ADR-075), for the owner's view of the thread; read
            # fresh, since a fall is recorded while the job runs. Never shown to her from here.
            tier = (task_records.get(self.app.store, task['_id'], fields=['tier']) or task).get('tier')
            view = {k: v for k, v in (tier or {}).items() if k in ('chosen', 'ran')}
            if (tier or {}).get('fell'):
                view.update(reason=tier['fell'].get('reason'), mid_run=bool(tier['fell'].get('mid_run')))
            self.emit({'kind': 'collab', 'session_id': session_id, 'task_id': task['_id'],
                       'thread': task.get('thread') or task['_id'], 'title': task.get('title') or task.get('goal'),
                       'entry': {**entry, **({'tier': view} if view else {})}})

    def action_message(self, task, message):
        """Her words for a running action session: steered in at its next step (ADR-011 §4)."""
        self.emit({'kind': 'action_message', 'task_id': task['_id'], 'thread': task.get('thread') or task['_id'],
                   'message': message})

    def episode_finished(self, event, result, error):
        if event.get('channel'):
            from .ingress import episode_id
            row = message_records.get(self.app.store, 'in-' + episode_id(event))
            if row:
                self.project_input(row)
        session_id = (result or {}).get('native_session_id') or event.get('native_session_id')
        if session_id:
            self.emit({'kind': 'episode_finished', 'session_id': session_id,
                       'episode_id': (result or {}).get('_id'),
                       'state': (result or {}).get('state'), 'error': error,
                       'task_id': (result or {}).get('task_id')})

    def project_input(self, row):
        if not row.get('event', {}).get('channel'):
            return
        if not self.navigation_ready.is_set():
            # Called inside Chat.receive's ingress lock. Waiting here for navigation, which the plugin confirms
            # only after initialize returns, deadlocks a start whose activations queue input while the adapter
            # delivers its spool. The row is durable; navigation.ready projects it.
            return
        if not receipt_records.sink_get(self.app.store, 'native-input:' + row['_id']):
            from .chat import INGRESS_TIMING as timing
            mark = time.monotonic()
            value = {'kind': 'channel_input', **self.channel_input(row)}
            timing.channel_input = time.monotonic() - mark
            self.emit_timing.__dict__.clear()
            self.emit(value)
            timing.__dict__.update(vars(self.emit_timing))

    def channel_title(self, route):
        """Conversation title a person can read (content only): the configured name, else the group name or
        peer name the platform last sent with a message in that scene, else, for a private chat, the name this
        profile keeps for that person (the owner's label for the owner, else a saved identity name), else the
        platform's id; an id too long to read (an OpenID) shows as 群聊 / 私聊 and its first six characters. A
        group she lets rest starts with focus.RESTING_MARK."""
        group = route['target']['type'] == 'group'
        # A configured name; earlier automatic admissions stored the number itself here, which is no name.
        name = route.get('display_name') if route.get('display_name') != route['target']['id'] else None
        if not name:
            # The newest message that carries the name: a notice (a join, a recall) carries none.
            last = message_records.inbound(self.app.store, route['scene_id'], group_name=group, peer_display=not group,
                                           by='received_at').first(
                newest_first=True, fields=['event.raw.group_name', 'event.raw.asuna_peer'])
            raw = (last or {}).get('event', {}).get('raw', {})
            name = raw.get('group_name') if group else (raw.get('asuna_peer') or {}).get('display')
        if not name and not group:
            # A platform that sends no name with private messages (an OpenID platform) still names someone
            # this profile knows: the owner by the persona's word for them, anyone else by their saved name.
            from .people import People
            people = People(self.app.store)
            person = people.person(route.get('person_id'))
            if person and person == people.owner:
                name = people.owner_label
            else:
                saved = people_records.identity(self.app.store, person, ['display_name']) if person else None
                name = (saved or {}).get('display_name')
        target = str(route['target']['id'])
        unnamed = target if len(target) <= 20 else ('群聊 ' if group else '私聊 ') + target[:6]
        name = ' '.join(str(name or '').split())[:40] or unnamed
        from . import focus
        scene = scene_records.get(self.app.store, route['scene_id']) if group else None
        return focus.RESTING_MARK + name if scene and not focus.active(self.app.store, scene) else name

    def retitle_scene(self, scene_id):
        """A group's conversation shows its state now (focus.RESTING_MARK): its binding's title, then the Host's."""
        from .channels import route_members
        config = self.app.config
        route = next((route for channel in config.get('channels', {}).values()
                      for route in channel.get('routes', {}).values() if route['scene_id'] == scene_id), None)
        binding = session_records.main(self.app.store, scene_id, lane='character')
        if not route or not binding or not route_members(route):
            return
        title = self.channel_title(route)
        if binding.get('native_title') == title:
            return
        record = self.bind_session(binding['_id'], {
            **{key: binding[key] for key in ('lane', 'scene_id', 'person_id', 'persona', 'cwd', 'policy_epoch')},
            'native_title': title, 'previous_native_title': binding.get('native_title')})
        self.host_call('retitle', {'session_id': record['_id'], 'binding': record})

    def channel_input(self, row):
        """A real processed platform receipt, including quiet/error outcomes; never a model turn."""
        from .channels import route_for_scene
        store, config = self.app.store, self.app.config
        scene = scene_records.authorize(store, row['scene_id'], row['author'])
        if row['policy_epoch'] != scene['policy_epoch']:
            raise Denied('NATIVE_SESSION_EPOCH_CHANGED')
        route = route_for_scene(config, row['event']['channel']['id'], row['scene_id'])
        ep = {'_id': row['episode_id'], 'scope_key': scene['scope_key'],
              'scene_id': scene['_id'], 'person_id': row['author'], 'persona': config['chat']['persona'],
              'policy_epoch': scene['policy_epoch'], 'character_context': scene.get('character_context')}
        session_id = self.resolve_role_session(ep)
        binding = session_records.get(store, session_id)
        if not binding or not binding.get('main_conversation'):
            binding = self.bind_session(session_id, {**(binding or {}), **ep, 'lane': 'character', 'scope_key': scene['scope_key'],
                'cwd': self.channel_workspace(channel_kinds.of(scene['_id'])), 'role_session_id': session_id,
                'main_conversation': True, 'native_title': self.channel_title(route), 'navigation_version': 1})
        indexer = getattr(self.app, 'memory_indexer', None)
        if indexer and scene['_id'] not in indexer.scene_ids:
            indexer.scene_ids.append(scene['_id'])
            if indexer.summarizer:
                indexer.summarizer.scene_ids.append(scene['_id'])
                indexer.summarizer.initialize()
        # Label line + indented message (people.py): a name can't close the label or start a new speaker.
        return {'session_id': session_id, 'binding': binding, 'input': {
            'id': row['_id'], 'text': People(store).transcript(scene, row), 'sender': row['event']['channel']['sender_id'],
            'received_at': row['received_at'], 'state': row.get('ingress_state', 'ACCEPTED')}}

    def dispatch(self, method, args):
        if method == 'validate_settings':
            from .native_settings import runtime_settings
            channel_kinds.load(args.get('channels'))
            config = runtime_settings(args['deployment'], args.get('secrets', {}), args['models'], args['admission'],
                                      persona=args['persona'])
            if config['chat']['persona'] != args['persona']:
                raise ValueError('PERSONA_STATE_ID_MISMATCH')
            from .state import Store
            from .host import prepare_channels
            observer = Store(config)
            try:
                observer.ping()
                from .channel_admission import restore_admissions
                restore_admissions(observer)
                prepare_channels(observer, dry_run=True)
            finally:
                observer.close()
            return {'valid': True}
        if method == 'host_result':
            with self.pending_lock:
                future = self.host_pending.get(args['request_id'])
                if future and not future.done():
                    if args.get('error'):
                        future.set_exception(RuntimeError(args['error']))
                    else:
                        future.set_result(args.get('value'))
            return {'accepted': True}
        if method == 'initialize':
            return self.initialize(**args)
        if method == 'status':
            return self.status()
        if not self.app:
            raise RuntimeError('BUSINESS_WORKER_NOT_READY')
        if method == 'roots.tally':
            # Her lanes' requests the plugin rewrote, per session since its last count (ADR-098 D2), for her week.
            from . import local_roots
            rows = [row for row in args.get('sessions') or () if isinstance(row, dict)]
            self.app.store.audit('roots:' + self.app.config['chat']['persona'], local_roots.TALLY,
                                 {'sessions': [{'session_id': str(row.get('session_id')), 'lane': str(row.get('lane')),
                                                'requests': int(row.get('requests') or 0),
                                                'rewritten': int(row.get('rewritten') or 0)} for row in rows[:500]]})
            return {'kept': len(rows)}
        if method == 'roots.refused':
            # The plugin refused her lanes' requests for want of a table: one audit event says why (ADR-098 D2).
            from . import local_roots
            self.app.store.audit('roots:' + self.app.config['chat']['persona'], local_roots.REFUSED_EVENT,
                                 {'lane': str(args.get('lane')), 'reason': str(args.get('reason'))[:300]})
            return {'kept': True}
        if method == 'settings.quiesce':
            # unfinished_tasks also includes work dequeued before its active
            # flag is set. The ingress fence closes admission in that window.
            with self.controller.ingress_lock, self.controller.state_lock, self.pending_lock:
                if (self.controller.active or self.controller.active_task
                        or any(getattr(future, 'asuna_lane', None) != 'summary' for future in self.pending.values())
                        or self.controller.pending.unfinished_tasks
                        or self.controller.task_queue.unfinished_tasks):
                    raise RuntimeError('ASUNA_BUSY: wait for the current role and action to finish')
                self.controller.reconfiguring = True
                for future in self.pending.values():
                    if not future.done():
                        future.set_exception(RuntimeError('BACKGROUND_SUMMARY_PAUSED_FOR_SETTINGS'))
            return {'quiesced': True}
        if method == 'host.came_back':
            # ADR-101: a start completed; the plugin hands over the span she was down, recorded once.
            from . import host_stops
            return {'stop_id': host_stops.worker_down(self.app.store, args)['_id']}
        if method == 'navigation.ready':
            for entry in self.navigation['entries']:
                record = session_records.get(self.app.store, entry['session_id'])
                if record.get('navigation_version') != 1:
                    session_records.save(self.app.store, {**record, 'navigation_version': 1},
                        expected=record['revision'], stream='native-binding:' + record['_id'])
            self.navigation_ready.set()
            # Recover only native projection work, never model/tool execution.
            # Historical business rows predating this feature remain in Memory.
            for row in message_records.channel_inbound(self.app.store, self.projection_start['since']).each():
                try:
                    self.project_input(row)
                except Denied:
                    pass  # Revoked scenes must not project into a new epoch.
            return {'ready': True}
        if method == 'channel_input.ack':
            row = message_records.get(self.app.store, args['input_id'], from_channel=True)
            if not row:
                raise ValueError('NATIVE_INPUT_NOT_FOUND')
            receipt_id = 'native-input:' + row['_id']
            if not receipt_records.sink_get(self.app.store, receipt_id):
                try:
                    receipt_records.save_sink(self.app.store, {'_id': receipt_id, 'kind': 'native_input_projection',
                        'input_id': row['_id'], 'native_session_id': args['session_id'],
                        'scope_key': row['scope_key'], 'policy_epoch': row['policy_epoch']}, stream=receipt_id)
                except Conflict:
                    if not receipt_records.sink_get(self.app.store, receipt_id):
                        raise
            return {'recorded': True}
        if method == 'input_policies':
            local = self.app.config['chat']
            ids = [row['id'] for row in args['sessions']]
            # Keys of the client's input words (ADR-011 §2.8): a platform's read-only view, or an internal session.
            rows = session_records.native(self.app.store, ids).rows()
            policies = {row['_id']: (self.read_only_note(channel_kinds.of(row['scene_id'])) if row['scene_id'] != local['scene_id']
                else {'key': 'internal'})
                for row in rows
                if row['scene_id'] != local['scene_id'] or row['lane'] != 'character'
                or row.get('successor_id') or row.get('retired')}
            for row in args['sessions']:
                for platform in channel_kinds.kinds():
                    if row.get('cwd') and Path(row['cwd']).resolve() == (DATA / 'work' / platform.KIND).resolve():
                        policies[row['id']] = self.read_only_note(platform)
            for row in rows:                 # the owner writes on a home line he joins (ADR-051)
                if self.joined_line(row):
                    policies.pop(row['_id'], None)
            return policies
        if method == 'heartbeat_now':
            # The owner's /heartbeat command (ADR-012 §8): one beat now, and when the next one is due.
            scheduler = self.app.coordinator.scheduler
            return scheduler.beat_now() if scheduler else {'state': 'NO_SCHEDULE'}
        if method == 'session_kinds':
            # Her conversations on a platform among these sessions: a group or a DM (the sidebar mark).
            local = self.app.config['chat']['scene_id']
            rows = session_records.native(self.app.store, list(args['session_ids'])[:500], lane='character',
                                          besides_scene=local).rows(fields=['scene_id'])
            kinds = {scene['_id']: scene.get('kind') for scene in scene_records.many(
                self.app.store, [row['scene_id'] for row in rows], fields=['kind'])}
            return {row['_id']: kinds[row['scene_id']] for row in rows if kinds.get(row['scene_id']) in ('group', 'dm')}
        if method == 'input':
            session_id = args['session_id']
            existing = session_records.get(self.app.store, session_id)
            local = self.app.config['chat']
            if existing and existing.get('successor_id'):
                raise Denied('NATIVE_CONVERSATION_CONTINUED: ' + existing['successor_id'])
            if existing and existing.get('retired'):
                raise Denied('NATIVE_CONVERSATION_RETIRED')
            # A home line the owner joins (ADR-051): its own character session, in its own folder.
            line = self.joined_line(existing)
            workspace = existing['cwd'] if line else local['workspace']
            if not args.get('cwd') or not workspace or Path(args['cwd']).resolve() != Path(workspace).resolve():
                raise Denied('NATIVE_INPUT_WORKSPACE_MISMATCH')
            if existing and not line and (existing['scene_id'], existing['person_id'], existing['lane']) != (
                    local['scene_id'], local['person_id'], 'character'):
                raise Denied('NATIVE_INPUT_SOURCE_MISMATCH')
            scene_id = line or local['scene_id']
            media = None
            if args.get('images'):
                # Pictures the owner attached: DSH shows them to her; the program keeps its own record.
                from .vision import local_uploads
                scene = scene_records.get(self.app.store, scene_id, fields=['scope_key'])
                media = local_uploads(self.app.store, scene['scope_key'], args['images'], args['message_ids'][0])
            return self.controller.submit(args['text'], event_id=args['message_ids'][0], scene_id=scene_id,
                native_session_id=session_id, native_message_ids=args['message_ids'], media=media)
        if method == 'result':
            with self.pending_lock:
                future = self.pending.get(args['token'])
                if not future:
                    raise ValueError('NATIVE_OPERATION_NOT_WAITING')
                if not future.done():
                    if args.get('error') and args.get('carry') is not None:
                        future.set_exception(ContextOverflow(args['error'], args['carry'], future.asuna_session_id))
                    elif args.get('error'):
                        future.set_exception(RuntimeError(args['error']))
                    else:
                        future.set_result(args['result'])
            return {'accepted': True}
        if method == 'session':
            record = self.session(args['session_id'])
            # The conversation's clock, for the times a Host tool shows its model (web_search's publication dates).
            from . import local_time
            from .schedule_rules import offset_minutes
            zone = local_time.zone_of(self.app.store, record['scene_id'])
            return {**record, 'timezone': None if zone.get('zone_unavailable') else zone['name'],
                    'utc_offset_minutes': offset_minutes(zone['tz'], clock.now())}
        if method == 'ui.titles':
            # A browser in another language opened the Web UI (ui-language.js): her rhythm tasks follow it.
            from .schedule import set_titles
            set_titles(args.get('titles'))
            scheduler = getattr(self.host, 'schedule', None) if self.host else None
            if scheduler:
                scheduler.retitle()
            return {'retitled': bool(scheduler)}
        if method == 'tier.fell':
            # ADR-075: a 高 job fell to 低 (the plugin saw a hard failure, or 高 resting when the job began).
            from . import action_tiers
            store = self.app.store
            task = task_records.get(store, args['task_id'])
            if task and (task.get('tier') or {}).get('ran') == '高':
                fell = {'reason': args['reason'], 'mid_run': bool(args.get('mid_run')), 'at': now(),
                        **({'code': args['code']} if args.get('code') else {})}
                task_records.save(store, {**task, 'tier': {**task['tier'], 'ran': action_tiers.LOW, 'fell': fell}},
                          expected=task['revision'], stream=task['_id'])
                store.audit(task['_id'], 'tier.fell', {'task_id': task['_id'], **fell})
            return {'recorded': bool(task)}
        if method == 'tier.rest':
            # ADR-075: 高 rests (until a retry clock, or with none until the owner sees to it) or is back.
            from . import action_tiers
            action_tiers.REST = ({'reason': args['reason'], 'until': args.get('until')} if args.get('reason') else None)
            self.app.store.audit('action-tiers', 'tier.rest', {**(action_tiers.REST or {'over': True}),
                                                               **({'code': args['code']} if args.get('code') else {})})
            return {'recorded': True}
        if method == 'stage.valid':
            with self.pending_lock:
                future=self.pending.get(args['token'])
                if not future or future.done():return {'valid':False}
                if args.get('session_id') and future.asuna_session_id != args['session_id']:
                    raise Denied('NATIVE_OPERATION_SESSION_MISMATCH')
                task=getattr(future,'asuna_task',None)
            if task:self.app.service.valid(task)
            return {'valid':True}
        if method in ('memory.page', 'memory.detail'):
            from .native_api import NativeMemory
            memory = NativeMemory(self, args['session_id'])
            return memory.detail(args['id']) if method == 'memory.detail' else memory.page(
                args.get('category', 'summary'), args.get('offset', 0), args.get('search', ''))
        if method == 'tool':
            record = self.session(args['session_id'])
            if record['lane'] != 'executor':
                raise Denied('ACTION_SESSION_REQUIRED')
            with self.pending_lock:
                future = self.pending.get(args.get('operation'))
                if not future or future.done():
                    raise Denied('NATIVE_OPERATION_NOT_ACTIVE')
                if future.asuna_lane != 'executor' or future.asuna_session_id != args['session_id']:
                    raise Denied('NATIVE_OPERATION_SESSION_MISMATCH')
                task, binding = future.asuna_task, future.asuna_binding
                broker_session = future.asuna_broker_session
            self.app.service.valid(task)
            self.app.broker.bind(broker_session, task, Path(binding['cwd']))
            # The action brain reads tool results on the local clock; receipts keep UTC (local_time.py).
            from . import local_time
            return local_time.for_model(self.app.broker.call(broker_session, args['call_id'], args['tool'], args['args']),
                                        local_time.zone_of(self.app.store, task['scene_id']))
        if method == 'tool_specs':
            # One list: the broker's, which is also what every call is checked against.
            return self.app.broker.specs
        if method == 'action_message.delivered':
            # The action session read her message at a step (index.js): no extra round needed for it.
            row = task_records.thread_message(self.app.store, args['message_id'], sender='character')
            if row and not row.get('delivered'):
                task_records.save_message(self.app.store, {**row, 'delivered': True, 'delivered_at': now()},
                                   expected=row['revision'], stream=row['task_id'])
            return {'recorded': True}
        if method == 'role_tool_specs':
            # A role session gets her tools as its conversation shows them (ADR-079 §9.7), fixed for the session.
            from .evidence import canonical
            from .role_tools import all_specs, declared_specs, session_specs
            record = (session_records.get(self.app.store, args['session_id'], native=True)
                      if args.get('session_id') else None)
            if not record:
                return declared_specs(all_specs())
            strict = session_specs(self.app.store, record['scene_id'], record.get('person_id'))
            speak = next((spec for spec in strict if spec['name'] == 'speak'), None)
            specs = declared_specs(strict)          # what DSH registers and the model reads (ADR-108 D4b)
            self.app.store.audit(record['_id'], 'session.tools', {
                'sha256': sha(canonical(specs)),
                'speak_parts': speak['parameters']['parts']['items']['properties']['kind'].get('enum') if speak else None,
                'quote': bool(speak and 'quote' in speak['parameters'])}, record.get('scope_key', 'operator'))
            return specs
        if method == 'role_tool_aliases':
            from .role_tools import aliases
            return aliases()
        if method == 'role_tool':
            # Her call in a character turn (ADR-011 §3): answered by the coordinator's own thread, which is
            # waiting on this very turn (NativeLane.wait). A refusal is her own to correct, not an error.
            from .role_tools import Refused
            record = self.session(args['session_id'])
            if record['lane'] != 'character':
                raise Denied('ROLE_SESSION_REQUIRED')
            with self.pending_lock:
                future = self.pending.get(args.get('operation'))
                if not future or future.done():
                    raise Denied('NATIVE_OPERATION_NOT_ACTIVE')
                if future.asuna_lane != 'character' or future.asuna_session_id != args['session_id']:
                    raise Denied('NATIVE_OPERATION_SESSION_MISMATCH')
            reply = Future()
            future.asuna_calls.put(({'call_id': args['call_id'], 'tool': args['tool'], 'args': args.get('args'),
                                     **({'thinking': args['thinking']} if isinstance(args.get('thinking'), dict) else {})},
                                    reply))
            try:
                value, conclude = reply.result(timeout=self.app.config['workflow_timeout_seconds'])
            except Refused as exc:
                return {'refused': str(exc)}
            return {'value': value, 'conclude': bool(conclude)}
        if method == 'persona.sources':
            # Settings card: source roots (path masked to its last segment), states, jobs and recent runs.
            from . import audit as audit_trail
            from .persona_data import persona_sources, persona_runtime
            from .render import render_status
            persona = self.app.config['chat']['persona']
            sources = [{'id': k, 'state': v['state'], 'path': '…/' + Path(v['path']).name}
                       for k, v in persona_sources(self.app.config, persona).items()]
            jobs = [{'id': j['id'], 'sources': j['sources'], 'grants': j['grants']}
                    for j in (self.app.config.get('persona_contribution') or {}).get('jobs') or []]
            runs = [{k: e['payload'].get(k) for k in ('run_id', 'job', 'status', 'exit_code', 'dry_run', 'counts', 'report_artifact_ids')}
                    for e in audit_trail.events(self.app.store, 'persona_job.finished').rows(newest_first=True, limit=5)]
            return {'persona': persona, 'sources': sources, 'jobs': jobs, 'runs': runs,
                    'export_configured': bool(persona_runtime(self.app.config, persona).get('export_dir')),
                    'render': render_status(self.app.store, persona)}
        if method == 'persona.export':
            # Owner-only rendering of the document layer to the locally configured directory.
            from .persona_data import export_documents, persona_runtime
            persona = self.app.config['chat']['persona']
            target = persona_runtime(self.app.config, persona).get('export_dir')
            if not target:
                raise ValueError('EXPORT_DIR_NOT_CONFIGURED')
            return export_documents(self.app.store, persona, target, ROOT)
        if method == 'persona.job_run':
            from .persona_jobs import JobRunner
            persona = self.app.config['chat']['persona']
            return JobRunner(self.app.store, persona, retrieval=self.app.retrieval).run(
                args['job'], dry_run=bool(args.get('dry_run', True)), args=args.get('args') or {})
        if method == 'affect.import':
            # Persona-job import path (exposed through the persona data API in P4).
            from .affect import AffectLedger
            from .render import model_and_policy
            persona = self.app.config['chat']['persona']
            return AffectLedger(self.app.store, persona, *model_and_policy(self.app.store, persona)).import_batch(
                args['origin'], args.get('events', []), args.get('amendments', []), dry_run=bool(args.get('dry_run')))
        if method == 'schedule.deliver':
            if not self.host.schedule:
                raise RuntimeError('SCHEDULE_NOT_MOUNTED')
            return self.host.schedule.deliver(args)
        if method == 'persona.check':
            # A persona publication is read as persona.resources and the next start take it, before it is selected:
            # one this worker would refuse is never selected or committed (floor.js prepare).
            try:
                read_persona(self.app.config, args['persona'])
            except ValueError as exc:
                return {'refused': '%s：正在跑的这个工作进程装不上这个人格包，这次没有选用也没有提交；照这个改了再发布' % exc}
            return {'refused': None}
        if method == 'persona.resources':
            # A persona publication applies in place: her model and contribution now, her skills in new action scopes.
            model, folders = self.app.config.get('persona_model'), self.app.config.get('_skill_directories')
            take_persona(self.app.config, args['persona'])
            self.app.config['_skill_directories'] = args['skill_directories']
            # A published adapter is what the next integration_start (or restoration) runs.
            releases = [entry['integration_release'] for entry in args.get('channels') or () if entry.get('integration_release')]
            if releases:
                self.app.config['_native_integration_release'] = releases[0]
            return {'accepted': True, 'applied': [
                'persona model swapped' if self.app.config['persona_model'] != model else 'persona model unchanged',
                'skills swapped: new action scopes read them from this package' if args['skill_directories'] != folders
                else 'skills unchanged', 'existing self heads preserved']}
        if method == 'publication.activated':
            for publication in args['publications']:
                receipt_id = publication['receipt_id']
                prior = receipt_records.sink_get(self.app.store, receipt_id)
                if prior:
                    receipt_records.save_sink(self.app.store, {**prior, 'state': 'ACTIVE',
                        'activated_at': publication['activated_at']}, expected=prior['revision'], stream=prior.get('task_id', receipt_id))
                else:
                    # Recovery has a real native source, but is not a fabricated
                    # role task. Its activation stays in its own receipt stream.
                    receipt_records.save_sink(self.app.store, {**publication, '_id': receipt_id,
                        'kind': 'native_recovery_publish'}, stream=receipt_id)
            self.host._complete_activations()
            self.host.activation_settled.set()
            return {'accepted': True}
        raise ValueError('UNKNOWN_BUSINESS_METHOD')

    def close(self):
        self.stopping.set()
        with self.pending_lock:
            for future in [*self.pending.values(), *self.host_pending.values()]:
                if not future.done():
                    future.set_exception(RuntimeError('DSH_HOST_DISCONNECTED'))
        self.stack.close()


class NativeScheduleLane:
    """Only transports business operations to the Host's native scheduler."""
    def __init__(self, worker, config):
        self.worker = worker
        self.scheduler_session = 'asuna-scheduler-' + sha(config['database'].encode())[:24]

    def schedule(self, path, payload=None):
        return self.worker.host_call('schedule', {
            'session_id': self.scheduler_session, 'path': path, 'payload': payload or {}})

    def close(self):
        pass


class NativeDevelopmentBridge:
    """Keep source publication available even when this worker cannot import."""
    PAGE_BYTES = 262144

    def __init__(self, worker, config, store):
        self.worker, self.config, self.store = worker, config, store

    # development_run's own time in the Host (floor.js: 35 s unless the call gives 1..600) and the room after it.
    RUN_SECONDS, RUN_SPARE_SECONDS = 35, 60

    @classmethod
    def wait_seconds(cls, tool, args):
        """How long to wait for the Host's answer: a command runs as long as it was given there and then returns what
        it printed, so the wait covers that time; every other development tool answers within the Host's 90 s."""
        if tool != 'development_run':
            return 120
        given = args.get('timeout')
        return (given if type(given) is int and 1 <= given <= 600 else cls.RUN_SECONDS) + cls.RUN_SPARE_SECONDS

    def call(self, task, tool, args):
        from . import visibility
        scene = scene_records.get(self.store, task['scene_id']) or {'_id': task['scene_id']}
        if not task.get('development_grant') or visibility.session_class(
                self.config, self.store, scene, task['requester_id']) != visibility.OWNER_PRIVATE:
            from .tasks import capability_refusal
            raise Denied(capability_refusal(self.store, task, tool))
        if tool == 'development_database_read':
            from .state import COLLECTIONS
            from . import dbread
            collection=args.get('collection')
            query=args.get('filter',{}); projection=args.get('projection')
            skip=args.get('skip',0);limit=args.get('limit',20);sort=args.get('sort')
            if collection not in COLLECTIONS:
                # Not a permission: the name does not exist. Say which do, and where the common guesses live.
                raise Denied('DEVELOPMENT_COLLECTION_DENIED: 没有集合 %r；有的是 %s。关系、文档和自我描述都是 '
                             'state_heads/state_revisions 里的行；collection 照抄其中一个' % (collection, ', '.join(COLLECTIONS)))
            if not isinstance(query,dict) or projection is not None and not isinstance(projection,dict):
                raise ValueError('DEVELOPMENT_QUERY_INVALID: filter 要是对象（给的是 %s），projection 要是对象或不写（给的是 %s）；'
                                 '例如 filter {"kind": "x"}，projection {"text": 1}'
                                 % (type(query).__name__, type(projection).__name__))
            if type(skip) is not int or skip<0 or type(limit) is not int or not 1<=limit<=50:
                raise ValueError('DEVELOPMENT_PAGE_INVALID: skip 要是 0 或更大的整数，limit 要是 1..50 的整数；给的是 skip=%s，limit=%s'
                                 % (str(skip)[:20], str(limit)[:20]))
            if sort is not None and (not isinstance(sort,dict) or any(v not in (1,-1) for v in sort.values())):
                raise ValueError('DEVELOPMENT_SORT_INVALID: sort 要写成 {字段: 1 或 -1}，例如 {"created_at": -1}；给的是 %s'
                                 % json.dumps(sort, ensure_ascii=False, default=str)[:120])
            # Her own filter/projection/sort, in MongoDB's syntax, read by her MongoDB read tool (dbread); one MongoDB
            # refuses comes back as its short reason (QueryInvalid, a ValueError), never the server's full reply.
            rows=dbread.development_rows(self.store.config,self.store.name,collection,query,projection,sort,skip,
                                         limit)
            size=len(json.dumps(rows,ensure_ascii=False,default=str).encode())
            if size>self.PAGE_BYTES:
                raise ValueError('DEVELOPMENT_PAGE_TOO_LARGE: 这一页 %d 行有 %.1f KiB，上限 %d KiB；limit 改小（比如 %d），'
                                 '或用 projection 只取要的字段' % (len(rows), size/1024, self.PAGE_BYTES//1024,
                                                             max(1, limit*self.PAGE_BYTES//size)))
            return {'database':self.store.name,'collection':collection,'skip':skip,'limit':limit,'rows':rows}
        try:
            from . import errands
            episode = errands.home_turn(self.store, episode_records.get(self.store, task.get('episode_id'))) or {}
            result = self.worker.host_call('development', {'tool':tool,'args':args, 'origin': {
                'task_id': task['_id'], 'scope_key': task['scope_key'], 'intent_revision': task['intent_revision'],
                # A self-improvement turn runs with nobody present (ADR-021 D4: it never publishes onto a waiting change).
                'unattended': episode.get('episode_kind') == 'self_development'},
                # Her publication is committed in the checkout under her own git name (`character_git`).
                **({'author': self.store.config.get('character_git')} if tool == 'development_publish' else {})},
                timeout=self.wait_seconds(tool, args))
        except RuntimeError as exc:
            if tool == 'development_write' and 'EEXIST' in str(exc):
                raise ValueError('DEVELOPMENT_FILE_EXISTS: %s 已经存在；要替换就加 overwrite: true，要保留就换个路径'
                                 % str(args.get('path'))[:200]) from None
            raise
        if tool == 'development_publish' and result.get('receipt_id'):
            receipt_records.save_sink(self.store, {
                **result, '_id':result['receipt_id'], 'kind':'self_development_publish',
                'scope_key':task['scope_key'], 'task_id':task['_id'],
                'intent_revision':task['intent_revision']}, stream=task['_id'])
            # The Host selects only a project's newest publication: an earlier one still waiting to start
            # never will. Left APPLIED, it would keep asking for a worker restart that never activates it.
            for older in receipt_records.sink_of_kind(self.store, 'self_development_publish',
                    project=result.get('project'), states=['APPLIED','HOST_RESTART_REQUIRED'],
                    besides=result['receipt_id']).each():
                receipt_records.save_sink(self.store, {**older, 'state':'SUPERSEDED', 'superseded_by':result['receipt_id'],
                    'superseded_at':clock.now().isoformat()},
                    expected=older['revision'], stream=older.get('task_id', older['_id']))
            if result['state'] == 'ACTIVE':
                self.worker.host._complete_activations()
        return result


# A coded refusal ("CODE: cause; what to do") is written for whoever reads it and goes out as it is.
# Anything else is a fault in the program, named by its class; a brain calling a tool is told so,
# because its arguments are not the cause and the same call will fail the same way.
CODED = re.compile(r'[A-Z][A-Z0-9]*_[A-Z0-9_]+(?::|$)')
TOOL_METHODS = frozenset({'tool', 'role_tool'})


def error_text(method, exc, message=None):
    message = str(exc) if message is None else message
    if CODED.match(message):
        return message
    fault = type(exc).__name__ + (': ' + message if message else '')
    if method in TOOL_METHODS:
        return ('TOOL_FAULT: 程序内部出错（%s），不是参数写错；同样的调用会一样失败：'
                '换个做法，或者把这一步没做成写进结果。' % fault[:600])
    return fault


# Host replies only complete a waiting Future: handled on the reader thread, never queued behind
# their own waiters. Calls that may wait for a host reply (a CONSULT stage, a development host
# call) or run long (persona jobs) get their own thread. So no dispatch-pool thread ever waits on
# Future.result(), and a pool of any size cannot deadlock (ADR-009 D-8, T7.2).
REPLIES = frozenset({'result', 'host_result'})
DETACHED = frozenset({'tool', 'role_tool', 'persona.job_run'})


class Dispatcher:
    def __init__(self, worker, threads=8):
        self.worker = worker
        self.pool = ThreadPoolExecutor(max_workers=threads, thread_name_prefix='asuna-dispatch')

    def respond(self, request):
        worker = self.worker
        try:
            value = worker.dispatch(request['method'], request.get('args', {}))
            worker.emit({'id': request['id'], 'value': value})
        except Exception as exc:
            message = str(exc)
            if worker.app:
                message = redact_text(message, worker.app.config)
            # Validation/initialization can fail before an Application exists.
            # Private proposed credentials must not escape through that error.
            for value in request.get('args', {}).get('secrets', {}).values():
                if isinstance(value, str) and value:
                    message = message.replace(value, '[凭据已隐藏]')
            worker.emit({'id': request['id'], 'error': error_text(request.get('method'), exc, message)})

    def handle(self, request):
        method = request.get('method')
        if method in REPLIES:
            self.respond(request)
        elif method in DETACHED:
            threading.Thread(target=self.respond, args=(request,), name='asuna-call-' + method,
                             daemon=True).start()
        else:
            self.pool.submit(self.respond, request)

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=True)


def serve(stream, dispatcher, record):
    """The Host's requests, one JSON line each. A line that is not a request is recorded and skipped: one bad line
    must not end the worker, and with it every running turn and task. Returns when the Host closes the pipe."""
    for line in stream:
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError('NOT_A_REQUEST')
        except ValueError as exc:
            # Never the line itself: it may carry her words or a credential.
            record('host.input_rejected', {'error': type(exc).__name__ + ': ' + str(exc)[:200], 'chars': len(line)})
            continue
        dispatcher.handle(request)
    record('host.input_closed', {})


def main():
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        stream.reconfigure(encoding='utf-8')
    argparse.ArgumentParser(description=__doc__).parse_args()
    worker = BusinessWorker()
    dispatcher = Dispatcher(worker)

    def record(kind, payload):
        evidence = getattr(worker.app, 'evidence', None) if worker.app else None
        if evidence:
            evidence.record(kind, payload)
        else:
            print(kind, json.dumps(payload), file=sys.stderr, flush=True)
    try:
        serve(sys.stdin, dispatcher, record)
    finally:
        worker.close()
        dispatcher.close()


if __name__ == '__main__':
    main()
