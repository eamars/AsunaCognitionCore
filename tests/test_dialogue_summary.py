"""Personal summary persistence through the existing Mongo and native lane."""
import copy
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from asuna.config import ROOT
from asuna.dialogue_summary import DialogueSummarizer
from asuna.dsh_lane import DshLane
from asuna.evidence import Evidence


def test_personal_batch_summary_uses_source_window_and_confirmed_output(store):
    calls = []

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append(body)
            def event(delta, finish=None):
                return 'data: ' + json.dumps({
                    'id': 'chatcmpl-summary-fixture', 'object': 'chat.completion.chunk',
                    'created': 1, 'model': body['model'],
                    'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}],
                }) + '\n\n'
            data = (event({'role': 'assistant', 'content': 'A 说了两件事，小满已答复一件。'}) +
                    event({}, 'stop') + 'data: [DONE]\n\n').encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = copy.deepcopy(store.config)
    config['executor'].update(
        base_url=f'http://127.0.0.1:{server.server_port}/v1',
        model='summary-fixture', context_window=8192, max_tokens=256,
        token_counter='conservative_bytes', sampling={})
    evidence = Evidence(ROOT / 'reports' / ('test-dialogue-summary-' + store.name))
    try:
        with DshLane(config, store, evidence, 'summary') as lane:
            summary = DialogueSummarizer(store, evidence, lane, 'dm-a')
            summary.initialize()
            for seq, (author, direction, state) in enumerate([
                ('A', 'inbound', None), ('xiaoman', 'outbound', 'DELIVERED'),
                ('A', 'inbound', None), ('xiaoman', 'outbound', 'READY'),
                ('A', 'inbound', None),
            ], 1):
                store.put('messages', {
                    '_id': f'summary-source-{seq}', 'scene_id': 'dm-a',
                    'scope_key': 'scene:dm-a', 'policy_epoch': 1, 'scene_seq': seq,
                    'author': author, 'direction': direction, 'text': f'消息 {seq}',
                    **({'delivery_state': state} if state else {})}, stream='summary-fixture')
            saved = summary.tick()
            assert saved['source_event_ids'] == [
                'summary-source-1', 'summary-source-2',
                'summary-source-3', 'summary-source-5']
            assert saved['creator_model'] == 'summary-fixture'
            assert saved['body_markdown'] == 'A 说了两件事，小满已答复一件。'
            assert len(calls) == 1 and not calls[0].get('tools')
            assert store.db.messages.find_one({'_id': 'summary-source-4'}).get('summary_batch_id') is None
            for source in saved['source_event_ids']:
                assert store.db.messages.find_one({'_id': source})['summary_batch_id'] == saved['_id']
            summary.next_attempt = 0
            assert summary.tick() is None
            assert len(calls) == 1
            for seq in (6, 7, 8):
                store.put('messages', {
                    '_id': f'summary-source-{seq}', 'scene_id': 'dm-a',
                    'scope_key': 'scene:dm-a', 'policy_epoch': 1,
                    'scene_seq': seq, 'author': 'A', 'direction': 'inbound',
                    'text': f'后来消息 {seq}'}, stream='summary-fixture')
            assert summary.tick() is None  # The older draft is not yet public.
            pending = store.db.messages.find_one({'_id': 'summary-source-4'})
            store.put('messages', {**pending, 'delivery_state': 'DELIVERED'},
                      expected=pending['revision'], stream='summary-fixture')
            later = summary.tick()
            assert later['source_event_ids'] == [
                'summary-source-4', 'summary-source-6',
                'summary-source-7', 'summary-source-8']
            assert len(calls) == 2
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
