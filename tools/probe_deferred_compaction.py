"""E24: interruption after real monologue, persisted queue, restart, safe summary."""
import json,uuid
from asuna.config import ROOT,load,BUNDLE
from asuna.evidence import Evidence,write_json
from asuna.experiments import freeze
from asuna.state import Store
from asuna.dsh_lane import DshLane
from asuna.coordinator import Coordinator

name='deferred-compaction-'+uuid.uuid4().hex[:10];ev=Evidence(ROOT/'reports'/name);cfg=load();freeze(cfg,BUNDLE/'fixtures/acceptance_cases.json',ev,'PROBE-E24-deferred')
write_json(ev.root/'probe-plan.json',{'required':['interrupted monologue resumes without summarizing partial episode','queued compaction survives restart','exactly one real summary before next episode','queue clears only after native receipt','subsequent episode either commits or explicitly fails protocol without publication'], 'quality_scope':'Engineering boundary only. Natural-language completion is separately reported; a protocol failure cannot establish role quality.'})
store=Store(cfg,'asuna_v2_test_'+name.replace('-','_'));store.migrate();store.seed();status='FAIL'
try:
    def crash(point):
        if point=='after_lane_delivery':raise RuntimeError('INJECTED_AFTER_MONOLOGUE_DELIVERY')
    with DshLane(cfg,store,ev) as lane:
        c=Coordinator(store,lane,crash=crash)
        try:c.ingest({'event_id':'interrupted','scene_id':'dm-a','person_id':'A','text':'我回来了。'})
        except RuntimeError as exc:assert str(exc)=='INJECTED_AFTER_MONOLOGUE_DELIVERY'
        ep=store.db.episodes.find_one({'source_event_id':'interrupted'});assert ep['state']=='PREPARED'
        assert store.db.sessions.find_one({'binding_key':'xiaoman:dm-a:1:P1'})['last_phase']=='MONOLOGUE'
        lane.compact('xiaoman:dm-a:1:P1')
    with DshLane(cfg,store,ev) as lane:
        c=Coordinator(store,lane);c.recover()
        assert store.db.episodes.find_one({'_id':ep['_id']})['state']=='COMMITTED'
        assert store.db.audit_events.count_documents({'type':'compaction.native'})==0
        after=c.ingest({'event_id':'next','scene_id':'dm-a','person_id':'A','text':'我们先随便聊一会儿，不安排任务。'})
        assert after['state'] in ('COMMITTED','FAILED_PROTOCOL')
        if after['state']=='FAILED_PROTOCOL':
            assert store.db.messages.count_documents({'episode_id':after['_id'],'delivery_state':'DELIVERED'})==0
        ev.record('phase_quality',{'state':after['state'],'failure':after.get('failure'),'counts_as_character_quality_pass':after['state']=='COMMITTED'})
        assert store.db.audit_events.count_documents({'type':'compaction.native'})==1
        assert not store.db.sessions.find_one({'binding_key':'xiaoman:dm-a:1:P1'})['compact_requested']
    write_json(ev.root/'trace.json',list(store.db.audit_events.find({})));status='PASS'
except Exception as exc:ev.record('probe.error',{'type':type(exc).__name__,'message':str(exc)})
finally:store.client.close()
write_json(ev.root/'result.json',{'test_id':'PROBE-E24-deferred','status':status,'commands':[{'argv':['python','tools/probe_deferred_compaction.py'],'exit_code':0 if status=='PASS' else 1}],'mode':'real_Gemma_native_restart_queued_summary'});print(json.dumps({'run':name,'status':status}));raise SystemExit(0 if status=='PASS' else 1)
