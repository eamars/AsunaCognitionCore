"""Private business worker for the DSH Host plugin; no model or Web runtime.

The existing Coordinator prepares a stage and consumes its real result on its
queue thread. A NativeLane yields that request across stdio, releasing the Host
hook to run the native loop. It never calls an agent or waits inside its loop.
"""
from __future__ import annotations

import argparse
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import threading
import uuid

from .application import Application
from .host import RuntimeHost
from .config import ROOT, load, redact_text
from .evidence import Evidence, sha
from .lanes import LaneResult
from .resources import workspace_grant
from .queue import RuntimeLease
from .skills import skills_directory, skill_directories
from .state import Denied, now, Conflict
from .tasks import WORKSPACE_TOOLS, INTEGRATION_TOOLS, DEVELOPMENT_TOOLS


class NativeLane:
    def __init__(self, worker, config, store, evidence, lane='character', *args):
        self.worker, self.store, self.lane = worker, store, lane
        self.model = {**config['character' if lane == 'character' else 'executor'],
                      **config.get('_native_routes', {}).get('character' if lane == 'character' else 'action', {})}
        self.lock = threading.RLock()

    def generate(self, binding, operation, phase, text, system, **kwargs):
        with self.lock:
            prior = self.store.db.lane_receipts.find_one({'_id': operation})
            if prior and prior.get('native_host'):
                return LaneResult(**prior['result'])
            if not self.worker.navigation_ready.wait(self.store.config['workflow_timeout_seconds']):
                raise RuntimeError('NATIVE_NAVIGATION_NOT_READY')
            task = None
            if self.lane == 'summary':
                scene = self.store.db.scenes.find_one({'scope_key': kwargs['scope_key'],
                                                       'policy_epoch': kwargs['policy_epoch']})
                if not scene:
                    raise Denied('SUMMARY_SCENE_STALE')
                person = scene['members'][0]
                self.store.authorize(scene['_id'], person)
                ep = {'_id': operation, 'scene_id': scene['_id'], 'person_id': person,
                      'scope_key': scene['scope_key'], 'policy_epoch': scene['policy_epoch'],
                      'character_context': scene.get('character_context'),
                      'persona': self.store.config['chat']['persona']}
                ep['native_session_id'] = self.worker.resolve_role_session(ep)
            elif self.lane == 'executor' or phase == 'CONSULT':
                task_id = operation.split(':execute:', 1)[0].split(':consult:', 1)[0]
                task = self.store.db.tasks.find_one({'_id': task_id})
                ep = self.store.db.episodes.find_one({'_id': task['episode_id']})
            else:
                ep = self.store.db.episodes.find_one({'_id': operation.split(':', 1)[0]})
            if not ep:
                raise ValueError('NATIVE_EPISODE_BINDING_REQUIRED')
            role_id = ep.get('native_session_id')
            if not role_id:
                raise ValueError('NATIVE_ROLE_SESSION_REQUIRED')
            role_id = self.worker.continued_session(role_id)
            native_id = (('asuna-action-' if self.lane == 'executor' else 'asuna-summary-')
                         + sha((binding + ':' + operation).encode())[:32]
                         if self.lane != 'character' else role_id)
            grant = workspace_grant(self.store.config, ep['scene_id'], ep['person_id'])
            cwd = (self.worker.qq_workspace if self.lane == 'character' and ep['scene_id'].startswith('qq:')
                   else str(Path(grant['workspace']).resolve()))
            record = self.worker.bind_session(native_id, {
                'lane': self.lane, 'scene_id': ep['scene_id'], 'person_id': ep['person_id'],
                'scope_key': ep['scope_key'], 'policy_epoch': ep['policy_epoch'],
                'character_context': ep.get('character_context'),
                'persona': ep['persona'], 'cwd': cwd,
                'role_session_id': role_id, 'task_id': task['_id'] if task else None,
                'parent_session_id': role_id if self.lane != 'character' else None,
                'broker_session': 's-' + sha(binding.encode())[:40],
                'allowed_capabilities': task['allowed_capabilities'] if self.lane == 'executor' else [],
                'system': system,
                'skills_dir': str(skills_directory(self.store.config, ep['scene_id'], ep['person_id']) or ''),
                'skill_directories': [str(path) for path in skill_directories(self.store.config, ep['scene_id'], ep['person_id'])],
            })
            request = {'kind': 'stage', 'token': operation, 'session_id': native_id,
                       'lane': self.lane, 'phase': phase, 'text': text, 'system': system,
                       'episode_id': ep['_id'], 'binding': record}
            if self.lane == 'character':
                source = self.store.db.messages.find_one({'_id': 'in-' + ep['_id']})
                if source and source.get('event', {}).get('channel'):
                    request['channel_input'] = self.worker.channel_input(source)
            future = Future()
            future.asuna_lane = self.lane
            with self.worker.controller.ingress_lock, self.worker.pending_lock:
                if self.worker.controller.reconfiguring:
                    raise RuntimeError('HOST_RECONFIGURING')
                if operation in self.worker.pending:
                    raise RuntimeError('NATIVE_OPERATION_ALREADY_RUNNING')
                self.worker.pending[operation] = future
            self.worker.emit(request)
            try:
                value = future.result(timeout=self.store.config['workflow_timeout_seconds'])
                result = LaneResult(**value)
                self.store.put('lane_receipts', {
                    '_id': operation, 'native_host': True, 'native_session_id': native_id,
                    'scope_key': ep['scope_key'], 'result': vars(result)}, stream=operation)
                return result
            finally:
                with self.worker.pending_lock:
                    self.worker.pending.pop(operation, None)

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

    def initialize(self, persona, skill_directories=None, routes=None, models=None, integration_project=None, skill_workspace=None, native_sessions=None,
                   deployment=None, secrets=None, qq_admission='explicit', apply_integrations=False):
        # Worker initialization is managed by the native Host.
        if self.app:
            return self.status()
        from .native_settings import runtime_settings
        config = {**(runtime_settings(deployment, secrets or {}, models, qq_admission, create_dirs=True)
                     if deployment else load(self.config_path)), 'task_mode': 'workspace'}
        # Share the legacy lane's ownership lock. Two frontends may never run
        # the same business queue or publish the same scene concurrently.
        self.stack.enter_context(RuntimeLease(Path(config['dsh_home']) / config['database'] / 'character' / 'runtime.lock'))
        # Existing state identity wins. Package defaults seed only absent heads.
        if config['chat']['persona'] != persona['id']:
            raise ValueError('PERSONA_STATE_ID_MISMATCH')
        config['chat'] = {**config['chat'], 'persona_file': persona['persona_file'],
                          'display_name': persona['display_name']}
        config['character_id'] = persona['character_id']
        config['persona_contribution'] = persona
        config['_skill_directories'] = skill_directories or persona.get('skill_directories', [])
        config['_native_routes'] = routes or {}
        for lane, key in (('character', 'character'), ('action', 'executor')):
            if models and lane in models:
                config[key] = {**config[key], **models[lane]}
        config['_integration_project'] = integration_project
        config['_native_apply_integrations'] = apply_integrations
        if persona.get('integration_directory'):
            config['_native_integration_release'] = str(Path(persona['resource_root']) / persona['integration_directory'])
        config['_skill_workspace'] = skill_workspace
        # The immutable package supplies generic instructions; local state and
        # source projects have separate roots and never replace live self heads.
        from .config import RESOURCES
        if RESOURCES.is_dir():
            config['prompts_dir'] = str(RESOURCES / 'prompts')
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
        self.host = self.stack.enter_context(RuntimeHost(
            config, evidence, lane_factory=lambda *a: NativeLane(self, *a), broker_http=False,
            schedule_lane=NativeScheduleLane(self, config), configure_controller=configure,
            development_factory=lambda c,s: NativeDevelopmentBridge(self,c,s)))
        self.watch = threading.Thread(target=self.watch_host, name='native-lifecycle', daemon=True)
        self.watch.start()
        return {**self.status(), 'navigation': self.navigation}

    def prepare_navigation(self, native_sessions):
        """Bind real native conversations; the Host owns their logs and workspaces."""
        from .channels import route_members
        store, config = self.app.store, self.app.config
        known = {row['id']: row for row in native_sessions}
        local = config['chat']
        qq_workspace = (ROOT / '.runtime' / 'work' / 'qq').resolve()
        qq_workspace.mkdir(parents=True, exist_ok=True)
        Path(local['workspace']).mkdir(parents=True, exist_ok=True)
        self.qq_workspace = str(qq_workspace)
        scenes = [(local['scene_id'], local['person_id'], 'Local', '小满 · 本地私聊')]
        for channel in config.get('channels', {}).values():
            for route in channel.get('routes', {}).values():
                if route['target']['type'] == 'group' and route['target']['id'] in channel.get('blocked_groups', []):
                    continue
                members = [grant for sender, grant in route_members(route).items()
                           if sender not in channel.get('blocked_senders', [])]
                if not members or not route['scene_id'].startswith('qq:'):
                    continue
                scene_id = route['scene_id']
                label = '群聊' if ':group:' in scene_id else '私聊'
                scenes.append((scene_id, members[0]['person_id'], 'QQ',
                               label + ' · ' + (route.get('display_name') or scene_id.rsplit(':', 1)[-1])))
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
            cwd = str(Path(local['workspace']).resolve()) if workspace == 'Local' else self.qq_workspace
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
                'workspaces': {'QQ': self.qq_workspace, 'Local': str(Path(local['workspace']).resolve())}}

    @staticmethod
    def role_session_id(ep):
        key = json.dumps([ep['scene_id'], ep['persona'], ep['policy_epoch'],
                          ep.get('character_context')], sort_keys=True)
        return 'asuna-role-' + sha(key.encode())[:32]

    def continued_session(self, session_id):
        record = self.app.store.db.sessions.find_one({'_id': session_id}) or {}
        return record.get('successor_id', session_id)

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
                'schedules_active': bool(self.host and getattr(self.host, 'schedule', None)),
                'integration_active': integration['state'] == 'RUNNING',
                'integration_state': integration['state'], 'integration_error': integration.get('error'),
                'database': 'connected' if self.app else 'unavailable',
                'self_source': 'existing Mongo state heads' if self.app else None,
                'active_role': self.controller.active if self.controller else None,
                'queued_inputs': self.controller.pending.qsize() if self.controller else 0,
                'queued_tasks': self.controller.task_queue.qsize() if self.controller else 0,
                'active_task': self.controller.active_task if self.controller else None}

    def bind_session(self, session_id, values):
        prior = self.app.store.db.sessions.find_one({'_id': session_id})
        identity = ('lane', 'scene_id', 'persona', 'cwd')
        if values['lane'] != 'character':
            identity += ('person_id',)
        if prior and any(prior.get(k) != values.get(k) for k in identity):
            raise Denied('NATIVE_BINDING_IDENTITY_CHANGED')
        scene = self.app.store.authorize(values['scene_id'], values['person_id'])
        if scene['policy_epoch'] != values['policy_epoch']:
            raise Denied('NATIVE_SESSION_EPOCH_CHANGED')
        return self.app.store.put('sessions', {
            **(prior or {}), **values, '_id': session_id, 'native_host': True,
            'binding_key': 'native-host:' + session_id,
        }, expected=prior['revision'] if prior else None, stream='native-binding:' + session_id)

    def session(self, session_id):
        record = self.app.store.db.sessions.find_one({'_id': session_id, 'native_host': True})
        if not record:
            raise Denied('NATIVE_SESSION_NOT_BOUND')
        scene = self.app.store.authorize(record['scene_id'], record['person_id'])
        if scene['policy_epoch'] != record['policy_epoch']:
            raise Denied('NATIVE_SESSION_EPOCH_CHANGED')
        return record

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

    def channel_input(self, row):
        """A real processed QQ receipt, including quiet/error outcomes; never a model turn."""
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
                'cwd': self.qq_workspace, 'role_session_id': session_id, 'main_conversation': True,
                'native_title': ('群聊' if route['target']['type'] == 'group' else '私聊') + ' · '
                    + (route.get('display_name') or route['target']['id']), 'navigation_version': 1})
        indexer = getattr(self.app, 'memory_indexer', None)
        if indexer and scene['_id'] not in indexer.scene_ids:
            indexer.scene_ids.append(scene['_id'])
            if indexer.summarizer:
                indexer.summarizer.scene_ids.append(scene['_id'])
                indexer.summarizer.initialize()
        return {'session_id': session_id, 'binding': binding, 'input': {
            'id': row['_id'], 'text': row['text'], 'sender': row['event']['channel']['sender_id'],
            'received_at': row['received_at'], 'state': row.get('ingress_state', 'ACCEPTED')}}

    def dispatch(self, method, args):
        if method == 'validate_settings':
            from .native_settings import runtime_settings
            config = runtime_settings(args['deployment'], args.get('secrets', {}), args['models'], args['qq_admission'])
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
            policies = {row['_id']: ('QQ 会话仅供查看，请在 QQ 中回复。' if row['scene_id'] != local['scene_id']
                else '这是内部工作会话，请回到小满的本地私聊。')
                for row in self.app.store.db.sessions.find({'_id': {'$in': ids}, 'native_host': True})
                if row['scene_id'] != local['scene_id'] or row['lane'] != 'character'
                or row.get('successor_id') or row.get('retired')}
            for row in args['sessions']:
                if row.get('cwd') and Path(row['cwd']).resolve() == (ROOT / '.runtime/work/qq').resolve():
                    policies[row['id']] = 'QQ 会话仅供查看，请在 QQ 中回复。'
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
        if method in ('memory.page', 'memory.detail'):
            from .native_api import NativeMemory
            memory = NativeMemory(self, args['session_id'])
            return memory.detail(args['id']) if method == 'memory.detail' else memory.page(
                args.get('category', 'summary'), args.get('offset', 0), args.get('search', ''))
        if method == 'tool':
            record = self.session(args['session_id'])
            if record['lane'] != 'executor':
                raise Denied('ACTION_SESSION_REQUIRED')
            task = self.app.store.db.tasks.find_one({'_id': record['task_id']})
            self.app.broker.bind(record['broker_session'], task, Path(record['cwd']))
            return self.app.broker.call(record['broker_session'], args['call_id'], args['tool'], args['args'])
        if method == 'tool_specs':
            return [*WORKSPACE_TOOLS, *INTEGRATION_TOOLS, *DEVELOPMENT_TOOLS]
        if method == 'schedule.deliver':
            return self.host.schedule.deliver(args)
        if method == 'persona.resources':
            self.app.config['_skill_directories'] = args['skill_directories']
            self.app.config['chat']['persona_file'] = args['persona']['persona_file']
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
        if not task.get('development_grant') or (task['scene_id'],task['requester_id']) != (
                self.config['chat']['scene_id'],self.config['chat']['person_id']):
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
            if result['state'] == 'ACTIVE':
                self.worker.host._complete_activations()
        return result


def main():
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    worker = BusinessWorker(args.config)
    pool = ThreadPoolExecutor(max_workers=8)

    def respond(request):
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

    try:
        for line in sys.stdin:
            request = json.loads(line)
            pool.submit(respond, request)
    finally:
        worker.close()
        pool.shutdown(wait=True, cancel_futures=True)


if __name__ == '__main__':
    main()
