"""Shared local controller reused by the native Web host; there is no terminal adapter."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from queue import Queue, Empty
import threading
import traceback
import uuid

from .config import redact_text as redact
from .ingress import episode_id, persist_input, input_state
from .router import FairQueue


class SceneQueue(Queue):
    """Queue's existing condition/unfinished-task accounting with scene fairness."""
    def _init(self, maxsize):
        self.queue = FairQueue()

    def _qsize(self):
        return sum(len(items) for items in self.queue.queues.values())

    def _put(self, item):
        self.queue.put(item[0]['scene_id'], item)

    def _get(self):
        return self.queue.pop()


def local_settings(config):
    settings = config['chat']
    for key in ('scene_id', 'person_id', 'persona', 'display_name', 'persona_file'):
        if not settings.get(key):
            raise ValueError(f'CHAT_CONFIG_REQUIRED: {key}')
    return settings


try:                                  # 跨场景只读联动（A2）
    from . import scene_links
except Exception:
    scene_links = None


def seed_documents(store, settings):
    """Conversion before seeding; seeds only fill missing document heads (ADR-009 §5.4)."""
    from .documents import DocumentStore
    docs = DocumentStore(store, settings['persona'])
    docs.convert_legacy_persona()
    seeds = (store.config.get('persona_contribution') or {}).get('seeds') or []
    for seed in seeds:
        if not docs.head(seed['slug']):
            docs.seed(seed['slug'], seed['kind'], Path(seed['path']).read_text(encoding='utf-8'),
                      path=Path(seed['path']).name, title=seed.get('title'))
    if not docs.head('persona') and settings.get('persona_file'):
        # A v1 contribution without seeds: its persona file is the persona seed.
        source = Path(settings['persona_file'])
        docs.seed('persona', 'persona', source.read_text(encoding='utf-8'), path=source.name)


def prepare_local_scene(store, settings):
    """Initialize only missing local state; never reseed memories or revisions."""
    person, scene = settings['person_id'], settings['scene_id']
    scope = 'scene:' + scene
    if not store.db.identities.find_one({'_id': person}):
        store.put('identities', {'_id': person, 'person_id': person, 'platform': 'local',
                  'account_id': person, 'display_name': '本机用户'}, stream='local-setup')
    if not store.db.scenes.find_one({'_id': scene}):
        store.put('scenes', {'_id': scene, 'scene_id': scene, 'kind': 'dm', 'members': [person],
                  'scope_key': scope, 'policy_epoch': 1, 'sequence': 0}, stream='local-setup')
    authorized = store.authorize(scene, person)
    if authorized['kind'] != 'dm' or authorized['scope_key'] != scope:
        raise PermissionError('LOCAL_CHAT_SCENE_CONFIG_MISMATCH')
    seed_documents(store, settings)
    if scene_links:
        # 派生投影：配置里的联动边与 canonical 映射在库里留一份看得见的副本（读路径现算自配置）。
        scene_links.sync_identity_docs(store, store.config)
    target = (scene_links.relationship_target(store.config, store.db,
              {'_id': scene, 'scope_key': scope}, person) if scene_links
              else {'entity': 'relationship:' + person, 'scope': scope})
    store.init_head(target['entity'], target['scope'],
                    {'body': '这是通过本机界面交流的用户。尚无共同经历，不预设熟悉程度。'}, [])
    if scene_links:
        scene_links.sync_scene_docs(store, store.config, [scene])


