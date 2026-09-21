"""Thin, operator-local UI adapter over Chat and existing scoped Mongo records."""
from __future__ import annotations

from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
import threading
from urllib.parse import parse_qs, urlsplit
import uuid
import httpx

from .config import ROOT, redact_text
from .state import Store
from .model_settings import public_models, edited_models, revision, persist, LANES


def display(value):
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)


def is_error(value):
    if not isinstance(value, dict):
        return False
    return bool(value.get('error') or value.get('traceback') or value.get('failure') or
                value.get('exit_code') or any(is_error(v) for v in value.values() if isinstance(v, dict)))


def trace_step(event, action=False):
    """Unknown event kinds keep their original type and payload."""
    kind, payload = event['type'], event.get('payload', {})
    if kind == 'state.commit' and payload.get('collection') == 'artifacts':
        payload = payload['document']
        kind = 'tool_call' if payload['state'] == 'INTENT' else 'tool_result'
    elif kind.startswith('state.') or kind == 'context.prepared':
        return None  # Storage bookkeeping and full prompt/context are not UI steps.
    tool = kind.startswith('tool')
    role = kind.startswith('phase.') or kind.startswith('understanding.')
    actor_role = 'tool' if tool else 'role' if role else 'action' if action else 'system'
    actor = '工具调用' if kind == 'tool_call' else '工具结果' if tool else '角色脑' if role else '行动脑' if action else '系统 / 协调器'
    status = 'error' if any(word in kind for word in ('failed', 'error')) or is_error(payload) else 'running' if kind.endswith('started') else 'ok'
    summary = next((payload[key] for key in ('content', 'traceback', 'error', 'goal', 'tool', 'state', 'phase') if payload.get(key)), kind)
    return {'id': event['_id'], 'type': kind, 'actor': actor, 'actorRole': actor_role,
            'label': actor + (' · ' + payload['phase'] if payload.get('phase') else ''),
            'summary': display(summary), 'createdAt': event.get('occurred_at'), 'status': status, 'payload': payload}


def inspector_record(row, kind='memory'):
    content = row.get('body_markdown') or row.get('content') or row.get('title') or row['_id']
    body = content.get('body', display(content)) if isinstance(content, dict) else str(content)
    fields = {key: value for key, value in row.items() if key not in ('embedding', '_last_op')}
    return {'id': row['_id'], 'kind': kind, 'title': row.get('title') or body[:70],
            'description': row.get('kind', kind), 'createdAt': row.get('occurred_at', row.get('created_at')),
            'source': ', '.join(row.get('source_event_ids', row.get('source_ids', []))),
            'excerpt': body, 'fields': fields}


