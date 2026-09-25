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
import socket
import subprocess
import threading
from urllib.parse import parse_qs, urlsplit
import uuid
import httpx

from .config import ROOT, redact_text
from .state import Store, Denied
from .model_settings import public_models, edited_models, revision, persist, LANES
from .ui_stream import UiStreamHub

try:                                  # 跨场景只读联动（A2）：关系记录只有一份，展示也按那一份
    from . import scene_links
except Exception:
    scene_links = None


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


def inspector_record(row, kind='memory', *, detail=False):
    content = row.get('body_markdown') or row.get('content') or row.get('title') or row['_id']
    body = content.get('body', display(content)) if isinstance(content, dict) else str(content)
    result = {'id': row['_id'], 'kind': kind, 'title': row.get('title') or body[:70],
            'description': row.get('kind', kind), 'createdAt': row.get('occurred_at', row.get('created_at')),
            'excerpt': body[:160]}
    if detail:
        result['source'] = ', '.join(row.get('source_event_ids', row.get('source_ids', [])))
        result['fields'] = {key: value for key, value in row.items() if key not in ('embedding', '_last_op')}
    return result


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
        # Stream authorization resolves the same scene/channel selector as
        # /state without rebuilding the transcript or exposing context IDs.
        scene = self._scene_selection(selected)['scene']
        return {'_id': scene['_id'], 'scope_key': scene['scope_key'], 'policy_epoch': scene['policy_epoch']}

    def _scene_selections(self):
        """Return authorized scene navigation choices and their host bindings."""
        from .channels import route_members

        local = self.store.authorize(self.settings['scene_id'], self.settings['person_id'])
        local_latest = self.store.db.messages.find_one(
            {'scene_id': local['_id'], 'scope_key': local['scope_key'], 'policy_epoch': local['policy_epoch'],
             '$or': [{'occurred_at': {'$type': 'string'}}, {'received_at': {'$type': 'string'}}]},
            {'occurred_at': 1, 'received_at': 1}, sort=[('scene_seq', -1)])
        local_item = {'id': local['_id'], 'title': '本机私聊', 'channelType': 'local-dm',
                      'updatedAt': ((local_latest or {}).get('occurred_at') or
                                    (local_latest or {}).get('received_at') or '')}
        selections = {local['_id']: {'scene': local, 'settings': self.settings, 'external': False,
                                     'route': None, 'member': None, 'interactive': True,
                                     'item': local_item}}
        for channel_id, channel in self.store.config.get('channels', {}).items():
            for route in channel.get('routes', {}).values():
                members = route_members(route)
                if not members:
                    continue
                scene = self.store.db.scenes.find_one({'_id': route['scene_id'], 'channel_id': channel_id})
                if not scene:
                    continue
                target_type = route['target']['type']
                sender = (route.get('operator_sender_id') if target_type == 'group'
                          else route.get('sender_id'))
                member = members.get(sender) or next(iter(members.values()))
                try:
                    scene = self.store.authorize(route['scene_id'], member['person_id'])
                except (PermissionError, Denied):
                    continue
                interactive = (target_type == 'group' and
                               route.get('operator_sender_id') in members and self.controller is not None)
                if target_type == 'dm':
                    interactive = (self._same_configured_person(
                        member.get('person_id'), self.settings['person_id']) and self.controller is not None)
                latest = self.store.db.messages.find_one(
                    {'scene_id': scene['_id'], 'scope_key': scene['scope_key'],
                     'policy_epoch': scene['policy_epoch'],
                     '$or': [{'occurred_at': {'$type': 'string'}}, {'received_at': {'$type': 'string'}}]},
                    {'occurred_at': 1, 'received_at': 1}, sort=[('scene_seq', -1)])
                item = {'id': scene['_id'],
                        'title': f"{channel_id} · {'群聊' if target_type == 'group' else '私聊'} · {route['target']['id']}",
                        'channelType': f'{channel_id}-{target_type}',
                        'updatedAt': ((latest or {}).get('occurred_at') or
                                      (latest or {}).get('received_at') or '')}
                selections[scene['_id']] = {
                    'scene': scene,
                    'settings': {**self.settings, 'scene_id': route['scene_id'],
                                 'person_id': member['person_id']},
                    'external': True, 'route': route, 'channel_id': channel_id,
                    'member': member, 'interactive': interactive, 'item': item,
                }
        return selections

    def _same_configured_person(self, left, right):
        if left == right:
            return True
        return bool(scene_links and left and right and
                    scene_links.canonical_person_id(self.store.config, self.store.db, left) ==
                    scene_links.canonical_person_id(self.store.config, self.store.db, right))

    def _scene_selection(self, selected='', *, selections=None):
        selections = selections or self._scene_selections()
        key = selected or self.settings['scene_id']
        selection = selections.get(key)
        if not selection:
            raise ValueError('场景不存在或已不可访问')
        return selection

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
        selections = self._scene_selections()
        selection = self._scene_selection(selected, selections=selections)
        item = selection['item']
        data = self._snapshot(settings=selection['settings'], external=selection['external'],
                              before_seq=before_seq)
        scene_prompt = selection['external'] and selection['interactive']
        target_type = (selection.get('route') or {}).get('target', {}).get('type')
        prompt_verb = '在此 QQ 群发言' if target_type == 'group' else '回复此 QQ 私聊'
        data.update(sceneId=selection['scene']['_id'], title=item['title'],
                    subtitle=(f"{item['channelType']} · {selection['scene']['_id']} · 分段加载消息 / 100 条记忆"),
                    scenes=[row['item'] for row in selections.values()],
                    scenePrompt=scene_prompt,
                    scenePromptPlaceholder=(f'本机指令；小满将{prompt_verb}' if scene_prompt else ''),
                    scenePromptLabel=(f'请小满{prompt_verb}' if scene_prompt else '发送'),
                    readOnly=self.controller is None or (selection['external'] and not selection['interactive']),
                    canSend=(self.controller is not None and selection['interactive'] and
                             not self.models_applying and getattr(self.controller.app, 'models_ready', True)))
        data['hasPendingWork'] = bool(self.controller and (
            self.controller.pending.unfinished_tasks or self.controller.task_queue.unfinished_tasks)) or data['hasPendingWork']
        data['inspectorRevision'] = hashlib.sha256(repr([(record['id'], record['kind'], record['title'],
            record.get('description'), record.get('createdAt')) for record in data['records']]).encode('utf-8')).hexdigest()[:16]
        revision_parts = [data['sceneId'], data['modelSettings']['revision'], data['canSend'], data['hasPendingWork']]
        revision_parts.extend((message['id'], message.get('sceneSeq'), message.get('revision'))
                              for message in data['messages'])
        revision_parts.append(data['inspectorRevision'])
        data['revision'] = hashlib.sha256(repr(revision_parts).encode('utf-8')).hexdigest()[:20]
        self.stream_hub.mark_durable({step.get('displayKey') for message in data['messages']
                                      for step in message.get('internalSteps', []) if step['type'] in ('phase.output', 'execution.output')
                                      and step.get('displayKey')})
        return json.loads(redact_text(json.dumps(data, ensure_ascii=False, default=str), self.store.config))

    def _snapshot(self, *, settings=None, external=False, before_seq=None):
        store, settings = self.store, settings or self.settings
        scene = store.authorize(settings['scene_id'], settings['person_id'])
        scope = {'scope_key': scene['scope_key'], 'policy_epoch': scene['policy_epoch']}
        # Operator projection includes generated SPEAK while platform delivery is
        # pending; deliveryState below keeps it distinct from an accepted post.
        message_query = {**scope, 'scene_id': scene['_id'], '$or': [
            {'direction': 'inbound'}, {'direction': 'outbound', 'phase': 'SPEAK'},
            *([] if external else [{'direction':'internal'}])]}
        if before_seq is not None:
            message_query['scene_seq'] = {'$lt': before_seq}
        recent = list(store.db.messages.find(message_query).sort('scene_seq', -1).limit(13))
        page_rows = list(reversed(recent[:12]))
        has_more = len(recent) > 12
        oldest_seq = page_rows[0]['scene_seq'] if page_rows else None
        def episode_id(message):
            return message.get('episode_id') or message['_id'].removeprefix('in-')
        # DSH keeps the active turn in its followed window. Keep the real
        # running task's owner visible even after newer messages move past it.
        active_tasks = list(store.db.tasks.find(
            {**scope, 'scene_id': scene['_id'], 'state': {'$in': ['READY', 'RUNNING']}},
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
        owner_rows = []
        for owner in active_owners - {episode_id(row) for row in page_rows}:
            if owner:
                owner_rows.extend(store.db.messages.find({**scope, 'scene_id': scene['_id'],
                    'episode_id': owner, '$or': message_query['$or']}).sort('scene_seq', -1).limit(12))
        rows = sorted({row['_id']: row for row in [*page_rows, *owner_rows]}.values(),
                      key=lambda row: row['scene_seq'])
        visible_ids = {episode_id(m) for m in rows}
        by_id = {ep['_id']: ep for ep in store.db.episodes.find(
            {'_id': {'$in': list(visible_ids)}, **scope, 'scene_id': scene['_id']},
            {'system': 0, 'context': 0})}
        for row in rows:
            if episode_id(row) not in by_id and row.get('host_managed'):
                by_id[episode_id(row)] = ingress_projection(row)
        traces = {}
        task_owners = {}
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
            if not public and not internal and by_id[ep_id].get('episode_kind', 'external') not in (
                    'external', 'owner_group_prompt', 'owner_dm_prompt'):
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
            episode_kind = row.get('event', {}).get('episode_kind') or by_id[ep_id].get('episode_kind')
            if not public and episode_kind in ('owner_group_prompt', 'owner_dm_prompt'):
                message['authorLabel'] = '本机指令（非 QQ 来信）'
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
        for message in rendered:
            steps = message.get('internalSteps', [])
            if steps:
                message['traceCount'] = len(steps)
                message['errorCount'] = sum(step['status'] == 'error' for step in steps)
            projected = []
            for step in steps:
                payload = step.get('payload', {})
                if not isinstance(payload, dict):
                    payload = {}
                projected.append({**{key: value for key, value in step.items() if key not in ('payload', 'providerCalls')},
                    'summary': step['summary'][:240],
                    'payload': {key: payload[key] for key in ('phase', 'operation', 'attempt', 'tool', 'finish_reason')
                                if key in payload and isinstance(payload[key], (str, int, float, bool))},
                    'hasProviderDiagnostic': bool(payload.get('request_refs'))})
            if steps:
                message['internalSteps'] = projected
            message['revision'] = hashlib.sha256(repr((message.get('text'), message.get('authorLabel'),
                message.get('deliveryState'), message.get('turnStatus'),
                tuple((step['id'], step['status'], step['summary']) for step in projected))).encode('utf-8')).hexdigest()[:16]
        records = []
        for row in store.db.memory_units.aggregate([
                {'$match': {'$or': [scope, {'scope_key': 'global-safe', 'policy_epoch': 1}], 'status': 'active'}},
                {'$sort': {'occurred_at': -1, '_id': 1}}, {'$limit': 100},
                {'$project': {'_id': 1, 'kind': 1, 'title': 1, 'occurred_at': 1, 'created_at': 1,
                              'body_markdown': {'$cond': [
                                  {'$eq': [{'$type': '$body_markdown'}, 'string']},
                                  {'$substrCP': ['$body_markdown', 0, 160]}, '']}}}]):
            kind = row.get('kind')
            records.append(inspector_record(row, 'memory' if kind in (None, 'chat_chunk', 'monologue') else kind))
        target = (scene_links.relationship_target(store.config, store.db, scene,
                  settings['person_id']) if scene_links
                  else {'entity': 'relationship:' + settings['person_id'],
                        'scope': scene['scope_key']})
        relation = store.head(target['entity'], target['scope'])
        if relation:
            records.append(inspector_record(relation[1], 'relationship'))
        if external:
            for row in store.db.messages.find({**scope, 'scene_id': scene['_id'], 'direction': 'outbound', 'phase': 'SPEAK'},
                    {'_id': 1, 'delivery_state': 1, 'platform_message_id': 1, 'occurred_at': 1}).sort('scene_seq', -1).limit(80):
                records.append({'id': row['_id'], 'kind': 'integration', 'title': '平台回执 · ' + row.get('delivery_state', 'UNKNOWN'),
                                'description': row.get('platform_message_id', row['_id']), 'createdAt': row.get('occurred_at')})
        integration = None if external else getattr(getattr(self, 'host', None), 'integration', None)
        if integration:
            status = integration.status()
            records.append({'id': 'integration-owner', 'kind': 'integration', 'title': '集成运行器',
                            'description': status['state']})
        with self.lock:
            notices = list(self.notices) if not external else []
        data = {'sceneId': scene['_id'], 'title': scene['_id'],
                'subtitle': f"{'通道场景' if external else '本机私聊'} · {scene['_id']} · 分段加载消息 / 100 条记忆",
                'scenes': [], 'messages': rendered + notices, 'records': records,
                'hasMore': has_more, 'beforeSeq': oldest_seq, 'hasPendingWork': bool(active_tasks),
                'readOnly': external or self.controller is None,
                'canSend': not external and self.controller is not None and not self.models_applying and getattr(self.controller.app, 'models_ready', True),
                'modelSettings': self.models_snapshot(),
                'emptyReasons': {'preference': '当前存储没有独立的偏好记录；原始内容可在记忆中查看。',
                                 'group_preference': '当前场景没有群偏好记录。'}}
        latest_scene = store.authorize(settings['scene_id'], settings['person_id'])
        if latest_scene['policy_epoch'] != scene['policy_epoch'] or latest_scene['scope_key'] != scene['scope_key']:
            raise PermissionError('场景授权已变化，请刷新')
        # Same credential redaction as the terminal trace, including nested payloads.
        return json.loads(redact_text(json.dumps(data, ensure_ascii=False, default=str), store.config))

    def trace_detail(self, event_id, selected=''):
        scene = self.stream_scene(selected)
        event = self.store.db.audit_events.find_one({'_id': event_id, 'scope_key': scene['scope_key']})
        if not event or trace_step(event) is None:
            raise PermissionError('当前场景没有该执行记录')
        owner = {'_id': event['stream_id'], 'scene_id': scene['_id'], 'scope_key': scene['scope_key'],
                 'policy_epoch': scene['policy_epoch']}
        if not (self.store.db.episodes.find_one(owner, {'_id': 1}) or
                self.store.db.tasks.find_one(owner, {'_id': 1})):
            raise PermissionError('当前场景没有该执行记录')
        return json.loads(redact_text(json.dumps({'id': event_id, 'type': event['type'],
            'payload': event.get('payload', {})}, ensure_ascii=False, default=str), self.store.config))

    def inspector_detail(self, record_id, kind, selected=''):
        selection = self._scene_selection(selected)
        scene = selection['scene']
        scope = {'scope_key': scene['scope_key'], 'policy_epoch': scene['policy_epoch']}
        if kind == 'memory' or kind not in ('relationship', 'integration'):
            row = self.store.db.memory_units.find_one({'_id': record_id, 'status': 'active',
                '$or': [scope, {'scope_key': 'global-safe', 'policy_epoch': 1}]}, {'embedding': 0})
            if not row or ('memory' if row.get('kind') in (None, 'chat_chunk', 'monologue') else row['kind']) != kind:
                raise PermissionError('当前场景没有该检查器记录')
            record = inspector_record(row, kind, detail=True)
        elif kind == 'relationship':
            target = (scene_links.relationship_target(self.store.config, self.store.db, scene,
                      selection['settings']['person_id']) if scene_links else
                      {'entity': 'relationship:' + selection['settings']['person_id'], 'scope': scene['scope_key']})
            relation = self.store.head(target['entity'], target['scope'])
            if not relation or relation[1]['_id'] != record_id:
                raise PermissionError('当前场景没有该检查器记录')
            record = inspector_record(relation[1], kind, detail=True)
        elif record_id == 'integration-owner' and not selection['external'] and getattr(getattr(self, 'host', None), 'integration', None):
            status = self.host.integration.status()
            record = {'id': record_id, 'kind': kind, 'title': '集成运行器', 'description': status['state'], 'fields': status}
        else:
            row = self.store.db.messages.find_one({'_id': record_id, **scope,
                'scene_id': scene['_id'], 'direction': 'outbound', 'phase': 'SPEAK'})
            if not selection['external'] or not row:
                raise PermissionError('当前场景没有该检查器记录')
            record = {'id': record_id, 'kind': kind, 'title': '平台回执 · ' + row.get('delivery_state', 'UNKNOWN'),
                      'description': row.get('platform_message_id', record_id), 'fields': row}
        return json.loads(redact_text(json.dumps(record, ensure_ascii=False, default=str), self.store.config))

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
            raise PermissionError('只读模式不能发送消息')
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
            selection = self._scene_selection(body.get('scene', ''))
            if selection['external']:
                if body.get('integration') or body.get('development'):
                    raise Denied('CHANNEL_PROMPT_HAS_NO_DEVELOPMENT_GRANT')
                if not selection['interactive']:
                    raise Denied('SCENE_IS_READ_ONLY')
                route = selection['route']
                channel_id = selection['channel_id']
                scene_id = selection['scene']['_id']
                target_type = route['target']['type']
                sender = (route.get('operator_sender_id') if target_type == 'group'
                          else route.get('sender_id'))
                member = selection['member']
                if not sender or not member or member.get('person_id') != selection['settings']['person_id']:
                    raise Denied('CHANNEL_OWNER_NOT_CONFIGURED')
                key=str(uuid.uuid4())
                episode_kind = 'owner_group_prompt' if target_type == 'group' else 'owner_dm_prompt'
                event={'event_id':key,'scene_id':scene_id,'person_id':member['person_id'],'text':value.strip(),
                       'adapter_id':'owner-web','episode_kind':episode_kind,
                       'channel':{'id':channel_id,'account_id':self.store.config['channels'][channel_id]['account_id'],
                                  'target':route['target'],'platform_event_id':None,'sender_id':sender},
                       'trusted_context_events':[{'kind':episode_kind,'text':(
                           '这是本机 owner 请你在当前授权群发言的指令，不是群成员刚发来的 QQ 消息；'
                           '用你自己的判断生成群内公开发言。没有获得额外工具、私聊记忆或配置权限。'
                           if target_type == 'group' else
                           '这是本机 owner 请你回复当前授权 QQ 私聊的指令，不是新的 QQ 来信；'
                           '沿用该私聊场景已有认知会话与历史。没有获得额外工具、私聊记忆或配置权限。')}]}
                if target_type == 'group':
                    event['group_context']={'wake_reason':'owner_group_prompt','topic_id':key,
                                            'reply_to':None,'reply_message_id':None,
                                            'mentioned_account_ids':[]}
                return {'accepted':True,**self.controller.receive(event)}
            if selection['scene']['_id'] != self.settings['scene_id']:
                raise Denied('SCENE_IS_READ_ONLY')
            return {'accepted': True, **self.controller.submit(value.strip())}
        else:
            raise ValueError('未知操作')


class BridgeWorkbench(Workbench):
    """Stable Web-facing view while a RuntimeHost is replaced."""
    def __init__(self, store, settings, link):
        super().__init__(store, settings)
        self.link = link
        self.stream_hub = link.stream_hub
        self.stop_requested = threading.Event()

    def snapshot(self, selected='', before_seq=None):
        from .ui_runtime import RuntimeUnavailable
        if self.link.ready.is_set():
            try:
                state = self.link.call('snapshot', selected, before_seq)
                state['runtimeState'] = 'ready'
                state['revision'] += ':ready'
                return state
            except RuntimeUnavailable:
                pass
        state = super().snapshot(selected, before_seq)
        state['runtimeState'] = 'restarting'
        state['canSend'] = False
        state['revision'] += ':restarting'
        return state

    def command(self, path, body):
        if path == '/stop':
            self.stop_requested.set()
            return {'accepted': True}
        return self.link.call('command', path, body)

    def trace_detail(self, event_id, selected=''):
        return self.link.call('trace_detail', event_id, selected) if self.link.ready.is_set() else super().trace_detail(event_id, selected)

    def inspector_detail(self, record_id, kind, selected=''):
        return (self.link.call('inspector_detail', record_id, kind, selected) if self.link.ready.is_set()
                else super().inspector_detail(record_id, kind, selected))

    def provider_diagnostic(self, event_id, selected=''):
        return (self.link.call('provider_diagnostic', event_id, selected) if self.link.ready.is_set()
                else super().provider_diagnostic(event_id, selected))


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
                version, calls = workbench.stream_hub.snapshot()
                visible = workbench.live_streams(scene, calls)
                allowed = {call['id'] for call in visible}
                try:
                    payload = json.dumps({'version': version, 'calls': visible}, ensure_ascii=False).encode('utf-8')
                    self.wfile.write(b'event: snapshot\ndata: ' + payload + b'\n\n')
                    self.wfile.flush()
                    while True:
                        current, events = workbench.stream_hub.events_since(version)
                        if not events:
                            self.wfile.write(b': keepalive\n\n')
                        for event in events:
                            if event['kind'] == 'reset':
                                allowed.clear()
                                self.wfile.write(b'event: reset\ndata: {}\n\n')
                                continue
                            if event['kind'] == 'start' and workbench.live_streams(scene, [event]):
                                allowed.add(event['id'])
                            if event['id'] not in allowed:
                                continue
                            public = {key: value for key, value in event.items() if key != 'scope_key'}
                            payload = json.dumps(public, ensure_ascii=False).encode('utf-8')
                            self.wfile.write(b'event: ' + event['kind'].encode() + b'\ndata: ' + payload + b'\n\n')
                            if event['kind'] == 'end':
                                allowed.discard(event['id'])
                        self.wfile.flush()
                        version = current
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
                        value = workbench.snapshot(query.get('scene', [''])[0],
                                                   int(raw_before) if raw_before else None)
                    elif self.command == 'GET' and url.path == '/stream':
                        return self.stream(parse_qs(url.query).get('scene', [''])[0])
                    elif self.command == 'GET' and url.path == '/provider-diagnostic':
                        value = workbench.provider_diagnostic(parse_qs(url.query).get('event', [''])[0],
                                                              parse_qs(url.query).get('scene', [''])[0])
                    elif self.command == 'GET' and url.path == '/trace-detail':
                        query = parse_qs(url.query)
                        value = workbench.trace_detail(query.get('event', [''])[0], query.get('scene', [''])[0])
                    elif self.command == 'GET' and url.path == '/inspector-detail':
                        query = parse_qs(url.query)
                        value = workbench.inspector_detail(query.get('id', [''])[0], query.get('kind', [''])[0],
                                                           query.get('scene', [''])[0])
                    elif self.command == 'POST' and url.path in ('/send', '/models', '/models/discover', '/stop', '/integration/stop', '/self-development/offer'):
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
    web_logged = False
    try:
        process = subprocess.Popen(command, cwd=ROOT, env=env)
        print(f'Asuna UI: DSH 会在系统默认浏览器自动打开并完成本机认证；进入后点击侧栏 Asuna。'
              f' 若浏览器未自动打开，请复制下一行 dsh web: 地址。端口：{port}。', flush=True)
        while True:
            if not web_logged:
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=.1):
                        pass
                    if getattr(workbench, 'evidence', None):
                        workbench.evidence.record('web.ready', {'port': port})
                    web_logged = True
                except OSError:
                    pass
            try:
                return process.wait(timeout=.5)
            except subprocess.TimeoutExpired:
                if getattr(workbench, 'stop_requested', None) and workbench.stop_requested.is_set():
                    return 0
                if getattr(getattr(workbench, 'link', None), 'fatal', None) and workbench.link.fatal.is_set():
                    return 75
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
    from .evidence import Evidence
    from .ui_runtime import RuntimeLink
    evidence = Evidence(Path(out) if out else ROOT / 'reports' / ('ui-' + uuid.uuid4().hex[:12]))
    store = Store(config, database)
    streams = UiStreamHub()
    link = RuntimeLink(config, database, evidence.root, streams)
    workbench = BridgeWorkbench(store, settings, link)
    workbench.evidence = evidence
    link.start()
    try:
        return serve(workbench, port)
    finally:
        link.stop()
        store.client.close()
