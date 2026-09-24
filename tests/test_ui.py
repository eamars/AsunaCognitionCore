"""UI contract regressions with real isolated Mongo + Chat; model output is a double.

These do not claim live model or rendered-browser verification.
"""
import json
import hashlib
from pathlib import Path
from types import SimpleNamespace
import uuid

import httpx
import pytest

from asuna.chat import Chat
from asuna.config import load
from asuna.coordinator import Coordinator
from asuna.evidence import Evidence
from asuna.lanes import FakeLane, LaneResult
from asuna.router import Router
from asuna.state import Store
from asuna.ui import UiBridge, Workbench, inspector_record, native_call_projection, raw_provider_response, trace_step, turn_status


def test_native_steps_keep_request_identity_across_tool_boundary():
    events = [
        {'type': 'turn/start', 'seq': 1, 'time': 1000, 'data': {'turn': 4}},
        {'type': 'step/start', 'seq': 2, 'time': 1100, 'data': {'turn': 4, 'step': 1}},
        {'type': 'user/message', 'seq': 3, 'time': 1101, 'data': {'id': 'request-message'}},
        {'type': 'assistant/message', 'seq': 4, 'time': 1300, 'data': {'turn': 4, 'step': 1,
            'message': {'content': [{'type': 'reasoning', 'text': '工具前的思考'}, {'type': 'tool-call'}]}}},
        {'type': 'tool/call', 'seq': 5, 'time': 1301, 'data': {'callId': 'tool-1'}},
        {'type': 'tool/result', 'seq': 6, 'time': 1500, 'data': {}},
        {'type': 'step/start', 'seq': 7, 'time': 1600, 'data': {'turn': 4, 'step': 2}},
        {'type': 'assistant/message', 'seq': 8, 'time': 1800, 'data': {'turn': 4, 'step': 2,
            'message': {'content': [{'type': 'reasoning', 'text': '工具后的思考'},
                                    {'type': 'text', 'text': '最终答复'}]}}},
        {'type': 'turn/end', 'seq': 9, 'time': 1801, 'data': {'turn': 4}},
    ]
    refs = [{'artifact_path': f'reports/run/{number:05d}-provider.request.json'} for number in (1, 2)]
    calls = native_call_projection(events, 'request-message', refs, 'task:execute:1')
    assert [call['id'] for call in calls] == [
        'task:execute:1:00001-provider.request.json', 'task:execute:1:00002-provider.request.json']
    assert calls[0]['createdAt'] < calls[1]['createdAt']
    assert calls[0]['parts'] == [{'field': 'reasoning_content', 'text': '工具前的思考'}]
    assert calls[1]['parts'] == [{'field': 'reasoning_content', 'text': '工具后的思考'},
                                 {'field': 'content', 'text': '最终答复'}]
    assert native_call_projection(events, 'request-message', refs[:1], 'task:execute:1') == []


def test_live_provider_stream_keeps_native_fields_and_scene_identity(ui_store, tmp_path):
    chat, view = controller(ui_store, tmp_path, reply('完成'))
    chat.worker.start()
    bridge = UiBridge(view)
    client = httpx.Client(base_url=f'http://127.0.0.1:{bridge.server.server_port}', trust_env=False,
                         headers={'Authorization': 'Bearer ' + bridge.token}, timeout=5)
    try:
        chat.submit('观察流')
        chat.pending.join()
        episode = chat.latest
        view.stream_hub('start', 'call-a', lane='character', phase='SPEAK',
                        operation=episode + ':SPEAK:0', scope_key='scene:dm-a', request_ref='request-a.json')
        view.stream_hub('start', 'call-b', lane='executor', phase='execution',
                        operation=episode + ':execute:0', scope_key='scene:dm-b', request_ref='request-b.json')
        view.stream_hub('start', 'call-c', lane='character', phase='compaction',
                        operation=episode + ':SPEAK:0', scope_key='scene:dm-a', request_ref='request-c.json')
        view.stream_hub('text', 'call-c', field='content', text='内部上下文压缩摘要')
        assert client.get('/stream', headers={'Authorization': 'bad'}).status_code == 403
        with client.stream('GET', '/stream') as response:
            assert response.status_code == 200
            lines = iter(response.iter_lines())
            assert next(lines) == 'event: snapshot'
            initial = json.loads(next(lines).removeprefix('data: '))
            assert [call['id'] for call in initial['calls']] == ['call-a']
            view.stream_hub('chunk', 'call-a', chunk='data: {"choices":[{"delta":{"reasoning_content":"想法"}}]}\n\n'.encode())
            view.stream_hub('text', 'call-a', field='reasoning_content', text='想法')
            for line in lines:
                if line.startswith('data: ') and 'reasoning_content' in line and '想法' in line:
                    value = json.loads(line.removeprefix('data: '))
                    assert value['calls'][0]['parts'] == [{'field': 'reasoning_content', 'text': '想法'}]
                    assert 'body_utf8' not in value['calls'][0]
                    assert 'content' not in value['calls'][0]
                    break
            else:
                pytest.fail('live reasoning text did not arrive')
            view.stream_hub('text', 'call-a', field='content', text='真实正文')
            for line in lines:
                if line.startswith('data: ') and '真实正文' in line:
                    value = json.loads(line.removeprefix('data: '))
                    assert value['calls'][0]['parts'] == [
                        {'field': 'reasoning_content', 'text': '想法'},
                        {'field': 'content', 'text': '真实正文'},
                    ]
                    break
            else:
                pytest.fail('read-only body projection did not cross the HTTP stream')
    finally:
        client.close()
        bridge.close()
        chat.stop()


