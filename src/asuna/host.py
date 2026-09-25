"""Long-lived owner of Application, queues and adapter listeners; Web is a client."""
from contextlib import ExitStack
from pathlib import Path
import threading
import time
from types import SimpleNamespace

from .application import Application
from .channels import Channels, ChannelServer, route_members
from .chat import Chat, local_settings, prepare_local_scene
from .config import ROOT
from .memory_indexer import MemoryIndexer
from .state import Denied, now

try:                                  # 跨场景只读联动（A2）
    from . import scene_links
except Exception:
    scene_links = None


def prepare_channels(store):
    """Explicit DM/group identities and disjoint per-member resource grants."""
    scene_ids, tokens, workspaces = set(), set(), []
    new_identities = False
    local = store.config['chat']
    # The A2 resolver reads the same two collections for every channel member.
    # Keep one startup-local read view and include any setup rows written below.
    # The resolver itself, its aliases, and its results are unchanged.
    if scene_links and scene_links.canonical_map(store.config):
        identity_rows = list(store.db.identities.find({}))
        scene_rows = list(store.db.scenes.find({}))
        relationship_db = SimpleNamespace(
            identities=SimpleNamespace(find=lambda _query: identity_rows),
            scenes=SimpleNamespace(find=lambda _query: scene_rows))
    else:
        relationship_db = store.db
    for channel_id, channel in store.config.get('channels', {}).items():
        token = channel.get('token', '')
        if not isinstance(token, str) or not token.isascii() or len(token) < 24 or token in tokens:
            raise ValueError('CHANNEL_TOKEN_MUST_BE_UNIQUE_AND_AT_LEAST_24_CHARS')
        tokens.add(token)
        if not isinstance(channel.get('account_id'), str) or not channel['account_id']:
            raise ValueError('CHANNEL_ACCOUNT_REQUIRED')
        for route in channel['routes'].values():
            scene_id = route['scene_id']
            if scene_id == local['scene_id'] or scene_id in scene_ids:
                raise Denied('CHANNEL_SCENE_MUST_BE_DISTINCT')
            scene_ids.add(scene_id)
            kind = route['target']['type']
            members = route_members(route)
            if not members or not isinstance(route['target'].get('id'), str) or not route['target']['id']:
                raise Denied('CHANNEL_TARGET_OR_MEMBERS_REQUIRED')
            if kind == 'dm' and route['target']['id'] != route['sender_id']:
                raise Denied('CHANNEL_DM_TARGET_MISMATCH')
            people = []
            for sender, grant in members.items():
                person = grant['person_id']
                if not isinstance(sender, str) or not sender or not isinstance(person, str) or not person or person in people:
                    raise Denied('CHANNEL_MEMBER_BINDING_INVALID')
                people.append(person)
                workspace = Path(grant['workspace']).resolve()
                if not workspace.is_relative_to((ROOT / '.runtime' / 'channels').resolve()):
                    raise Denied('CHANNEL_WORKSPACE_OUTSIDE_CHANNEL_ROOT')
                local_workspace = Path(local['workspace']).resolve()
                if any(workspace.is_relative_to(other) or other.is_relative_to(workspace)
                       for other in [local_workspace, *workspaces]):
                    raise Denied('CHANNEL_WORKSPACE_OVERLAP')
                workspaces.append(workspace)
                identity = store.db.identities.find_one({'_id': person})
                if identity is None:
                    created = store.put('identities', {'_id': person, 'person_id': person, 'platform': channel_id,
                                                      'account_id': sender}, stream='host:setup')
                    if relationship_db is not store.db:
                        identity_rows.append(created)
                    new_identities = True
                elif (identity['platform'], identity['account_id']) != (channel_id, sender):
                    raise Denied('CHANNEL_IDENTITY_BINDING_CONFLICT')
                target = (scene_links.relationship_target(
                    store.config, relationship_db,
                    {'_id': scene_id, 'scope_key': 'scene:' + scene_id}, person) if scene_links
                    else {'entity': 'relationship:' + person, 'scope': 'scene:' + scene_id})
                # 没配 canonical 映射时就是原来那一份；配了之后别名场景不再另起一条关系记录。
                store.init_head(target['entity'], target['scope'],
                                {'body': '这是当前授权场景中的参与者，不预设其他私域身份或共同经历。'}, [])
                workspace.mkdir(parents=True, exist_ok=True)
            scene = store.db.scenes.find_one({'_id': scene_id})
            if scene is None:
                created = store.put('scenes', {'_id': scene_id, 'scene_id': scene_id, 'kind': kind,
                                               'members': people, 'scope_key': 'scene:' + scene_id,
                                               'policy_epoch': 1, 'sequence': 0, 'channel_id': channel_id,
                                               'channel_account_id': channel['account_id']}, stream='host:setup')
                if relationship_db is not store.db:
                    scene_rows.append(created)
            else:
                if (scene.get('channel_id') != channel_id or scene.get('channel_account_id') != channel['account_id'] or scene['kind'] != kind
                        or set(scene['members']) != set(people) or scene['scope_key'] != 'scene:' + scene_id):
                    raise Denied('CHANNEL_SCENE_BINDING_CONFLICT')
    if scene_links:
        # 派生投影：联动边与 canonical 映射写进 scenes／identities，只为可观察；
        # 读路径每次现算自配置，删掉配置键立刻回到原状。
        if new_identities:
            scene_links.sync_identity_docs(store, store.config)
        scene_links.sync_scene_docs(store, store.config, sorted(scene_ids | {local['scene_id']}))
    return scene_ids


