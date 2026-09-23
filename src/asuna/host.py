"""Long-lived owner of Application, queues and adapter listeners; Web is a client."""
from contextlib import ExitStack
from pathlib import Path
import threading

from .application import Application
from .channels import Channels, ChannelServer, route_members
from .chat import Chat, local_settings, prepare_local_scene
from .config import ROOT
from .memory_indexer import MemoryIndexer
from .state import Denied


def prepare_channels(store):
    """Explicit DM/group identities and disjoint per-member resource grants."""
    scene_ids, tokens, workspaces = set(), set(), []
    local = store.config['chat']
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
                    store.put('identities', {'_id': person, 'person_id': person, 'platform': channel_id,
                                            'account_id': sender}, stream='host:setup')
                elif (identity['platform'], identity['account_id']) != (channel_id, sender):
                    raise Denied('CHANNEL_IDENTITY_BINDING_CONFLICT')
                store.init_head('relationship:' + person, 'scene:' + scene_id,
                                {'body': '这是当前授权场景中的参与者，不预设其他私域身份或共同经历。'}, [])
                workspace.mkdir(parents=True, exist_ok=True)
            scene = store.db.scenes.find_one({'_id': scene_id})
            if scene is None:
                store.put('scenes', {'_id': scene_id, 'scene_id': scene_id, 'kind': kind,
                                    'members': people, 'scope_key': 'scene:' + scene_id,
                                    'policy_epoch': 1, 'sequence': 0, 'channel_id': channel_id,
                                    'channel_account_id': channel['account_id']}, stream='host:setup')
            else:
                if (scene.get('channel_id') != channel_id or scene.get('channel_account_id') != channel['account_id'] or scene['kind'] != kind
                        or set(scene['members']) != set(people) or scene['scope_key'] != 'scene:' + scene_id):
                    raise Denied('CHANNEL_SCENE_BINDING_CONFLICT')
    return scene_ids


class RuntimeHost:
    def __init__(self, config, evidence, database=None):
        self.config, self.evidence, self.database = config, evidence, database
        self.stack = ExitStack()
        self.shutdown_requested = threading.Event()

    def __enter__(self):
        try:
            self.app = self.stack.enter_context(Application({**self.config, 'task_mode': 'workspace'}, self.evidence, self.database))
            self.settings = local_settings(self.config)
            prepare_local_scene(self.app.store, self.settings)
            scenes = prepare_channels(self.app.store)
            self.integration = None
            if self.config.get('integration', {}).get('enabled'):
                from .integration import IntegrationRunner
                self.integration = IntegrationRunner(self.config)
                self.app.broker.integration = self.integration
                self.stack.callback(self.integration.close)
            self.controller = Chat(self.app, self.settings, emit=lambda text: self.evidence.record('host.notice', {'text': text}))
            channels = Channels(self.controller)
            channels.recover_sending()
            self.controller.recover_inputs()
            self._recover_tasks()
            indexer = MemoryIndexer(self.app.store, self.evidence, [self.settings['scene_id'], *sorted(scenes)],
                                    summary_lane=self.app.summary_lane,
                                    summary_scene=self.settings['scene_id'],
                                    summary_can_run=lambda: self.controller.active_task is None
                                        and self.controller.task_queue.empty()).start()
            self.app.memory_indexer = indexer
            self.stack.callback(indexer.close)
            if self.config.get('channels'):
                self.channel_server = ChannelServer(channels, self.config.get('channel_port', 8766))
                self.stack.callback(self.channel_server.close)
                self.evidence.record('host.channels_started', {'port': self.channel_server.server.server_port})
            if self.integration:
                self.integration.restore()
            from .schedule import ScheduleService
            self.schedule = ScheduleService(self.app, self.controller)
            self.app.coordinator.scheduler = self.schedule
            self.controller.worker.start()
            self.controller.task_worker.start()
            self.stack.callback(self.controller.stop)
            self.stack.callback(self.schedule.close)
            return self
        except BaseException:
            self.stack.close()
            raise

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
        self.stack.close()
