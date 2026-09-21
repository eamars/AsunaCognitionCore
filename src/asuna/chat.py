"""Shared local controller; terminal interaction is an explicit debug adapter only."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from queue import Queue, Empty
import sys
import threading
import traceback
import uuid

from .application import Application
from .config import ROOT, redact_text as redact
from .evidence import Evidence, canonical, sha
from .memory_indexer import MemoryIndexer
from .ingress import persist_input, input_state
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
    if not store.head('persona:' + settings['persona'], 'global-safe'):
        source = Path(settings['persona_file'])
        store.init_head('persona:' + settings['persona'], 'global-safe',
                        {'body': source.read_text(encoding='utf-8')}, [str(source)])
    store.init_head('relationship:' + person, scope,
                    {'body': '这是通过本机界面交流的用户。尚无共同经历，不预设熟悉程度。'}, [])


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
            try:
                task_id, revision = self.task_queue.get(timeout=.1)
            except Empty:
                continue
            try:
                with self.state_lock:
                    if self.stopping.is_set():
                        continue
                    self.active_task = task_id
                task = self.app.store.db.tasks.find_one({'_id': task_id})
                if task['state'] != 'READY' or task['intent_revision'] != revision:
                    continue
                from .resources import workspace_grant
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

    def new_context(self):
        self.pending.put(({'_new_context': True, 'event_id': str(uuid.uuid4()),
            'scene_id': self.settings['scene_id'], 'person_id': self.settings['person_id']}, None))

    def compact(self):
        self.pending.put(({'_compact': True, 'event_id': str(uuid.uuid4()),
            'scene_id': self.settings['scene_id'], 'person_id': self.settings['person_id']}, None))

    def submit(self, text):
        event = {'event_id': str(uuid.uuid4()), 'scene_id': self.settings['scene_id'],
                 'person_id': self.settings['person_id'], 'text': text}
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

    def recover_inputs(self):
        """Called once by the owning host before it exposes any clients."""
        with self.ingress_lock:
            for row in self.app.store.db.messages.find({'host_managed': True,
                    'ingress_state': {'$in': ['ACCEPTED', 'PROCESSING']}}).sort('received_at', 1):
                episode = row['episode_id']
                if episode not in self.enqueued:
                    self.enqueued.add(episode)
                    self.pending.put((row['event'], episode))
                    self.app.evidence.record('host.input_recovered', {'episode_id': episode})

    def _work(self):
        while not self.stopping.is_set():
            try:
                event, episode = self.pending.get(timeout=.1)
            except Empty:
                continue
            try:
                with self.state_lock:
                    if self.stopping.is_set():
                        self.app.evidence.record('chat.abandoned', event)
                        continue
                    self.active = episode
                if event.get('_compact'):
                    scene = self.app.store.authorize(event['scene_id'], event['person_id'])
                    binding = f"xiaoman:{scene['_id']}:{scene['policy_epoch']}:{self.settings['persona']}"
                    if scene.get('character_context'):
                        binding += ':' + scene['character_context']
                    if not self.app.store.db.sessions.find_one({'binding_key': binding}):
                        self.emit('[系统] 当前上下文尚无对话可压缩。')
                        continue
                    self.app.character.compact(binding)
                    self.emit('[系统] 已请求原生压缩，将在下一次完整认知轮次的边界执行；实际结果以执行记录为准。')
                    continue
                if event.get('_new_context'):
                    scene = self.app.store.authorize(event['scene_id'], event['person_id'])
                    if self.app.store.db.tasks.find_one({'scene_id': scene['_id'], 'state': {'$in': ['READY', 'RUNNING']}}):
                        self.emit('[系统] 请等当前行动结束后再新建上下文。')
                        continue
                    generation = str(uuid.uuid4())
                    self.app.store.put('scenes', {**scene, 'character_context': generation},
                                       expected=scene['revision'], stream='chat:new-context')
                    self.app.evidence.record('chat.new_context', {'scene_id': scene['_id'], 'generation': generation})
                    self.emit('[系统] 已切换新的角色上下文，保留人格、场景和数据库记忆；下一条输入自动检索。')
                    continue
                if event.get('_feedback_task'):
                    task = self.app.store.db.tasks.find_one({'_id': event['_feedback_task']})
                    result = self.app.service.feedback(task, self.app.coordinator)
                    if result is None:
                        continue
                    episode = result['_id']
                    self.latest = episode
                else:
                    scene = self.app.store.authorize(event['scene_id'], event['person_id'])
                    source = self.app.store.db.messages.find_one({'_id': 'in-' + episode})
                    if source['policy_epoch'] != scene['policy_epoch']:
                        raise PermissionError('INPUT_POLICY_STALE')
                    if event.get('channel'):
                        from .channels import route_for_scene
                        route = route_for_scene(self.app.config, event['channel']['id'], event['scene_id'])
                        if (route['person_id'] != event['person_id'] or route['target'] != event['channel']['target']
                                or event['channel']['account_id'] != self.app.config['channels'][event['channel']['id']]['account_id']):
                            raise PermissionError('INPUT_ROUTE_STALE')
                    input_state(self.app.store, episode, 'PROCESSING')
                    previous = self.app.store.db.episodes.find_one({'_id': episode})
                    if previous and previous['state'] in ('PREPARED', 'MONOLOGUE_ACCEPTED', 'DECISION_ACCEPTED', 'SPEAK_ACCEPTED'):
                        # Native lane receipts govern recovery; never invent a new operation ID.
                        result = self.app.router.coordinator.advance(episode)
                    else:
                        result = self.app.router.receive(event, persona=self.settings['persona'])
                    input_state(self.app.store, episode, 'COMPLETE', result_state=result['state'])
                self.app.store.authorize(event['scene_id'], event['person_id'])
                messages = list(self.app.store.db.messages.find({
                    'episode_id': episode, 'scene_id': event['scene_id'],
                    'direction': 'outbound', 'phase': 'SPEAK', 'delivery_state': 'DELIVERED'
                }).sort('scene_seq', 1))
                for message in messages:
                    self.emit(f"{self.settings['display_name']}：{message['text']}")
                if result['state'] == 'WAITING_TASK':
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
                with self.state_lock:
                    self.active = None
                with self.ingress_lock:
                    self.enqueued.discard(episode)
                self.pending.task_done()

    def trace(self):
        scene = self.app.store.authorize(self.settings['scene_id'], self.settings['person_id'])
        episode = self.latest
        if episode is None:
            previous = self.app.store.db.messages.find_one({'scene_id': scene['_id'], 'direction': 'inbound'}, sort=[('scene_seq', -1)])
            episode = previous['_id'].removeprefix('in-') if previous else None
        if not episode:
            return '[系统] 尚无交互记录。'
        lines = [f'[trace] 数据库 {self.app.store.name} / episodes / {episode}',
                 f'本次原记录：{self.app.evidence.root.resolve()}']
        ep = self.app.store.db.episodes.find_one({'_id': episode, 'scope_key': scene['scope_key'], 'policy_epoch': scene['policy_epoch']})
        if self.app.store.db.episodes.find_one({'_id': episode}) and ep is None:
            raise PermissionError('TRACE_SCOPE_OR_EPOCH_CHANGED')
        if ep:
            context = ep['context']
            lines += ['状态：' + ep['state'], '实际人格与共同约束：\n' + ep['system'],
                      '人格来源：state_revisions/' + ep['manifest']['persona_revision'],
                      '当前输入：' + context['event']['text'],
                      '关系：' + json.dumps(context['relationship'], ensure_ascii=False),
                      '关系来源：state_revisions/' + str(ep['manifest']['relationship_revision'])]
            if 'available_skills_from_native_dsh' in context:
                lines.append('本轮角色实际收到的原生技能目录：\n' + json.dumps(context['available_skills_from_native_dsh'], ensure_ascii=False, indent=2))
            if ep.get('understanding_update'):
                lines.append('角色理解修订实际结果：\n' + json.dumps(ep['understanding_update'], ensure_ascii=False, indent=2))
            for memory in context['memories']:
                lines.append(f"召回 {memory['_id']}（{memory.get('epistemic_type')}；来源 {memory.get('source_event_ids')}）：\n{memory['body_markdown']}")
            retrieval = ep['manifest']['retrieval']
            lines.append(f"检索方式：{retrieval['path']}；待索引回读：{retrieval.get('pending_backread', [])}；检索错误：{retrieval.get('failure')}")
            if ep.get('silent_reason'):
                lines.append('明确沉默原因：' + ep['silent_reason'])
            if ep.get('failure'):
                lines.append('失败原因：' + ep['failure'])
        else:
            lines.append('输入已入队，尚未完成上下文准备。')
        for event in self.app.store.db.audit_events.find({'stream_id': episode, 'scope_key': scene['scope_key']}).sort('seq', 1):
            if event['type'] == 'phase.output':
                value = event['payload']
                lines.append(f"{event['occurred_at']} {value['phase']}（结束原因 {value['finish_reason']}）：\n{value['content'] or '[空输出]'}")
                lines.extend('实际请求：' + ref['artifact_path'] for ref in value['request_refs'])
            elif event['type'] in ('phase.started', 'phase.failed', 'chat.error', 'publication.receipt'):
                lines.append(f"{event['occurred_at']} {event['type']}\n" + json.dumps(event['payload'], ensure_ascii=False, indent=2, default=str))
        if ep:
            binding = f"xiaoman:{scene['_id']}:{scene['policy_epoch']}:{ep['persona']}"
            if ep.get('character_context'):
                binding += ':' + ep['character_context']
            native = self.app.store.db.sessions.find_one({'binding_key': binding})
            if native:
                lines.append('原生会话／压缩次数：' + native['_id'] + ' / ' + str(native.get('compaction_generation', 0)))
                for record in self.app.store.db.audit_events.find({'type': 'compaction.native',
                        'payload.session_id': native['_id']}).sort('occurred_at', 1):
                    lines.append('实际原生压缩：\n' + json.dumps(record['payload'], ensure_ascii=False, indent=2, default=str))
        task_id = (ep or {}).get('task_id') or (ep or {}).get('control_result', {}).get('task_id') or self.latest_task
        if task_id:
            task = self.app.store.db.tasks.find_one({'_id': task_id, 'scope_key': scene['scope_key'], 'policy_epoch': scene['policy_epoch']})
            lines.append('实际委托：\n' + json.dumps(task, ensure_ascii=False, indent=2, default=str))
            if task:
                for item in self.app.store.db.artifacts.find({'task_id': task['_id'], 'scope_key': scene['scope_key'], 'intent_revision': task['intent_revision']}):
                    lines.append(f"实际工具 {item['_id']} / {item.get('tool')} / {item['state']}\n" +
                                 json.dumps({'args': item.get('args'), 'result': item.get('result')}, ensure_ascii=False, indent=2, default=str))
                for item in self.app.store.db.audit_events.find({'stream_id': task['_id'], 'scope_key': scene['scope_key'],
                                                                 'type': {'$in': ['execution.output', 'execution.failed', 'tool.failed', 'skills.native_calls']}}).sort('seq', 1):
                    lines.append(f"{item['occurred_at']} {item['type']}\n" + json.dumps(item['payload'], ensure_ascii=False, indent=2, default=str))
        # Include native error bodies, including failures before a stage returned.
        roots = {self.app.evidence.root.resolve()}
        if ep:
            for binding in self.app.store.db.sessions.find({'scope_key': scene['scope_key'], 'policy_epoch': scene['policy_epoch']}):
                roots.update(Path(p).resolve() for p in binding.get('evidence_roots', []))
        for root in sorted(roots):
            if not root.is_relative_to(ROOT.resolve()):
                continue
            for path in sorted(root.glob('*.json')):
                if not any(kind in path.name for kind in ('lane.receipt', 'chat.error', 'chat.persistence_error', 'chat.task_error', 'chat.task_persistence_error')):
                    continue
                payload = json.loads(path.read_text(encoding='utf-8'))['payload']
                if payload.get('episode_id') == episode:
                    lines.append(f'原始错误 {path}:\n' + payload['traceback'])
                if task_id and payload.get('task_id') == task_id:
                    lines.append(f'原始行动错误 {path}:\n' + payload['traceback'])
                if payload.get('operation', '').startswith(tuple(x + ':' for x in (episode, task_id) if x)):
                    body = payload['body']
                    if payload.get('status_code', 200) >= 400 or body.get('finish_reason') not in ('completed', 'stop'):
                        lines.append(f'原始 DSH 回执 {path}:\n' + json.dumps(body, ensure_ascii=False, indent=2))
        counts = list(self.app.store.db.memory_units.aggregate([
            {'$match': {'scope_key': scene['scope_key'], 'policy_epoch': scene['policy_epoch'], 'status': 'active'}},
            {'$group': {'_id': '$embedding_status', 'count': {'$sum': 1}}}]))
        lines.append('当前场景记忆索引状态：' + json.dumps(counts, ensure_ascii=False))
        for path in sorted(self.app.evidence.root.glob('*memory.index_error.json'))[-1:]:
            lines.append('最近索引错误（待处理记录会重试）：\n' + path.read_text(encoding='utf-8'))
        result = redact('\n'.join(lines), self.app.config)
        path = self.app.evidence.root / f'trace-{episode}.txt'
        path.write_text(result, encoding='utf-8')
        return result + '\n可读记录：' + str(path.resolve())

    def stop(self):
        with self.state_lock:
            self.stopping.set()
            active = self.active
            active_task = self.active_task
        if self.pending.unfinished_tasks or self.task_queue.unfinished_tasks:
            self.emit('[系统] 正在停止宿主；未开始的已保存输入将在下次启动恢复，正在执行的任务撤销权限。')
        # Fence this application's work before shutting down its action lane.
        for task_id, revision in self.scheduled_tasks.copy():
            task = self.app.store.db.tasks.find_one({'_id': task_id})
            if task and task['intent_revision'] == revision and task['state'] in ('READY', 'RUNNING'):
                self.app.service.cancel(task_id, reason='host_stop', person_id=task['requester_id'])
        if active_task:
            self.app.executor_lane.sdk.close()
        if active:
            # SDK shutdown is bounded and only owns this Application's process.
            self.app.character.sdk.close()
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


async def terminal(controller, *, debug=False):
    if not debug:
        raise PermissionError('CLI_DEBUG_ONLY: 正式交互使用 Web UI')
    from prompt_toolkit import PromptSession
    from prompt_toolkit.patch_stdout import patch_stdout
    # patch_stdout redraws the unfinished input instead of overwriting it.
    session = PromptSession() if sys.stdin.isatty() else None
    with patch_stdout():
        controller.worker.start()
        controller.task_worker.start()
        print('[DEBUG] 仅限故障诊断；正式交互与验收请使用 Web UI。/help 帮助；/trace 最近过程；/quit 退出。', flush=True)
        try:
            while True:
                try:
                    text = (await session.prompt_async('你：') if session else await asyncio.to_thread(sys.stdin.readline))
                except (EOFError, KeyboardInterrupt):
                    break
                if not text:
                    if session:
                        continue
                    break
                text = text.strip()
                if not text:
                    continue
                if text == '/quit':
                    break
                if text == '/help':
                    print('[系统] 直接输入中文聊天。/trace 查看真实过程；/new 新上下文，保留记忆；/compact 在完整轮次边界压缩当前上下文；/quit 退出。')
                elif text == '/compact':
                    controller.compact()
                elif text == '/new':
                    controller.new_context()
                elif text == '/trace':
                    try:
                        print(await asyncio.to_thread(controller.trace))
                    except Exception:
                        print('[系统] 无法读取 trace：\n' + redact(traceback.format_exc(), controller.app.config))
                elif text.startswith('/'):
                    print('[系统] 未知命令。可用 /help、/trace、/quit。')
                else:
                    controller.submit(text)
        finally:
            await asyncio.to_thread(controller.stop)


def chat(config, database=None, out=None, *, debug=False):
    if not debug:
        raise PermissionError('CLI_DEBUG_ONLY: 正式交互使用 Web UI')
    settings = local_settings(config)
    name = 'chat-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:6]
    evidence = Evidence(Path(out) if out else ROOT / 'reports' / name)
    try:
        with Application({**config, 'task_mode': 'workspace'}, evidence, database) as app:
            prepare_local_scene(app.store, settings)
            app.memory_indexer = MemoryIndexer(app.store, evidence, settings['scene_id']).start()
            app.stack.callback(app.memory_indexer.close)
            asyncio.run(terminal(Chat(app, settings), debug=True))
        return 0
    except Exception:
        error = redact(traceback.format_exc(), config)
        evidence.record('chat.startup_error', {'traceback': error})
        print('[系统] 启动或关闭失败：\n' + error, file=sys.stderr)
        print(f'[系统] 原记录：{evidence.root.resolve()}', file=sys.stderr)
        return 1
