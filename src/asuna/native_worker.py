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
from .grants import workspace_grant
from .skills import skills_directory, skill_directories
from .state import Denied
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
                      'persona': self.store.config['chat']['persona'],
                      'native_session_id': 'asuna-summary-' + sha(binding.encode())[:32]}
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
            native_id = ('asuna-action-' + sha(binding.encode())[:32]
                         if self.lane == 'executor' else role_id)
            grant = workspace_grant(self.store.config, ep['scene_id'], ep['person_id'])
            record = self.worker.bind_session(native_id, {
                'lane': self.lane, 'scene_id': ep['scene_id'], 'person_id': ep['person_id'],
                'scope_key': ep['scope_key'], 'policy_epoch': ep['policy_epoch'],
                'persona': ep['persona'], 'cwd': str(Path(grant['workspace']).resolve()),
                'role_session_id': role_id, 'task_id': task['_id'] if task else None,
                'broker_session': 's-' + sha(binding.encode())[:40],
                'allowed_capabilities': task['allowed_capabilities'] if self.lane == 'executor' else [],
                'system_sha256': sha(system.encode()),
                'skills_dir': str(skills_directory(self.store.config, ep['scene_id'], ep['person_id']) or ''),
                'skill_directories': [str(path) for path in skill_directories(self.store.config, ep['scene_id'], ep['person_id'])],
            })
            request = {'kind': 'stage', 'token': operation, 'session_id': native_id,
                       'lane': self.lane, 'phase': phase, 'text': text, 'system': system,
                       'episode_id': ep['_id'], 'binding': record}
            future = Future()
            with self.worker.pending_lock:
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

    def initialize(self, persona, skill_directories=None, routes=None, models=None, integration_project=None, skill_workspace=None):
        # Worker initialization is managed by the native Host.
        if self.app:
            return self.status()
        config = {**load(self.config_path), 'task_mode': 'workspace'}
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
        config['_skill_workspace'] = skill_workspace
        evidence = Evidence(ROOT / 'reports' / ('native-host-' + uuid.uuid4().hex[:10]))
        def configure(host):
            self.app, self.controller = host.app, host.controller
            self.controller.on_episode_finished = self.episode_finished
            self.app.coordinator.native_session_resolver = self.resolve_role_session
        self.host = self.stack.enter_context(RuntimeHost(
            config, evidence, lane_factory=lambda *a: NativeLane(self, *a), broker_http=False,
            schedule_lane=NativeScheduleLane(self, config), configure_controller=configure,
            development_factory=lambda c,s: NativeDevelopmentBridge(self,c,s)))
        self.watch = threading.Thread(target=self.watch_host, name='native-lifecycle', daemon=True)
        self.watch.start()
        return self.status()

    def watch_host(self):
        while not self.stopping.wait(.5):
            if self.host.restart_requested.is_set():
                self.emit({'kind': 'restart_requested', 'reason': 'published-worker'})
                return

    def resolve_role_session(self, ep):
        """Bind trusted, normalized ingress; old transcripts stay read-only."""
        store = self.app.store
        if ep.get('task_id'):
            task = store.db.tasks.find_one({'_id': ep['task_id']})
            original = store.db.episodes.find_one({'_id': task['episode_id']}) if task else None
            if original and original.get('native_session_id'):
                return original['native_session_id']
        source = store.db.messages.find_one({'_id': 'in-' + ep['_id']}) or {}
        plan_id = source.get('event', {}).get('scheduled_plan_id')
        plan = store.db.plans.find_one({'_id': plan_id}) if plan_id else None
        original = store.db.episodes.find_one({'_id': plan.get('source_episode_id')}) if plan else None
        if original and original.get('native_session_id'):
            return original['native_session_id']
        key = json.dumps([ep['scene_id'], ep['person_id'], ep['persona'], ep['policy_epoch'],
                          ep.get('character_context')], sort_keys=True)
        session_id = 'asuna-role-' + sha(key.encode())[:32]
        store.audit(ep['_id'], 'native.context.bound', {
            'native_session_id': session_id, 'legacy_history': 'read-only',
            'context': 'new native conversation; no tool or message replay'}, ep['scope_key'])
        return session_id

    def status(self):
        return {'ready': bool(self.app), 'persona': self.app.config['chat']['persona'] if self.app else None,
                'workspace': self.app.config['chat']['workspace'] if self.app else None,
                'transport': 'stdio', 'model_runtime': 'dsh-host',
                'channels_active': bool(self.host and getattr(self.host, 'channel_server', None)),
                'schedules_active': bool(self.host and getattr(self.host, 'schedule', None)),
                'integration_active': bool(self.host and self.host.integration),
                'database': 'connected' if self.app else 'unavailable',
                'self_source': 'existing Mongo state heads' if self.app else None,
                'active_role': self.controller.active if self.controller else None,
                'queued_inputs': self.controller.pending.qsize() if self.controller else 0,
                'queued_tasks': self.controller.task_queue.qsize() if self.controller else 0,
                'active_task': self.controller.active_task if self.controller else None}

    def bind_session(self, session_id, values):
        prior = self.app.store.db.sessions.find_one({'_id': session_id})
        identity = ('lane', 'scene_id', 'person_id', 'persona', 'cwd')
        if prior and any(prior.get(k) != values.get(k) for k in identity):
            raise Denied('NATIVE_BINDING_IDENTITY_CHANGED')
        # Bindings keep a hash of the stage system prompt, never its full text.
        kept = {k: v for k, v in (prior or {}).items() if k != 'system'}
        return self.app.store.put('sessions', {
            **kept, **values, '_id': session_id, 'native_host': True,
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
        session_id = (result or {}).get('native_session_id') or event.get('native_session_id')
        if session_id:
            self.emit({'kind': 'episode_finished', 'session_id': session_id,
                       'episode_id': (result or {}).get('_id'),
                       'state': (result or {}).get('state'), 'error': error,
                       'task_id': (result or {}).get('task_id')})

    def dispatch(self, method, args):
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
        if method == 'input':
            session_id = args['session_id']
            existing = self.app.store.db.sessions.find_one({'_id': session_id})
            local = self.app.config['chat']
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
                args.get('category', 'all'), args.get('offset', 0))
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
