"""Thin, operator-local UI adapter over Chat and existing scoped Mongo records."""
from __future__ import annotations

from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import threading
from urllib.parse import parse_qs, urlsplit
import uuid
import httpx

from .config import ROOT, redact_text
from .state import Store, Denied
from .model_settings import public_models, edited_models, revision, persist, LANES
from .ui_stream import UiStreamHub


def display(value):
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)


def is_error(value):
    if not isinstance(value, dict):
        return False
    return bool(value.get('error') or value.get('traceback') or value.get('failure') or
                value.get('exit_code') or any(is_error(v) for v in value.values() if isinstance(v, dict)))


def trace_step(event, action=False):
    """Unknown event kinds keep their original type and payload."""
    kind, payload = event['type'], dict(event.get('payload', {}))
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
    if kind in ('phase.output', 'execution.output') and payload.get('finish_reason') not in (None, 'stop'):
        status = 'error'
    summary = next((payload[key] for key in ('content', 'traceback', 'error', 'goal', 'tool', 'state', 'phase') if payload.get(key)), kind)
    return {'id': event['_id'], 'type': kind, 'actor': actor, 'actorRole': actor_role,
            'label': actor + (' · ' + payload['phase'] if payload.get('phase') else ''),
            'summary': display(summary), 'createdAt': event.get('occurred_at'), 'status': status,
            'sourceStreamId': event.get('stream_id'), 'payload': payload}


# ── 本轮状态：程序事实与角色决定分开说 ────────────────────────────────
# 一条已落库的入站可能停在三个不同的地方：程序闸门（没建 episode、没调模型）、
# 角色自己选了沉默（模型跑过）、或者根本还没轮到。三者必须在 Web 上分得清，
# 否则"程序没让它进模型"会被读成"她看了一眼、选择不说"。
PROGRAM_HOLD_OUTCOMES = ('PROACTIVE_HOLD',)   # proactive.OUTCOME_HOLD
PROGRAM_HOLD_STATES = ('PROACTIVE_HELD',)     # chat.py 再核拦下时写的 result_state
RUNNING_PHASES = ('PREPARED', 'MONOLOGUE_ACCEPTED', 'DECISION_ACCEPTED', 'SPEAK_ACCEPTED')
INGRESS_PENDING = {'ACCEPTED': ('已接收，排队中', '程序还没轮到这一轮，模型尚未调用'),
                   'PROCESSING': ('处理中', '程序正在准备这一轮，还没有结果')}
# 闸门名字跟 P5 的 holds 名单对齐（tools/p5b_ui_offline_check.py 会拿 proactive.py 源码对账）。
# 没见过的名字原样显示，不替它编解释。
HOLD_GATES = {
    'not_enrolled': '这个场景没开主动模式',
    'not_a_group_scene': '不是群场景',
    'trigger_without_time': '这条消息读不到发生时间',
    'quiet_hours': '安静时段',
    'dense_exchange': '群里正在快速一问一答',
    'candidate_merge_window': '这波消息还没发完',
    'probe_cooldown': '刚问过一轮，还在冷却',
    'scene_cooldown': '距上次自己插话太近',
    'hourly_cap': '这一小时主动说过太多次',
    'topic_attempt_unanswered': '这条话题插过一次还没人接',
    'foreground_busy': '前台行动在跑，或队列里排着别的输入',
    'decision_write_conflict': '决定没写进行记录（并发）',
}


def program_hold(ep):
    """程序闸门拦下的那条入站：没有角色 episode，模型一次都没被调用。

    只读程序自己写在行上的字段（processing_outcome／result_state／proactive），
    不从正文或场景猜。再核拦下时以 recheck_hold 为准——第一次评估的 holds 是空的，
    那一次闸门确实是开着的。
    """
    if not isinstance(ep, dict):
        return None
    if (ep.get('processing_outcome') not in PROGRAM_HOLD_OUTCOMES
            and ep.get('result_state') not in PROGRAM_HOLD_STATES):
        return None
    record = ep.get('proactive') if isinstance(ep.get('proactive'), dict) else {}
    recheck = record.get('recheck_hold')
    raw = recheck if (isinstance(recheck, list) and recheck) else record.get('holds')
    holds = [gate for gate in (raw or []) if isinstance(gate, str) and gate]
    parts = [HOLD_GATES[gate] + '（' + gate + '）' if gate in HOLD_GATES else gate for gate in holds]
    detail = ('程序按这个场景的闸门停下了：没有创建角色回合，模型未被调用。拦下的原因：'
              + ('、'.join(parts) if parts else '行里没写闸门名单'))
    if recheck:
        detail += '。入队时闸门还开着，真要跑之前再核被拦下'
    return {'label': '程序拦下 · 未进入模型', 'detail': detail, 'kind': 'program_hold', 'holds': holds}


def ingress_projection(row):
    """一条已落库、还没有角色 episode 的入站行 → 本轮状态需要的最小投影。

    只搬程序已经写下的事实；proactive 里留下状态要用的几项，完整判断仍在那一行记录和审计里。
    """
    ep = {'_id': row['episode_id'], 'state': row.get('ingress_state') or '',
          'character_context': row.get('character_context', 'initial'),
          'no_wake': row.get('processing_outcome') == 'RECORDED_NO_WAKE'}
    for field in ('processing_outcome', 'result_state'):
        if isinstance(row.get(field), str):
            ep[field] = row[field]
    record = row.get('proactive')
    if isinstance(record, dict):
        ep['proactive'] = {key: record[key] for key in ('holds', 'recheck_hold', 'wake', 'decided_at')
                           if key in record}
    if row.get('failure'):
        ep['failure'] = row['failure']
    return ep


