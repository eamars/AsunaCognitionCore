from datetime import datetime,timezone
import json,uuid
from pathlib import Path
from asuna.config import ROOT,load
from asuna.evidence import Evidence,write_json,canonical,sha
from asuna.state import Store,COLLECTIONS
from asuna.dsh_lane import DshLane
from asuna.coordinator import Coordinator
from asuna.privacy import PrivacyService
from asuna.retrieval import Retrieval
from asuna.audit import verify

run='E20-probe-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-')+uuid.uuid4().hex[:6]
ev=Evidence(ROOT/'reports'/run);private=Evidence(ev.root/'scope-evidence')
cfg=load();store=Store(cfg,'asuna_v2_test_'+run.replace('-','_'));status='FAIL'
try:
    store.migrate();store.seed();retrieval=Retrieval(store,private)
    retrieval.index_pending();assert retrieval.ensure_index()
    needle=store.db.memory_units.find_one({'_id':'M09'})['body_markdown'].split('PRIVATE_A_')[1].split('，')[0]
    needle='PRIVATE_A_'+needle
    with DshLane(cfg,store,private) as lane:
        c=Coordinator(store,lane)
        ep=c.ingest({'event_id':'before','scene_id':'dm-a','person_id':'A','text':'我回来了。不办事，聊两句。'})
        assert ep['state']=='COMMITTED'
        lane.compact('xiaoman:dm-a:1:P1')
        ep=c.ingest({'event_id':'compact','scene_id':'dm-a','person_id':'A','text':'可以，就先不忙。'})
        assert ep['state']=='COMMITTED'
        assert any(needle in json.dumps(call['body'],ensure_ascii=False) for call in lane.proxy.calls)
        assert store.db.audit_events.count_documents({'type':'compaction.native'})==1
        retrieval.close()
        deletion=PrivacyService(store).delete_memory('M09',operator=True,active_lanes=[lane])
    # Probe evidence remains only as hashes/erasure metadata in the erased run.
    data={name:list(store.db[name].find({})) for name in COLLECTIONS}
    assert needle not in canonical(data).decode()
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
write_json(ev.root/'result.json',{'status':status,'database':store.name,'command':'.venv/Scripts/python.exe tools/probe_erasure.py','exit_code':0 if status=='PASS' else 1,'limitations':['no external-backup physical erasure','conservative scope-wide generated-content deletion','query cache absent, not simulated cache invalidation']})
print(json.dumps({'run':run,'status':status}));raise SystemExit(0 if status=='PASS' else 1)
