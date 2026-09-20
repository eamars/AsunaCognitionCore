import json,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import httpx
from asuna.audit import reconcile_calls
from asuna.evidence import Evidence,sha,write_json
from asuna.provider_proxy import ProviderProxy


def test_E22_proxy_timeout_has_terminal_audit(tmp_path):
    observed=[]
    class Upstream(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            body=self.rfile.read(int(self.headers['Content-Length']));observed.append(sha(body))
            if self.path=='/apply-template':value={'prompt':'fixture'}
            elif self.path=='/tokenize':value={'tokens':[1,2,3]}
            else:
                time.sleep(.1);value={'ignored':'too late'}
            data=json.dumps(value).encode()
            try:
                self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
    upstream=ThreadingHTTPServer(('127.0.0.1',0),Upstream)
    thread=threading.Thread(target=upstream.serve_forever,daemon=True);thread.start()
    evidence=Evidence(tmp_path/'audit')
    cfg={'base_url':f'http://127.0.0.1:{upstream.server_port}/v1','model':'local-fixture','max_tokens':64,'sampling':{'temperature':0},'transport_read_timeout_seconds':.01}
    proxy=ProviderProxy(cfg,evidence,'character')
    try:
        with httpx.Client(trust_env=False,timeout=10) as client:
            response=client.post(proxy.url+'/chat/completions',json={'model':cfg['model'],'messages':[{'role':'user','content':'timeout fixture'}]})
        assert response.status_code==200 # local admission only
        assert 'ASUNA_PROVIDER_BOUNDARY_FAILED' in response.text
        assert not proxy.calls
        events=[json.loads(p.read_text(encoding='utf-8')) for p in evidence.root.glob('*.json')]
        assert reconcile_calls(observed,events)=={'requests':3,'responses_or_errors':3,'matched':True}
        error=next(e['payload'] for e in events if e['type']=='provider.error')
        assert error['type']=='ReadTimeout' and error['upstream_submitted'] is True
        assert error['request_ref'] and error['partial_response_utf8']==''
        write_json(tmp_path/'independent-observation.json',{'observed_body_hashes':observed,'join':reconcile_calls(observed,events),'local_admission_status_code':response.status_code,'terminal_error':error['type'],'accepted_model_calls':len(proxy.calls)})
    finally:
        proxy.close();upstream.shutdown();upstream.server_close();thread.join()
