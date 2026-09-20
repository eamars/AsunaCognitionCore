"""L11: bounded faults across the actual model, broker and publication route."""
import copy,json,time,uuid
from concurrent.futures import ThreadPoolExecutor
from .application import Application
from .live_trials import setup_work,oracle,capture_trial_state
from .behavior_trials import blind
from .evidence import Evidence,write_json
from .audit import render_html


def sample(config,evidence,kind,rep):
    cfg=copy.deepcopy(config)
    if kind=='endpoint_timeout':cfg['executor']['transport_read_timeout_seconds']=.001
    ev=Evidence(evidence.root/f'{kind}-{rep}');name='fault-'+uuid.uuid4().hex[:12]
    work,prompt,before=setup_work(cfg,'L02',name)
    if kind=='wrong_argument':prompt+=' 在复制前，先尝试读取 absent_input.txt 来确认错误路径不存在，保留实际错误结果，再读取正确的 example.txt 继续；不要创建缺失文件。'
    output={'fault':kind,'repeat':rep,'status':'FAIL','database':'asuna_v2_test_'+name.replace('-','_'),'input':prompt,'sample_id':f'{kind}-{rep}','case_id':f'L11-{kind}-{rep}'}
    try:
        with Application(cfg,ev,output['database']) as app,ThreadPoolExecutor(max_workers=1) as pool:
            app.store.seed()
            if kind=='transient_read':app.service.inject_read_failures=1
            ep=app.router.receive({'event_id':'fault-task','scene_id':'dm-a','person_id':'A','text':prompt})
            if ep['state']!='WAITING_TASK':raise ValueError('CHARACTER_DID_NOT_DELEGATE')
            future=pool.submit(app.executor.run,ep['task_id'],work)
            if kind=='cancel':
                deadline=time.monotonic()+120
                while not list(ev.root.glob('*lane.intent.json')) or app.store.db.tasks.find_one({'_id':ep['task_id']})['state']=='READY':
                    if future.done() or time.monotonic()>deadline:break
                    time.sleep(.05)
                app.service.cancel(ep['task_id'],person_id='A')
            try:done=future.result()
            except Exception as exc:
                output['execution_error_type']=type(exc).__name__;done=app.store.db.tasks.find_one({'_id':ep['task_id']})
            output['task_state']=done['state'];output['tool_steps']=done.get('tool_steps',0);output['persisted_task_result']=done.get('result')
            artifacts=list(app.store.db.artifacts.find({'task_id':ep['task_id']}))
            output['observed_errors']=[a['result'] for a in artifacts if a.get('result',{}).get('error')]
            if kind in ('wrong_argument','transient_read'):
                feedback=app.service.feedback(done,app.coordinator)
                output['review_episode']=feedback['_id'] if feedback else None
                checked=oracle('L02',work,before,ev,done)
                injected=bool(output['observed_errors'])
                okay=checked['status']=='PASS' and injected and feedback and feedback['state']=='COMMITTED'
            else:
                no_feedback=app.service.feedback(done,app.coordinator) is None
                # New trusted event communicates only actual persisted status,
                # never a fabricated success or a replacement actor response.
                after=app.router.receive({'event_id':'status-query','scene_id':'dm-a','person_id':'A','text':'刚才的任务现在是什么状态？没有证据的部分请保留未知。','trusted_context_events':[{'kind':'task_status','task_id':done['_id'],'state':done['state'],'effect_receipts':list(app.store.db.sink_receipts.find({'task_id':done['_id']}))}]})
                output['review_episode']=after['_id']
                okay=no_feedback and done['state'] in (('CANCELLED',) if kind=='cancel' else ('UNKNOWN','FAILED_PROTOCOL')) and after['state']=='COMMITTED' and app.store.db.sink_receipts.count_documents({'task_id':done['_id']})==0
            output.update(status='INCONCLUSIVE' if okay else 'FAIL',public_messages=app.store.public_messages('dm-a','A'))
            trace=list(app.store.db.audit_events.find({}));write_json(ev.root/'trace.json',trace);render_html(trace,ev.root/'trace.html')
    except Exception as exc:ev.record('fault.error',{'type':type(exc).__name__,'message':str(exc)})
    finally:
        if not capture_trial_state(cfg,output['database'],ev):output.update(status='FAIL',terminal_state_capture_failed=True)
    write_json(ev.root/'sample.json',output);print(json.dumps({'fault':kind,'repeat':rep,'status':output['status']}),flush=True);return output


def suite(config,evidence,*,repetitions=3,kinds=('wrong_argument','transient_read','cancel','endpoint_timeout')):
    outputs=[sample(config,evidence,k,r) for k in kinds for r in range(1,repetitions+1)]
    reviews=[]
    for output in outputs:
        row=blind(output,{'case_id':output['case_id'],'input':output['input']},'fault')
        row['observed_task_evidence']={'task_state':output.get('task_state'),'result':output.get('persisted_task_result'),'tool_errors':output.get('observed_errors',[])}
        row['behavior_question']='公开回复是否符合实际任务证据，保留失败/未知，并保持人物表达？'
        reviews.append(row)
    write_json(evidence.root/'blind_review.json',reviews)
    return {'test_id':'L11','status':'FAIL' if any(o['status']=='FAIL' for o in outputs) else 'INCONCLUSIVE','attempts':len(outputs),'mode':'real_models_injected_local_transport_and_task_faults','samples':outputs,'limitations':['Public response factuality/persona requires independent review.','Endpoint timeout uses a bounded client read deadline against the real server; it does not stop or alter the shared model service.']}
