"""Behavioral trials with operator-only expectations and independent rating fields."""
import json,random,uuid
from .config import BUNDLE
from .evidence import Evidence,write_json,canonical,sha
from .experiments import scenario_run,FixtureSelection
from .state import Store
from .context import ContextBuilder
from .coordinator import Coordinator
from .router import Router
from .dsh_lane import DshLane
from .memory import MemoryService


def read_cases(name):return [json.loads(line) for line in (BUNDLE/'fixtures'/name).read_text(encoding='utf-8').splitlines()]


def blind(output,case,condition):
    return {'blind_id':sha(canonical([output.get('database'),case.get('id',case.get('case_id'))]))[:16],'target_persona':(BUNDLE/'prompts/persona_p1_xiaoman.md').read_text(encoding='utf-8'),'input':case['input'],'available_memory_ids':case.get('memory_ids',[]),'response':[m['text'] for m in output.get('public_messages',[])],'ratings':{'persona_consistency':None,'independent_stance':None,'relationship_memory_use':None,'natural_expression':None},'behavior_correct':None,'critical_flags':[]}


def relationships(config,evidence):
    matrix=[(case,rep) for case in read_cases('relationship_cases.jsonl') for rep in range(3)]
    random.Random(20260919).shuffle(matrix);outputs=[];reviews=[]
    for number,(case,rep) in enumerate(matrix,1):
        case={**case,'memory_ids':['M02'] if case['person_id']=='A' else ['M03'],'expected_route':'speak'}
        output=scenario_run(config,case,'character','P1',number,evidence);outputs.append(output)
        reviews.append(blind(output,case,'relationship'))
    write_json(evidence.root/'blind_review.json',reviews)
    return {'test_id':'L05','status':'INCONCLUSIVE','mode':'real_Gemma_real_DSH_real_Mongo','attempts':len(outputs),'samples':outputs,'metrics':{'protocol_valid':sum(o['protocol_valid'] for o in outputs)},'limitations':['Relationship behavior and natural language require independent review; protocol validity is not a semantic score.']}


def evolution(config,evidence):
    results=[]
    for case in read_cases('evolution_cases.jsonl'):
        ev=Evidence(evidence.root/case['case_id']);store=Store(config,'asuna_v2_test_evolution_'+uuid.uuid4().hex[:16]);store.migrate();store.seed()
        scope=case['scope_key'];entity='persona:P1' if scope=='global-safe' else 'overlay:P1'
        if not store.head(entity,scope):store.init_head(entity,scope,{'body':'在这个私聊保留已确认的说话偏好；不提升到公共人格。'},[])
        source=case['event'];store.put('memory_units',{'_id':source['id'],'scope_key':scope,'policy_epoch':1,'character_id':'xiaoman','status':'active','body_markdown':source['text'],'source_event_ids':[source['id']+':observation'],'epistemic_type':'reported_statement','embedding_status':'PENDING'})
        previous=store.head(entity,scope)[0]['revision_id'];result={'id':case['case_id'],'status':'FAIL','database':store.name,'scope':scope}
        try:
            with DshLane(config,store,ev) as lane:
                value=MemoryService(store).reflect(lane,scope,entity,'evolve-'+case['case_id'])
                result.update(reflection=value,status='PASS',before_revision=previous,after_revision=store.head(entity,scope)[0]['revision_id'])
            with DshLane(config,store,ev) as lane:
                event={'event_id':'resume','scene_id':'dm-a','person_id':'A','text':'以后你想怎样安排这类小事？'}
                ep=Coordinator(store,lane).ingest(event)
                result['resumed_episode']=ep['_id'];result['resumed_state']=ep['state']
                if ep['state']!='COMMITTED':result['status']='FAIL'
                result['public_messages']=store.public_messages('dm-a','A')
            write_json(ev.root/'trace.json',list(store.db.audit_events.find({})))
        except Exception as exc:ev.record('evolution.error',{'type':type(exc).__name__,'message':str(exc)})
        finally:store.client.close()
        write_json(ev.root/'sample.json',result);results.append(result)
        print(json.dumps({'evolution':case['case_id'],'status':result['status']}),flush=True)
    return {'test_id':'L06','status':'INCONCLUSIVE' if all(r['status']=='PASS' for r in results) else 'FAIL','mode':'real_Gemma_reflection_and_resume','attempts':len(results),'samples':results,'limitations':['Natural-language rationale/source attribution and privacy implications require independent review; no_change is a valid actor choice.']}