@pytest.fixture
def ui_store():
    config = load('config/local.example.json')
    store = Store(config, 'asuna_v2_test_ui_' + uuid.uuid4().hex[:12])
    store.migrate()
    store.seed()
    yield store
    store.client.close()  # Isolated test records retained, as in existing tests.


def controller(store, tmp_path, outputs):
    lane = FakeLane(store, outputs)
    settings = {'scene_id': 'dm-a', 'person_id': 'A', 'persona': 'P1', 'display_name': '小满'}
    workbench = Workbench(store, settings)
    app = SimpleNamespace(store=store, config=store.config, evidence=Evidence(tmp_path / 'evidence'),
                          character=lane, router=Router(store, Coordinator(store, lane)))
    chat = Chat(app, settings, emit=workbench.emit)
    workbench.controller = chat
    return chat, workbench


def reply(value):
    return [LaneResult('角色独白'), LaneResult(json.dumps({'next': 'speak', 'goal': '回应',
            'constraints': [], 'recall_query': '', 'speak_before_action': False})), LaneResult(value)]


def test_stream_scene_authorizes_context_without_rebuilding_history(ui_store, monkeypatch):
    scene = ui_store.authorize('dm-a', 'A')
    ui_store.db.episodes.insert_one({'_id': 'episode-old-context', 'schema_version': 1, 'scene_id': scene['_id'],
                                     'scope_key': scene['scope_key'], 'policy_epoch': scene['policy_epoch'],
                                     'character_context': 'older'})
    view = Workbench(ui_store, {'scene_id': 'dm-a', 'person_id': 'A', 'display_name': '小满'})
    monkeypatch.setattr(view, 'snapshot', lambda *_: pytest.fail('stream authorization rebuilt the transcript'))
    assert view.stream_scene('older')['_id'] == 'dm-a'
    with pytest.raises(ValueError, match='会话不存在'):
        view.stream_scene('another-scene')
    with pytest.raises(ValueError, match='通道未配置'):
        view.stream_scene('channel:dm-a')


def test_silent_turn_stays_with_input_instead_of_creating_system_message(ui_store, tmp_path):
    outputs = [LaneResult('角色独白'), LaneResult(json.dumps({'next': 'silent', 'goal': '此时不需要回复',
                'constraints': [], 'recall_query': '', 'speak_before_action': False}))]
    chat, view = controller(ui_store, tmp_path, outputs)
    chat.worker.start()
    try:
        chat.submit('暂时不用回复')
        chat.pending.join()
        messages = view.snapshot()['messages']
        assert len(messages) == 1 and messages[0]['role'] == 'user'
        assert messages[0]['turnStatus']['label'] == '角色选择不发言'
        assert messages[0]['turnStatus']['detail'] == '此时不需要回复'
        assert any(step['type'] == 'phase.output' for step in messages[0]['internalSteps'])
        assert turn_status({'no_wake': True, 'state': 'COMPLETE'}, '') is None
    finally:
        chat.stop()