def turn_status(ep, created_at, task=None):
    state = ep.get('state', '')
    if ep.get('no_wake'):
        return None  # Routine group chatter has no agent turn to explain.
    if state in RUNNING_PHASES:
        return None  # A running phase is not a completed, silent turn.
    hold = program_hold(ep)
    if ep.get('silent_reason'):
        label = '行动结果未追加公开回复' if ep.get('episode_kind') == 'task_feedback' else '角色选择不发言'
        detail = ep['silent_reason']
    elif ep.get('failure') or state.startswith('FAILED') or state == 'INTERRUPTED':
        label, detail = '本轮未完成', '展开执行过程查看错误'
    elif hold:
        label, detail = hold['label'], hold['detail']
    elif state == 'WAITING_TASK':
        label, detail = ('行动已排队', '等待行动脑开始') if (task or {}).get('state') == 'READY' else ('行动处理中', '可展开执行过程查看进度')
    elif ep.get('episode_kind') == 'task_feedback':
        label, detail = '行动反馈已处理', '未追加公开回复'
    elif state in INGRESS_PENDING:
        label, detail = INGRESS_PENDING[state]
    else:
        label, detail = '本轮已结束', '没有公开回复'
    status = {'label': label, 'detail': detail, 'createdAt': created_at, 'state': state}
    if hold:
        status.update(kind=hold['kind'], holds=hold['holds'])
    return status