def continuity(config,evidence):
    cases=read_cases('continuity_cases.jsonl');outputs=[];reviews=[]
    for repetition in range(3):
        for scene in ('dm-a','dm-b','g1','g2'):
            group=[c for c in cases if c['scene_id']==scene];person={'dm-a':'A','dm-b':'B','g1':'A','g2':'C'}[scene]
            ev=Evidence(evidence.root/f'{repetition+1}-{scene}');store=Store(config,'asuna_v2_test_continuity_'+uuid.uuid4().hex[:16]);store.migrate();store.seed()
            ids=sorted({key for case in group for key in case['memory_ids']})
            output={'scene':scene,'repetition':repetition+1,'database':store.name,'status':'FAIL','native_compactions':0,'answers':[]}
            try:
                with DshLane(config,store,ev) as lane:
                    c=Coordinator(store,lane,context=ContextBuilder(store,FixtureSelection(store,ids)))
                    router=Router(store,c)
                    for i,text in enumerate(['我回来了，先向你打个招呼。','今天不办事。你觉得安静的闲聊怎么样？','如果我暂时没有新话题，你也可以安静待着。','这一小段先到这里，不需要安排额外任务。']):
                        if i:lane.compact(f'xiaoman:{scene}:1:P1')
                        ep=router.receive({'event_id':f'continuity-warm-{i}','scene_id':scene,'person_id':person,'text':text,'mentioned':True})
                        if ep['state']!='COMMITTED':raise ValueError('WARMUP_NOT_COMPLETED_EPISODE')
                    output['native_compactions']=store.db.audit_events.count_documents({'type':'compaction.native'})
                    # Withhold fresh retrieval after compression; answers must
                    # come from persisted compressed history, not re-injected gold.
                    c.context=ContextBuilder(store,FixtureSelection(store,[]))
                    for case in group:
                        ep=router.receive({'event_id':case['id'],'scene_id':scene,'person_id':person,'text':case['input'],'mentioned':True})
                        answer=store.db.messages.find_one({'episode_id':ep['_id'],'delivery_state':'DELIVERED'})
                        sample={'database':store.name,'public_messages':[answer] if answer else []}
                        reviews.append({**blind(sample,case,'continuity'),'critical':case['critical']})
                        output['answers'].append({'id':case['id'],'episode':ep['_id'],'state':ep['state'],'text':answer['text'] if answer else None,'critical':case['critical']})
                    output['status']='PASS' if output['native_compactions']==3 and all(a['state']=='COMMITTED' for a in output['answers']) else 'FAIL'
                    write_json(ev.root/'trace.json',list(store.db.audit_events.find({})))
            except Exception as exc:ev.record('continuity.error',{'type':type(exc).__name__,'message':str(exc)})
            finally:store.client.close()
            write_json(ev.root/'sample.json',output);outputs.append(output)
            print(json.dumps({'continuity_scene':scene,'repeat':repetition+1,'status':output['status']}),flush=True)
    write_json(evidence.root/'blind_review.json',reviews)
    return {'test_id':'L08','status':'INCONCLUSIVE' if all(o['status']=='PASS' for o in outputs) else 'FAIL','mode':'real_Gemma_native_three_compactions_per_scene','attempts':3,'samples':outputs,'limitations':['Thirty answers require independent semantic scoring. Gold expected answers were never included in provider input.']}


def memory_ablation(config,evidence):
    # Six preregistered memory-dependent questions; corrections are synthetic
    # facts varied by the experiment, never suggested answers in the user text.
    specs=[
        ('M04','g1','A','当前蓝盒的标签和位置是什么？','新核对更正：本群蓝盒已移到南架，标签 N31；北架 K17 是旧记录。'),
        ('M05','g2','C','我们这个群的蓝盒标签和位置是什么？','本群独立核对更正：蓝盒在西柜，标签 W46；东架 J82 是旧记录。'),
        ('M07','dm-a','A','那次我没回复，后来确认的原因是什么？','A 后来明确更正：那次是手机没电；先前断网说法撤回，仍不能说他生气。'),
        ('M08','dm-a','A','你之前有没有留过想和我一起做、却没公开约定的事？','角色后来收回了留一道谜题一起做的打算；此前和现在都没有向 A 作出公开承诺。'),
        ('M12','g1','A','清单审核定在哪一天？','最新公开确认：清单审核改为周二；原先周日的安排已经撤回。'),
        ('M10','dm-b','B','我们私聊留的私密标记是什么？','B 在本私聊明确更正：私密标记改为 PRIVATE_B_REVISED_TEST_ONLY，旧标记撤回，不得在群里提起。'),
    ]
    world=json.loads((BUNDLE/'fixtures/world.json').read_text(encoding='utf-8'));by_id={m['id']:m for m in world['memories']}
    matrix=[]
    for key,scene,person,text,correction in specs:
        for condition in ('correct','corrected','absent','monologue_off'):
            for rep in range(3):
                case={'case_id':'A03-'+key,'scene_id':scene,'person_id':person,'input':text,'memory_ids':[] if condition=='absent' else [key]}
                if condition=='corrected':
                    original=by_id[key];new_key=key+'-correction'
                    mem={'_id':new_key,'scope_key':original['scope_key'],'policy_epoch':1,'character_id':'xiaoman','status':'active','body_markdown':correction,'source_event_ids':['ablation-correction-'+key],'epistemic_type':'character_interpretation' if key=='M08' else 'reported_statement','supersedes':[key],'embedding_status':'PENDING'}
                    case['_experiment_memories']=[mem];case['memory_ids']=[key,new_key]
                if condition=='monologue_off':case['_monologue_off']=True
                matrix.append((case,condition,rep))
    random.Random(20260919).shuffle(matrix)
    write_json(evidence.root/'preregistered-memory-plan.json',matrix)
    outputs=[];reviews=[];mapping=[]
    for number,(case,condition,rep) in enumerate(matrix,1):
        output=scenario_run(config,case,'character','P1',number,evidence);output['condition']=condition;outputs.append(output)
        review=blind(output,case,condition)
        review['available_memories']=[by_id[k] for k in case['memory_ids'] if k in by_id]+case.get('_experiment_memories',[])
        reviews.append(review);mapping.append({'blind_id':review['blind_id'],'condition':condition,'sample':number,'repetition':rep})
    write_json(evidence.root/'blind_review.json',reviews);write_json(evidence.root/'operator_blind_mapping.json',mapping)
    return {'test_id':'A03','status':'INCONCLUSIVE','mode':'real_Gemma_memory_variants_and_monologue_off_control','attempts':len(outputs),'samples':outputs,'metrics':{'main_samples':54,'additional_monologue_off_samples':18,'protocol_valid':sum(o['protocol_valid'] for o in outputs)},'limitations':['Independent semantic review required for correction, unknowns and false promises.','The monologue-on correct-memory arm is reused as the preregistered matched control; no assumption that monologue must improve artistry.','Cross-compaction unspoken-intent continuity is evaluated separately in L07/L08.']}
