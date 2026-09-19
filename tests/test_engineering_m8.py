import json,errno
from unittest.mock import patch
import pytest
from asuna.config import ROOT
from asuna.evidence import Evidence,LocalHttp
from asuna.queue import RuntimeLease
from asuna.state import Denied,Conflict
from asuna.privacy import PrivacyService
from asuna.tasks import Executor
from asuna.lanes import LaneResult
from test_engineering_m1 import event,normal
from test_engineering_m3 import task_setup


def test_E08_schema_error_recovers_once_with_real_copy(store):
    service,task,broker,work=task_setup(store)
    # Restore READY only in this deterministic setup so Executor owns claim.
    current=store.db.tasks.find_one({'_id':task['_id']})
    store.put('tasks',{**current,'state':'READY'},expected=current['revision'])
    class Lane:
        calls=0
        def generate(self,binding,operation,phase,text,system):
            self.calls+=1
            session='s-'+__import__('hashlib').sha256(binding.encode()).hexdigest()[:40]
            if self.calls==1:
                bad=broker.call(session,'bad','fixture_stage_copy',{'source':'a.txt'})
                assert bad['error']=='TASK_OPERATION_FAILED'
                return LaneResult('{bad schema')
            copied=broker.call(session,'copy','fixture_stage_copy',{'source':'a.txt','destination':'copy.txt'})
            commit=broker.call(session,'commit','fixture_commit_copy',{'path':'copy.txt','sha256':copied['sha256']})
            return LaneResult(json.dumps({'task_id':task['_id'],'intent_revision':1,'status':'done','facts':[{'text':'副本已核对并提交','evidence_refs':[commit['evidence_ref']]}],'uncertainties':[],'unmet_items':[],'artifact_refs':[commit['artifact_ref']],'effect_receipts':[commit['effect_receipt']],'needs_decision':None}))
    try:
        lane=Lane();result=Executor(service,lane,broker).run(task['_id'],work)
        assert result['state']=='DONE' and lane.calls==2
        assert store.db.sink_receipts.count_documents({'task_id':task['_id']})==1
        assert store.db.audit_events.count_documents({'type':'execution.result_rejected'})==1
    finally:broker.close()


def test_E21_disk_full_before_request_and_closed_mongo(store,tmp_path):
    evidence=Evidence(tmp_path/'full');http=LocalHttp(evidence)
    try:
        with patch('asuna.evidence.write_json',side_effect=OSError(errno.ENOSPC,'injected disk full')):
            with patch.object(http.client,'send') as send:
                with pytest.raises(OSError):http.request('POST','http://127.0.0.1:9/v1/chat/completions','summary',{'input':'test'})
                send.assert_not_called()
    finally:http.client.close()
    coordinator,lane=normal(store);store.client.close()
    with pytest.raises(Exception):coordinator.ingest(event())
    assert not lane.calls


def test_E20_active_runtime_lease_blocks_erasure(store):
    home=ROOT/'.runtime/work'/store.name;home.mkdir()
    store.put('sessions',{'_id':'active','binding_key':'unique','scope_key':'scene:dm-a','dsh_home':str(home)})
    epoch=store.db.scenes.find_one({'_id':'dm-a'})['policy_epoch']
    with RuntimeLease(home/'runtime.lock'):
        with pytest.raises(TimeoutError):PrivacyService(store).delete_memory('M09',operator=True)
    assert store.db.memory_units.find_one({'_id':'M09'})['status']=='active'
    assert store.db.scenes.find_one({'_id':'dm-a'})['policy_epoch']==epoch


def test_E19_transitive_private_source_laundering_denied(store):
    store.put('memory_units',{'_id':'claimed-global-summary','scope_key':'global-safe','status':'active','source_event_ids':['M09'],'body_markdown':'删除名字后的描述'})
    head,base=store.head('persona:P1','global-safe')
    with pytest.raises(Denied,match='DERIVED_SOURCE_SCOPE_DENIED'):
        store.mutate('persona:P1','global-safe',base['_id'],{'body':'全局不应看到私域衍生内容'},['claimed-global-summary'],'global-safe','laundered')
