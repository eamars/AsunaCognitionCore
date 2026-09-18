from datetime import datetime,timezone
import json
import uuid
from pathlib import Path
from asuna.config import ROOT,load
from asuna.state import Store
from asuna.evidence import Evidence,write_json,sha
from asuna.dsh_lane import DshLane
from asuna.coordinator import Coordinator
from asuna.tasks import TaskService,ToolBroker,Executor
from asuna.audit import render_html

run='M3-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-')+uuid.uuid4().hex[:6]
ev=Evidence(ROOT/'reports'/run)
cfg=load();store=Store(cfg,'asuna_v2_test_'+run.replace('-','_'))
workspace=Path(cfg['workdir'])/run/'task';workspace.mkdir(parents=True)
original=b'Asuna controlled fixture. Keep this original unchanged.\n'
(workspace/'example.txt').write_bytes(original)
service=TaskService(store);broker=ToolBroker(service)
status='FAIL'
try:
    store.migrate();store.seed()
    with DshLane(cfg,store,ev) as character, DshLane(cfg,store,ev,'executor',broker.rows,broker.token) as executor:
        c=Coordinator(store,character)
        ep=c.ingest({'event_id':'copy','scene_id':'dm-a','person_id':'A','text':'请查阅你当前受控任务目录里的 example.txt，保留原件，复制到 copies/example.txt，核实 SHA256 后提交这个副本的模拟回执，做完告诉我。'})
        assert ep['state']=='WAITING_TASK',ep['state']
        task=Executor(service,executor,broker).run(ep['task_id'],workspace)
        assert task['state']=='DONE',task['state']
        assert task['result']['effect_receipts']
        assert (workspace/'example.txt').read_bytes()==original
        assert (workspace/'copies/example.txt').read_bytes()==original
        feedback=service.feedback(task,c)
        assert feedback['state']=='COMMITTED',feedback['state']
        assert all(not call['body'].get('tools') for call in character.proxy.calls)
        assert all('fixture_lookup' in json.dumps(call['body'].get('tools',[])) for call in executor.proxy.calls)
        trace=list(store.db.audit_events.find({}).sort([('stream_id',1),('seq',1)]))
        write_json(ev.root/'trace.json',trace);render_html(trace,ev.root/'trace.html')
        status='PASS'
except Exception as exc:ev.record('probe.error',{'type':type(exc).__name__,'message':str(exc)})
finally:broker.close()
write_json(ev.root/'result.json',{'status':status,'database':store.name,'command':'.venv/Scripts/python.exe tools/probe_executor.py','exit_code':0 if status=='PASS' else 1,'limitations':['one copy task; not L02 ten repetitions','no human cognition scoring']})
print(json.dumps({'run':run,'status':status}));raise SystemExit(0 if status=='PASS' else 1)
