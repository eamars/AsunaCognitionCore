"""L10: interleaved production ingress while a real executor task is active."""
import json,re,time,uuid
from concurrent.futures import ThreadPoolExecutor
from .application import Application
from .live_trials import setup_work,oracle
from .evidence import write_json,canonical
from .config import ROOT,BUNDLE
from .audit import render_html


def suite(config,evidence):
    work,prompt,before=setup_work(config,'L02','parallel-'+uuid.uuid4().hex[:12])
    result={'test_id':'L10','status':'FAIL','attempts':1,'mode':'real_interleaved_ingress_and_executor','timeline':[]}
    database='asuna_v2_test_parallel_'+uuid.uuid4().hex[:16];result['database']=database
    try:
        with Application(config,evidence,database) as app,ThreadPoolExecutor(max_workers=1) as pool:
            app.store.seed()
            original=app.router.receive({'event_id':'parallel-task','scene_id':'dm-a','person_id':'A','text':prompt})
            if original['state']!='WAITING_TASK':raise ValueError('CHARACTER_DID_NOT_DELEGATE')
            result['timeline'].append({'kind':'task_start','time_ns':time.time_ns(),'task_id':original['task_id']})
            def execute():
                try:return app.executor.run(original['task_id'],work)
                finally:result['timeline'].append({'kind':'executor_return','time_ns':time.time_ns()})
            future=pool.submit(execute)
            events=[]
            for i in range(5):
                for scene,person in [('g1','A'),('g2','C'),('dm-b','B'),('dm-a','A')]:
                    events.append({'event_id':f'interleaved-{scene}-{i}','scene_id':scene,'person_id':person,'text':f'这是第{i+1}次简短闲聊，先向你打声招呼，不追加任何文件任务。','mentioned':True})
            # Router owns the same fair queue used by the CLI simulator.
            episodes=app.router.batch(events)
            result['timeline'].append({'kind':'scene_batch_return','time_ns':time.time_ns()})
            done=future.result();feedback=app.service.feedback(done,app.coordinator)
            checked=oracle('L02',work,before,evidence,done)
            trace=list(app.store.db.audit_events.find({}).sort([('stream_id',1),('seq',1)]))
            contexts={e['stream_id']:e['payload']['context'] for e in trace if e['type']=='context.prepared'}
            world=json.loads((BUNDLE/'fixtures/world.json').read_text(encoding='utf-8'))
            private={m['scope_key']:m['body_markdown'] for m in world['memories'] if m['id'] in ('M09','M10')}
            canaries={scope:re.search(r'PRIVATE_[A-Za-z0-9_]+',body).group() for scope,body in private.items()}
            violations=[]
            for event in trace:
                if event['type']!='phase.output':continue
                context=contexts.get(event['stream_id']);scope=context['scope_key'] if context else None
                for ref in event['payload'].get('request_refs',[]):
                    if not isinstance(ref,dict):raise ValueError('REQUEST_REFERENCE_NOT_FULLY_QUALIFIED')
                    raw=json.loads((ROOT/ref['artifact_path']).read_text(encoding='utf-8'))['payload']['body_utf8']
                    for forbidden,canary in canaries.items():
                        if scope!=forbidden and canary in raw:violations.append({'episode':event['stream_id'],'forbidden_scope':forbidden,'request':ref})
            # Use the router stream sequence, independent of per-episode order.
            sequence=[e['payload']['scene'] for e in app.store.db.audit_events.find({'stream_id':'router','type':'event.received','payload.event_id':{'$regex':'^interleaved-'}}).sort('seq',1)]
            fair=all(not(sequence[i]==sequence[i+1]==sequence[i+2]) for i in range(len(sequence)-2))
            start=next(e['time_ns'] for e in result['timeline'] if e['kind']=='task_start');finish=next(e['time_ns'] for e in result['timeline'] if e['kind']=='executor_return')
            # Mongo audit timestamps are wall-clock strings; use actual provider
            # evidence timestamps to prove overlapping lane activity.
            actor_during=False
            for path in evidence.root.glob('*provider.request.json'):
                e=json.loads(path.read_text(encoding='utf-8'))
                if e['payload'].get('lane')=='character' and start<e['time_ns']<finish:actor_during=True
            result.update(task_status=checked['status'],feedback_state=feedback['state'] if feedback else None,queue_sequence=sequence,actor_request_during_executor=actor_during,scope_violations=violations,episode_states=[e['state'] for e in episodes],public_messages=list(app.store.db.messages.find({'direction':'outbound','delivery_state':'DELIVERED'})))
            result['status']='PASS' if checked['status']=='PASS' and actor_during and fair and not violations and feedback and feedback['scene_id']=='dm-a' and feedback['task_id']==original['task_id'] and all(e['state']=='COMMITTED' for e in episodes) else 'FAIL'
            write_json(evidence.root/'trace.json',trace);render_html(trace,evidence.root/'trace.html')
    except Exception as exc:evidence.record('parallel.error',{'type':type(exc).__name__,'message':str(exc)})
    result['limitations']=['Synthetic private canary scope check; arbitrary semantic disclosure still requires human review.','Ingress queue is synchronous per actor lane; executor runs concurrently in its separate native lane.']
    return result
