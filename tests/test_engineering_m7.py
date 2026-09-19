import json,subprocess,sys,threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import httpx,pytest
from asuna.config import ROOT
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane,LaneResult
from asuna.evidence import Evidence,LocalHttp,sha
from asuna.audit import reconcile_calls,verify
from test_engineering_m1 import decision,normal,event
from test_engineering_m3 import task_setup


@pytest.mark.parametrize('point',['after_task_persist','after_lane_delivery','after_tool_commit','after_send_before_receipt','before_commit_audit'])
def test_E14_five_actual_process_crash_points(store,point):
    p=subprocess.run([sys.executable,str(ROOT/'tests/crash_matrix_worker.py'),store.name,point],capture_output=True)
    assert p.returncode==77,p.stderr.decode(errors='replace')
    store.recover_commits()
    lane=FakeLane(store,[decision(),LaneResult('回来了。')])
    Coordinator(store,lane).recover()
    assert store.db.sink_receipts.count_documents({})<=1
    if point in ('after_task_persist','after_tool_commit'):
        assert store.db.tasks.count_documents({})==1
        assert store.db.episodes.find_one({'source_event_id':'matrix'})['state']=='WAITING_TASK'
    else:
        assert store.db.episodes.find_one({'source_event_id':'matrix'})['state']=='COMMITTED'
        assert store.db.sink_receipts.count_documents({})==1
    verify(list(store.db.audit_events.find({})))


def test_E12_read_only_source_and_allowed_code_write(store):
    service,task,broker,work=task_setup(store)
    try:
        result=broker.call('s-test','immutable','sandbox_run',{'argv':['python3','-c',"from pathlib import Path;Path('a.txt').write_text('tamper')"]})
        assert result['exit_code']!=0 and (work/'a.txt').read_text()=='controlled original'
        assert broker.call('s-test','write','sandbox_run',{'argv':['python3','-c',"open('new.txt','w').write('allowed')"]})['exit_code']==0
    finally:broker.close()


def test_E22_independent_observer_detects_missing_auxiliary_call(tmp_path):
    observed=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            body=self.rfile.read(int(self.headers['Content-Length']));observed.append(sha(body))
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(b'{"ok":true}')
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    evidence=Evidence(tmp_path/'audit');http=LocalHttp(evidence);url=f'http://127.0.0.1:{server.server_port}'
    try:
        for purpose in ('MONOLOGUE','SPEAK','compaction','repair','embedding.query'):http.request('POST',url,purpose,{'purpose':purpose})
        events=[json.loads(p.read_text(encoding='utf-8')) for p in evidence.root.glob('*.json')]
        assert reconcile_calls(observed,events)['requests']==5
        # Intentional negative against a local stub, not an unaudited real model.
        with httpx.Client(trust_env=False) as raw:raw.post(url,json={'purpose':'deliberately_unaudited_title'})
        with pytest.raises(ValueError,match='COUNT_MISMATCH'):reconcile_calls(observed,events)
    finally:http.client.close();server.shutdown();server.server_close();thread.join()