def test_running_feedback_task_stays_with_original_input_and_ready_task_is_queued(ui_store):
    scene = ui_store.authorize('dm-a', 'A')
    scope = {'scene_id': scene['_id'], 'scope_key': scene['scope_key'],
             'policy_epoch': scene['policy_epoch']}
    context = scene.get('character_context', 'initial')
    root, child, queued = 'ep-ui-root', 'ep-ui-feedback', 'ep-ui-queued'
    for ep_id, kind, state in ((root, 'external', 'WAITING_TASK'),
                               (child, 'task_feedback', 'WAITING_TASK'),
                               (queued, 'external', 'WAITING_TASK')):
        ui_store.db.episodes.insert_one({'_id': ep_id, 'schema_version': 1, **scope, 'character_context': context,
                                         'episode_kind': kind, 'source_event_id': ep_id, 'state': state,
                                         'task_id': 'task-' + ep_id})
    for seq, ep_id, kind in ((1, root, 'external'), (2, child, 'task_feedback'),
                              (16, queued, 'external')):
        ui_store.db.messages.insert_one({'_id': 'in-' + ep_id, 'schema_version': 1, **scope, 'episode_id': ep_id,
                                         'scene_seq': seq, 'direction': 'inbound',
                                         'text': kind, 'event': {'episode_kind': kind},
                                         'received_at': f'2026-09-24T00:00:{seq:02d}+00:00'})
    for seq in range(3, 16):
        ep_id = f'ep-ui-filler-{seq}'
        ui_store.db.episodes.insert_one({'_id': ep_id, 'schema_version': 1, **scope, 'character_context': context,
                                         'source_event_id': ep_id, 'state': 'COMMITTED'})
        ui_store.db.messages.insert_one({'_id': 'in-' + ep_id, 'schema_version': 1, **scope, 'episode_id': ep_id,
                                         'scene_seq': seq, 'direction': 'inbound',
                                         'text': 'filler', 'received_at': f'2026-09-24T00:00:{seq:02d}+00:00'})
    for ep_id, state, parent in ((root, 'BLOCKED', None), (child, 'RUNNING', 'task-' + root),
                                  (queued, 'READY', None)):
        ui_store.db.tasks.insert_one({'_id': 'task-' + ep_id, 'request_key': 'task-' + ep_id,
                                      'schema_version': 1, **scope, 'episode_id': ep_id,
                                      'state': state, 'intent_revision': 1,
                                      **({'continues_task_id': parent} if parent else {})})
    ui_store.audit('task-' + child, 'tool_call', {'tool': 'read_file'}, scene['scope_key'])
    view = Workbench(ui_store, {'scene_id': 'dm-a', 'person_id': 'A', 'display_name': '小满'})
    messages = view.snapshot()['messages']
    owner = next(message for message in messages if message['id'] == 'in-' + root)
    assert owner['taskIds'] == ['task-' + child]
    assert any(step['sourceStreamId'] == 'task-' + child for step in owner['internalSteps'])
    assert not any(message['id'] == 'in-' + child for message in messages)
    assert next(message for message in messages if message['id'] == 'in-' + queued)['turnStatus']['label'] == '行动已排队'


def test_resumed_speak_uses_actual_operation_and_stage_time(ui_store):
    scene = ui_store.authorize('dm-a', 'A')
    scope = {'scene_id': scene['_id'], 'scope_key': scene['scope_key'],
             'policy_epoch': scene['policy_epoch']}
    ep_id = 'ep-ui-resumed-speak'
    operation = ep_id + ':SPEAK:0:resume:1'
    ui_store.db.episodes.insert_one({'_id': ep_id, 'schema_version': 1, **scope,
                                     'character_context': scene.get('character_context', 'initial'),
                                     'source_event_id': ep_id, 'state': 'COMMITTED'})
    ui_store.db.messages.insert_many([
        {'_id': 'in-' + ep_id, 'schema_version': 1, **scope, 'episode_id': ep_id,
         'scene_seq': 1, 'direction': 'inbound', 'text': '请回复',
         'received_at': '2026-09-24T00:00:00+00:00'},
        {'_id': ep_id + ':speak:0', 'schema_version': 1, **scope, 'episode_id': ep_id,
         'scene_seq': 2, 'direction': 'outbound', 'phase': 'SPEAK', 'text': '恢复后的回复',
         'delivery_state': 'DELIVERED'},
    ])
    started = ui_store.audit(ep_id, 'phase.started', {'phase': 'SPEAK', 'operation': operation}, scene['scope_key'])
    ui_store.audit(ep_id, 'phase.output', {'phase': 'SPEAK', 'operation': operation,
                                          'content': '恢复后的回复', 'finish_reason': 'stop'}, scene['scope_key'])
    view = Workbench(ui_store, {'scene_id': 'dm-a', 'person_id': 'A', 'display_name': '小满'})
    public = next(message for message in view.snapshot()['messages'] if message['role'] == 'assistant')
    assert public['displayKey'] == operation
    assert public['createdAt'] == started['occurred_at']
    assert next(step for step in public['internalSteps'] if step['type'] == 'phase.output')['displayKey'] == operation


