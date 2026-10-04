import subprocess,sys
import pytest
from asuna.config import ROOT
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane,LaneResult
from asuna.audit import verify
from test_engineering_m1 import decision
from test_engineering_m3 import task_setup


@pytest.mark.parametrize('point',['after_task_persist','after_lane_delivery','after_tool_commit','after_send_before_receipt','before_commit_audit'])
def test_E14_five_actual_process_crash_points(store,point):
    p=subprocess.run([sys.executable,str(ROOT/'tests/crash_matrix_worker.py'),store.name,point],capture_output=True)
    assert p.returncode==77,p.stderr.decode(errors='replace')
    store.recover_commits()
    lane=FakeLane(store,[decision(),LaneResult('回来了。')])
    Coordinator(store,lane).recover()
    assert store.db.sink_receipts.count_documents({})<=1
    if point in ('after_task_persist','after_tool_commit'):
        assert store.db.tasks.count_documents({})==1
        assert store.db.episodes.find_one({'source_event_id':'matrix'})['state']=='WAITING_TASK'
    else:
        assert store.db.episodes.find_one({'source_event_id':'matrix'})['state']=='COMMITTED'
        assert store.db.sink_receipts.count_documents({})==1
    verify(list(store.db.audit_events.find({})))


def test_E12_read_only_source_and_allowed_code_write(store):
    service,task,broker,work=task_setup(store)
    store.config['channels']['fixture']['routes']['dm-a']['read_only_paths']=['a.txt']   # the grant protects the source
    broker.bind('s-test',task,work)
    try:
        result=broker.call('s-test','immutable','sandbox_run',{'argv':['python3','-c',"from pathlib import Path;Path('a.txt').write_text('tamper')"]})
        assert result['exit_code']!=0 and (work/'a.txt').read_text()=='controlled original'
        assert broker.call('s-test','write','sandbox_run',{'argv':['python3','-c',"open('new.txt','w').write('allowed')"]})['exit_code']==0
    finally:broker.close()


