"""Shared local controller reused by the native Web host; there is no terminal adapter."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from queue import Queue, Empty
import threading
import traceback
import uuid

from . import handover
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
    for key in ('scene_id', 'person_id', 'persona', 'display_name'):
        if not settings.get(key):
            raise ValueError(f'CHAT_CONFIG_REQUIRED: {key}')
    return settings


try:                                  # 跨场景只读联动（A2）
    from . import scene_links
except Exception:
    scene_links = None


def seed_documents(store, settings):
    """Seeds only fill missing document heads (ADR-009 §5.4)."""
    from .documents import DocumentStore
    docs = DocumentStore(store, settings['persona'])
    seeds = (store.config.get('persona_contribution') or {}).get('seeds') or []
    for seed in seeds:
        if not docs.head(seed['slug']):
            docs.seed(seed['slug'], seed['kind'], Path(seed['path']).read_text(encoding='utf-8'),
                      path=Path(seed['path']).name, title=seed.get('title'))


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
        self.on_input_received = None
        self.restart_pending = threading.Event()
        # ADR-030: results on their way back to her (queued or being handed back now), and the watchdog over them.
        self.handbacks = set()
        self.watchdog = threading.Thread(target=self._watch, name='asuna-handover-watchdog', daemon=True)

    def _schedule(self, task_id):
        task = self.app.store.db.tasks.find_one({'_id': task_id})
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
                    self.hand_back(task)
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

    def submit(self, text, *, event_id=None, native_session_id=None, native_message_ids=None, media=None):
        if media:
            # Pictures the owner attached (vision.local_uploads): their placeholders lead the text, as a
            # platform's do, so history and recall know a picture came even after her session compacts.
            marks = ' '.join(item['placeholder'] for item in media['items'])
            text = marks + ('\n' + text if text else '')
        event = {'event_id': event_id or str(uuid.uuid4()), 'scene_id': self.settings['scene_id'],
                 'person_id': self.settings['person_id'], 'text': text}
        if media:
            event['raw'] = {'asuna_media': media}
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

    def offer_internal(self, kind, event_id, scene_id, person_id, text, **visit):
        """Queue a heartbeat or settlement opportunity in an owner-private scene (ADR-009 §10), her visit to
        a group (ADR-012 §4.2), which carries what she went there for and wakes the group as a scene tick, or a
        note of hers to a home conversation (ADR-018). Each waits behind what that scene already has queued."""
        extras = {'visit': {'scene_tick', 'group_context', 'visit'}, 'note': {'note'}}
        if kind not in ('presence', 'settlement', 'visit', 'note') or not event_id.startswith(kind + ':') \
                or bool(visit) != (kind in extras) or set(visit) - extras.get(kind, set()):
            raise ValueError('INVALID_INTERNAL_EVENT')
        return self.receive({'event_id': event_id, 'scene_id': scene_id, 'person_id': person_id,
                             'adapter_id': kind, 'episode_kind': kind, 'text': text, **visit})

    def offer_self_development(self, event_id: str, *, text=None, trusted_context_events=None,
                               task_id=None, stage=None):
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
        if stage:event['night_stage']=stage                 # ADR-021: one stage of her night self-development
        return self.receive(event)

    def receive(self, event):
        """Trusted host envelope only; adapters must use the bound channel API."""
        with self.ingress_lock:
            if self.stopping.is_set():
                raise RuntimeError('HOST_STOPPING')
            if self.reconfiguring:
                raise RuntimeError('HOST_RECONFIGURING')
            from .integration import event_profile
            if 'integration_profile' not in event:
                granted = event_profile(self.app.config, event, self.app.store)
                if granted:
                    # The same decision the router makes, so the stored input and the handled one agree.
                    event = {**event, 'integration_profile': granted}
            row, created = persist_input(self.app.store, event, managed=True)
            if self.on_input_received:
                try:
                    self.on_input_received(row)
                except Exception:
                    # The input is already durable. Its UI projection can be
                    # retried without asking the adapter to invent a new input.
                    self.app.evidence.record('host.input_projection_error', {
                        'input_id': row['_id'], 'traceback': redact(traceback.format_exc(), self.app.config)})
            episode = row['episode_id']
            if row.get('ingress_state') == 'ACCEPTED' and episode not in self.enqueued:
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

    def _sticker_pool(self, event, episode):
        """Stickers posted in a group go to her candidate pool while their links still work (owner 2026-10-06).
        Fetching runs off the input path; a failure is evidence, never a failed input."""
        channel = event.get('channel') if isinstance(event.get('channel'), dict) else {}
        if (channel.get('target') or {}).get('type') != 'group' or not (event.get('raw') or {}).get('asuna_media'):
            return

        def run():
            try:
                from .blobs import BlobStore
                from .stickers import pool_seen
                pool_seen(self.app.store, BlobStore(self.app.store), self.app.config, 'in-' + episode)
            except Exception:
                self.app.evidence.record('sticker.pool_error', {'episode_id': episode,
                                                                 'traceback': traceback.format_exc()[-800:]})
        threading.Thread(target=run, name='sticker-pool', daemon=True).start()

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
                    result = self.app.service.feedback(task, self.app.coordinator, short=event.get('_short', False),
                                                       again=event.get('_again', False))
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
                    if source.get('absorbed_by'):
                        # An earlier turn here had this line in view: she answered it there, or chose not to.
                        input_state(self.app.store, episode, 'COMPLETE', result_state='SEEN_IN_TURN')
                        continue
                    if event.get('channel'):
                        from .channels import route_for_scene, route_members
                        route = route_for_scene(self.app.config, event['channel']['id'], event['scene_id'])
                        member = route_members(route).get(event['channel'].get('sender_id', route.get('sender_id')), {})
                        if (member.get('person_id') != event['person_id'] or route['target'] != event['channel']['target']
                                or event['channel']['account_id'] != self.app.config['channels'][event['channel']['id']]['account_id']):
                            raise PermissionError('INPUT_ROUTE_STALE')
                    input_state(self.app.store, episode, 'PROCESSING')
                    if self._proactive_stale(event, episode):
                        # P5：入队时闸门还开着，真要开口时已经不该插这句——不建 episode、不调模型。
                        input_state(self.app.store, episode, 'COMPLETE', result_state='PROACTIVE_HELD')
                        continue
                    previous = self.app.store.db.episodes.find_one({'_id': episode})
                    from .coordinator import RESUMABLE
                    if previous and previous['state'] in RESUMABLE:
                        # Native lane receipts govern recovery; never invent a new operation ID.
                        result = self.app.router.coordinator.advance(episode)
                    else:
                        result = self.app.router.receive(event, persona=self.settings['persona'])
                    input_state(self.app.store, episode, 'COMPLETE', result_state=result['state'])
                    self._proactive_consider(event, episode, result)
                    self._sticker_pool(event, episode)
                self.app.store.authorize(event['scene_id'], event['person_id'])
                messages = list(self.app.store.db.messages.find({
                    'episode_id': episode, 'scene_id': event['scene_id'],
                    'direction': 'outbound', 'phase': 'SPEAK', 'delivery_state': 'DELIVERED'
                }).sort('scene_seq', 1))
                for message in messages:
                    self.emit(f"{self.settings['display_name']}：{message['text']}")
                ready = [task_id for task_id in result.get('task_ids') or ()
                         if self.app.store.db.tasks.find_one({'_id': task_id, 'state': 'READY'})]
                for task_id in ready:
                    self._schedule(task_id)
                if not ready and result.get('silent_reason'):
                    self.emit('[系统] 角色明确选择本轮不发言；请查看本轮执行详情中的原因。')
                elif not ready and not messages:
                    self.emit(f"[系统] 本轮没有公开发言，状态：{result['state']}。请展开本轮执行详情查看原始过程。")
                self.app.evidence.record('chat.completed', {'episode_id': episode, 'state': result['state']})
            except Exception:
                error = redact(traceback.format_exc(), self.app.config)
                self.app.evidence.record('chat.error', {'episode_id': episode, 'traceback': error})
                if event.get('_feedback_task'):
                    # A result that failed on its way back (ADR-030): the asking line itself was answered, it did not
                    # fail. What failed is recorded where the watchdog reads it: her turn on it ended, or the hand-back
                    # never reached a turn.
                    try:
                        from .handover import result_event_id
                        task = self.app.store.db.tasks.find_one({'_id': event['_feedback_task']})
                        short = event.get('_short', False)
                        turn = self.app.store.db.episodes.find_one({'source_event_id': result_event_id(task, short),
                                                                    'episode_kind': 'task_feedback'})
                        if turn and turn['state'] not in ('COMMITTED', 'WAITING_TASK'):
                            self.app.store.put('episodes', {**turn, 'state': 'INTERRUPTED' if self.stopping.is_set()
                                               else 'FAILED_RUNTIME', 'failure': error}, expected=turn['revision'], stream=turn['_id'])
                        elif not turn:
                            self.app.service.record_handback_failure(task['_id'], short)
                        self.app.service.handback(task, 'missed', 'turn' if turn else 'report', error.strip().splitlines()[-1][:200],
                                                  short=short)
                    except Exception:
                        self.app.evidence.record('chat.handback_record_error', {'task_id': event['_feedback_task'],
                            'traceback': redact(traceback.format_exc(), self.app.config)})
                    self.emit(f'[系统] 本轮未完成；请查看本轮执行详情中的原始错误。原记录：{self.app.evidence.root.resolve()}')
                    continue
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
                    if event.get('_feedback_task') and not (result and result['state'] == 'FAILED_PROTOCOL'):
                        self.handbacks.discard(event['_feedback_task'])
                with self.ingress_lock:
                    self.enqueued.discard(episode)
                self.pending.task_done()
                if self.on_turn_finished:
                    self.on_turn_finished()

    def hand_back(self, task, short=False, again=False):
        """Queue a finished task's result for her turn; the watchdog leaves it alone while it is on its way."""
        with self.state_lock:
            if task['_id'] in self.handbacks:
                return
            self.handbacks.add(task['_id'])
        self.pending.put(({'_feedback_task': task['_id'], 'event_id': task['_id'] + ':feedback', '_short': short,
                           '_again': again, 'scene_id': task['scene_id'], 'person_id': task['requester_id']},
                          task['episode_id']))

    def _watch(self):
        """ADR-030: every minute (first one minute after start), the definite failures and only those."""
        while not self.stopping.wait(handover.SWEEP_SECONDS):
            if self.restart_pending.is_set():
                continue
            try:
                self.sweep()
            except Exception:
                self.app.evidence.record('handover.sweep_error', {'traceback': redact(traceback.format_exc(), self.app.config)})

    def sweep(self):
        store, service = self.app.store, self.app.service
        with self.state_lock:
            running, on_its_way = self.active_task, set(self.handbacks)
        for task in handover.orphaned(store, running):
            closed = service.close_orphan(task)
            if closed:
                self.app.evidence.record('handover.orphan_closed', {'task_id': task['_id']})
                on_its_way.discard(task['_id'])
        for task in handover.lost(store, on_its_way | ({running} if running else set())):
            step = handover.next_step(store, task)
            self.app.evidence.record('handover.lost', {'task_id': task['_id'], 'step': step,
                                                      'cause': handover.cause(store, task)})
            if step == handover.GIVE_UP:
                service.give_up_handback(task)
            else:
                self.hand_back(task, short=step == handover.SHORT, again=True)

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
        if self.watchdog.ident is not None:
            self.watchdog.join(timeout=10)
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