def test_http_chat_and_native_context_switch_preserve_memory(ui_store, tmp_path):
    chat, view = controller(ui_store, tmp_path, reply('第一句回复') + reply('第二句回复'))
    chat.worker.start()
    bridge = UiBridge(view)
    client = httpx.Client(base_url=f'http://127.0.0.1:{bridge.server.server_port}', trust_env=False,
                         headers={'Authorization': 'Bearer ' + bridge.token})
    try:
        assert client.post('/send', json={'text': '第一句输入'}).status_code == 200
        chat.pending.join()
        first = client.get('/state').json()
        assert [m['text'] for m in first['messages'] if m['role'] in ('user', 'assistant')] == ['第一句输入', '第一句回复']
        assert any(step['type'] == 'phase.output' for m in first['messages'] for step in m.get('internalSteps', []))
        public = next(m for m in first['messages'] if m['role'] == 'assistant')
        stages = [step for step in public['internalSteps'] if step['type'] == 'phase.output']
        assert next(step for step in stages if step['payload']['phase'] == 'MONOLOGUE')['payload']['content'] == '角色独白'
        assert next(step for step in stages if step['payload']['phase'] == 'SPEAK')['displayKey'] == public['displayKey']
        assert public['deliveryState'] == 'DELIVERED'
        assert not any(step['status'] == 'running' for m in first['messages'] for step in m.get('internalSteps', []))
        assert first['conversations'][0]['updatedAt']
        assert client.post('/new', json={}).status_code == 200
        chat.pending.join()
        assert client.post('/send', json={'text': '第二句输入'}).status_code == 200
        chat.pending.join()
        latest = client.get('/state').json()
        assert latest['conversationId'] != first['conversationId']
        assert any(m['text'] == '第二句回复' for m in latest['messages'])
        assert not any(m['text'] == '第一句回复' for m in latest['messages'])
        history = client.get('/state', params={'conversation': first['conversationId']}).json()
        assert not history['canSend']
        assert any(m['text'] == '第一句回复' for m in history['messages'])
        ui_store.db.messages.update_one({'_id': public['id']}, {'$set': {'delivery_state': 'READY'}})
        pending = next(m for m in view.snapshot(first['conversationId'])['messages'] if m['id'] == public['id'])
        assert pending['deliveryState'] == 'READY' and pending['text'] == public['text']
        assert {r['id'] for r in first['records']}.issubset({r['id'] for r in latest['records']})
        assert client.post('/send', json={'text': ' '}).status_code == 400
        assert client.post('/send', json=[]).status_code == 400
    finally:
        client.close()
        bridge.close()
        chat.stop()


def test_scope_epoch_redaction_and_generic_records(ui_store, tmp_path):
    chat, view = controller(ui_store, tmp_path, reply('回复'))
    chat.worker.start()
    try:
        chat.submit('输入')
        chat.pending.join()
        ep = chat.latest
        ui_store.audit(ep, 'future.event', {'content': '新事件', 'extra': {'field': 42}}, 'scene:dm-a')
        ui_store.audit(ep, 'tool.failed', {'error': '读取失败 ' + ui_store.config['mongo_uri']}, 'scene:dm-a')
        ui_store.put('memory_units', {'_id': 'ui-other-epoch', 'scope_key': 'scene:dm-a', 'policy_epoch': 99,
                                     'status': 'active', 'body_markdown': 'EPOCH_PRIVATE'})
        ui_store.put('memory_units', {'_id': 'ui-other-scene', 'scope_key': 'scene:dm-b', 'policy_epoch': 1,
                                     'status': 'active', 'body_markdown': 'SCENE_PRIVATE'})
        value = view.snapshot()
        encoded = json.dumps(value, ensure_ascii=False)
        assert 'EPOCH_PRIVATE' not in encoded and 'SCENE_PRIVATE' not in encoded
        assert ui_store.config['mongo_uri'] not in encoded
        steps = next(m['internalSteps'] for m in value['messages'] if m['role'] == 'assistant')
        assert any(s['type'] == 'future.event' and s['payload']['extra']['field'] == 42 for s in steps)
        assert any(s['status'] == 'error' and '读取失败' in s['summary'] for s in steps)
        with pytest.raises(ValueError):
            view.snapshot('not-a-context')
        ui_store.db.scenes.update_one({'_id': 'dm-a'}, {'$set': {'members': []}})
        with pytest.raises(PermissionError):
            view.snapshot()
        with pytest.raises(PermissionError):
            view.command('/send', {'text': 'denied'})
    finally:
        chat.stop()
    record = inspector_record({'_id': 'future', 'content': {'new_field': [1, 2]}, 'extra': True}, 'future_record')
    assert record['kind'] == 'future_record' and record['fields']['extra']