class Workbench:
    def __init__(self, store, settings, controller=None):
        self.store, self.settings, self.controller = store, settings, controller
        self.notices = []
        self.lock = threading.Lock()
        self.command_lock = threading.Lock()
        self.models_applying = False
        self.models_error = ''
        self.model_thread = None

    def models_snapshot(self):
        return {'models': public_models(self.store.config), 'revision': revision(self.store.config),
                'applying': self.models_applying, 'error': self.models_error,
                'ready': self.controller is None or getattr(self.controller.app, 'models_ready', True)}

    def apply_models(self, body):
        controller = self.controller
        if not self.store.config.get('_model_settings_path'):
            raise ValueError('当前启动未指定可保存的模型配置路径')
        candidate = edited_models(self.store.config, body)
        if controller.pending.unfinished_tasks or controller.task_queue.unfinished_tasks or self.store.db.tasks.find_one({'scene_id': self.settings['scene_id'], 'state': {'$in': ['READY', 'RUNNING']}}):
            raise ValueError('请等当前回复、排队消息和行动完成后再切换模型')
        self.models_applying, self.models_error = True, ''
        previous = self.store.config
        def apply():
            try:
                controller.app.replace_models(candidate)
                try:
                    persist(candidate, candidate['_model_settings_path'])
                except Exception:
                    controller.app.replace_models(previous)
                    raise
                self.emit('[系统] 两条模型配置已保存并应用；后续消息使用新配置。')
            except Exception as exc:
                self.models_error = redact_text(redact_text(str(exc), candidate), previous)
                self.emit('[系统] 模型配置未应用：' + self.models_error)
            finally:
                self.models_applying = False
        self.model_thread = threading.Thread(target=apply, daemon=True)
        self.model_thread.start()
        return {'accepted': True}

    def discover_models(self, body):
        from .config import validate_endpoint
        lane = body.get('lane')
        if lane not in LANES:
            raise ValueError('未知模型职责')
        base = body.get('base_url', '').rstrip('/')
        validate_endpoint(base)
        saved = self.store.config[lane]
        key = body.get('api_key') or (saved.get('api_key') if base == saved['base_url'].rstrip('/') and not body.get('clear_api_key') else '')
        try:
            with httpx.Client(timeout=10, trust_env=False, follow_redirects=False) as client:
                response = client.get(base + '/models', headers={'Authorization': 'Bearer ' + key} if key else {})
                response.raise_for_status()
                rows = response.json()['data']
                return {'models': [{'id': row['id']} for row in rows if isinstance(row.get('id'), str)]}
        except Exception as exc:
            raise ValueError('读取模型列表失败；请核对地址、凭据和服务状态（' + type(exc).__name__ + '）') from None

    def emit(self, text):
        if text.startswith('[系统]'):
            with self.lock:
                self.notices.append({'id': str(uuid.uuid4()), 'role': 'system', 'authorLabel': '系统',
                                     'text': text, 'createdAt': datetime.now(timezone.utc).isoformat()})
                self.notices = self.notices[-8:]

    def snapshot(self, selected=''):
        store, settings = self.store, self.settings
        scene = store.authorize(settings['scene_id'], settings['person_id'])
        scope = {'scope_key': scene['scope_key'], 'policy_epoch': scene['policy_epoch']}
        episodes = list(store.db.episodes.find({**scope, 'scene_id': scene['_id']}, {'system': 0, 'context': 0}).sort('_id', 1))
        # Contexts are native Chat /new generations, not fabricated channels.
        current = scene.get('character_context', 'initial')
        groups = {current: []}
        by_id = {ep['_id']: ep for ep in episodes}
        for ep in episodes:
            groups.setdefault(ep.get('character_context', 'initial'), []).append(ep['_id'])
        chosen = selected or current
        if chosen not in groups:
            raise ValueError('会话不存在或已不可访问')
        messages = list(store.db.messages.find({**scope, 'scene_id': scene['_id'], '$or': [
            {'direction': 'inbound'}, {'direction': 'outbound', 'delivery_state': 'DELIVERED', 'phase': 'SPEAK'}]}).sort('scene_seq', 1))
        def episode_id(message):
            return message.get('episode_id') or message['_id'].removeprefix('in-')
        conversations = []
        for context, ids in groups.items():
            rows = [m for m in messages if episode_id(m) in ids]
            first = next((m['text'] for m in rows if m['direction'] == 'inbound' and by_id[episode_id(m)].get('episode_kind', 'external') == 'external'), '本机聊天')
            conversations.append({'id': context, 'title': ('当前 · ' if context == current else '') + first[:28],
                                  'channelType': 'local',
                                  'updatedAt': next((m.get('occurred_at') or m.get('received_at') for m in reversed(rows) if m.get('occurred_at') or m.get('received_at')), ''),
                                  '_order': rows[-1]['scene_seq'] if rows else 0})
        conversations.sort(key=lambda row: (row['id'] == current, row['_order']), reverse=True)
        for item in conversations:
            item.pop('_order')
        rows = [m for m in messages if episode_id(m) in groups[chosen]][-80:]
        visible_ids = {episode_id(m) for m in rows}
        traces = {}
        for ep_id in visible_ids:
            ep = by_id[ep_id]
            task_id = ep.get('task_id') or ep.get('control_result', {}).get('task_id')
            task = store.db.tasks.find_one({'_id': task_id, **scope}) if task_id else None
            streams = [ep_id] + ([task_id] if task else [])
            events = list(store.db.audit_events.find({'stream_id': {'$in': streams}, 'scope_key': scene['scope_key']}).sort([('occurred_at', 1), ('seq', 1)]))
            steps = [step for event in events if (step := trace_step(event, event['stream_id'] == task_id))]
            finished = {event.get('payload', {}).get('operation') for event in events if event['type'] in ('phase.output', 'phase.failed')}
            for step in steps:
                if step['type'] == 'phase.started' and (step['payload'].get('operation') in finished or ep['state'] in ('COMMITTED', 'INTERRUPTED', 'FAILED_RUNTIME', 'FAILED_PROTOCOL')):
                    step['status'] = 'ok'
            if ep.get('failure'):
                steps.append({'id': ep_id + ':failure', 'type': 'episode.failure', 'label': '执行失败', 'status': 'error', 'summary': display(ep['failure']), 'payload': ep['failure']})
            traces[ep_id] = steps
        rendered, attached = [], set()
        for row in rows:
            ep_id = episode_id(row)
            public = row['direction'] == 'outbound'
            if not public and by_id[ep_id].get('episode_kind', 'external') != 'external':
                continue  # Task feedback is an internal event, not a user utterance.
            message = {'id': row['_id'], 'role': 'assistant' if public else 'user',
                       'authorLabel': settings['display_name'] if public else '你',
                       'text': row['text'], 'createdAt': row.get('occurred_at', row.get('received_at')), '_order': row['scene_seq']}
            if public:
                message['internalSteps'] = traces[ep_id]
                attached.add(ep_id)
            rendered.append(message)
        for ep_id in dict.fromkeys(episode_id(row) for row in rows if episode_id(row) not in attached):
            ep = by_id[ep_id]
            input_row = next(row for row in rows if episode_id(row) == ep_id)
            # Never manufacture an assistant reply for a pending, silent or failed turn.
            rendered.append({'id': ep_id + ':status', 'role': 'system', 'authorLabel': '执行状态',
                             'text': ep.get('silent_reason') or ep['state'], 'internalSteps': traces[ep_id],
                             '_order': input_row['scene_seq'] + 0.5})
        rendered.sort(key=lambda row: row['_order'])
        for row in rendered:
            row.pop('_order')
        records = []
        for row in store.db.memory_units.find({'$or': [scope, {'scope_key': 'global-safe', 'policy_epoch': 1}], 'status': 'active'}, {'embedding': 0}).sort([('occurred_at', -1), ('_id', 1)]).limit(100):
            kind = row.get('kind')
            records.append(inspector_record(row, 'memory' if kind in (None, 'chat_chunk', 'monologue') else kind))
        relation = store.head('relationship:' + settings['person_id'], scene['scope_key'])
        if relation:
            records.append(inspector_record(relation[1], 'relationship'))
        with self.lock:
            notices = list(self.notices) if chosen == current else []
        data = {'conversationId': chosen, 'title': next(row['title'] for row in conversations if row['id'] == chosen),
                'subtitle': f"本机聊天 · {scene['_id']} · 最近 80 条消息 / 100 条记忆 · " + ('当前上下文' if chosen == current else '历史上下文（只读）'),
                'conversations': conversations, 'messages': rendered + notices, 'records': records,
                'readOnly': self.controller is None, 'canSend': chosen == current and not self.models_applying and (self.controller is None or getattr(self.controller.app, 'models_ready', True)),
                'modelSettings': self.models_snapshot(),
                'emptyReasons': {'preference': '当前存储没有独立的偏好记录；原始内容可在记忆中查看。',
                                 'group_preference': '当前本机场景没有群偏好记录。'}}
        latest_scene = store.authorize(settings['scene_id'], settings['person_id'])
        if latest_scene['policy_epoch'] != scene['policy_epoch'] or latest_scene['scope_key'] != scene['scope_key']:
            raise PermissionError('场景授权已变化，请刷新')
        # Same credential redaction as the terminal trace, including nested payloads.
        return json.loads(redact_text(json.dumps(data, ensure_ascii=False, default=str), store.config))

    def command(self, path, body):
        with self.command_lock:
            return self._command(path, body)

    def _command(self, path, body):
        self.store.authorize(self.settings['scene_id'], self.settings['person_id'])
        if self.controller is None:
            raise PermissionError('只读模式不能发送消息或新建上下文')
        if self.models_applying:
            raise ValueError('正在应用模型配置，请稍候')
        if path == '/models/discover':
            return self.discover_models(body)
        if path == '/models':
            return self.apply_models(body)
        if not getattr(self.controller.app, 'models_ready', True):
            raise ValueError('模型运行时未就绪，请在模型设置中修正并重新应用')
        if path == '/send':
            value = body.get('text')
            if not isinstance(value, str) or not 1 <= len(value.strip()) <= 16000:
                raise ValueError('请输入 1–16000 字的消息')
            self.controller.submit(value.strip())
        elif path == '/new':
            self.controller.new_context()
        else:
            raise ValueError('未知操作')
        return {'accepted': True}


