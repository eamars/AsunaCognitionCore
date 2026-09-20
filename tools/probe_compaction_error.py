"""Exercise real DSH pre-step rejection and durable causal error receipts."""
import json,sys,threading,uuid
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from asuna.config import ROOT,BUNDLE,load
from asuna.evidence import Evidence,write_json
from asuna.experiments import freeze
from asuna.state import Store
from asuna.dsh_lane import DshLane

class Upstream(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
        if self.path=='/apply-template':data=json.dumps({'prompt':'fixture'}).encode();kind='application/json'
        elif self.path=='/tokenize':data=json.dumps({'tokens':[1,2,3]}).encode();kind='application/json'
        else:
            is_summary=str(body['messages'][-1]['content']).startswith('ASUNA_COMPACTION_V1\n')
            content='Oversized deterministic summary. '*1000 if is_summary else 'tiny'
            frames=[{'id':'fixture','object':'chat.completion.chunk','created':0,'model':'fixture','choices':[{'index':0,'delta':{'role':'assistant','content':content},'finish_reason':None}]},
                    {'id':'fixture','object':'chat.completion.chunk','created':0,'model':'fixture','choices':[{'index':0,'delta':{},'finish_reason':'stop'}]}]
            data=(''.join('data: '+json.dumps(v)+'\n\n' for v in frames)+'data: [DONE]\n\n').encode();kind='text/event-stream'
        self.send_response(200);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)

ev=Evidence(ROOT/'reports'/('compaction-error-probe-'+uuid.uuid4().hex[:12]));cfg=load()
server=ThreadingHTTPServer(('127.0.0.1',0),Upstream);threading.Thread(target=server.serve_forever,daemon=True).start()
cfg['character']['base_url']=f'http://127.0.0.1:{server.server_port}/v1'
freeze(cfg,BUNDLE/'fixtures/acceptance_cases.json',ev,'PROBE-NATIVE-COMPACTION-ERROR')
write_json(ev.root/'plan.json',{'boundary':'installed DSH engine, production bridge, real Mongo persistence','substitution':'deterministic loopback model output; no real-model quality claim','required':['native rejects summary larger than history','exact accepted message yields error with empty output and native cause','failed summary does not become successful compaction','replay returns same error without another provider call']})
store=Store(cfg,'asuna_v2_test_cerror_'+uuid.uuid4().hex[:14]);store.migrate();status='FAIL'
system='This deterministic transport fixture tests native error provenance. It does not assess model quality or personality. Return only the controlled fixture response.'
try:
    with DshLane(cfg,store,ev) as lane:
        first=lane.generate('tiny-history','initial','SPEAK','tiny',system)
        assert first.finish_reason=='stop'
        lane.compact('tiny-history')
        value=lane.generate('tiny-history','rejected-summary','SPEAK','continue',system)
        assert value.finish_reason=='error' and value.content=='' and not value.reasoning
        receipts=[json.loads(p.read_text(encoding='utf-8'))['payload'] for p in ev.root.glob('*lane.receipt.json')]
        receipt=next(r for r in receipts if r['operation']=='rejected-summary');body=receipt['body']
        assert receipt['status_code']==200 and body['message_admitted_to_surface'] is False
        assert 'summary is not smaller' in body['native_reason']['error']['message']
        accepted=body['events'][0]
        assert accepted['type']=='agent/inbox/spliced' and accepted['data']['inserted'][0]['id']==body['message_id']
        assert not body['compactions'] and not list(store.db.audit_events.find({'stream_id':'rejected-summary','type':'compaction.native'}))
        count=len(lane.proxy.calls)
        replay=lane.generate('tiny-history','rejected-summary','SPEAK','continue',system)
        assert replay==value and len(lane.proxy.calls)==count==2
        ev.record('causal_error.checked',{'receipt_message_id':body['message_id'],'native_reason':body['native_reason'],'empty_output':True,'failed_compaction_not_applied':True,'replay_without_model_call':True})
    status='PASS'
except Exception as exc:ev.record('probe.error',{'type':type(exc).__name__,'message':str(exc)})
finally:server.shutdown();server.server_close();store.client.close()
code=int(status!='PASS');write_json(ev.root/'result.json',{'test_id':'PROBE-NATIVE-COMPACTION-ERROR','status':status,'commands':[{'argv':[sys.executable,*sys.argv],'exit_code':code}],'limitations':['Deterministic model substitute; actual DSH summary-size guard and adapter persistence are exercised.']});print(json.dumps({'run':ev.root.name,'status':status}),flush=True);raise SystemExit(code)
