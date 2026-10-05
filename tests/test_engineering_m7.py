import subprocess,sys
from pathlib import Path
import pytest
from asuna.config import ROOT
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane,FakeTurn
from asuna.audit import verify
from asuna.tasks import TaskService,ToolBroker

THINK=('think',{'thought':'宿主重启了，接着把这回合做完。'})


def delegated(store):
    """One delegated task (ADR-011 delegate), claimed and bound to the fixture grant's workspace."""
    lane=FakeLane(store,[FakeTurn([('think',{'thought':'要先核实，交给行动脑。'}),
                                   ('delegate',{'title':'复制受控文件','brief':'复制受控文件，保留原件。'})],'我先去核实。')])
    ep=Coordinator(store,lane).ingest({'event_id':'copy','scene_id':'dm-a','person_id':'A','text':'复制受控文件，保留原件。'})
    service=TaskService(store);task=service.claim(ep['task_ids'][0])
    work=Path(store.config['channels']['fixture']['routes']['dm-a']['workspace'])
    (work/'a.txt').write_text('controlled original',encoding='utf-8')
    return service,task,ToolBroker(service),work


@pytest.mark.parametrize('point',['after_task_persist','after_lane_delivery','after_tool_commit','after_send_before_receipt','before_commit_audit'])
def test_E14_five_actual_process_crash_points(store,point):
    p=subprocess.run([sys.executable,str(ROOT/'tests/crash_matrix_worker.py'),store.name,point],capture_output=True)
    assert p.returncode==77,p.stderr.decode(errors='replace')
    store.recover_commits()
    # A turn cut off mid-way resumes as a new turn in the same session; it is told what already took effect.
    lane=FakeLane(store,[FakeTurn([THINK],'回来了。')])
    Coordinator(store,lane).recover()
    assert store.db.sink_receipts.count_documents({})<=1
    ep=store.db.episodes.find_one({'source_event_id':'matrix'})
    if point in ('after_task_persist','after_tool_commit'):
        assert store.db.tasks.count_documents({})==1
        assert ep['state']=='WAITING_TASK'
        assert ep['task_ids']==[store.db.tasks.find_one({})['_id']]
    else:
        assert ep['state']=='COMMITTED'
        assert store.db.sink_receipts.count_documents({})==1
    verify(list(store.db.audit_events.find({})))
