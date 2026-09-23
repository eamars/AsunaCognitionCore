"""The installed DSH compacts after pricing a newly claimed role input."""
import copy
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from asuna.config import ROOT
from asuna.dsh_lane import DshLane
from asuna.evidence import Evidence


def test_pending_role_input_uses_native_compaction_before_generation(store):
    calls = []

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            last = body['messages'][-1]['content']
            kind = 'summary' if last.startswith('ASUNA_COMPACTION_V1\n') else 'ordinary'
            calls.append(kind)
            answer = 'Earlier long message summarized.' if kind == 'summary' else 'Received.'
            def event(delta, finish=None):
                return 'data: ' + json.dumps({
                    'id': 'chatcmpl-pressure-fixture', 'object': 'chat.completion.chunk',
                    'created': 1, 'model': body['model'],
                    'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}],
                }) + '\n\n'
            data = (event({'role': 'assistant', 'content': answer}) +
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
    config['character'].update(
        base_url=f'http://127.0.0.1:{server.server_port}/v1',
        model='pressure-fixture', context_window=8192, max_tokens=256,
        token_counter='conservative_bytes', sampling={})
    evidence = Evidence(ROOT / 'reports' / ('test-pending-pressure-' + store.name))
    try:
        with DshLane(config, store, evidence, 'character') as lane:
            system = 'System prompt for an isolated pressure probe. ' * 4
            first = lane.generate('pending-pressure', 'pending-pressure:1',
                                  'MONOLOGUE', '甲' * 16000, system)
            second = lane.generate('pending-pressure', 'pending-pressure:2',
                                   'MONOLOGUE', '乙' * 16000, system)
        receipts = [json.loads(path.read_text(encoding='utf-8'))['payload']
                    for path in evidence.root.glob('*lane.receipt.json')]
        receipt = next(row['body'] for row in receipts
                       if row['operation'] == 'pending-pressure:2')
        assert first.finish_reason == second.finish_reason == 'stop'
        assert calls == ['ordinary', 'summary', 'ordinary']
        assert receipt['pressure']['projected'] >= receipt['pressure']['threshold']
        assert receipt['pressure']['compacted'] is True
        assert len(receipt['compactions']) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
