"""The existing provider boundary must expose native bytes before completion."""
import threading

import httpx
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from asuna.evidence import Evidence
from asuna.provider_proxy import ProviderProxy
from asuna.ui_stream import UiStreamHub


def test_raw_reasoning_arrives_before_provider_completion_and_display_failure_is_isolated(tmp_path):
    first_sent = threading.Event()
    release = threading.Event()
    first = b'data: {"choices":[{"delta":{"reasoning_content":"first"}}]}\n\n'
    second = b'data: {"choices":[{"delta":{"content":"second"}}]}\n\ndata: [DONE]\n\n'

    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            self.wfile.write(first)
            self.wfile.flush()
            first_sent.set()
            assert release.wait(5)
            self.wfile.write(second)
            self.wfile.flush()

    server = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    cfg = {'base_url': f'http://127.0.0.1:{server.server_port}/v1', 'model': 'fixture',
           'context_window': 2048, 'max_tokens': 64, 'sampling': {}}
    proxy = ProviderProxy(cfg, Evidence(tmp_path / 'audit'), 'character')
    hub = UiStreamHub()
    proxy.ui_operation = 'ep-fixture:SPEAK:0'
    proxy.scope_key = 'scene:fixture'

    def observer(kind, call_id, **value):
        hub(kind, call_id, **value)
        if kind == 'chunk':
            raise RuntimeError('render disconnected')

    proxy.ui_observer = observer
    result = {}

    def request():
        with httpx.Client(trust_env=False, timeout=10) as client:
            result['response'] = client.post(proxy.url + '/chat/completions',
                                             json={'model': 'fixture', 'stream': True,
                                                   'messages': [{'role': 'user', 'content': 'probe'}]})

    worker = threading.Thread(target=request)
    worker.start()
    try:
        assert first_sent.wait(5)
        # The producer may have flushed before the proxy read it.
        with hub.condition:
            assert hub.condition.wait_for(lambda: any(first.decode() in call['body_utf8']
                                                     for call in hub.calls.values()), 5)
        _, calls = hub.snapshot()
        assert calls[0]['body_utf8'] == first.decode()
        assert worker.is_alive()  # Native reasoning is visible during generation.
        release.set()
        worker.join(5)
        assert not worker.is_alive()
        assert result['response'].status_code == 200
        assert proxy.calls[0]['raw'] == (first + second).decode()
        assert hub.snapshot()[1][0]['body_utf8'] == (first + second).decode()
    finally:
        release.set()
        worker.join(5)
        proxy.close()
        server.shutdown()
        server.server_close()
        server_thread.join()
