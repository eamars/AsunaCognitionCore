"""Actual DSH HTTP stack queued >300s, local deterministic upstream; no model claim."""
import json,sys,threading,time,uuid
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from asuna.config import ROOT,BUNDLE,load
from asuna.evidence import Evidence,write_json
from asuna.experiments import freeze
from asuna.state import Store
from asuna.queue import EndpointLock
from asuna.dsh_lane import DshLane

class Upstream(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length','0')))
        if self.path=='/apply-template':data=json.dumps({'prompt':'transport probe'}).encode();kind='application/json'
        elif self.path=='/tokenize':data=json.dumps({'tokens':[1,2,3]}).encode();kind='application/json'
        else:
            data=('data: '+json.dumps({'id':'probe','object':'chat.completion.chunk','created':0,'model':'transport-fixture','choices':[{'index':0,'delta':{'role':'assistant','content':'LOCAL_TRANSPORT_FIXTURE'},'finish_reason':None}]})+'\n\ndata: '+json.dumps({'id':'probe','object':'chat.completion.chunk','created':0,'model':'transport-fixture','choices':[{'index':0,'delta':{},'finish_reason':'stop'}],'usage':{'prompt_tokens':3,'completion_tokens':2,'total_tokens':5}})+'\n\ndata: [DONE]\n\n').encode();kind='text/event-stream'
        self.send_response(200);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)

server=ThreadingHTTPServer(('127.0.0.1',0),Upstream);threading.Thread(target=server.serve_forever,daemon=True).start()
ev=Evidence(ROOT/'reports'/('queue-header-probe-'+uuid.uuid4().hex[:10]));cfg=load();cfg['character']['base_url']=f'http://127.0.0.1:{server.server_port}/v1'
freeze(cfg,BUNDLE/'fixtures/acceptance_cases.json',ev,'PROBE-DSH-queued-headers')
write_json(ev.root/'probe-plan.json',{'queue_hold_seconds':430,'minimum_measured_queue_seconds':400,'boundary':'actual installed DSH pi-ai/OpenAI HTTP transport, including body inactivity','substituted':'local deterministic upstream and tokenizer, not Gemma','required':'native stop and unchanged durable output after >400 seconds queue wait; real SSE keepalive comments are not model content','previous_probe_limit':'303s may finish before the approximately 305s native body-inactivity timer fires; it did not exclude the observed live failure.'})
store=Store(cfg,'asuna_v2_test_headers_'+uuid.uuid4().hex[:14]);store.migrate();store.seed();status='FAIL';held=threading.Event();release=threading.Event()
def occupy():
    with EndpointLock(cfg['character']['base_url']):held.set();release.wait(430)
worker=threading.Thread(target=occupy);worker.start();held.wait()
try:
    with DshLane(cfg,store,ev) as lane:
        system='This is a local deterministic HTTP transport fixture. It checks the installed DSH client boundary, not persona adherence or real model capability. Return the upstream fixture unchanged.'
        started=time.monotonic();value=lane.generate('header-transport','header-op','MONOLOGUE','probe transport',system)
        elapsed=time.monotonic()-started
        assert elapsed>400 and value.finish_reason=='stop' and value.content=='LOCAL_TRANSPORT_FIXTURE'
        assert len(lane.proxy.calls)==1 and lane.proxy.calls[-1]['status']==200
        response=json.loads((ev.root/lane.proxy.calls[-1]['response_ref']).read_text(encoding='utf-8'))['payload']
        beats=list(ev.root.glob('*proxy.keepalive.json'))
        assert response['queue_seconds']>400 and len(beats)>=26
        assert 'ASUNA_LOCAL_TRANSPORT_WAITING' not in lane.proxy.calls[-1]['raw']
        ev.record('transport.checked',{'elapsed_seconds':elapsed,'actual_queue_seconds':response['queue_seconds'],'native_finish':value.finish_reason,'content':value.content,'keepalives':len(beats),'upstream_generation_calls':len(lane.proxy.calls),'response_unchanged':True})
    status='PASS'
except Exception as exc:ev.record('probe.error',{'type':type(exc).__name__,'message':str(exc)})
finally:release.set();worker.join();server.shutdown();server.server_close();store.client.close()
code=0 if status=='PASS' else 1
write_json(ev.root/'result.json',{'test_id':'PROBE-DSH-queued-headers','status':status,'mode':'actual_DSH_transport_deterministic_loopback_upstream','commands':[{'argv':[sys.executable,*sys.argv],'exit_code':code}],'limitations':['This is HTTP transport evidence only; real model quality and long context must still be evaluated separately.']});print(json.dumps({'run':ev.root.name,'status':status}),flush=True);raise SystemExit(code)