def raw_provider_response(request_refs, root=None):
    """Read the exact saved response stream paired with the final request ref."""
    if not isinstance(request_refs, list) or not request_refs:
        raise ValueError('原始 provider response 不可用')
    ref = request_refs[-1]
    artifact_path = ref.get('artifact_path') if isinstance(ref, dict) else None
    if not isinstance(artifact_path, str):
        raise ValueError('原始 provider response 引用无效')
    root = Path(root or ROOT).resolve()
    reports_root = (root / 'reports').resolve()
    request_path = (root / artifact_path).resolve()
    if not request_path.is_relative_to(reports_root) or not request_path.name.endswith('-provider.request.json'):
        raise PermissionError('原始 provider response 引用越界')
    try:
        request_bytes = request_path.read_bytes()
        request_event = json.loads(request_bytes)
    except (OSError, ValueError) as exc:
        raise ValueError('原始 provider request 不可用') from exc
    if ref.get('sha256') != hashlib.sha256(request_bytes).hexdigest():
        raise PermissionError('原始 provider request 校验失败')
    request_payload = request_event.get('payload', {})
    call_id = request_payload.get('call_id')
    if request_event.get('type') != 'provider.request' or not call_id:
        raise PermissionError('原始 provider request 不匹配')
    for response_path in request_path.parent.glob('*-provider.response.json'):
        try:
            response_event = json.loads(response_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        response_payload = response_event.get('payload', {})
        if (response_event.get('type') == 'provider.response' and
                response_payload.get('request_ref') == request_path.name and
                response_payload.get('call_id') == call_id and
                200 <= response_payload.get('status_code', 0) < 300 and
                isinstance(response_payload.get('body_utf8'), str)):
            return response_payload['body_utf8']
    raise ValueError('原始 provider response 不可用')


def provider_metadata(raw):
    """Only non-content wire facts for the Web diagnostic; the audit keeps raw."""
    frames, sse, done = [], False, False
    for line in raw.splitlines():
        if not line.startswith('data:'):
            continue
        sse = True
        value = line[5:].strip()
        if value == '[DONE]':
            done = True
            continue
        try:
            packet = json.loads(value)
        except ValueError:
            continue
        if isinstance(packet, dict):
            frames.append(packet)
    if not sse:
        try:
            packet = json.loads(raw)
        except ValueError:
            packet = None
        if isinstance(packet, dict):
            frames.append(packet)
    result = {'wire_format': 'sse' if sse else 'json' if frames else 'text',
              'response_bytes': len(raw.encode('utf-8')), 'frame_count': len(frames)}
    if sse:
        result['stream_done'] = done
    finishes = []
    for packet in frames:
        for source, target in (('id', 'response_id'), ('model', 'model'), ('created', 'created')):
            if isinstance(packet.get(source), (str, int)):
                result[target] = packet[source]
        for choice in packet.get('choices', []) if isinstance(packet.get('choices'), list) else []:
            if isinstance(choice, dict) and isinstance(choice.get('finish_reason'), str):
                if choice['finish_reason'] not in finishes:
                    finishes.append(choice['finish_reason'])
        usage = packet.get('usage')
        if isinstance(usage, dict):
            counts = {key: usage[key] for key in ('prompt_tokens', 'completion_tokens', 'total_tokens',
                                                  'input_tokens', 'output_tokens')
                      if isinstance(usage.get(key), (int, float)) and not isinstance(usage[key], bool)}
            if counts:
                result['usage'] = counts
    if finishes:
        result['finish_reasons'] = finishes
    return result


def native_call_projection(events, receipt_id, request_refs, operation):
    """Project one real DSH turn's Assistant steps onto its ordered requests.

    A mismatched count is not an identity join. In that case the caller keeps
    the existing aggregate output instead of assigning text to a guessed call.
    """
    target = next((index for index, event in enumerate(events)
                   if event.get('type') == 'user/message' and event.get('data', {}).get('id') == receipt_id), None)
    if target is None:
        return []
    opening_index = next((index for index in range(target, -1, -1)
                          if events[index].get('type') == 'turn/start'), None)
    if opening_index is None:
        return []
    turn = events[opening_index].get('data', {}).get('turn')
    closing = next((index for index in range(target + 1, len(events))
                    if events[index].get('type') == 'turn/end' and events[index].get('data', {}).get('turn') == turn), None)
    if closing is None:
        return []
    window = events[opening_index:closing + 1]
    assistants = [event for event in window if event.get('type') == 'assistant/message'
                  and event.get('data', {}).get('turn') == turn]
    if len(assistants) != len(request_refs) or not assistants:
        return []
    starts = {event.get('data', {}).get('step'): event.get('time') for event in window
              if event.get('type') == 'step/start' and event.get('data', {}).get('turn') == turn}
    calls = []
    for event, ref in zip(assistants, request_refs):
        path = ref.get('artifact_path') if isinstance(ref, dict) else None
        if not isinstance(path, str):
            return []
        request_id = Path(path).name
        if not re.fullmatch(r'\d+-provider\.request\.json', request_id):
            return []
        blocks = event.get('data', {}).get('message', {}).get('content', [])
        if not isinstance(blocks, list):
            return []
        parts = [{'field': 'reasoning_content' if block['type'] == 'reasoning' else 'content',
                  'text': block['text']}
                 for block in blocks if isinstance(block, dict) and block.get('type') in ('reasoning', 'text')
                 and isinstance(block.get('text'), str) and block['text']]
        millis = starts.get(event.get('data', {}).get('step')) or event.get('time')
        if not isinstance(millis, (int, float)):
            return []
        calls.append({'id': f'{operation}:{request_id}', 'request_ref': request_id,
                      'operation': operation, 'lane': 'executor',
                      'phase': 'execution', 'createdAt': datetime.fromtimestamp(millis / 1000, timezone.utc).isoformat(),
                      'status': 'settled', 'parts': parts})
    return calls if len({call['id'] for call in calls}) == len(calls) else []


def audited_request_purpose(ref):
    """Classify a request, hash-checking any proposed compaction exclusion."""
    path = ref.get('artifact_path') if isinstance(ref, dict) else None
    if not isinstance(path, str):
        return None
    target = (ROOT / path).resolve()
    if not target.is_relative_to((ROOT / 'reports').resolve()) or not target.name.endswith('-provider.request.json'):
        return None
    with target.open('rb') as source:
        heading = source.read(4096)
        match = re.search(rb'"purpose"\s*:\s*"([^"]+)"', heading)
        if not match:
            return None
        purpose = match.group(1).decode('ascii', errors='replace')
        if purpose != 'compaction':
            return purpose
        raw = heading + source.read()
    if ref.get('sha256') != hashlib.sha256(raw).hexdigest():
        return None
    event = json.loads(raw)
    return event.get('payload', {}).get('purpose') if event.get('type') == 'provider.request' else None


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
        self.stream_hub = UiStreamHub()

    def attach_streams(self):
        if self.controller:
            app = self.controller.app
            app.character.proxy.ui_observer = self.stream_hub
            app.executor_lane.proxy.ui_observer = self.stream_hub

    def native_execution_calls(self, operation, request_refs, native_logs=None, receipts=None, sessions=None):
        """Read DSH's existing step record for a settled Asuna operation."""
        receipt = (receipts.get(operation) if receipts is not None else
                   self.store.db.lane_receipts.find_one({'_id': operation},
                                                        {'session_id': 1, 'result.receipt': 1, 'result.request_refs': 1}))
        if not receipt or receipt.get('result', {}).get('request_refs') != request_refs:
            return []
        session_id = receipt.get('session_id')
        if not isinstance(session_id, str) or not re.fullmatch(r's-[0-9a-f]{40}', session_id):
            return []
        session = (sessions.get(session_id) if sessions is not None else
                   self.store.db.sessions.find_one({'_id': session_id}, {'dsh_home': 1}))
        if not session or not isinstance(session.get('dsh_home'), str):
            return []
        home = Path(session['dsh_home']).resolve()
        if not home.is_relative_to((ROOT / '.runtime' / 'asuna-dsh').resolve()):
            return []
        logs = list(home.glob(f'sessions/*/{session_id}/session.v3.jsonl'))
        if len(logs) != 1:
            return []
        try:
            if native_logs is not None and session_id in native_logs:
                events = native_logs[session_id]
            else:
                events = [json.loads(line) for line in logs[0].read_text(encoding='utf-8').splitlines() if line]
                if native_logs is not None:
                    native_logs[session_id] = events
            projected = native_call_projection(events, receipt['result'].get('receipt'), request_refs, operation)
            if projected:
                return projected
            # A native compaction has its own provider request but no Assistant
            # step in the action turn. Confirm that classification from the
            # existing hash-checked audit before matching ordered requests.
            classified = [(ref, audited_request_purpose(ref)) for ref in request_refs]
            if any(purpose not in ('execution', 'execution-repair', 'compaction') for _, purpose in classified):
                return []
            ordinary = [ref for ref, purpose in classified if purpose != 'compaction']
            return native_call_projection(events, receipt['result'].get('receipt'), ordinary, operation)
        except (OSError, ValueError, TypeError, OverflowError):
            return []

    def stream_scene(self, selected=''):
        # Opening an observation connection must not rebuild the full transcript
        # beside the /state request. Check the same scene/context membership here.
        local = self.store.authorize(self.settings['scene_id'], self.settings['person_id'])
        if selected.startswith('channel:'):
            from .channels import route_members
            scene = None
            for channel_id, channel in self.store.config.get('channels', {}).items():
                for route in channel['routes'].values():
                    if selected != 'channel:' + route['scene_id'] or not route_members(route):
                        continue
                    configured = self.store.db.scenes.find_one({'_id': route['scene_id'], 'channel_id': channel_id})
                    if configured:
                        member = next(iter(route_members(route).values()))
                        scene = self.store.authorize(route['scene_id'], member['person_id'])
                        break
                if scene:
                    break
            if not scene:
                raise ValueError('通道未配置或已不可访问')
        else:
            scene = local
            current = scene.get('character_context', 'initial')
            if selected and selected != current:
                scope = {'scene_id': scene['_id'], 'scope_key': scene['scope_key'],
                         'policy_epoch': scene['policy_epoch']}
                context = {'$or': [{'character_context': selected}] +
                           ([{'character_context': {'$exists': False}}] if selected == 'initial' else [])}
                if not (self.store.db.episodes.find_one({**scope, **context}, {'_id': 1}) or
                        self.store.db.messages.find_one({**scope, 'host_managed': True, **context}, {'_id': 1})):
                    raise ValueError('会话不存在或已不可访问')
        return {'_id': scene['_id'], 'scope_key': scene['scope_key'], 'policy_epoch': scene['policy_epoch']}

    def live_streams(self, scene, calls):
        current = self.store.db.scenes.find_one({'_id': scene['_id'], 'scope_key': scene['scope_key'],
                                                 'policy_epoch': scene['policy_epoch']})
        if not current:
            raise PermissionError('场景授权已变化，请刷新')
        visible = []
        for call in calls:
            operation = call.get('operation')
            # An internal DSH compaction can inherit the enclosing phase's
            # operation ID; its summary is not that phase's visible output.
            if (call.get('phase') == 'compaction' or call.get('scope_key') != scene['scope_key']
                    or not isinstance(operation, str)):
                continue
            owner_id = operation.split(':', 1)[0]
            query = {'_id': owner_id, 'scene_id': scene['_id'], 'scope_key': scene['scope_key'],
                     'policy_epoch': scene['policy_epoch']}
            if self.store.db.episodes.find_one(query, {'_id': 1}) or self.store.db.tasks.find_one(query, {'_id': 1}):
                visible.append(call)
        return visible

    def models_snapshot(self):
        return {'models': public_models(self.store.config), 'revision': revision(self.store.config),
                'applying': self.models_applying, 'error': self.models_error,
                'ready': self.controller is None or getattr(self.controller.app, 'models_ready', True)}

    def apply_models(self, body):
        controller = self.controller
        if not self.store.config.get('_model_settings_path'):
            raise ValueError('当前启动未指定可保存的模型配置路径')
        candidate = edited_models(self.store.config, body)
        with controller.ingress_lock:
            if controller.pending.unfinished_tasks or controller.task_queue.unfinished_tasks or self.store.db.tasks.find_one({'state': {'$in': ['READY', 'RUNNING']}}):
                raise ValueError('请等当前回复、排队消息和行动完成后再切换模型')
            controller.reconfiguring = True
        self.models_applying, self.models_error = True, ''
        previous = self.store.config
        def apply():
            try:
                controller.app.replace_models(candidate)
                self.attach_streams()
                try:
                    persist(candidate, candidate['_model_settings_path'])
                except Exception:
                    controller.app.replace_models(previous)
                    self.attach_streams()
                    raise
                self.emit('[系统] 两条模型配置已保存并应用；后续消息使用新配置。')
            except Exception as exc:
                self.models_error = redact_text(redact_text(str(exc), candidate), previous)
                self.emit('[系统] 模型配置未应用：' + self.models_error)
            finally:
                controller.reconfiguring = False
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
            # These turn outcomes are shown beside their recorded input/trace.
            # A global transient notice loses scene and episode identity.
            if text.startswith(('[系统] 本轮没有公开发言', '[系统] 角色明确选择本轮不发言',
                                '[系统] 本轮未完成', '[系统] 行动已排队')):
                return
            with self.lock:
                self.notices.append({'id': str(uuid.uuid4()), 'role': 'system', 'authorLabel': '系统',
                                     'text': text, 'createdAt': datetime.now(timezone.utc).isoformat()})
                self.notices = self.notices[-8:]

    def snapshot(self, selected='', before_seq=None):
        # This is the local operator's read-only view, never an impersonated
        # channel command or a grant to the remote participant.
        self.store.authorize(self.settings['scene_id'], self.settings['person_id'])
        from .channels import route_members
        channels = {}
        for channel_id, channel in self.store.config.get('channels', {}).items():
            for route in channel['routes'].values():
                scene = self.store.db.scenes.find_one({'_id': route['scene_id'], 'channel_id': channel_id})
                if scene and route_members(route):
                    key = 'channel:' + scene['_id']
                    channels[key] = (route, {'id': key, 'title': f"{channel_id} · {route['target']['type']} · {route['target']['id']}",
                                             'channelType': channel_id, 'updatedAt': ''})
        if selected.startswith('channel:'):
            if selected not in channels:
                raise ValueError('通道未配置或已不可访问')
            route, item = channels[selected]
            member = next(iter(route_members(route).values()))
            data = self._snapshot(settings={**self.settings, 'scene_id': route['scene_id'], 'person_id': member['person_id']},
                                  external=True, before_seq=before_seq)
            data.update(conversationId=selected, title=item['title'], conversations=[{'id': '', 'title': '本机聊天', 'channelType': 'local', 'updatedAt': ''}])
            if route['target']['type']=='group' and route.get('operator_sender_id') in route_members(route) and self.controller:
                data.update(readOnly=False,channelPrompt=True,canSend=not self.models_applying and getattr(self.controller.app,'models_ready',True),
                            subtitle='本机指令 · 小满将在此群发言；输入不会伪装成 QQ 来信')
        else:
            data = self._snapshot(selected, before_seq=before_seq)
        data['conversations'].extend(item for _, item in channels.values())
        self.stream_hub.mark_durable({step.get('displayKey') for message in data['messages']
                                      for step in message.get('internalSteps', []) if step['type'] in ('phase.output', 'execution.output')
                                      and step.get('displayKey')})
        return json.loads(redact_text(json.dumps(data, ensure_ascii=False, default=str), self.store.config))

    def _snapshot(self, selected='', *, settings=None, external=False, before_seq=None):
        store, settings = self.store, settings or self.settings
        scene = store.authorize(settings['scene_id'], settings['person_id'])
        scope = {'scope_key': scene['scope_key'], 'policy_epoch': scene['policy_epoch']}
        episodes = list(store.db.episodes.find({**scope, 'scene_id': scene['_id']}, {'system': 0, 'context': 0}).sort('_id', 1))
        known = {ep['_id'] for ep in episodes}
        for row in store.db.messages.find({**scope, 'scene_id': scene['_id'], 'host_managed': True}):
            if row['episode_id'] not in known:
                episodes.append(ingress_projection(row))
        # Contexts are native Chat /new generations, not fabricated channels.
        current = scene.get('character_context', 'initial')
        groups = {current: []}
        by_id = {ep['_id']: ep for ep in episodes}
        for ep in episodes:
            groups.setdefault(ep.get('character_context', 'initial'), []).append(ep['_id'])
        if external:
            groups = {current: list(by_id)}
        chosen = selected or current
        if chosen not in groups:
            raise ValueError('会话不存在或已不可访问')
        # Operator projection includes generated SPEAK while platform delivery is
        # pending; deliveryState below keeps it distinct from an accepted post.
        messages = list(store.db.messages.find({**scope, 'scene_id': scene['_id'], '$or': [
            {'direction': 'inbound'}, {'direction': 'outbound', 'phase': 'SPEAK'},
            *([] if external else [{'direction':'internal'}])]}).sort('scene_seq', 1))
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
        context_rows = [m for m in messages if episode_id(m) in groups[chosen]
                        and (before_seq is None or m['scene_seq'] < before_seq)]
        page_start = max(0, len(context_rows) - 12)
        while page_start and episode_id(context_rows[page_start - 1]) == episode_id(context_rows[page_start]):
            page_start -= 1
        page_rows = context_rows[page_start:]
        has_more = page_start > 0
        oldest_seq = page_rows[0]['scene_seq'] if page_rows else None
        # DSH keeps the active turn in its followed window. Keep the real
        # running task's owner visible even after newer messages move past it.
        active_tasks = list(store.db.tasks.find(
            {**scope, 'state': {'$in': ['READY', 'RUNNING']}},
            {'episode_id': 1, 'continues_task_id': 1}))
        lineage_tasks = {task['_id']: task for task in active_tasks}
        def ancestors(task):
            seen = {task['_id']}
            while task.get('continues_task_id'):
                parent_id = task['continues_task_id']
                if parent_id in seen:
                    break
                seen.add(parent_id)
                parent = lineage_tasks.get(parent_id)
                if parent is None:
                    parent = store.db.tasks.find_one({'_id': parent_id, **scope},
                                                     {'episode_id': 1, 'continues_task_id': 1})
                    if parent is None:
                        break
                    lineage_tasks[parent_id] = parent
                yield parent
                task = parent
        active_owners = {task.get('episode_id') for task in active_tasks}
        for task in active_tasks:
            active_owners.update(parent.get('episode_id') for parent in ancestors(task))
        active_owners.intersection_update(groups[chosen])
        rows = sorted({row['_id']: row for row in [
            *page_rows, *(row for row in messages if episode_id(row) in active_owners),
        ]}.values(), key=lambda row: row['scene_seq'])
        visible_ids = {episode_id(m) for m in rows}
        traces = {}
        task_owners = {}
        native_logs, native_projections = {}, {}
        task_ids = {ep.get('task_id') or ep.get('control_result', {}).get('task_id')
                    for ep_id in visible_ids if (ep := by_id[ep_id])}
        task_ids.discard(None)
        tasks = {task['_id']: task for task in store.db.tasks.find({'_id': {'$in': list(task_ids)}, **scope})}
        stream_ids = visible_ids | tasks.keys()
        events_by_stream = {stream_id: [] for stream_id in stream_ids}
        for event in store.db.audit_events.find({'stream_id': {'$in': list(stream_ids)},
                                                 'scope_key': scene['scope_key'],
                                                 '$or': [
                                                     {'type': {'$nin': ['state.intent', 'state.commit', 'context.prepared']}},
                                                     {'type': 'state.commit', 'payload.collection': 'artifacts'},
                                                 ]}).sort([('occurred_at', 1), ('seq', 1)]):
            events_by_stream[event['stream_id']].append(event)
        operations = set()
        for ep_id in visible_ids:
            ep = by_id[ep_id]
            task_id = ep.get('task_id') or ep.get('control_result', {}).get('task_id')
            task = tasks.get(task_id)
            if not task:
                continue
            for event in events_by_stream.get(ep_id, []) + events_by_stream.get(task_id, []):
                if event['type'] != 'execution.output':
                    continue
                attempt = event.get('payload', {}).get('attempt')
                operations.add(f"{task_id}:execute:{task['intent_revision']}" +
                               (f':{attempt}' if attempt is not None else ''))
        receipts = {receipt['_id']: receipt for receipt in store.db.lane_receipts.find(
            {'_id': {'$in': list(operations)}},
            {'session_id': 1, 'result.receipt': 1, 'result.request_refs': 1})}
        session_ids = {receipt.get('session_id') for receipt in receipts.values()
                       if isinstance(receipt.get('session_id'), str)}
        sessions = {session['_id']: session for session in store.db.sessions.find(
            {'_id': {'$in': list(session_ids)}}, {'dsh_home': 1})}
        for ep_id in visible_ids:
            ep = by_id[ep_id]
            task_id = ep.get('task_id') or ep.get('control_result', {}).get('task_id')
            task = tasks.get(task_id)
            if task:
                task_owners[task_id] = task.get('episode_id')
            events = sorted(events_by_stream.get(ep_id, []) + (events_by_stream.get(task_id, []) if task else []),
                            key=lambda event: (event.get('occurred_at'), event.get('seq')))
            steps = [step for event in events if (step := trace_step(event, event['stream_id'] == task_id))]
            for step in steps:
                if step['type'] == 'phase.output':
                    step['displayKey'] = step['payload'].get('operation')
                elif step['type'] == 'execution.output' and task:
                    attempt = step['payload'].get('attempt')
                    step['displayKey'] = f"{task_id}:execute:{task['intent_revision']}" + (f':{attempt}' if attempt is not None else '')
                    if step['id'] not in native_projections:
                        native_projections[step['id']] = self.native_execution_calls(
                            step['displayKey'], step['payload'].get('request_refs', []), native_logs,
                            receipts, sessions)
                    step['providerCalls'] = native_projections[step['id']]
            finished = {event.get('payload', {}).get('operation') for event in events if event['type'] in ('phase.output', 'phase.failed')}
            for step in steps:
                if step['type'] == 'phase.started' and (step['payload'].get('operation') in finished or ep['state'] in ('COMMITTED', 'INTERRUPTED', 'FAILED_RUNTIME', 'FAILED_PROTOCOL')):
                    step['status'] = 'ok'
            if ep.get('failure'):
                steps.append({'id': ep_id + ':failure', 'type': 'episode.failure', 'label': '执行失败', 'status': 'error', 'summary': display(ep['failure']), 'payload': ep['failure']})
            traces[ep_id] = steps
        rendered, attached = [], set()
        input_times = {episode_id(row): row.get('occurred_at') or row.get('received_at')
                       for row in rows if row['direction'] in ('inbound','internal')}
        for row in rows:
            ep_id = episode_id(row)
            public = row['direction'] == 'outbound'
            internal = row['direction'] == 'internal'
            if not public and not internal and by_id[ep_id].get('episode_kind', 'external') not in ('external','owner_group_prompt'):
                continue  # Task feedback is an internal event, not a user utterance.
            speak = next((step for step in reversed(traces.get(ep_id, []))
                          if step['type'] == 'phase.output' and step['sourceStreamId'] == ep_id
                          and step['payload'].get('phase') == 'SPEAK' and step['status'] != 'error'), None) if public else None
            speak_operation = speak.get('displayKey') if speak else None
            started = next((step for step in traces.get(ep_id, []) if step['type'] == 'phase.started'
                            and step['payload'].get('operation') == speak_operation), None) if speak_operation else None
            created_at = ((started or {}).get('createdAt') or (speak or {}).get('createdAt') or row.get('occurred_at')
                          or row.get('received_at') or input_times.get(ep_id)) if public else (
                              row.get('occurred_at') or row.get('received_at'))
            message = {'id': row['_id'], 'role': 'assistant' if public else 'system' if internal else 'user',
                       'episodeId': ep_id, 'taskId': by_id[ep_id].get('task_id') or by_id[ep_id].get('control_result', {}).get('task_id'),
                       'authorLabel': settings['display_name'] if public else (row.get('event', {}).get('channel', {}).get('sender_id') or row.get('author', '未知发言者')) if external else '你',
                       'text': row['text'], 'createdAt': created_at,
                       'sceneSeq': row['scene_seq'], '_order': row['scene_seq']}
            if public:
                message['displayKey'] = speak_operation or ep_id + ':SPEAK:0'
                message['deliveryState'] = row.get('delivery_state', 'UNKNOWN')
            if not public and row.get('event',{}).get('episode_kind')=='owner_group_prompt':
                message['authorLabel']='本机 owner 指令（非 QQ 来信）'
            if internal:
                message['authorLabel']='内部自我开发机会（非用户消息）'
            if public:
                message['internalSteps'] = traces[ep_id]
                attached.add(ep_id)
            message['taskOwnerEpisodeId'] = task_owners.get(message['taskId'])
            rendered.append(message)
        for ep_id in dict.fromkeys(episode_id(row) for row in rows if episode_id(row) not in attached):
            ep = by_id[ep_id]
            if ep.get('no_wake'):
                continue
            input_row = next(row for row in rows if episode_id(row) == ep_id)
            task_id = ep.get('task_id') or ep.get('control_result', {}).get('task_id')
            target = next((m for m in reversed(rendered) if m['role'] in ('user','system') and m['episodeId'] == ep_id), None)
            if target is None and task_id:
                target = next((m for m in reversed(rendered) if m.get('taskId') == task_id), None)
            if target is None and task_id and task_id in tasks:
                for parent in ancestors(tasks[task_id]):
                    target = next((m for m in reversed(rendered) if m.get('taskId') == parent['_id']), None)
                    if target is not None:
                        break
            if target is None:
                continue  # Its input is outside the visible 80-message window.
            occurred = next((step.get('createdAt') for step in reversed(traces[ep_id]) if step.get('createdAt')),
                            input_row.get('occurred_at', input_row.get('received_at')))
            target['turnStatus'] = turn_status(ep, occurred, tasks.get(task_id))
            if task_id and task_id != target.get('taskId'):
                target.setdefault('taskIds', []).append(task_id)
            prior = target.get('internalSteps', [])
            target['internalSteps'] = list({step['id']: step for step in [*prior, *traces[ep_id]]}.values())
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
        if external:
            for row in store.db.messages.find({**scope, 'scene_id': scene['_id'], 'direction': 'outbound', 'phase': 'SPEAK'}).sort('scene_seq', -1).limit(80):
                records.append({'id': row['_id'], 'kind': 'integration', 'title': '平台回执 · ' + row.get('delivery_state', 'UNKNOWN'),
                                'description': row.get('platform_message_id', row['_id']), 'fields': row})
        integration = None if external else getattr(getattr(self, 'host', None), 'integration', None)
        if integration:
            status = integration.status()
            records.append({'id': 'integration-owner', 'kind': 'integration', 'title': '集成运行器',
                            'description': status['state'], 'fields': status})
        with self.lock:
            notices = list(self.notices) if chosen == current and not external else []
        data = {'conversationId': chosen, 'title': next(row['title'] for row in conversations if row['id'] == chosen),
                'subtitle': f"{'通道检查（本机只读）' if external else '本机聊天'} · {scene['_id']} · 分段加载消息 / 100 条记忆 · " + ('当前上下文' if chosen == current else '历史上下文（只读）'),
                'conversations': conversations, 'messages': rendered + notices, 'records': records,
                'hasMore': has_more, 'beforeSeq': oldest_seq,
                'readOnly': external or self.controller is None, 'canSend': not external and chosen == current and not self.models_applying and (self.controller is None or getattr(self.controller.app, 'models_ready', True)),
                'modelSettings': self.models_snapshot(),
                'integrationAvailable': integration is not None,
                'selfDevelopmentAvailable': not external and bool(store.config.get('self_development',{}).get('enabled')),
                'emptyReasons': {'preference': '当前存储没有独立的偏好记录；原始内容可在记忆中查看。',
                                 'group_preference': '当前场景没有群偏好记录。'}}
        latest_scene = store.authorize(settings['scene_id'], settings['person_id'])
        if latest_scene['policy_epoch'] != scene['policy_epoch'] or latest_scene['scope_key'] != scene['scope_key']:
            raise PermissionError('场景授权已变化，请刷新')
        # Same credential redaction as the terminal trace, including nested payloads.
        return json.loads(redact_text(json.dumps(data, ensure_ascii=False, default=str), store.config))

    def provider_diagnostic(self, event_id, selected=''):
        scene = self.stream_scene(selected)
        if not isinstance(event_id, str) or not event_id:
            raise ValueError('缺少 provider output event id')
        event = self.store.db.audit_events.find_one({'_id': event_id, 'scope_key': scene['scope_key']})
        if not event or event.get('type') not in ('phase.output', 'execution.output'):
            raise PermissionError('当前场景没有该 provider output')
        owner = {'_id': event['stream_id'], 'scene_id': scene['_id'], 'scope_key': scene['scope_key'],
                 'policy_epoch': scene['policy_epoch']}
        if not (self.store.db.episodes.find_one(owner, {'_id': 1}) or self.store.db.tasks.find_one(owner, {'_id': 1})):
            raise PermissionError('当前场景没有该 provider output')
        raw = raw_provider_response(event.get('payload', {}).get('request_refs', []), root=ROOT)
        return {'diagnostic': {'source_event': event_id, 'event_type': event['type'],
                               **provider_metadata(raw)}}

    def command(self, path, body):
        with self.command_lock:
            return self._command(path, body)

    def _command(self, path, body):
        self.store.authorize(self.settings['scene_id'], self.settings['person_id'])
        if self.controller is None:
            raise PermissionError('只读模式不能发送消息或新建上下文')
        if path == '/stop':
            if not getattr(self, 'host', None):
                raise ValueError('宿主停止入口不可用')
            self.host.shutdown_requested.set()
            return {'accepted': True}
        if path == '/integration/stop':
            runner = getattr(getattr(self, 'host', None), 'integration', None)
            if not runner: raise ValueError('集成运行器未启用')
            return runner.call('integration_stop', {})
        if self.models_applying:
            raise ValueError('正在应用模型配置，请稍候')
        if path == '/models/discover':
            return self.discover_models(body)
        if path == '/models':
            return self.apply_models(body)
        if not getattr(self.controller.app, 'models_ready', True):
            raise ValueError('模型运行时未就绪，请在模型设置中修正并重新应用')
        if path == '/self-development/offer':
            return {'accepted':True,**self.controller.offer_self_development(
                'self-development:manual:'+uuid.uuid4().hex)}
        if path == '/send':
            value = body.get('text')
            if not isinstance(value, str) or not 1 <= len(value.strip()) <= 16000:
                raise ValueError('请输入 1–16000 字的消息')
            if type(body.get('integration', False)) is not bool:
                raise ValueError('INVALID_INTEGRATION_SELECTION')
            if type(body.get('development',False)) is not bool:
                raise ValueError('INVALID_DEVELOPMENT_SELECTION')
            selected=body.get('conversation','')
            if selected.startswith('channel:'):
                if body.get('integration') or body.get('development'):
                    raise Denied('GROUP_PROMPT_HAS_NO_DEVELOPMENT_GRANT')
                from .channels import route_for_scene,route_members
                scene_id=selected[len('channel:'):]
                scene=self.store.db.scenes.find_one({'_id':scene_id,'kind':'group'})
                if not scene:raise Denied('GROUP_PROMPT_ROUTE_REQUIRED')
                channel_id=scene['channel_id'];route=route_for_scene(self.store.config,channel_id,scene_id)
                sender=route.get('operator_sender_id');member=route_members(route).get(sender)
                if not member:raise Denied('GROUP_PROMPT_OWNER_NOT_CONFIGURED')
                key=str(uuid.uuid4())
                event={'event_id':key,'scene_id':scene_id,'person_id':member['person_id'],'text':value.strip(),
                       'adapter_id':'owner-web','episode_kind':'owner_group_prompt',
                       'channel':{'id':channel_id,'account_id':self.store.config['channels'][channel_id]['account_id'],
                                  'target':route['target'],'platform_event_id':None,'sender_id':sender},
                       'group_context':{'wake_reason':'owner_group_prompt','topic_id':key,'reply_to':None,'reply_message_id':None,'mentioned_account_ids':[]},
                       'trusted_context_events':[{'kind':'owner_group_prompt','text':'这是本机 owner 请你在当前授权群发言的指令，不是群成员刚发来的 QQ 消息；用你自己的判断生成群内公开发言。没有获得额外工具、私聊记忆或配置权限。'}]}
                return {'accepted':True,**self.controller.receive(event)}
            return {'accepted': True, **self.controller.submit(value.strip(),
                integration=body.get('integration', False),development=body.get('development',False))}
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

            def stream(self, selected):
                scene = workbench.stream_scene(selected)
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Connection', 'close')
                self.end_headers()
                version = -1
                try:
                    while True:
                        current, calls = workbench.stream_hub.snapshot()
                        if current != version:
                            visible = workbench.live_streams(scene, calls)
                            payload = json.dumps({'version': current, 'calls': visible}, ensure_ascii=False).encode('utf-8')
                            self.wfile.write(b'event: snapshot\ndata: ' + payload + b'\n\n')
                            version = current
                        else:
                            self.wfile.write(b': keepalive\n\n')
                        self.wfile.flush()
                        workbench.stream_hub.wait(version)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, PermissionError):
                    return

            def handle_request(self):
                status = 200
                try:
                    if self.headers.get('Authorization') != 'Bearer ' + owner.token:
                        raise PermissionError('UI_AUTH_REQUIRED')
                    url = urlsplit(self.path)
                    if self.command == 'GET' and url.path == '/state':
                        query = parse_qs(url.query)
                        raw_before = query.get('before', [''])[0]
                        if raw_before and (not raw_before.isdecimal() or int(raw_before) < 1):
                            raise ValueError('INVALID_BEFORE_SEQ')
                        value = workbench.snapshot(query.get('conversation', [''])[0],
                                                   int(raw_before) if raw_before else None)
                    elif self.command == 'GET' and url.path == '/stream':
                        return self.stream(parse_qs(url.query).get('conversation', [''])[0])
                    elif self.command == 'GET' and url.path == '/provider-diagnostic':
                        value = workbench.provider_diagnostic(parse_qs(url.query).get('event', [''])[0],
                                                              parse_qs(url.query).get('conversation', [''])[0])
                    elif self.command == 'POST' and url.path in ('/send', '/new', '/models', '/models/discover', '/stop', '/integration/stop', '/self-development/offer'):
                        size = int(self.headers.get('Content-Length', '0'))
                        if not 0 < size <= 65536:
                            raise ValueError('INVALID_BODY_SIZE')
                        body = json.loads(self.rfile.read(size))
                        if not isinstance(body, dict):
                            raise ValueError('INVALID_BODY')
                        value = workbench.command(url.path, body)
                    else:
                        status, value = 404, {'error': '未知接口'}
                except (PermissionError, Denied) as exc:
                    status, value = 403, {'error': str(exc)}
                except (ValueError, TypeError) as exc:
                    status, value = 400, {'error': str(exc)}
                except Exception as exc:
                    status, value = 503, {'error': redact_text(str(exc), workbench.store.config)}
                data = json.dumps(value, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(data)))
                try:
                    self.end_headers()
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass

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
               '--patch', str(ROOT / 'dsh-plugin/ui/cordis.patch.yml'), '--host', '127.0.0.1', '--port', str(port)]
    process = None
    try:
        process = subprocess.Popen(command, cwd=ROOT, env=env)
        print(f'Asuna UI: DSH 会在系统默认浏览器自动打开并完成本机认证；进入后点击侧栏 Asuna。'
              f' 若浏览器未自动打开，请复制下一行 dsh web: 地址。端口：{port}。', flush=True)
        while True:
            try:
                return process.wait(timeout=.5)
            except subprocess.TimeoutExpired:
                if getattr(workbench, 'host', None) and workbench.host.shutdown_requested.is_set():
                    return 75 if workbench.host.restart_requested.is_set() else 0
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
    from .chat import local_settings
    settings = local_settings(config)
    if read_only:
        store = Store(config, database)
        try:
            store.authorize(settings['scene_id'], settings['person_id'])
            return serve(Workbench(store, settings), port)
        finally:
            store.client.close()
    from .host import RuntimeHost
    from .evidence import Evidence
    evidence = Evidence(Path(out) if out else ROOT / 'reports' / ('ui-' + uuid.uuid4().hex[:12]))
    with RuntimeHost(config, evidence, database) as host:
        workbench = Workbench(host.app.store, settings, host.controller)
        workbench.attach_streams()
        workbench.host = host
        host.controller.emit = workbench.emit
        try:
            return serve(workbench, port)
        finally:
            if workbench.model_thread:
                workbench.model_thread.join()
