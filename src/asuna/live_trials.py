"""File-task acceptance and a separately labelled Qwen-only capability control."""
import copy,difflib,json,shutil,uuid
from pathlib import Path
from .config import ROOT,BUNDLE
from .evidence import Evidence,sha,write_json
from .application import Application
from .state import Store
from .sandbox import Sandbox
from .dsh_lane import DshLane
from .tasks import TaskService,ToolBroker,Executor
from .audit import render_html


def source_hashes(work):return {p.relative_to(work).as_posix():sha(p.read_bytes()) for p in sorted(work.rglob('*')) if p.is_file()}


def setup_work(config,test,name):
    work=Path(config['workdir'])/name/'task';work.mkdir(parents=True)
    if test=='L02':
        (work/'example.txt').write_text('Asuna isolated copy task '+name+'\n原件必须保留。\n',encoding='utf-8')
        prompt='请查阅你当前受控任务目录里的 example.txt，保留原件，复制到 copies/example.txt，核实 SHA256 后提交这个副本的模拟回执，做完告诉我。'
    else:
        folder=BUNDLE/'fixtures'/('code_task' if test=='L03' else 'reconcile_task')
        for p in folder.iterdir():
            if p.is_file():shutil.copyfile(p,work/p.name)
        prompt='请完成你当前受控任务目录 START_HERE.md 中的任务，实际读取文件和运行检查，保留原始任务与测试文件，完成后给我准确结果。'
        if test=='L03':prompt='这是原项目的隔离工作副本。请读取 START_HERE.md，并按其中要求只修改本工作目录的 stats.py，运行可见测试；START_HERE.md 和 test_visible.py 只读，原始任务包不在此目录。修好后告诉我。'
    return work,prompt,source_hashes(work)


def oracle(test,work,before,evidence,task):
    result={'source_hashes_before':before,'source_hashes_after':source_hashes(work),'task_state':task.get('state') if task else None,'status':'FAIL'}
    unchanged=all((work/key).is_file() and sha((work/key).read_bytes())==value for key,value in before.items() if not(test=='L03' and key=='stats.py'))
    result['protected_inputs_unchanged']=unchanged
    if test=='L02':
        correct=(work/'copies/example.txt').exists() and sha((work/'copies/example.txt').read_bytes())==before['example.txt']
        result['copy_correct']=correct;result['effect_receipts']=(task or {}).get('result',{}).get('effect_receipts',[])
        result['status']='PASS' if correct and unchanged and result['effect_receipts'] and task['state']=='DONE' else 'FAIL'
    elif test=='L03':
        # Untrusted generated code and the hidden oracle execute together only
        # in a separate namespace never mounted in the executor's workspace.
        private_work=work.parent/'operator-oracle';private_work.mkdir()
        shutil.copyfile(work/'stats.py',private_work/'stats.py')
        shutil.copyfile(BUNDLE/'fixtures/oracles/test_stats_hidden.py',private_work/'test_hidden.py')
        hidden=Sandbox(private_work).run(['python3','-m','unittest','test_hidden.py'])
        visible=Sandbox(work).run(['python3','-m','unittest','test_visible.py'])
        result.update(hidden_oracle=hidden,visible_checks=visible)
        old=(BUNDLE/'fixtures/code_task/stats.py').read_text(encoding='utf-8').splitlines(keepends=True)
        new=(work/'stats.py').read_text(encoding='utf-8').splitlines(keepends=True)
        (evidence.root/'stats.diff').write_text(''.join(difflib.unified_diff(old,new,fromfile='input/stats.py',tofile='output/stats.py')),encoding='utf-8')
        (evidence.root/'stats.py.txt').write_text(''.join(new),encoding='utf-8')
        result['status']='PASS' if unchanged and hidden['exit_code']==0 and visible['exit_code']==0 and task and task['state']=='DONE' else 'FAIL'
    else:
        expected=json.loads((BUNDLE/'fixtures/oracles/reconcile_expected.json').read_text(encoding='utf-8'))
        actual=json.loads((work/'report.json').read_text(encoding='utf-8')) if (work/'report.json').exists() else {}
        result['report']=actual
        # source_files may be either the required count plus a hash map, or
        # twelve filename/hash objects; the count and each hash must agree.
        files=actual.get('source_files');count=len(files) if isinstance(files,(list,dict)) else files
        serialized=json.dumps(actual,ensure_ascii=False)
        hashes=all(key in serialized and value in serialized for key,value in before.items() if key.endswith('.csv'))
        correct=all(actual.get(k)==expected[k] for k in ('unique_posted_count','total_amount_cents')) and count==12 and hashes
        result.update(exact_oracle=correct,source_hashes_reported=hashes)
        result['status']='PASS' if correct and unchanged and task and task['state']=='DONE' else 'FAIL'
    write_json(evidence.root/'oracle.json',result)
    return result