def test_failed_episode_is_system_status_not_fake_assistant(ui_store, tmp_path):
    chat, view = controller(ui_store, tmp_path, [])
    chat.worker.start()
    try:
        chat.submit('触发无模型输出错误')
        chat.pending.join()
        value = view.snapshot()
        assert not any(m['role'] == 'assistant' for m in value['messages'])
        assert any(s['status'] == 'error' for m in value['messages'] for s in m.get('internalSteps', []))
    finally:
        chat.stop()


def test_bridge_auth_readonly_and_tool_payload(ui_store):
    view = Workbench(ui_store, {'scene_id': 'dm-a', 'person_id': 'A', 'display_name': '小满'})
    bridge = UiBridge(view)
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{bridge.server.server_port}', trust_env=False) as client:
            assert client.get('/state').status_code == 403
            client.headers['Authorization'] = 'Bearer ' + bridge.token
            assert client.get('/state').json()['readOnly']
            assert client.post('/send', json={'text': 'blocked'}).status_code == 403
            assert client.post('/new', json={}).status_code == 403
    finally:
        bridge.close()
    step = trace_step({'_id': 'tool', 'type': 'state.commit', 'payload': {'collection': 'artifacts',
        'document': {'state': 'DONE', 'tool': 'read_file', 'result': {'execution': {'exit_code': 1}}}}}, True)
    assert step['type'] == 'tool_result' and step['status'] == 'error'


def test_trace_output_keeps_reasoning_in_payload():
    payload = {'request_refs': [{'artifact_path': 'reports/001-provider.request.json'}],
               'content': 'final answer', 'reasoning': 'separate reasoning content', 'finish_reason': 'stop'}
    step = trace_step({'_id': 'output', 'type': 'execution.output', 'payload': payload}, True)

    assert step['payload'] == payload
    assert 'thinking' not in step


def test_raw_provider_response_preserves_captured_stream(tmp_path):
    evidence = tmp_path / 'reports' / 'ui-test'
    evidence.mkdir(parents=True)
    request_name = '00102-provider.request.json'
    request = evidence / request_name
    request.write_text(json.dumps({'type': 'provider.request', 'payload': {'call_id': 'call-1'}}), encoding='utf-8')
    raw = 'data: {"choices":[{"delta":{"reasoning_content":"line 1\\nline 2","content":"ok"}}]}\r\n\r\n'
    response = evidence / '00111-provider.response.json'
    response.write_text(json.dumps({'type': 'provider.response', 'payload': {
        'request_ref': request_name, 'call_id': 'call-1', 'status_code': 200, 'body_utf8': raw}}), encoding='utf-8')
    ref = {'artifact_path': request.relative_to(tmp_path).as_posix(),
           'sha256': hashlib.sha256(request.read_bytes()).hexdigest()}

    assert raw_provider_response([ref], root=tmp_path) == raw