class Chat:
    def __init__(self, app, settings, emit=print):
        self.app, self.settings, self.emit = app, settings, emit
        self.pending = SceneQueue()
        self.stopping = threading.Event()
        self.latest = None
        self.active = None
        self.state_lock = threading.Lock()
        self.worker = threading.Thread(target=self._work, name='asuna-chat', daemon=True)
        self.task_queue = Queue()
        self.task_worker = threading.Thread(target=self._tasks, name='asuna-actions', daemon=True)
        self.scheduled_tasks = set()
        self.active_task = None
        self.latest_task = None
        self.ingress_lock = threading.RLock()
        self.enqueued = set()
        self.reconfiguring = False
        self.on_turn_finished = None
        self.on_episode_finished = None
        self.restart_pending = threading.Event()

    def _schedule(self, episode):
        task = self.app.store.db.tasks.find_one({'_id': episode['task_id']})
        self.latest_task = task['_id']
        key = (task['_id'], task['intent_revision'])
        if key not in self.scheduled_tasks:
            self.scheduled_tasks.add(key)
            self.task_queue.put(key)
            self.emit('[系统] 行动已排队，仍可继续输入。')

    def _tasks(self):
        while not self.stopping.is_set():
            if self.restart_pending.is_set():
                self.stopping.wait(.1)
                continue
            try:
                task_id, revision = self.task_queue.get(timeout=.1)
            except Empty:
                continue
            try:
                with self.state_lock:
                    if self.stopping.is_set():
                        continue
                    if self.restart_pending.is_set():
                        self.task_queue.put((task_id, revision))
                        continue
                    self.active_task = task_id
                task = self.app.store.db.tasks.find_one({'_id': task_id})
                if task['state'] != 'READY' or task['intent_revision'] != revision:
                    continue
                from .grants import workspace_grant
                grant = workspace_grant(self.app.config, task['scene_id'], task['requester_id'])
                task = self.app.executor.run(task_id, Path(grant['workspace']))
                if not self.stopping.is_set():
                    self.pending.put(({'_feedback_task': task_id, 'event_id': task_id + ':feedback',
                                       'scene_id': task['scene_id'], 'person_id': task['requester_id']}, task['episode_id']))
                    self.app.evidence.record('chat.task_result_queued', {'task_id': task_id, 'state': task['state']})
            except Exception:
                error = redact(traceback.format_exc(), self.app.config)
                self.app.evidence.record('chat.task_error', {'task_id': task_id, 'traceback': error})
                try:
                    self.app.store.audit(task_id, 'execution.failed', {'traceback': error}, task['scope_key'])
                    current = self.app.store.db.tasks.find_one({'_id': task_id})
                    cancelled = current and current['state'] == 'CANCELLED'
                except Exception:
                    cancelled = False
                    self.app.evidence.record('chat.task_persistence_error', {'task_id': task_id,
                        'traceback': redact(traceback.format_exc(), self.app.config)})
                self.emit('[系统] 已撤销任务的行动权限。' if cancelled else '[系统] 行动未完成；请查看本轮执行详情中的原始错误，聊天仍可继续。')
            finally:
                with self.state_lock:
                    self.active_task = None
                self.task_queue.task_done()
                if self.on_turn_finished:
                    self.on_turn_finished()

    def submit(self, text, *, event_id=None, native_session_id=None, native_message_ids=None):
        event = {'event_id': event_id or str(uuid.uuid4()), 'scene_id': self.settings['scene_id'],
                 'person_id': self.settings['person_id'], 'text': text}
        if native_session_id:
            event.update(native_session_id=native_session_id,native_message_ids=native_message_ids or [])
        config=self.app.config
        identity=(event['scene_id'],event['person_id'])
        local=config.get('chat',{})
        if identity==(local.get('scene_id'),local.get('person_id')):
            profile=config.get('integration',{})
            if (profile.get('enabled') is True and
                    identity==(profile.get('scene_id'),profile.get('person_id'))):
                event['integration_profile']='owner'
            if config.get('self_development',{}).get('enabled') is True:
                event['development_profile']='owner'
        return self.receive(event)

    def offer_self_development(self, event_id: str, *, text=None, trusted_context_events=None,
                               task_id=None):
        """Queue a host-origin opportunity in the owner's existing role scene."""
        if not event_id.startswith('self-development:'):
            raise ValueError('INVALID_SELF_DEVELOPMENT_EVENT')
        event = {
            'event_id': event_id,
            'scene_id': self.settings['scene_id'],
            'person_id': self.settings['person_id'],
            'adapter_id': 'self-development',
            'episode_kind': 'self_development',
            'text': text or ('这是一次内部自我开发机会，不是用户消息或新授权。你可以回顾近期经历，'
                             '自行决定是否值得反思、继续旧工作、委托改进，或者什么都不做。无需公开回复。'),
            'trusted_context_events': trusted_context_events or [],
        }
        previous = self.app.store.db.messages.find_one({'_id': 'in-' + episode_id(event)})
        if previous:
            prior_profile = (previous.get('event') or {}).get('integration_profile')
            if prior_profile is not None:
                event['integration_profile'] = prior_profile
        integration=self.app.config.get('integration',{})
        if (previous is None and integration.get('enabled') is True and
                (event['scene_id'],event['person_id']) ==
                (integration.get('scene_id'),integration.get('person_id'))):
            event['integration_profile']='owner'
        if task_id:event['task_id']=task_id
        return self.receive(event)

    def receive(self, event):
        """Trusted host envelope only; adapters must use the bound channel API."""
        with self.ingress_lock:
            if self.stopping.is_set():
                raise RuntimeError('HOST_STOPPING')
            if self.reconfiguring:
                raise RuntimeError('HOST_RECONFIGURING')
            row, created = persist_input(self.app.store, event, managed=True)
            episode = row['episode_id']
            if row['ingress_state'] == 'ACCEPTED' and episode not in self.enqueued:
                self.enqueued.add(episode)
                self.pending.put((row['event'], episode))
            self.latest = episode
            return {'status': 'accepted' if created else 'duplicate', 'episode_id': episode,
                    'received_at': row['received_at']}

    def _proactive_open(self, scene_id):
        """前台行动在跑、或本场景已经排着别的输入 → 这次主动机会直接作废，不排队等。"""
        if self.active_task is not None or not self.task_queue.empty():
            return False
        with self.pending.mutex:
            return not self.pending.queue.queues.get(scene_id)

    def _proactive_group_row(self, event, episode):
        """主动判断只在已授权群场景的旁听行上做；读不到就照实放弃这次机会。"""
        from . import proactive
        woken = (event.get('group_context') or {}).get('wake_reason') == proactive.WAKE_REASON
        if not woken and not (event.get('channel') and 'group_context' in event):
            return None, None, None          # 不是通道群消息：没有旁听行可判断
        row = self.app.store.db.messages.find_one({'_id': 'in-' + episode})
        scene = self.app.store.db.scenes.find_one({'_id': event['scene_id']})
        if not scene or scene.get('kind') != 'group' or not row:
            return None, None, None
        return proactive, scene, row

    def _proactive_consider(self, event, episode, result):
        """分寸判断是可选腿：它自己出错只记证据，不许把已经跑完的一轮改成失败。"""
        try:
            self._proactive_consider_inner(event, episode, result)
        except Exception:
            self.app.evidence.record('proactive.consider_error', {'episode_id': episode,
                                                                  'traceback': traceback.format_exc()[-800:]})

    def _proactive_consider_inner(self, event, episode, result):
        """旁听行落库之后的一次分寸判断：只由新入站消息触发，没有任何定时器重开旧话题。"""
        if result.get('state') != 'RECEIVED_NO_WAKE':
            return
        proactive, scene, row = self._proactive_group_row(event, episode)
        if not proactive:
            return
        decision, updated = proactive.consider(
            self.app.store, self.app.evidence, self.app.config, scene, row,
            now_ts=proactive.now_ts(), can_run=self._proactive_open(scene['_id']))
        if updated is None:
            return
        with self.ingress_lock:
            self.enqueued.add(episode)
        self.latest = episode
        self.pending.put((updated['event'], episode))
        self.app.evidence.record('proactive.enqueued', {'episode_id': episode,
            'scene_id': scene['_id'], 'holds': decision.get('holds', [])})

    def _proactive_stale(self, event, episode):
        """再核本身出错就当拦下：她自己的插话宁可少说一次，也不把一条旁听消息变成用户看得见的报错。"""
        try:
            return self._proactive_stale_inner(event, episode)
        except Exception:
            self.app.evidence.record('proactive.recheck_error', {'episode_id': episode,
                                                                 'traceback': traceback.format_exc()[-800:]})
            return True

    def _proactive_stale_inner(self, event, episode):
        """主动回合真要在跑之前再核一次闸门：这中间她可能已经说过一句、或前台开始忙了。"""
        from . import proactive
        if (event.get('group_context') or {}).get('wake_reason') != proactive.WAKE_REASON:
            return False                       # 不是她自己插的那句：该跑就跑，闸门管不着
        proactive, scene, row = self._proactive_group_row(event, episode)
        if not proactive:
            return False
        limits = proactive.route_settings(self.app.config, scene)
        moment = proactive.now_ts()
        profile = proactive.observe(self.app.store, scene, now_ts=moment, trigger=row, limits=limits)
        decision = proactive.decide(profile, limits, now_ts=moment,
                                    can_run=self._proactive_open(scene['_id']))
        if decision['fire']:
            return False
        current = self.app.store.db.messages.find_one({'_id': row['_id']})
        if not current:
            return True
        record = {**(current.get('proactive') or {}), 'wake': False,
                  'recheck_hold': decision['holds'],
                  'recheck_at': datetime.fromtimestamp(moment, timezone.utc).isoformat()}
        try:
            self.app.store.put('messages', {**current, 'processing_outcome': proactive.OUTCOME_HOLD,
                                           'proactive': record}, expected=current['revision'],
                               stream=episode)
        except Exception:
            pass
        self.app.evidence.record('proactive.hold', {'scene_id': scene['_id'], 'message_id': row['_id'],
            'stage': 'recheck', 'holds': decision['holds']})
        return True

    def recover_inputs(self):
        """Called once by the owning host before it exposes any clients."""
        with self.ingress_lock:
            for row in self.app.store.db.messages.find({'host_managed': True,
                    'ingress_state': {'$in': ['ACCEPTED', 'PROCESSING', 'FAILED']}}).sort('received_at', 1):
                episode = row['episode_id']
                # A failure before episode creation made no model/tool calls.
                # Keep its original identity and diagnostic when resuming.
                if row['ingress_state']=='FAILED':
                    if self.app.store.db.episodes.find_one({'_id':episode}) or 'retrieval' not in row.get('failure','').lower():
                        continue  # Only migrate the known pre-RAG failure; no blanket replay.
                if episode not in self.enqueued:
                    self.enqueued.add(episode)
                    self.pending.put((row['event'], episode))
                    self.app.evidence.record('host.input_recovered', {'episode_id': episode})

    def _work(self):
        while not self.stopping.is_set():
            if self.restart_pending.is_set():
                self.stopping.wait(.1)
                continue
            try:
                event, episode = self.pending.get(timeout=.1)
            except Empty:
                continue
            result = None
            error = None
            try:
                with self.state_lock:
                    if self.stopping.is_set():
                        self.app.evidence.record('chat.abandoned', event)
                        continue
                    if self.restart_pending.is_set():
                        self.pending.put((event, episode))
                        continue
                    self.active = episode or event['event_id']
                if event.get('_feedback_task'):
                    task = self.app.store.db.tasks.find_one({'_id': event['_feedback_task']})
                    result = self.app.service.feedback(task, self.app.coordinator)
                    if result is None:
                        continue
                    episode = result['_id']
                    self.latest = episode
                    if result['state']=='FAILED_PROTOCOL' and not self.stopping.is_set():
                        # The same durable feedback episode remains eligible.
                        # Give its role session the original error on the next
                        # normal queue turn; do not ingest or rerun the action.
                        self.pending.put((event, task['episode_id']))
                else:
                    scene = self.app.store.authorize(event['scene_id'], event['person_id'])
                    source = self.app.store.db.messages.find_one({'_id': 'in-' + episode})
                    if source['policy_epoch'] != scene['policy_epoch']:
                        raise PermissionError('INPUT_POLICY_STALE')
                    if event.get('channel'):
                        from .channels import route_for_scene, route_members
                        route = route_for_scene(self.app.config, event['channel']['id'], event['scene_id'])
                        member = route_members(route).get(event['channel'].get('sender_id', route.get('sender_id')), {})
                        if event.get('episode_kind')=='owner_group_prompt' and route.get('operator_sender_id')!=event['channel'].get('sender_id'):
                            raise PermissionError('GROUP_PROMPT_OWNER_REVOKED')
                        if (event.get('episode_kind') == 'owner_dm_prompt' and
                                (route['target']['type'] != 'dm' or
                                 route.get('sender_id') != event['channel'].get('sender_id'))):
                            raise PermissionError('DM_PROMPT_OWNER_REVOKED')
                        if (member.get('person_id') != event['person_id'] or route['target'] != event['channel']['target']
                                or event['channel']['account_id'] != self.app.config['channels'][event['channel']['id']]['account_id']):
                            raise PermissionError('INPUT_ROUTE_STALE')
                    input_state(self.app.store, episode, 'PROCESSING')
                    if self._proactive_stale(event, episode):
                        # P5：入队时闸门还开着，真要开口时已经不该插这句——不建 episode、不调模型。
                        input_state(self.app.store, episode, 'COMPLETE', result_state='PROACTIVE_HELD')
                        continue
                    previous = self.app.store.db.episodes.find_one({'_id': episode})
                    if previous and previous['state'] in ('PREPARED', 'MONOLOGUE_ACCEPTED', 'DECISION_ACCEPTED', 'SPEAK_ACCEPTED', 'INTERRUPTED'):
                        # Native lane receipts govern recovery; never invent a new operation ID.
                        result = self.app.router.coordinator.advance(episode)
                    else:
                        result = self.app.router.receive(event, persona=self.settings['persona'])
                    input_state(self.app.store, episode, 'COMPLETE', result_state=result['state'])
                    self._proactive_consider(event, episode, result)
                self.app.store.authorize(event['scene_id'], event['person_id'])
                messages = list(self.app.store.db.messages.find({
                    'episode_id': episode, 'scene_id': event['scene_id'],
                    'direction': 'outbound', 'phase': 'SPEAK', 'delivery_state': 'DELIVERED'
                }).sort('scene_seq', 1))
                for message in messages:
                    self.emit(f"{self.settings['display_name']}：{message['text']}")
                if result.get('task_id') and self.app.store.db.tasks.find_one({'_id':result['task_id'],'state':'READY'}):
                    self._schedule(result)
                elif result.get('silent_reason'):
                    self.emit('[系统] 角色明确选择本轮不发言；请查看本轮执行详情中的原因。')
                elif not messages:
                    self.emit(f"[系统] 本轮没有公开发言，状态：{result['state']}。请展开本轮执行详情查看原始过程。")
                self.app.evidence.record('chat.completed', {'episode_id': episode, 'state': result['state']})
            except Exception:
                error = redact(traceback.format_exc(), self.app.config)
                self.app.evidence.record('chat.error', {'episode_id': episode, 'traceback': error})
                try:
                    input_state(self.app.store, episode, 'FAILED', failure=error)
                    self.app.store.audit(episode, 'chat.error', {'traceback': error}, 'scene:' + event['scene_id'])
                    ep = self.app.store.db.episodes.find_one({'_id': episode})
                    if ep and ep['state'] not in ('COMMITTED', 'WAITING_TASK'):
                        self.app.store.put('episodes', {**ep, 'state': 'INTERRUPTED' if self.stopping.is_set() else 'FAILED_RUNTIME',
                                           'failure': error}, expected=ep['revision'], stream=episode)
                except Exception:
                    self.app.evidence.record('chat.persistence_error', {'episode_id': episode,
                        'traceback': redact(traceback.format_exc(), self.app.config)})
                self.emit(f'[系统] 本轮未完成；请查看本轮执行详情中的原始错误。原记录：{self.app.evidence.root.resolve()}')
            finally:
                if self.on_episode_finished:
                    try:
                        self.on_episode_finished(event, result, error)
                    except Exception:
                        self.app.evidence.record('chat.completion_callback_error', {
                            'episode_id': episode, 'traceback': redact(traceback.format_exc(), self.app.config)})
                with self.state_lock:
                    self.active = None
                with self.ingress_lock:
                    self.enqueued.discard(episode)
                self.pending.task_done()
                if self.on_turn_finished:
                    self.on_turn_finished()

    def stop(self):
        with self.state_lock:
            self.stopping.set()
            active = self.active
            active_task = self.active_task
        if self.pending.unfinished_tasks or self.task_queue.unfinished_tasks:
            self.emit('[系统] 正在停止宿主；未开始的已保存输入将在下次启动恢复，正在执行的任务撤销权限。')
        # Fence this application's work before shutting down its action lane.
        if not self.restart_pending.is_set():
            for task_id, revision in self.scheduled_tasks.copy():
                task = self.app.store.db.tasks.find_one({'_id': task_id})
                if task and task['intent_revision'] == revision and task['state'] in ('READY', 'RUNNING'):
                    self.app.service.cancel(task_id, reason='host_stop', person_id=task['requester_id'])
        if active_task:
            self.app.executor_lane.close()
        if active:
            self.app.character.close()
        self.worker.join(timeout=10)
        if self.task_worker.ident is not None:
            self.task_worker.join(timeout=10)
        abandoned = []
        while True:
            try:
                event, episode = self.pending.get_nowait()
            except Empty:
                break
            abandoned.append(event['event_id'])
            self.pending.task_done()
        self.app.evidence.record('chat.stopped', {'abandoned_event_ids': abandoned, 'worker_stopped': not self.worker.is_alive(),
                                                'task_worker_stopped': not self.task_worker.is_alive()})

