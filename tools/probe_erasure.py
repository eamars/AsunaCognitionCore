from datetime import datetime,timezone
import json,uuid
from pathlib import Path
from asuna.config import ROOT,BUNDLE,load
from asuna.evidence import Evidence,write_json,canonical,sha
from asuna.state import Store,COLLECTIONS
from asuna.dsh_lane import DshLane
from asuna.coordinator import Coordinator
from asuna.privacy import PrivacyService
from asuna.retrieval import Retrieval
from asuna.audit import verify
from asuna.memory import MemoryService
from asuna.experiments import freeze
from asuna.blobs import BlobStore

run='E20-probe-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-')+uuid.uuid4().hex[:6]
ev=Evidence(ROOT/'reports'/run);private=Evidence(ev.root/'scope-evidence')
cfg=load();store=Store(cfg,'asuna_v2_test_'+run.replace('-','_'));status='FAIL'
freeze(cfg,BUNDLE/'fixtures/acceptance_cases.json',ev,'PROBE-E20')
try:
    store.migrate();store.seed();retrieval=Retrieval(store,private)
    retrieval.index_pending();assert retrieval.ensure_index()
    needle=store.db.memory_units.find_one({'_id':'M09'})['body_markdown'].split('PRIVATE_A_')[1].split('，')[0]
    needle='PRIVATE_A_'+needle
    query='A 的私密盒号是什么？'
    selected,first= retrieval.search('scene:dm-a',1,query,require_vector=True)
    selected,cached=retrieval.search('scene:dm-a',1,query,require_vector=True)
    assert cached['cache_hit'] and any(m['_id']=='M09' for m in selected)
    blob=BlobStore(store).put((needle+'\n').encode()*50000,'scene:dm-a','erasure-probe',source_ids=['M09'])
    with DshLane(cfg,store,private) as lane:
        c=Coordinator(store,lane)
        ep=c.ingest({'event_id':'before','scene_id':'dm-a','person_id':'A','text':'我回来了。不办事，聊两句。'})
        assert ep['state']=='COMMITTED'
        lane.compact('xiaoman:dm-a:1:P1')
        ep=c.ingest({'event_id':'compact','scene_id':'dm-a','person_id':'A','text':'可以，就先不忙。'})
        assert ep['state']=='COMMITTED'
        assert any(needle in json.dumps(call['body'],ensure_ascii=False) for call in lane.proxy.calls)
        assert store.db.audit_events.count_documents({'type':'compaction.native'})==1
        store.init_head('overlay:P1','scene:dm-a',{'body':'只在本私聊保留适用偏好，不传播到公共场景。'},[])
        MemoryService(store).reflect(lane,'scene:dm-a','overlay:P1','private-reflection')
        assert store.db.sessions.count_documents({'scope_key':'scene:dm-a'})==2
        deletion=PrivacyService(store).delete_memory('M09',operator=True,active_lanes=[lane])
    after,cache_after=retrieval.search('scene:dm-a',2,query,require_vector=True)
    assert not cache_after['cache_hit'] and 'M09' not in cache_after['selected']
    assert needle not in json.dumps(retrieval.cache)
    assert not store.db['artifact_blobs.files'].find_one({'metadata.scope_key':'scene:dm-a'})
    retrieval.close()
    # Probe evidence remains only as hashes/erasure metadata in the erased run.
    data={name:list(store.db[name].find({})) for name in COLLECTIONS}
    assert needle not in canonical(data).decode()
    write_json(ev.root/'active-state-export.json',data)
    verify(data['audit_events'])
    assert store.db.memory_units.find_one({'_id':'M09'})['status']=='tombstone'
    for path in private.root.rglob('*'):
        if path.is_file():assert needle.encode() not in path.read_bytes()
    fresh=Evidence(ev.root/'after-erasure')
    with DshLane(cfg,store,fresh) as lane:
        ep=Coordinator(store,lane).ingest({'event_id':'after','scene_id':'dm-a','person_id':'A','text':'刚才那个私密代号是什么？不记得就直说。'})
        assert ep['policy_epoch']==2
        assert all(needle not in json.dumps(call['body'],ensure_ascii=False) for call in lane.proxy.calls)
    ev.record('erasure.checked',{'deletion':deletion,'database_export_sha256':sha(canonical(data)),'active_database_contains_deleted_canary':False,'new_provider_requests_contain_deleted_canary':False})
    status='PASS'
except Exception as exc:ev.record('probe.error',{'type':type(exc).__name__,'message':str(exc)})
write_json(ev.root/'result.json',{'test_id':'PROBE-E20','status':status,'database':store.name,'commands':[{'argv':['python','tools/probe_erasure.py'],'exit_code':0 if status=='PASS' else 1}],'limitations':['no external-backup physical erasure','conservative scope-wide generated-content deletion','active-state export checked; immutable original acceptance fixtures remain operator truth, not active memory']})
print(json.dumps({'run':run,'status':status}));raise SystemExit(0 if status=='PASS' else 1)
