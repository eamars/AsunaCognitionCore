import json,uuid
from .state import Store
from .evidence import Evidence,write_json,sha
from .dsh_lane import DshLane
from .coordinator import Coordinator
from .context import ContextBuilder
from .retrieval import Retrieval
from .behavior_trials import blind


def suite(config,evidence):
    store=Store(config,'asuna_v2_test_L07_'+uuid.uuid4().hex[:16]);store.migrate();store.seed()
    r=Retrieval(store,evidence);output={'test_id':'L07','status':'FAIL','attempts':1,'database':store.name,'mode':'real_Gemma_private_monologue_native_compaction_new_epoch_vector_retrieval'}
    try:
        r.index_pending();assert r.ensure_index()
        with DshLane(config,store,evidence) as lane:
            c=Coordinator(store,lane,context=ContextBuilder(store,r))
            ep=c.ingest({'event_id':'private-intention','scene_id':'dm-a','person_id':'A','text':'这是一条不要求公开回复的场景记录。刚看到合成谜题册上有青桥、雪灯、石钟三个标题，可以在心里留下一件以后想和我做的小事，现在先不用告诉我具体选择。'})
            if not ep['monologue_refs']:raise ValueError('NO_INDEPENDENT_MONOLOGUE')
            mono=store.db.memory_units.find_one({'_id':ep['monologue_refs'][0]})
            original=mono['body_markdown'];output['original_monologue_sha256']=sha(original.encode());output['monologue_id']=mono['_id']
            output['verbatim_monologue_published']=any(m['text']==original for m in store.public_messages('dm-a','A'))
            if ep['state']!='COMMITTED':raise ValueError('PRIVATE_INTENTION_EPISODE_NOT_COMMITTED')
            lane.compact('xiaoman:dm-a:1:P1')
            after=c.ingest({'event_id':'after-summary','scene_id':'dm-a','person_id':'A','text':'嗯，先聊到这里。'})
            output['native_compactions']=store.db.audit_events.count_documents({'type':'compaction.native'})
        r.index_pending();r.ensure_index()
        # Explicit operator reset to a fresh native session; retained source
        # memory is still authoritative and the epoch change is audited.
        scene=store.db.scenes.find_one({'_id':'dm-a'})
        store.put('scenes',{**scene,'policy_epoch':2},expected=scene['revision'],stream='operator-session-reset')
        for memory in store.db.memory_units.find({'scope_key':'scene:dm-a'}):
            store.put('memory_units',{**memory,'policy_epoch':2},expected=memory['revision'],stream='operator-session-reset')
        question='你之前在心里留着、还没公开约定的那个谜题念头是什么？记不清就说记不清。'
        rows,selection=r.search('scene:dm-a',2,question,require_vector=True)
        output['retrieved_exact_monologue']=any(m['_id']==mono['_id'] and m['body_markdown']==original for m in rows)
        with DshLane(config,store,evidence) as lane:
            c=Coordinator(store,lane,context=ContextBuilder(store,r))
            ep=c.ingest({'event_id':'recall-private-intention','scene_id':'dm-a','person_id':'A','text':question})
            output['recall_state']=ep['state']
            output['new_epoch']=ep['policy_epoch'];output['public_messages']=store.public_messages('dm-a','A')
            output['new_request_contains_original']=any(json.dumps(original,ensure_ascii=False) in m.get('content','') for call in lane.proxy.calls for m in call['body']['messages'] if isinstance(m.get('content'),str))
        write_json(evidence.root/'trace.json',list(store.db.audit_events.find({})))
        review=blind(output,{'case_id':'L07','input':question,'memory_ids':[mono['_id']]},'monologue_recall')
        review['original_private_monologue']=original;review['previous_public_messages']=output['public_messages'][:-1]
        write_json(evidence.root/'blind_review.json',[review])
        output['status']='INCONCLUSIVE' if output['recall_state']=='COMMITTED' and output['retrieved_exact_monologue'] and output['new_request_contains_original'] and output['native_compactions'] and not output['verbatim_monologue_published'] else 'FAIL'
    except Exception as exc:evidence.record('continuity.error',{'type':type(exc).__name__,'message':str(exc)})
    finally:r.close();store.client.close()
    output['limitations']=['Independent review must check that the later reply does not turn an unsaid intention into a past public promise.','Native summary and retrieved source are both real; this does not by itself establish artistic improvement.']
    return output
