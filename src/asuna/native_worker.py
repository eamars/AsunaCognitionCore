"""Private business worker for the DSH Host plugin; no model or Web runtime.

The existing Coordinator prepares a stage and consumes its real result on its
queue thread. A NativeLane yields that request across stdio, releasing the Host
hook to run the native loop. It never calls an agent or waits inside its loop.
"""
from __future__ import annotations

import argparse
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from contextlib import ExitStack, nullcontext
import json
from pathlib import Path
from queue import Queue, Empty
import re
import sys
import threading
import time
import uuid

from . import channel_kinds
from .application import Application
from .host import RuntimeHost
from .config import ROOT, load, redact_text
from .evidence import Evidence, sha
from .lanes import LaneResult
from .grants import workspace_grant
from .people import People
from .skills import skill_directories
from .state import Denied, now, Conflict
from .queue import RuntimeLease
from .tasks import WORKSPACE_TOOLS, INTEGRATION_TOOLS, DEVELOPMENT_TOOLS, PERSONA_JOB_TOOLS


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
            role = self.store.db.sessions.find_one({'_id': role_id}, {'native_title': 1}) or {}
            return role.get('native_title') or ep['scene_id']
        return None

    def generate(self, binding, operation, phase, text, system, tools=None, handler=None, **kwargs):
        """One stage of a native turn. A character turn exposes `tools`: each call she makes reaches
        `handler` on this thread (role_tools.py) while the turn waits for its result."""
        with self.lock:
            prior = self.store.db.lane_receipts.find_one({'_id': operation})
            if prior and prior.get('native_host'):
                # A completed stage is final: its receipt answers a repeat without reopening the stage.
                return LaneResult(**{k: v for k, v in prior['result'].items() if k in LaneResult.__dataclass_fields__})
            if not self.worker.navigation_ready.wait(self.store.config['workflow_timeout_seconds']):
                raise RuntimeError('NATIVE_NAVIGATION_NOT_READY')
            task = None
            # A repair (answers.py) is the same stage asked again in the same session: parse its base operation.
            base = re.sub(r':fix-\d+$', '', operation)
            if self.lane == 'summary':
                scene = self.store.db.scenes.find_one({'scope_key': kwargs['scope_key'],
                                                       'policy_epoch': kwargs['policy_epoch']})
                if not scene:
                    raise Denied('SUMMARY_SCENE_STALE')
                person = scene['members'][0]
                self.store.authorize(scene['_id'], person)
                ep = {'_id': base, 'scene_id': scene['_id'], 'person_id': person,
                      'scope_key': scene['scope_key'], 'policy_epoch': scene['policy_epoch'],
                      'character_context': scene.get('character_context'),
                      'persona': self.store.config['chat']['persona']}
                ep['native_session_id'] = self.worker.resolve_role_session(ep)
            elif self.lane == 'executor' or phase == 'CONSULT':
                task_id = base.split(':execute:', 1)[0].split(':consult:', 1)[0]
                task = self.store.db.tasks.find_one({'_id': task_id})
                if not task:
                    raise Denied('STALE_TASK_FENCE')
                if self.lane == 'executor':
                    if base.split(':execute:', 1)[1].split(':', 1)[0] != str(task['intent_revision']):
                        raise Denied('STALE_TASK_FENCE')
                else:
                    artifact = self.store.db.artifacts.find_one({'_id':base.split(':consult:',1)[1],
                        'task_id':task_id,'intent_revision':task['intent_revision']})
                    if not artifact:
                        raise Denied('STALE_TASK_FENCE')
                ep = self.store.db.episodes.find_one({'_id': task['episode_id']})
            else:
                ep = self.store.db.episodes.find_one({'_id': base.split(':', 1)[0]})
            if not ep:
                raise ValueError('NATIVE_EPISODE_BINDING_REQUIRED')
            role_id = ep.get('native_session_id')
            if not role_id:
                raise ValueError('NATIVE_ROLE_SESSION_REQUIRED')
            role_id = self.worker.continued_session(role_id)
            if self.lane == 'executor':
                native_id = self.worker.action_session_id(binding, role_id, ep, task)
            elif self.lane == 'summary':
                native_id = 'asuna-summary-' + sha((binding + ':' + base).encode())[:32]
            elif self.lane == 'appraiser':
                native_id = 'asuna-appraiser-' + ep['persona']
            elif self.lane == 'attend':
                # One small gate session per group, shared by everyone who speaks there (attend.py).
                native_id = 'asuna-attend-' + sha(ep['scene_id'].encode())[:24]
            else:
                native_id = role_id
            if self.lane == 'appraiser':
                # One tool-free appraiser session per persona, owned by the local operator scene;
                # each request carries only that episode's own visible material.
                local = self.store.config['chat']
                owner = self.store.authorize(local['scene_id'], local['person_id'])
                grant, ep = local, {**ep, 'scene_id': owner['_id'], 'person_id': local['person_id'],
                                    'scope_key': owner['scope_key'], 'policy_epoch': owner['policy_epoch']}
            else:
                grant = workspace_grant(self.store.config, ep['scene_id'], ep['person_id'])
            platform = channel_kinds.of(ep['scene_id'])
            cwd = (self.worker.channel_workspace(platform) if self.lane in ('character', 'attend') and platform
                   else str(Path(grant['workspace']).resolve()))
            record = self.worker.bind_session(native_id, {
                'lane': self.lane, 'scene_id': ep['scene_id'], 'person_id': ep['person_id'],
                'scope_key': ep['scope_key'], 'policy_epoch': ep['policy_epoch'],
                'character_context': ep.get('character_context'),
                'persona': ep['persona'], 'cwd': cwd,
                'role_session_id': role_id, 'task_id': task['_id'] if task else None,
                'parent_session_id': role_id if self.lane != 'character' else None,
                'broker_session': 's-' + sha(binding.encode())[:40],
                **({'execution_binding': binding} if self.lane == 'executor' else {}),
                'allowed_capabilities': task['allowed_capabilities'] if self.lane == 'executor' else [],
                'system_sha256': sha(system.encode()),
                'skill_directories': [str(path) for path in skill_directories(self.store.config, ep['scene_id'], ep['person_id'],
                                                                              self.store.db)],
            })
            scene_kind = (self.store.db.scenes.find_one({'_id': ep['scene_id']}, {'kind': 1}) or {}).get('kind')
            request = {'kind': 'stage', 'token': operation, 'session_id': native_id, 'scene_kind': scene_kind,
                       'lane': self.lane, 'phase': phase, 'text': text, 'system': system,
                       'episode_id': ep['_id'], 'binding': record, 'title': self.child_title(task, role_id, ep),
                       **({'tools': list(tools)} if tools is not None else {}),
                       **({'trigger': kwargs['trigger']} if kwargs.get('trigger') else {}),
                       **({'context': kwargs['context'], 'tail': kwargs['tail']} if 'context' in kwargs else {})}
            if self.lane == 'executor' and task:
                request['task'] = {'_id': task['_id'], 'thread': task.get('thread') or task['_id'],
                                   'title': task.get('title') or task.get('goal'),
                                   'parent_session_id': record['parent_session_id']}
            if self.lane == 'character':
                source = self.store.db.messages.find_one({'_id': 'in-' + ep['_id']})
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
            with self.worker.controller.ingress_lock, (self.worker.app.service.lock if task else nullcontext()), self.worker.pending_lock:
                if self.worker.controller.reconfiguring:
                    raise RuntimeError('HOST_RECONFIGURING')
                if task:self.worker.app.service.valid(task)
                if operation in self.worker.pending:
                    raise RuntimeError('NATIVE_OPERATION_ALREADY_RUNNING')
                self.worker.pending[operation] = future
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
                self.store.put('lane_receipts', {
                    '_id': operation, 'native_host': True, 'native_session_id': native_id,
                    'scope_key': ep['scope_key'], 'result': vars(result)}, stream=operation)
                return result
            finally:
                with self.worker.pending_lock:
                    self.worker.pending.pop(operation, None)
                if self.lane == 'executor':
                    self.worker.app.broker.bindings.pop(future.asuna_broker_session, None)

    def turn_done(self, ep):
        """Her turn has no further stage (coordinator._turn): the plugin ends the native turn."""
        if self.lane == 'character' and ep.get('native_session_id'):
            self.worker.emit({'kind': 'turn_done', 'session_id': self.worker.continued_session(ep['native_session_id']),
                              'episode_id': ep['_id']})

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
                reply.set_result(future.asuna_handler(call['call_id'], call['tool'], call.get('args') or {}))
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
    def __init__(self, config_path):
        self.config_path = config_path
        self.stack = ExitStack()
        self.pending = {}
        self.pending_lock = threading.Lock()
        self.output_lock = threading.Lock()
        self.navigation_ready = threading.Event()
        self.app = None
        self.controller = None
        self.host = None
        self.host_pending = {}
        self.stopping = threading.Event()

    def host_call(self, method, args):
        request_id = uuid.uuid4().hex
        future = Future()
        with self.pending_lock:
            self.host_pending[request_id] = future
        self.emit({'kind': 'host_request', 'request_id': request_id, 'method': method, 'args': args})
        try:
            return future.result(timeout=120)
        finally:
            with self.pending_lock:
                self.host_pending.pop(request_id, None)

    def emit(self, value):
        with self.output_lock:
            sys.stdout.write(json.dumps(value, ensure_ascii=False, default=str) + '\n')
            sys.stdout.flush()

    def initialize(self, persona, skill_directories=None, routes=None, models=None, integration_project=None, native_sessions=None,
                   deployment=None, secrets=None, admission='explicit', apply_integrations=False,
                   schedule=True, channels=None):
        # Worker initialization is managed by the native Host.
        if self.app:
            return self.status()
        # Channel plugins (e.g. @asuna/napcat-qq) bring their platform's id formats before any route is read.
        channel_kinds.load(channels)
        from .native_settings import runtime_settings
        config = (runtime_settings(deployment, secrets or {}, models, admission, create_dirs=True)
                  if deployment else load(self.config_path))
        # One Host per database: two Hosts may never run the same business queue
        # or publish the same scene concurrently.
        self.stack.enter_context(RuntimeLease(Path(config['dsh_home']) / config['database'] / 'host.lock'))
        # Existing state identity wins. Package defaults seed only absent heads.
        if config['chat']['persona'] != persona['id']:
            raise ValueError('PERSONA_STATE_ID_MISMATCH')
        config['chat'] = {**config['chat'], 'display_name': persona['display_name']}
        config['character_id'] = persona['character_id']
        config['persona_contribution'] = persona
        # The persona model is validated here (jsonschema); an invalid model keeps Core inert.
        from .persona_model import load as load_model, neutral
        config['persona_model'] = (load_model(persona['model'], persona['id']) if persona.get('model')
                                   else neutral(persona['id'], persona['display_name']))
        config['_skill_directories'] = skill_directories or persona.get('skill_directories', [])
        config['_native_routes'] = routes or {}
        for lane, key in (('character', 'character'), ('action', 'executor')):
            if models and lane in models:
                config[key] = {**config[key], **models[lane]}
        config['_integration_project'] = integration_project
        config['_native_apply_integrations'] = apply_integrations
        # The installed adapter release belongs to the channel plugin that ships it.
        releases = [entry['integration_release'] for entry in channels or () if entry.get('integration_release')]
        if releases:
            config['_native_integration_release'] = releases[0]
        evidence = Evidence(ROOT / 'reports' / ('native-host-' + uuid.uuid4().hex[:10]))
        def configure(host):
            self.app, self.controller = host.app, host.controller
            self.navigation = self.prepare_navigation(native_sessions or [])
            self.projection_start = self.app.store.db.artifacts.find_one({'_id': 'native-channel-projection'})
            if not self.projection_start:
                self.projection_start = self.app.store.put('artifacts', {'_id': 'native-channel-projection',
                    'kind': 'native-channel-projection', 'since': now(), 'scope_key': 'operator'}, stream='native-channel-projection')
            self.controller.on_input_received = self.project_input
            self.controller.on_episode_finished = self.episode_finished
            self.app.coordinator.native_session_resolver = self.resolve_role_session
            self.app.coordinator.on_collab = self.collab
            self.app.coordinator.on_action_message = self.action_message
            self.app.service.on_fenced = self.task_fenced
            self.app.service.on_collab = self.collab
        self.host = self.stack.enter_context(RuntimeHost(
            config, evidence, lane_factory=lambda *a: NativeLane(self, *a), broker_http=False,
            schedule_lane=NativeScheduleLane(self, config) if schedule else False, configure_controller=configure,
            development_factory=lambda c,s: NativeDevelopmentBridge(self,c,s), awaits_activation=True))
        self.watch = threading.Thread(target=self.watch_host, name='native-lifecycle', daemon=True)
        self.watch.start()
        return {**self.status(), 'navigation': self.navigation}

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
        bindings = list(store.db.sessions.find({'native_host': True}))
        first = not any(row.get('navigation_version') == 1 for row in bindings)
        entries, retire = [], set()
        for scene_id, person, workspace, title in scenes:
            scene = store.authorize(scene_id, person)
            scene_bindings = [row for row in bindings if row.get('lane') == 'character'
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
            prior = store.db.sessions.find_one({'_id': session_id})
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
                store.put('sessions', updated, expected=old['revision'], stream='native-binding:' + old['_id'])
        primary = {entry['session_id'] for entry in entries}
        for old in bindings:
            if old.get('main_conversation') and old['_id'] not in primary and old['_id'] not in retire:
                retire.add(old['_id'])
                store.put('sessions', {**old, 'main_conversation': False, 'retired': True},
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
        """The shared native workspace of one platform's conversations (.runtime/work/<kind>)."""
        directory = (ROOT / '.runtime' / 'work' / platform.KIND).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        return str(directory)

    @staticmethod
    def role_session_id(ep):
        key = json.dumps([ep['scene_id'], ep['persona'], ep['policy_epoch'],
                          ep.get('character_context')], sort_keys=True)
        return 'asuna-role-' + sha(key.encode())[:32]

    def continued_session(self, session_id):
        record = self.app.store.db.sessions.find_one({'_id': session_id}) or {}
        return record.get('successor_id', session_id)

    def action_session_id(self, binding, role_id, ep, task):
        """One native context per authorized execution binding, including old logs."""
        query = {
            'native_host': True, 'lane': 'executor',
            'broker_session': 's-' + sha(binding.encode())[:40],
            'parent_session_id': role_id, 'scene_id': ep['scene_id'],
            'scope_key': ep['scope_key'], 'policy_epoch': ep['policy_epoch'],
            'person_id': ep['person_id'], 'persona': ep['persona'],
        }
        # Prefer the immediately preceding task's source when importing an old
        # operation-scoped binding. Do not import another actor or policy epoch.
        prior = None
        for task_id in (task['_id'], task.get('continues_task_id')):
            if task_id:
                prior = self.app.store.db.sessions.find_one({**query, 'task_id': task_id},
                    sort=[('binding_updated_at', -1), ('_id', -1)])
                if prior: break
        if not prior:
            prior = self.app.store.db.sessions.find_one(query,
                sort=[('binding_updated_at', -1), ('_id', -1)])
        if prior:
            return prior['_id']
        identity = json.dumps([binding, role_id, ep['scene_id'], ep['scope_key'],
                               ep['policy_epoch'], ep['person_id'], ep['persona']], sort_keys=True)
        return 'asuna-action-' + sha(identity.encode())[:32]

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
            task = store.db.tasks.find_one({'_id': ep['task_id']})
            original = store.db.episodes.find_one({'_id': task['episode_id']}) if task else None
            if original and original.get('native_session_id'):
                return self.continued_session(original['native_session_id'])
        source = store.db.messages.find_one({'_id': 'in-' + ep['_id']}) or {}
        plan_id = source.get('event', {}).get('scheduled_plan_id')
        plan = store.db.plans.find_one({'_id': plan_id}) if plan_id else None
        original = store.db.episodes.find_one({'_id': plan.get('source_episode_id')}) if plan else None
        if original and original.get('native_session_id'):
            return self.continued_session(original['native_session_id'])
        primary = store.db.sessions.find_one({'native_host': True, 'main_conversation': True,
            'scene_id': ep['scene_id'], 'persona': ep['persona'], 'policy_epoch': ep['policy_epoch'],
            'character_context': ep.get('character_context')})
        session_id = primary['_id'] if primary else self.role_session_id(ep)
        store.audit(ep['_id'], 'native.context.bound', {
            'native_session_id': session_id, 'legacy_history': 'read-only',
            'context': 'new native conversation; no tool or message replay'}, ep['scope_key'])
        return session_id

    def status(self):
        integration = self.host.integration.status() if self.host and self.host.integration else {'state': 'DISABLED'}
        return {'ready': bool(self.app), 'persona': self.app.config['chat']['persona'] if self.app else None,
                'workspace': self.app.config['chat']['workspace'] if self.app else None,
                'transport': 'stdio', 'model_runtime': 'dsh-host',
                'channels_active': bool(self.host and getattr(self.host, 'channel_server', None)),
                'channel_titles': [kind.TITLE for kind in channel_kinds.kinds()],
                'schedules_active': bool(self.host and getattr(self.host, 'schedule', None)),
                'integration_active': integration['state'] == 'RUNNING',
                'integration_state': integration['state'], 'integration_error': integration.get('error'),
                'database': 'connected' if self.app else 'unavailable',
                'self_source': 'existing Mongo state heads' if self.app else None,
                'active_role': self.controller.active if self.controller else None,
                'queued_inputs': self.controller.pending.qsize() if self.controller else 0,
                'queued_tasks': self.controller.task_queue.qsize() if self.controller else 0,
                'active_task': self.controller.active_task if self.controller else None}

    @staticmethod
    def read_only_note(platform):
        return {'key': 'read_only', **({'platform': platform.TITLE} if platform else {})}

    def bind_session(self, session_id, values):
        prior = self.app.store.db.sessions.find_one({'_id': session_id})
        identity = ('lane', 'scene_id', 'persona', 'cwd')
        if values['lane'] not in ('character', 'attend'):       # a group's sessions serve everyone in it
            identity += ('person_id',)
        if prior and any(prior.get(k) != values.get(k) for k in identity):
            raise Denied('NATIVE_BINDING_IDENTITY_CHANGED')
        scene = self.app.store.authorize(values['scene_id'], values['person_id'])
        if scene['policy_epoch'] != values['policy_epoch']:
            raise Denied('NATIVE_SESSION_EPOCH_CHANGED')
        # Bindings keep a hash of the stage system prompt, never its full text.
        kept = {k: v for k, v in (prior or {}).items() if k != 'system'}
        return self.app.store.put('sessions', {
            **kept, **values, '_id': session_id, 'native_host': True,
            'binding_key': 'native-host:' + session_id,
            'binding_updated_at': now(),
        }, expected=prior['revision'] if prior else None, stream='native-binding:' + session_id)

    def session(self, session_id):
        record = self.app.store.db.sessions.find_one({'_id': session_id, 'native_host': True})
        if not record:
            raise Denied('NATIVE_SESSION_NOT_BOUND')
        scene = self.app.store.authorize(record['scene_id'], record['person_id'])
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
        original = self.app.store.db.episodes.find_one({'_id': task['episode_id']}, {'native_session_id': 1}) or {}
        return self.continued_session(original['native_session_id']) if original.get('native_session_id') else None

    def collab(self, task, entry):
        """One entry of the two brains' thread (ADR-011 §7.1); the plugin appends it to her conversation."""
        session_id = self.parent_session(task)
        if session_id:
            self.emit({'kind': 'collab', 'session_id': session_id, 'task_id': task['_id'],
                       'thread': task.get('thread') or task['_id'], 'title': task.get('title') or task.get('goal'),
                       'entry': entry})

    def action_message(self, task, message):
        """Her words for a running action session: steered in at its next step (ADR-011 §4)."""
        self.emit({'kind': 'action_message', 'task_id': task['_id'], 'thread': task.get('thread') or task['_id'],
                   'message': message})

    def episode_finished(self, event, result, error):
        if event.get('channel'):
            from .ingress import episode_id
            row = self.app.store.db.messages.find_one({'_id': 'in-' + episode_id(event)})
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
        if not self.app.store.db.sink_receipts.find_one({'_id': 'native-input:' + row['_id']}):
            self.emit({'kind': 'channel_input', **self.channel_input(row)})

    def channel_title(self, route):
        """Conversation title a person can read (content only): the configured name, else the group name or
        peer name the platform last sent with a message in that scene, else the number."""
        group = route['target']['type'] == 'group'
        name = route.get('display_name')
        if not name:
            last = self.app.store.db.messages.find_one(
                {'scene_id': route['scene_id'], 'direction': 'inbound', 'event.raw': {'$exists': True}},
                {'event.raw.group_name': 1, 'event.raw.asuna_peer': 1}, sort=[('received_at', -1)])
            raw = (last or {}).get('event', {}).get('raw', {})
            name = raw.get('group_name') if group else (raw.get('asuna_peer') or {}).get('display')
        name = ' '.join(str(name or '').split())[:40] or route['target']['id']
        return name

    def channel_input(self, row):
        """A real processed platform receipt, including quiet/error outcomes; never a model turn."""
        from .channels import route_for_scene
        store, config = self.app.store, self.app.config
        scene = store.authorize(row['scene_id'], row['author'])
        if row['policy_epoch'] != scene['policy_epoch']:
            raise Denied('NATIVE_SESSION_EPOCH_CHANGED')
        route = route_for_scene(config, row['event']['channel']['id'], row['scene_id'])
        ep = {'_id': row['episode_id'], 'scope_key': scene['scope_key'],
              'scene_id': scene['_id'], 'person_id': row['author'], 'persona': config['chat']['persona'],
              'policy_epoch': scene['policy_epoch'], 'character_context': scene.get('character_context')}
        session_id = self.resolve_role_session(ep)
        binding = store.db.sessions.find_one({'_id': session_id})
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
            config = runtime_settings(args['deployment'], args.get('secrets', {}), args['models'], args['admission'])
            if config['chat']['persona'] != args['persona']:
                raise ValueError('PERSONA_STATE_ID_MISMATCH')
            from .state import Store
            from .host import prepare_channels
            observer = Store(config)
            try:
                observer.client.admin.command('ping')
                from .channel_admission import restore_admissions
                restore_admissions(observer)
                prepare_channels(observer, dry_run=True)
            finally:
                observer.client.close()
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
        if method == 'navigation.ready':
            for entry in self.navigation['entries']:
                record = self.app.store.db.sessions.find_one({'_id': entry['session_id']})
                if record.get('navigation_version') != 1:
                    self.app.store.put('sessions', {**record, 'navigation_version': 1},
                        expected=record['revision'], stream='native-binding:' + record['_id'])
            self.navigation_ready.set()
            # Recover only native projection work, never model/tool execution.
            # Historical business rows predating this feature remain in Memory.
            for row in self.app.store.db.messages.find({'host_managed': True,
                    'received_at': {'$gte': self.projection_start['since']},
                    'event.channel': {'$exists': True}}).sort('received_at', 1):
                try:
                    self.project_input(row)
                except Denied:
                    pass  # Revoked scenes must not project into a new epoch.
            return {'ready': True}
        if method == 'channel_input.ack':
            row = self.app.store.db.messages.find_one({'_id': args['input_id'], 'event.channel': {'$exists': True}})
            if not row:
                raise ValueError('NATIVE_INPUT_NOT_FOUND')
            receipt_id = 'native-input:' + row['_id']
            if not self.app.store.db.sink_receipts.find_one({'_id': receipt_id}):
                try:
                    self.app.store.put('sink_receipts', {'_id': receipt_id, 'kind': 'native_input_projection',
                        'input_id': row['_id'], 'native_session_id': args['session_id'],
                        'scope_key': row['scope_key'], 'policy_epoch': row['policy_epoch']}, stream=receipt_id)
                except Conflict:
                    if not self.app.store.db.sink_receipts.find_one({'_id': receipt_id}):
                        raise
            return {'recorded': True}
        if method == 'input_policies':
            local = self.app.config['chat']
            ids = [row['id'] for row in args['sessions']]
            # Keys of the client's input words (ADR-011 §2.8): a platform's read-only view, or an internal session.
            policies = {row['_id']: (self.read_only_note(channel_kinds.of(row['scene_id'])) if row['scene_id'] != local['scene_id']
                else {'key': 'internal'})
                for row in self.app.store.db.sessions.find({'_id': {'$in': ids}, 'native_host': True})
                if row['scene_id'] != local['scene_id'] or row['lane'] != 'character'
                or row.get('successor_id') or row.get('retired')}
            for row in args['sessions']:
                for platform in channel_kinds.kinds():
                    if row.get('cwd') and Path(row['cwd']).resolve() == (ROOT / '.runtime/work' / platform.KIND).resolve():
                        policies[row['id']] = self.read_only_note(platform)
            return policies
        if method == 'input':
            session_id = args['session_id']
            existing = self.app.store.db.sessions.find_one({'_id': session_id})
            local = self.app.config['chat']
            if not args.get('cwd') or Path(args['cwd']).resolve() != Path(local['workspace']).resolve():
                raise Denied('NATIVE_INPUT_WORKSPACE_MISMATCH')
            if existing and existing.get('successor_id'):
                raise Denied('NATIVE_CONVERSATION_CONTINUED: ' + existing['successor_id'])
            if existing and existing.get('retired'):
                raise Denied('NATIVE_CONVERSATION_RETIRED')
            if existing and (existing['scene_id'], existing['person_id'], existing['lane']) != (
                    local['scene_id'], local['person_id'], 'character'):
                raise Denied('NATIVE_INPUT_SOURCE_MISMATCH')
            return self.controller.submit(args['text'], event_id=args['message_ids'][0],
                native_session_id=session_id, native_message_ids=args['message_ids'])
        if method == 'result':
            with self.pending_lock:
                future = self.pending.get(args['token'])
                if not future:
                    raise ValueError('NATIVE_OPERATION_NOT_WAITING')
                if not future.done():
                    if args.get('error'):
                        future.set_exception(RuntimeError(args['error']))
                    else:
                        future.set_result(args['result'])
            return {'accepted': True}
        if method == 'session':
            return self.session(args['session_id'])
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
            return self.app.broker.call(broker_session, args['call_id'], args['tool'], args['args'])
        if method == 'tool_specs':
            return [*WORKSPACE_TOOLS, *INTEGRATION_TOOLS, *DEVELOPMENT_TOOLS, *PERSONA_JOB_TOOLS]
        if method == 'action_message.delivered':
            # The action session read her message at a step (index.js): no extra round needed for it.
            row = self.app.store.db.task_messages.find_one({'_id': args['message_id'], 'from': 'character'})
            if row and not row.get('delivered'):
                self.app.store.put('task_messages', {**row, 'delivered': True, 'delivered_at': now()},
                                   expected=row['revision'], stream=row['task_id'])
            return {'recorded': True}
        if method == 'role_tool_specs':
            from .role_tools import all_specs
            return all_specs()
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
            future.asuna_calls.put(({'call_id': args['call_id'], 'tool': args['tool'], 'args': args.get('args')}, reply))
            try:
                value, conclude = reply.result(timeout=self.app.config['workflow_timeout_seconds'])
            except Refused as exc:
                return {'refused': str(exc)}
            return {'value': value, 'conclude': bool(conclude)}
        if method == 'persona.sources':
            # Settings card: source roots (path masked to its last segment), states, jobs and recent runs.
            from .persona_data import persona_sources, persona_runtime
            from .render import render_status
            persona = self.app.config['chat']['persona']
            sources = [{'id': k, 'state': v['state'], 'path': '…/' + Path(v['path']).name}
                       for k, v in persona_sources(self.app.config, persona).items()]
            jobs = [{'id': j['id'], 'sources': j['sources'], 'grants': j['grants']}
                    for j in (self.app.config.get('persona_contribution') or {}).get('jobs') or []]
            runs = [{k: e['payload'].get(k) for k in ('run_id', 'job', 'status', 'exit_code', 'dry_run', 'counts', 'report_artifact_ids')}
                    for e in self.app.store.db.audit_events.find({'type': 'persona_job.finished'}).sort('occurred_at', -1).limit(5)]
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
        if method == 'persona.resources':
            self.app.config['_skill_directories'] = args['skill_directories']
            # A published adapter is what the next integration_start (or restoration) runs.
            releases = [entry['integration_release'] for entry in args.get('channels') or () if entry.get('integration_release')]
            if releases:
                self.app.config['_native_integration_release'] = releases[0]
            return {'accepted': True, 'applies': 'new action scopes; existing self heads preserved'}
        if method == 'publication.activated':
            for publication in args['publications']:
                receipt_id = publication['receipt_id']
                prior = self.app.store.db.sink_receipts.find_one({'_id': receipt_id})
                if prior:
                    self.app.store.put('sink_receipts', {**prior, 'state': 'ACTIVE',
                        'activated_at': publication['activated_at']}, expected=prior['revision'], stream=prior.get('task_id', receipt_id))
                else:
                    # Recovery has a real native source, but is not a fabricated
                    # role task. Its activation stays in its own receipt stream.
                    self.app.store.put('sink_receipts', {**publication, '_id': receipt_id,
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
    def __init__(self, worker, config, store):
        self.worker, self.config, self.store = worker, config, store

    def call(self, task, tool, args):
        from . import visibility
        scene = self.store.db.scenes.find_one({'_id': task['scene_id']}) or {'_id': task['scene_id']}
        if not task.get('development_grant') or visibility.session_class(
                self.config, self.store.db, scene, task['requester_id']) != visibility.OWNER_PRIVATE:
            raise Denied('DEVELOPMENT_GRANT_REQUIRED')
        if tool == 'development_database_read':
            from .state import COLLECTIONS
            collection=args.get('collection')
            query=args.get('filter',{}); projection=args.get('projection')
            skip=args.get('skip',0);limit=args.get('limit',20)
            if collection not in COLLECTIONS: raise Denied('DEVELOPMENT_COLLECTION_DENIED')
            if not isinstance(query,dict) or projection is not None and not isinstance(projection,dict):
                raise ValueError('DEVELOPMENT_QUERY_INVALID')
            if type(skip) is not int or skip<0 or type(limit) is not int or not 1<=limit<=50:
                raise ValueError('DEVELOPMENT_PAGE_INVALID')
            rows=list(self.store.db[collection].find(query,projection).skip(skip).limit(limit))
            if len(json.dumps(rows,ensure_ascii=False,default=str).encode())>262144:
                raise ValueError('DEVELOPMENT_PAGE_TOO_LARGE')
            return {'database':self.store.name,'collection':collection,'skip':skip,'limit':limit,'rows':rows}
        result = self.worker.host_call('development', {'tool':tool,'args':args, 'origin': {
            'task_id': task['_id'], 'scope_key': task['scope_key'], 'intent_revision': task['intent_revision']}})
        if tool == 'development_publish' and result.get('receipt_id'):
            self.store.put('sink_receipts', {
                **result, '_id':result['receipt_id'], 'kind':'self_development_publish',
                'scope_key':task['scope_key'], 'task_id':task['_id'],
                'intent_revision':task['intent_revision']}, stream=task['_id'])
            # The Host selects only a project's newest publication: an earlier one still waiting to start
            # never will. Left APPLIED, it would keep asking for a worker restart that never activates it.
            for older in self.store.db.sink_receipts.find({'kind':'self_development_publish',
                    'project':result.get('project'), 'state':{'$in':['APPLIED','HOST_RESTART_REQUIRED']},
                    '_id':{'$ne':result['receipt_id']}}):
                self.store.put('sink_receipts', {**older, 'state':'SUPERSEDED', 'superseded_by':result['receipt_id'],
                    'superseded_at':datetime.now(timezone.utc).isoformat()},
                    expected=older['revision'], stream=older.get('task_id', older['_id']))
            if result['state'] == 'ACTIVE':
                self.worker.host._complete_activations()
        return result


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
            worker.emit({'id': request['id'], 'error': type(exc).__name__ + ': ' + message})

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


def main():
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    worker = BusinessWorker(args.config)
    dispatcher = Dispatcher(worker)
    try:
        for line in sys.stdin:
            dispatcher.handle(json.loads(line))
    finally:
        worker.close()
        dispatcher.close()


if __name__ == '__main__':
    main()