class RuntimeHost:
    def __init__(self, config, evidence, database=None, stream_observer=None):
        self.config, self.evidence, self.database = config, evidence, database
        self.stream_observer = stream_observer
        self.stack = ExitStack()
        self.shutdown_requested = threading.Event()
        self.restart_requested = threading.Event()
        self.restart_pending = threading.Event()
        self._restart_watch_stop = threading.Event()
        self._restart_blocked_logged = False

    def __enter__(self):
        try:
            self.app = self.stack.enter_context(Application({**self.config, 'task_mode': 'workspace'}, self.evidence, self.database))
            if self.stream_observer:
                self.app.character.proxy.ui_observer = self.stream_observer
                self.app.executor_lane.proxy.ui_observer = self.stream_observer
            self.evidence.record('host.recovery.start', {})
            recovery_start = time.perf_counter()
            self.settings = local_settings(self.config)
            prepare_local_scene(self.app.store, self.settings)
            local_ready = time.perf_counter()
            scenes = prepare_channels(self.app.store)
            channel_scenes_ready = time.perf_counter()
            self.integration = None
            if self.config.get('integration', {}).get('enabled'):
                from .integration import IntegrationRunner
                self.integration = IntegrationRunner(self.config)
                self.app.broker.integration = self.integration
                self.stack.callback(self.integration.close)
            self.controller = Chat(self.app, self.settings, emit=lambda text: self.evidence.record('host.notice', {'text': text}))
            self.controller.on_turn_finished = self._maybe_restart_after_publish
            self.controller.restart_pending = self.restart_pending
            channels = Channels(self.controller)
            channels.recover_sending()
            self.controller.recover_inputs()
            inputs_ready = time.perf_counter()
            self._recover_tasks()
            tasks_ready = time.perf_counter()
            self.evidence.record('host.recovery.ready', {
                'local_seconds': round(local_ready - recovery_start, 3),
                'channel_scene_seconds': round(channel_scenes_ready - local_ready, 3),
                'input_seconds': round(inputs_ready - channel_scenes_ready, 3),
                'task_seconds': round(tasks_ready - inputs_ready, 3)})
            self.indexer = MemoryIndexer(self.app.store, self.evidence, [self.settings['scene_id'], *sorted(scenes)],
                                         summary_lane=self.app.summary_lane,
                                         summary_scenes=[self.settings['scene_id'], *sorted(scenes)],
                                         summary_can_run=lambda: self.controller.active_task is None
                                             and self.controller.task_queue.empty()).start()
            self.app.memory_indexer = self.indexer
            self.stack.callback(self.indexer.close)
            if self.config.get('channels'):
                self.channel_server = ChannelServer(channels, self.config.get('channel_port', 8766))
                self.stack.callback(self.channel_server.close)
                self.evidence.record('host.channels_started', {'port': self.channel_server.server.server_port})
            self.evidence.record('host.channels.ready', {})
            if self.integration:
                self.integration.restore()
            self.evidence.record('host.integration.ready', {})
            from .schedule import ScheduleService
            self.schedule = ScheduleService(self.app, self.controller)
            self.app.coordinator.scheduler = self.schedule
            self.evidence.record('host.schedule.ready', {})
            self.controller.worker.start()
            self.controller.task_worker.start()
            self.stack.callback(self.controller.stop)
            self.stack.callback(self.schedule.close)
            self._complete_activations()
            self._restart_watch = threading.Thread(target=self._watch_published_restart,
                                                   name='asuna-restart-watch', daemon=True)
            self._restart_watch.start()
            self.evidence.record('runtime.ready', {})
            return self
        except BaseException:
            indexer = getattr(self, 'indexer', None)
            if indexer:
                indexer.request_stop()
            self.stack.close()
            raise

    def _maybe_restart_after_publish(self):
        """Switch code only after the original action/feedback turn has settled."""
        applied=self.app.store.db.sink_receipts.find_one({
            'kind':'self_development_publish','state':'APPLIED'})
        if applied:
            with self.controller.state_lock:
                if not self.restart_pending.is_set():
                    self.evidence.record('restart.pending', {'receipt_id': applied['_id']})
                    self.restart_pending.set()
                if self.controller.active or self.controller.active_task:
                    if not self._restart_blocked_logged:
                        self.evidence.record('restart.blocked', {
                            'active_task': self.controller.active_task,
                            'active_role': self.controller.active,
                            'pending_queue': self.controller.pending.qsize(),
                            'task_queue': self.controller.task_queue.qsize()})
                        self._restart_blocked_logged = True
                    return
                if self.restart_requested.is_set():
                    return
                self.evidence.record('restart.requested', {'receipt_id': applied['_id']})
                self.restart_requested.set()
                self.shutdown_requested.set()

    def _watch_published_restart(self):
        # APPLIED may occur inside a still-running action. Mark the lifecycle
        # pending before that action returns, so the queues stop taking work.
        while not self._restart_watch_stop.wait(.5) and not self.shutdown_requested.is_set():
            if self.controller.active or self.controller.active_task:
                self._maybe_restart_after_publish()

    def _complete_activations(self):
        """A successfully constructed live host supplies the actual boot result."""
        store=self.app.store
        for row in store.db.sink_receipts.find({'kind':'self_development_publish','state':{'$in':['APPLIED','ACTIVE']}}):
            current=store.db.sink_receipts.find_one({'_id':row['_id']})
            active=(store.put('sink_receipts',{**current,'state':'ACTIVE','activated_at':now()},
                              expected=current['revision'],stream=current['task_id'])
                    if current['state']=='APPLIED' else current)
            self.controller.offer_self_development('self-development:publish:'+active['_id'],
                text='自我开发候选已由当前宿主实际启动。这里是上一行动目标的发布结果；你可决定继续观察、修正或不处理。',
                task_id=active['task_id'],
                trusted_context_events=[{'kind':'development_publish_result',
                    'task_id':active['task_id'],'candidate':active['candidate'],
                    'state':'ACTIVE','activated_at':active['activated_at'],
                    'changed_files':active['changed_files'],'boot_probe':active['boot_probe']}])

    def _recover_tasks(self):
        store = self.app.store
        for task in store.db.tasks.find({'state': {'$in': ['READY', 'RUNNING', 'RETURNED', 'DONE', 'PARTIAL', 'BLOCKED', 'NEEDS_CHARACTER_DECISION', 'UNKNOWN']}}):
            source = store.db.messages.find_one({'_id': task['raw_input_refs'][0]})
            seen = set()
            while source and source.get('event', {}).get('episode_kind') == 'task_feedback':
                if source['_id'] in seen:
                    raise Denied('TASK_SOURCE_CYCLE')
                seen.add(source['_id'])
                parent = store.db.tasks.find_one({'_id': source['event']['task_id']})
                source = store.db.messages.find_one({'_id': parent['raw_input_refs'][0]}) if parent else None
            if not source or not source.get('host_managed'):
                continue
            if task['state'] == 'READY':
                episode = store.db.episodes.find_one({'_id': task['episode_id']})
                if episode and episode.get('decision',{}).get('next')=='delegate':
                    self.controller._schedule({'task_id': task['_id']})
            elif task['state'] == 'RUNNING':
                # An in-flight executor may have produced effects. No blind retry.
                store.put('tasks', {**task, 'state': 'BLOCKED', 'feedback_state':'READY',
                                   'failure_type': 'HOST_INTERRUPTED_EXECUTOR',
                                   'result':{'error':'宿主中断了上次行动。保留原会话与已有记录；没有回执的操作须先核实，不要盲目重做。'}}, expected=task['revision'], stream=task['_id'])
                store.audit(task['_id'], 'execution.failed', {'reason': 'HOST_INTERRUPTED_EXECUTOR'}, task['scope_key'])
                self.controller.pending.put(({'_feedback_task':task['_id'],'event_id':task['_id']+':feedback','scene_id':task['scene_id'],'person_id':task['requester_id']}, task['episode_id']))
            elif task.get('feedback_state') == 'READY':
                self.controller.pending.put(({'_feedback_task': task['_id'], 'event_id': task['_id'] + ':feedback',
                                              'scene_id': task['scene_id'], 'person_id': task['requester_id']}, task['episode_id']))
            elif task.get('feedback_state') == 'DELIVERED':
                feedback = store.db.episodes.find_one({'_id': task.get('feedback_episode')})
                original = store.db.episodes.find_one({'_id': task['episode_id']})
                if feedback and feedback['state'] == 'COMMITTED' and original and original['state'] == 'WAITING_TASK':
                    store.put('episodes', {**original, 'state': 'COMMITTED', 'feedback_episode': feedback['_id']},
                              expected=original['revision'], stream=original['_id'])

    def __exit__(self, *args):
        try:
            self.evidence.record('host.stop.started', {})
        finally:
            self._restart_watch_stop.set()
            watcher = getattr(self, '_restart_watch', None)
            if watcher:
                watcher.join(timeout=2)
            indexer = getattr(self, 'indexer', None)
            if indexer:
                indexer.request_stop()
            self.stack.close()
            self.evidence.record('host.stop.finished', {})
