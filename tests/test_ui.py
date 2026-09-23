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
from asuna.ui import UiBridge, Workbench, inspector_record, raw_provider_response, trace_step, turn_status


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
        assert client.get('/stream', headers={'Authorization': 'bad'}).status_code == 403
        with client.stream('GET', '/stream') as response:
            assert response.status_code == 200
            lines = iter(response.iter_lines())
            assert next(lines) == 'event: snapshot'
            initial = json.loads(next(lines).removeprefix('data: '))
            assert [call['id'] for call in initial['calls']] == ['call-a']
            view.stream_hub('chunk', 'call-a', chunk=b'data: {"choices":[{"delta":{"reasoning_content":"')
            view.stream_hub('chunk', 'call-a', chunk='想法'.encode('utf-8')[:2])
            view.stream_hub('chunk', 'call-a', chunk='想法'.encode('utf-8')[2:] + b'"}}]}\n\n')
            # SSE may have emitted an intermediate snapshot while chunks arrived.
            for line in lines:
                if line.startswith('data: ') and 'reasoning_content' in line and '想法' in line:
                    value = json.loads(line.removeprefix('data: '))
                    assert value['calls'][0]['body_utf8'] == 'data: {"choices":[{"delta":{"reasoning_content":"想法"}}]}\n\n'
                    break
            else:
                pytest.fail('live raw provider bytes did not arrive')
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


def test_provider_response_bridge_returns_exact_scoped_body(tmp_path, monkeypatch, ui_store):
    import asuna.ui as ui
    monkeypatch.setattr(ui, 'ROOT', tmp_path)
    scene = ui_store.authorize('dm-a', 'A')
    evidence = tmp_path / 'reports' / 'ui-test'
    evidence.mkdir(parents=True)
    request_name = '00102-provider.request.json'
    request = evidence / request_name
    request.write_text(json.dumps({'type': 'provider.request', 'payload': {'call_id': 'call-1'}}), encoding='utf-8')
    raw = 'data: {"choices":[{"delta":{"reasoning_content":"native","content":"answer"}}]}\r\n\r\n'
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
            assert client.get(f'/provider-response?event={event["_id"]}').status_code == 403
            client.headers['Authorization'] = 'Bearer ' + bridge.token
            response = client.get(f'/provider-response?event={event["_id"]}')
            assert response.status_code == 200
            assert response.json() == {'body_utf8': raw}
            assert client.get('/provider-response?event=unknown').status_code == 403
    finally:
        bridge.close()


def test_ui_provider_response_returns_raw_body_for_scoped_output(tmp_path, monkeypatch, ui_store):
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

    assert view.provider_response(event['_id']) == {'body_utf8': raw}
