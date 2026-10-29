"""ADR-009 E14 on MongoDB, kept by ADR-104 decision 9 (a break would lose her data): five real process crash points,
each recovered without a line lost or sent twice."""
import json,os,subprocess,sys
from pathlib import Path

import pytest

from asuna.config import ROOT
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane,FakeTurn
from asuna.audit import verify

pytestmark = pytest.mark.world                # `store` is the fixture world

THINK=('think',{'thought':'宿主重启了，接着把这回合做完。'})


@pytest.mark.parametrize('point',['after_task_persist','after_lane_delivery','after_tool_commit','after_send_before_receipt','before_commit_audit'])
def test_E14_five_actual_process_crash_points(store,point):
    p=subprocess.run([sys.executable,str(Path(__file__).with_name('crash_matrix_worker.py')),store.name,point],
                     capture_output=True,env={**os.environ,'PYTHONPATH':str(ROOT/'src'),   # the code under test
                                              'ASUNA_CRASH_CONFIG':json.dumps(store.config)})
    assert p.returncode==77,p.stderr.decode(errors='replace')
    store.recover_commits()
    # A turn cut off mid-way resumes as a new turn in the same session; it is told what already took effect.
    lane=FakeLane(store,[FakeTurn([THINK],'回来了。')])
    Coordinator(store,lane).recover()
    assert store.raw.sink_receipts.count_documents({})<=1
    ep=store.raw.episodes.find_one({'source_event_id':'matrix'})
    if point in ('after_task_persist','after_tool_commit'):
        assert store.raw.tasks.count_documents({})==1
        assert ep['state']=='WAITING_TASK'
        assert ep['task_ids']==[store.raw.tasks.find_one({})['_id']]
    else:
        assert ep['state']=='COMMITTED'
        assert store.raw.sink_receipts.count_documents({})==1
    verify(list(store.raw.audit_events.find({})))