def test_provider_diagnostic_bridge_excludes_displayed_text(tmp_path, monkeypatch, ui_store):
    import asuna.ui as ui
    monkeypatch.setattr(ui, 'ROOT', tmp_path)
    scene = ui_store.authorize('dm-a', 'A')
    evidence = tmp_path / 'reports' / 'ui-test'
    evidence.mkdir(parents=True)
    request_name = '00102-provider.request.json'
    request = evidence / request_name
    request.write_text(json.dumps({'type': 'provider.request', 'payload': {'call_id': 'call-1'}}), encoding='utf-8')
    raw = ('data: {"id":"resp-1","model":"fixture","choices":[{"delta":{"reasoning_content":"native","content":"answer"},"finish_reason":"stop"}]}\r\n\r\n'
           'data: {"choices":[],"usage":{"prompt_tokens":12,"completion_tokens":7,"total_tokens":19}}\r\n\r\ndata: [DONE]\r\n\r\n')
    (evidence / '00111-provider.response.json').write_text(json.dumps({'type': 'provider.response', 'payload': {
        'request_ref': request_name, 'call_id': 'call-1', 'status_code': 200, 'body_utf8': raw}}), encoding='utf-8')
    ref = {'artifact_path': (Path('reports') / 'ui-test' / request_name).as_posix(),
               'sha256': hashlib.sha256(request.read_bytes()).hexdigest()}
    ui_store.db.episodes.insert_one({'_id': 'episode-provider-response', 'schema_version': 1, 'scene_id': scene['_id'],
                                     'scope_key': scene['scope_key'], 'policy_epoch': scene['policy_epoch'],
                                     'state': 'COMMITTED', 'character_context': 'initial'})
    event = ui_store.audit('episode-provider-response', 'phase.output', {'request_refs': [ref]}, scene['scope_key'])
    view = Workbench(ui_store, {'scene_id': 'dm-a', 'person_id': 'A', 'display_name': '小满'})
    bridge = UiBridge(view)
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{bridge.server.server_port}', trust_env=False) as client:
            assert client.get(f'/provider-diagnostic?event={event["_id"]}').status_code == 403
            client.headers['Authorization'] = 'Bearer ' + bridge.token
            response = client.get(f'/provider-diagnostic?event={event["_id"]}')
            assert response.status_code == 200
            assert response.json() == {'diagnostic': {'source_event': event['_id'], 'event_type': 'phase.output',
                'wire_format': 'sse', 'response_bytes': len(raw.encode()), 'frame_count': 2, 'stream_done': True,
                'response_id': 'resp-1', 'model': 'fixture', 'finish_reasons': ['stop'],
                'usage': {'prompt_tokens': 12, 'completion_tokens': 7, 'total_tokens': 19}}}
            assert 'native' not in response.text and 'answer' not in response.text
            assert client.get('/provider-diagnostic?event=unknown').status_code == 403
            assert client.get(f'/provider-response?event={event["_id"]}').status_code == 404
    finally:
        bridge.close()


def test_ui_provider_diagnostic_keeps_raw_only_in_audit(tmp_path, monkeypatch, ui_store):
    import asuna.ui as ui
    monkeypatch.setattr(ui, 'ROOT', tmp_path)
    scene = ui_store.authorize('dm-a', 'A')
    evidence = tmp_path / 'reports' / 'ui-test'
    evidence.mkdir(parents=True)
    request_name = '00102-provider.request.json'
    request = evidence / request_name
    request.write_text(json.dumps({'type': 'provider.request', 'payload': {'call_id': 'call-1'}}), encoding='utf-8')
    raw = 'data: {"choices":[{"delta":{"reasoning_content":"raw","content":"answer"}}]}\n\n'
    (evidence / '00111-provider.response.json').write_text(json.dumps({'type': 'provider.response', 'payload': {
        'request_ref': request_name, 'call_id': 'call-1', 'status_code': 200, 'body_utf8': raw}}), encoding='utf-8')
    ref = {'artifact_path': (Path('reports') / 'ui-test' / request_name).as_posix(),
               'sha256': hashlib.sha256(request.read_bytes()).hexdigest()}
    ui_store.db.episodes.insert_one({'_id': 'episode-provider-response', 'schema_version': 1, 'scene_id': scene['_id'],
                                     'scope_key': scene['scope_key'], 'policy_epoch': scene['policy_epoch'],
                                     'state': 'COMMITTED', 'character_context': 'initial'})
    event = ui_store.audit('episode-provider-response', 'phase.output', {'request_refs': [ref]}, scene['scope_key'])
    view = Workbench(ui_store, {'scene_id': 'dm-a', 'person_id': 'A', 'display_name': '小满'})

    diagnostic = view.provider_diagnostic(event['_id'])
    assert diagnostic['diagnostic']['response_bytes'] == len(raw.encode())
    assert 'raw' not in json.dumps(diagnostic) and 'answer' not in json.dumps(diagnostic)
    assert raw_provider_response([ref], root=tmp_path) == raw
