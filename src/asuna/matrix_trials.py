"""L09 repeats the same task under independently scheduled native summaries."""
import copy,json,uuid
from .application import Application
from .context import ContextBuilder
from .experiments import FixtureSelection
from .dsh_lane import DshLane
from .live_trials import setup_work,oracle
from .evidence import Evidence,write_json
from .audit import render_html


def sample(config,evidence,character_count,executor_count,repetition):
    cfg=copy.deepcopy(config)
    cfg['executor']['compact_at_steps']=[3,5,7,9,11] if executor_count else []
    ev=Evidence(evidence.root/f'c{character_count}-e{executor_count}-{repetition}')
    name='matrix-'+uuid.uuid4().hex[:12];work,prompt,before=setup_work(cfg,'L12',name)
    prompt+=' 请分段阅读各个 CSV，检查中间结果，再生成最终报告；原始 CSV 不得改动。'
    result={'character_compactions_target':character_count,'executor_compactions_target':executor_count,'repeat':repetition,'status':'FAIL'}
    try:
        with Application(cfg,ev,'asuna_v2_test_'+name.replace('-','_')) as app:
            app.store.seed();result['database']=app.store.name
            app.coordinator.context=ContextBuilder(app.store,FixtureSelection(app.store,['M02','M07','M08']))
            relationship_before=app.store.head('relationship:A','scene:dm-a')[0]['revision_id']
            for i,text in enumerate(['我回来了，向我打个招呼。','我今天想聊聊安静的爱好，你喜欢什么？','如果暂时不办事，我们还能聊点什么？','等我处理一份核对清单后，再回到闲聊。现在先回应一句。']):
                if i and character_count:app.character.compact('xiaoman:dm-a:1:P1')
                ep=app.router.receive({'event_id':'warm-'+str(i),'scene_id':'dm-a','person_id':'A','text':text})
                if ep['state']!='COMMITTED':raise ValueError('CHARACTER_WARMUP_FAILED')
            ep=app.router.receive({'event_id':'matrix-task','scene_id':'dm-a','person_id':'A','text':prompt})
            if ep['state']!='WAITING_TASK':raise ValueError('CHARACTER_DID_NOT_DELEGATE')
            original=app.store.db.tasks.find_one({'_id':ep['task_id']})
            # Restart the real character process while its accepted task waits.
            app.character.close()
            done=app.executor.run(ep['task_id'],work)
            app.character=app.stack.enter_context(DshLane(cfg,app.store,ev))
            app.coordinator.character=app.character
            feedback=app.service.feedback(done,app.coordinator)
            checked=oracle('L12',work,before,ev,done)
            char_generations=sum(s.get('compaction_generation',0) for s in app.store.db.sessions.find({'lane':'character'}))
            exec_generations=sum(s.get('compaction_generation',0) for s in app.store.db.sessions.find({'lane':'executor'}))
            effects=list(app.store.db.sink_receipts.find({'kind':'simulated_copy_commit'}))
            stable=all(original[k]==done[k] for k in ('_id','intent_revision','policy_epoch','scope_key','requester_id'))
            check=app.router.receive({'event_id':'matrix-recall','scene_id':'dm-a','person_id':'A','text':'那次我没回复，你后来确认的原因是什么？你心里留下的小谜题是否已经向我承诺过？'})
            result.update(status='INCONCLUSIVE' if checked['status']=='PASS' and char_generations==character_count and exec_generations==executor_count and stable and app.store.head('relationship:A','scene:dm-a')[0]['revision_id']==relationship_before and feedback and feedback['state']=='COMMITTED' and check['state']=='COMMITTED' else 'FAIL',actual_character_compactions=char_generations,actual_executor_compactions=exec_generations,task_identity_stable=stable,task_state=done['state'],task_id=done['_id'],effect_receipts=effects,public_messages=app.store.public_messages('dm-a','A'))
            trace=list(app.store.db.audit_events.find({}));write_json(ev.root/'trace.json',trace);render_html(trace,ev.root/'trace.html')
    except Exception as exc:ev.record('matrix.error',{'type':type(exc).__name__,'message':str(exc)})
    write_json(ev.root/'sample.json',result);print(json.dumps({'matrix':[character_count,executor_count,repetition],'status':result['status']}),flush=True)
    return result


def suite(config,evidence,*,repetitions=3,conditions=((0,0),(3,0),(0,5),(3,5))):
    outputs=[sample(config,evidence,c,e,r) for c,e in conditions for r in range(1,repetitions+1)]
    return {'test_id':'L09','status':'FAIL' if any(o['status']=='FAIL' for o in outputs) else 'INCONCLUSIVE','mode':'real_native_independent_compaction_matrix','attempts':len(outputs),'samples':outputs,'limitations':['Natural-language preservation of commitments/interpretations requires independent review.','Task may complete before five scheduled executor summaries; actual count is asserted, never padded with mock summaries.']}