def run_primary(config,test,number,evidence):
    config=copy.deepcopy(config)
    if test=='L12':config['executor']['compact_at_steps']=[4]
    ev=Evidence(evidence.root/f'task-{number:02d}');name=f'{test}-{uuid.uuid4().hex[:16]}'
    work,prompt,before=setup_work(config,test,name);database='asuna_v2_test_'+name.replace('-','_')
    output={'number':number,'database':database,'status':'FAIL','mode':'Gemma_intent_Qwen_tools_Gemma_feedback'};frozen=None
    try:
        with Application(config,ev,database) as app:
            app.store.seed()
            if test=='L12':app.service.inject_read_failures=1
            # Actual production route; no expected values or oracle mounted.
            ep=app.router.receive({'event_id':'input','scene_id':'dm-a','person_id':'A','text':prompt})
            if ep['state']!='WAITING_TASK':raise ValueError('CHARACTER_DID_NOT_DELEGATE')
            frozen=app.store.db.tasks.find_one({'_id':ep['task_id']})
            done=app.executor.run(ep['task_id'],work)
            feedback=app.service.feedback(done,app.coordinator)
            output['feedback_state']=feedback['state'] if feedback else None
            checked=oracle(test,work,before,ev,done)
            output.update(status=checked['status'],task_state=done['state'],public_messages=app.store.public_messages('dm-a','A'),task_id=done['_id'])
            if test=='L12':
                output['native_compactions']=app.store.db.audit_events.count_documents({'type':'compaction.native'})
                output['injected_read_failures']=app.store.db.audit_events.count_documents({'type':'fault.injected'})
                if not output['native_compactions'] or not output['injected_read_failures']:output['status']='FAIL'
            trace=list(app.store.db.audit_events.find({}).sort([('stream_id',1),('seq',1)]))
            write_json(ev.root/'trace.json',trace);render_html(trace,ev.root/'trace.html')
    except Exception as exc:
        output['error_type']=type(exc).__name__;ev.record('task.error',{'type':type(exc).__name__,'message':str(exc)})
    write_json(ev.root/'sample.json',output)
    print(json.dumps({'task':number,'test':test,'status':output['status']}),flush=True)
    return output,frozen,prompt,before,work


def run_control(config,test,number,evidence,frozen,prompt,original_work):
    ev=Evidence(evidence.root/f'control-{number:02d}');name=f'control-{test}-{uuid.uuid4().hex[:12]}'
    work,_,before=setup_work(config,test,name)
    if test=='L02':
        shutil.copyfile(original_work/'example.txt',work/'example.txt');before=source_hashes(work)
    store=Store(config,'asuna_v2_test_'+name.replace('-','_'));store.migrate();store.seed()
    output={'number':number,'status':'FAIL','database':store.name,'mode':'Qwen_only_frozen_same_task_no_character_calls'}
    service=TaskService(store);broker=ToolBroker(service)
    try:
        if not frozen:raise ValueError('NO_FROZEN_INTENT_FOR_MATCHED_CONTROL')
        task={**frozen,'state':'READY','fencing_token':0,'tool_steps':0}
        source=frozen['raw_input_refs'][0]
        store.put('messages',{'_id':source,'scope_key':task['scope_key'],'text':prompt})
        # Seed persona IDs are deterministic content hashes, but resolve the
        # corresponding revision in this isolated control database explicitly.
        task['persona_revision']=store.head('persona:P1','global-safe')[0]['revision_id']
        store.put('tasks',task)
        with DshLane(config,store,ev,'executor',broker.rows,broker.token) as lane:
            done=Executor(service,lane,broker).run(task['_id'],work)
            output['status']=oracle(test,work,before,ev,done)['status']
    except Exception as exc:output['error_type']=type(exc).__name__;ev.record('control.error',{'type':type(exc).__name__,'message':str(exc)})
    finally:broker.close();store.client.close()
    write_json(ev.root/'sample.json',output);return output


def suite(config,test,evidence,repetitions=None,controls=True):
    repetitions=repetitions or (10 if test=='L02' else 5);outputs=[];comparisons=[]
    for number in range(1,repetitions+1):
        output,frozen,prompt,before,work=run_primary(config,test,number,evidence);outputs.append(output)
        if controls:comparisons.append(run_control(config,test,number,evidence,frozen,prompt,work))
    successes=sum(o['status']=='PASS' for o in outputs);control_successes=sum(o['status']=='PASS' for o in comparisons)
    threshold=9 if test=='L02' else 4
    limitations=['Public response factual quality still requires independent review.']
    status='PASS' if successes>=threshold and repetitions==(10 if test=='L02' else 5) else 'FAIL'
    return {'test_id':test,'status':status,'mode':'real_models_real_DSH_real_sandbox_real_Mongo','attempts':repetitions,'samples':outputs,'controls':comparisons,'metrics':{'successes':successes,'control_successes':control_successes,'bridge_degradation':bool(comparisons and control_successes-successes>1)},'limitations':limitations}