class UiBridge:
    def __init__(self, workbench):
        self.token = secrets.token_hex(32)
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def handle_request(self):
                status = 200
                try:
                    if self.headers.get('Authorization') != 'Bearer ' + owner.token:
                        raise PermissionError('UI_AUTH_REQUIRED')
                    url = urlsplit(self.path)
                    if self.command == 'GET' and url.path == '/state':
                        value = workbench.snapshot(parse_qs(url.query).get('conversation', [''])[0])
                    elif self.command == 'POST' and url.path in ('/send', '/new', '/models', '/models/discover'):
                        size = int(self.headers.get('Content-Length', '0'))
                        if not 0 < size <= 65536:
                            raise ValueError('INVALID_BODY_SIZE')
                        body = json.loads(self.rfile.read(size))
                        if not isinstance(body, dict):
                            raise ValueError('INVALID_BODY')
                        value = workbench.command(url.path, body)
                    else:
                        status, value = 404, {'error': '未知接口'}
                except PermissionError as exc:
                    status, value = 403, {'error': str(exc)}
                except (ValueError, TypeError) as exc:
                    status, value = 400, {'error': str(exc)}
                except Exception as exc:
                    status, value = 503, {'error': redact_text(str(exc), workbench.store.config)}
                data = json.dumps(value, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = handle_request
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def serve(workbench, port):
    bridge = UiBridge(workbench)
    env = {**os.environ, 'DSH_HOME': str(ROOT / '.runtime' / 'ui-shell'), 'DSH_TELEMETRY_DISABLED': '1',
           'ASUNA_UI_BRIDGE': f'http://127.0.0.1:{bridge.server.server_port}', 'ASUNA_UI_TOKEN': bridge.token}
    command = ['node', str(ROOT / 'node_modules/@deepseek-ai/dsh/lib/bin.js'), '--profile', 'web',
               '--patch', str(ROOT / 'dsh-plugin/ui/cordis.patch.yml'), '--host', '127.0.0.1', '--port', str(port), '--no-open']
    process = None
    try:
        process = subprocess.Popen(command, cwd=ROOT, env=env)
        print(f'Asuna UI: http://127.0.0.1:{port}/asuna/ （DSH 原生页面也可从侧栏 Asuna 打开）', flush=True)
        return process.wait()
    except KeyboardInterrupt:
        return 0
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        bridge.close()


def ui(config, database=None, out=None, *, port=8765, read_only=False):
    from .chat import Chat, local_settings, prepare_local_scene
    settings = local_settings(config)
    if read_only:
        store = Store(config, database)
        try:
            store.authorize(settings['scene_id'], settings['person_id'])
            return serve(Workbench(store, settings), port)
        finally:
            store.client.close()
    from .application import Application
    from .evidence import Evidence
    from .memory_indexer import MemoryIndexer
    evidence = Evidence(Path(out) if out else ROOT / 'reports' / ('ui-' + uuid.uuid4().hex[:12]))
    with Application({**config, 'task_mode': 'workspace'}, evidence, database) as app:
        prepare_local_scene(app.store, settings)
        indexer = MemoryIndexer(app.store, evidence, settings['scene_id']).start()
        app.stack.callback(indexer.close)
        workbench = Workbench(app.store, settings)
        controller = Chat(app, settings, emit=workbench.emit)
        workbench.controller = controller
        controller.worker.start()
        controller.task_worker.start()
        try:
            return serve(workbench, port)
        finally:
            if workbench.model_thread:
                workbench.model_thread.join()
            controller.stop()
