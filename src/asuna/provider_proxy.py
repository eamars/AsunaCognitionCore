"""Loopback capture boundary for DSH's serialized provider traffic.

The provider adapter lacks top_p/seed fields in GenerateOptions. This boundary
pins only generation parameters, records both wire bodies, and never rewrites
messages/content. It has exactly one local upstream, no redirect/proxy fallback.
"""
from __future__ import annotations
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import codecs
import threading
import time
import uuid
import httpx
from .config import validate_endpoint
from .evidence import Evidence, canonical, sha
from .queue import EndpointLock
from .tokens import TokenMeter


class ProviderProxy:
    def __init__(self, cfg: dict, evidence: Evidence, lane: str):
        validate_endpoint(cfg['base_url'])
        self.cfg, self.evidence, self.lane = cfg, evidence, lane
        self.purpose = 'integration-probe'
        self.calls = []
        self.lock = threading.Lock()
        self.capacity_probe_override=False
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                call_id = str(uuid.uuid4())
                try:
                    if self.path != '/v1/chat/completions':
                        raise PermissionError('UNREGISTERED_PROVIDER_PATH')
                    size = int(self.headers.get('Content-Length', '0'))
                    if not 0 < size <= 16 * 1024 * 1024:
                        raise ValueError('REQUEST_SIZE')
                    incoming = self.rfile.read(size)
                    body = json.loads(incoming)
                    if body['model'] != cfg['model']:
                        raise PermissionError('MODEL_ROUTE_MISMATCH')
                    if lane == 'character' and body.get('tools'):
                        raise PermissionError('CHARACTER_TOOLS_FORBIDDEN')
                    evidence.record('dsh.provider_input', {'call_id': call_id, 'lane': lane, 'body': body})
                    body.update(cfg['sampling'])
                    body['max_tokens'] = min(body.get('max_tokens', cfg['max_tokens']), cfg['max_tokens'])
                    budget=TokenMeter(cfg,evidence,lane).check(body,owner.capacity_probe_override)
                    outgoing = canonical(body)
                    # Record exact bytes before network. Log failure prevents generation.
                    last=body.get('messages',[{}])[-1].get('content','')
                    purpose='compaction' if isinstance(last,str) and last.startswith('ASUNA_COMPACTION_V1\n') else owner.purpose
                    request_ref = evidence.record('provider.request', {'call_id': call_id, 'lane': lane, 'purpose': purpose, 'url':cfg['base_url']+'/chat/completions','body_utf8': outgoing.decode(), 'body_sha256': sha(outgoing), 'token_render_visibility':budget['method']})
                    started = time.perf_counter()
                    chunks = []
                    first = None
                    first_content=None;decoder=codecs.getincrementaldecoder('utf-8')();pending=''
                    with EndpointLock(cfg['base_url']) as queued, httpx.Client(timeout=httpx.Timeout(300, connect=10), trust_env=False, follow_redirects=False) as client:
                        with client.stream('POST', cfg['base_url'] + '/chat/completions', content=outgoing, headers={'Content-Type':'application/json'}) as response:
                            for chunk in response.iter_bytes():
                                if first is None:
                                    first = time.perf_counter() - started
                                chunks.append(chunk)
                                pending+=decoder.decode(chunk)
                                while '\n' in pending:
                                    line,pending=pending.split('\n',1)
                                    if line.startswith('data: ') and line[6:].strip()!='[DONE]':
                                        try:
                                            parsed=json.loads(line[6:])
                                            if first_content is None and any(c.get('delta',{}).get('content') for c in parsed.get('choices',[])):first_content=time.perf_counter()-started
                                        except (ValueError,TypeError):pass
                                # Save complete return before DSH can commit it; stream buffering
                                # does not provide public-text TTFT and is reported as such.
                            raw = b''.join(chunks)
                            ref = evidence.record('provider.response', {'call_id':call_id,'request_ref':request_ref,'status_code':response.status_code,'body_utf8':raw.decode('utf-8'),'transport_first_byte_seconds':first,'first_model_content_seconds':first_content,'public_text_ttft_seconds':None,'queue_seconds':queued.wait_seconds,'total_seconds':time.perf_counter()-started})
                            owner.calls.append({'call_id':call_id,'request_ref':request_ref,'response_ref':ref,'body':body,'raw':raw.decode('utf-8'),'status':response.status_code,'budget':budget})
                            self.send_response(response.status_code)
                            self.send_header('Content-Type', response.headers.get('content-type','text/event-stream'))
                            self.send_header('Connection', 'close')
                            self.end_headers()
                            self.wfile.write(raw)
                            self.wfile.flush()
                except Exception as exc:
                    try:
                        evidence.record('proxy.error', {'call_id':call_id,'type':type(exc).__name__})
                        self.send_error(502, 'ASUNA_PROVIDER_BOUNDARY_FAILED')
                    except Exception:
                        self.close_connection = True

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return f'http://127.0.0.1:{self.server.server_port}/v1'

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
