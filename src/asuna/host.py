"""Long-lived owner of Application, queues and adapter listeners; Web is a client."""
from contextlib import ExitStack
from pathlib import Path
import threading

from .application import Application
from .channels import Channels, ChannelServer
from .chat import Chat, local_settings, prepare_local_scene
from .config import ROOT
from .memory_indexer import MemoryIndexer
from .state import Denied


def prepare_channels(store):
    """Only explicitly configured DM bindings are enabled in the A-stage seam."""
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
            scene_id, person = route['scene_id'], route['person_id']
            if scene_id == local['scene_id'] or scene_id in scene_ids:
                raise Denied('CHANNEL_SCENE_MUST_BE_DISTINCT')
            scene_ids.add(scene_id)
            if (route['target'] != {'type': 'dm', 'id': route['sender_id']}
                    or not isinstance(route['sender_id'], str) or not route['sender_id']):
                raise Denied('ONLY_EXPLICIT_DM_ROUTES_SUPPORTED')
            workspace = Path(route['workspace']).resolve()
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
                                        'account_id': route['sender_id']}, stream='host:setup')
            elif (identity['platform'], identity['account_id']) != (channel_id, route['sender_id']):
                raise Denied('CHANNEL_IDENTITY_BINDING_CONFLICT')
            scene = store.db.scenes.find_one({'_id': scene_id})
            if scene is None:
                store.put('scenes', {'_id': scene_id, 'scene_id': scene_id, 'kind': 'dm',
                                    'members': [person], 'scope_key': 'scene:' + scene_id,
                                    'policy_epoch': 1, 'sequence': 0, 'channel_id': channel_id,
                                    'channel_account_id': channel['account_id']}, stream='host:setup')
            else:
                if (scene.get('channel_id') != channel_id or scene.get('channel_account_id') != channel['account_id'] or scene['kind'] != 'dm'
                        or scene['members'] != [person] or scene['scope_key'] != 'scene:' + scene_id):
                    raise Denied('CHANNEL_SCENE_BINDING_CONFLICT')
            store.init_head('relationship:' + person, 'scene:' + scene_id,
                            {'body': '这是通过已授权私聊通道交流的人物。尚不预设其他身份或共同经历。'}, [])
            workspace.mkdir(parents=True, exist_ok=True)
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
            self.controller = Chat(self.app, self.settings, emit=lambda text: self.evidence.record('host.notice', {'text': text}))
            channels = Channels(self.controller)
            channels.recover_sending()
            self.controller.recover_inputs()
            self._recover_tasks()
            indexer = MemoryIndexer(self.app.store, self.evidence, [self.settings['scene_id'], *sorted(scenes)]).start()
            self.stack.callback(indexer.close)
            self.controller.worker.start()
            self.controller.task_worker.start()
            self.stack.callback(self.controller.stop)
            if self.config.get('channels'):
                self.channel_server = ChannelServer(channels, self.config.get('channel_port', 8766))
                self.stack.callback(self.channel_server.close)
                self.evidence.record('host.channels_started', {'port': self.channel_server.server.server_port})
            return self
        except BaseException:
            self.stack.close()
            raise

    def _recover_tasks(self):
        store = self.app.store
        for task in store.db.tasks.find({'state': {'$in': ['READY', 'RUNNING', 'DONE', 'PARTIAL', 'BLOCKED', 'NEEDS_CHARACTER_DECISION']}}):
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
                if episode and episode['state'] in ('WAITING_TASK', 'COMMITTED'):
                    self.controller._schedule({'task_id': task['_id']})
                elif episode and episode['state'] in ('INTERRUPTED', 'FAILED_RUNTIME', 'FAILED_PROTOCOL'):
                    self.app.service.cancel(task['_id'], reason='origin_episode_interrupted', person_id=task['requester_id'])
            elif task['state'] == 'RUNNING':
                # An in-flight executor may have produced effects. No blind retry.
                store.put('tasks', {**task, 'state': 'UNKNOWN', 'automatic_retry': False,
                                   'failure_type': 'HOST_INTERRUPTED_EXECUTOR'}, expected=task['revision'], stream=task['_id'])
                store.audit(task['_id'], 'execution.failed', {'reason': 'HOST_INTERRUPTED_EXECUTOR'}, task['scope_key'])
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
