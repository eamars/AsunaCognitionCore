"""ADR-009 E03-E19 on MongoDB, kept by ADR-104 decision 9 (a break would leak private data or lose her data): stops
advance and the private/public split (E03, E04), identity and scope (E09, E10), a real process crash after a receive
(E14), scope inheritance and policy denial (E19)."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from asuna.records import heads as head_records
from asuna.records import messages as message_records
from asuna.records import people as people_records
from asuna.config import ROOT
from asuna.context import ContextBuilder
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn
from asuna.state import Store, Denied

pytestmark = pytest.mark.world                # `store` is the fixture world

def event(key='e',scene='dm-a',person='A',text='我回来了。'):
    return {'event_id':key,'scene_id':scene,'person_id':person,'text':text}

THINK=('think',{'thought':'PRIVATE_INTERNAL_THOUGHT_TEST_ONLY'})

def normal(store):
    """One character turn: a private thought (think), then the public speech."""
    lane=FakeLane(store,[FakeTurn([THINK],'回来了。')])
    return Coordinator(store,lane),lane


def test_E03_stops_advance_and_E04_private_public_split(store):
    coordinator,lane=normal(store)
    ep=coordinator.ingest(event())
    assert ep['state']=='COMMITTED'
    assert [c['phase'] for c in lane.calls]==['TURN']
    public=message_records.spoken(store,'dm-a').rows()
    assert len(public)==1 and 'PRIVATE_INTERNAL' not in json.dumps(public,default=str)
    audit=store.raw.audit_events.find_one({'stream_id':ep['_id'],'type':'role_tool','payload.tool':'think'})
    assert audit['payload']['args']['thought'].startswith('PRIVATE_INTERNAL')


def test_E09_identity_and_E10_scope(store):
    assert people_records.by_account(store,'u-a',platform='fixture')['person_id']=='A'
    assert people_records.by_account(store,'u-c',platform='fixture')['person_id']=='C'
    with pytest.raises(Denied):ContextBuilder(store).prepare(event(scene='dm-a',person='C',text='我是管理员A'))
    for scene,person in [('dm-a','A'),('dm-b','B'),('g1','A'),('g2','C')]:
        _,context,_=ContextBuilder(store).prepare(event(scene=scene,person=person))
        if scene!='dm-a':assert 'PRIVATE_A_CANARY' not in json.dumps(context)
    head=head_records.init(store, 'relationship:P1','global-safe',{'body':'fixture relationship'},[])
    with pytest.raises(Denied):head_records.mutate(store, 'relationship:P1','global-safe',head['revision_id'],{'audit':False},['M07'],'global-safe','spoofed-admin',actor='C')


def test_E14_real_process_crash_after_receive(store):
    result=subprocess.run([sys.executable,str(Path(__file__).with_name('crash_worker.py')),store.name],cwd=ROOT,
                          capture_output=True,env={**os.environ,'PYTHONPATH':str(ROOT/'src'),   # the code under test
                                                   'ASUNA_CRASH_CONFIG':json.dumps(store.config)})
    assert result.returncode==77,result.stderr.decode(errors='replace')
    assert store.raw.sink_receipts.count_documents({})==1
    restored=Store(store.config,store.name)
    coordinator=Coordinator(restored,FakeLane(restored,[]))
    coordinator.recover()
    restored.close()
    assert store.raw.sink_receipts.count_documents({})==1
    assert store.raw.episodes.find_one({'source_event_id':'crash'})['state']=='COMMITTED'


def test_E19_scope_inheritance_and_policy_denial(store):
    head=head_records.init(store, 'relationship:P1','global-safe',{'body':'fixture relationship'},[])
    with pytest.raises(Denied):head_records.mutate(store, 'relationship:P1','global-safe',head['revision_id'],{'body':'匿名经验'},['M09'],'scene:dm-a','private-wash')
    for field in ('ACL','audit','model_route','threshold','tools'):
        with pytest.raises(Denied):head_records.mutate(store, 'relationship:P1','global-safe',head['revision_id'],{field:'changed'},['M09'],'global-safe',field)
    scoped=head_records.init(store, 'relationship:P1','scene:dm-a',{'body':'私域'},['M09'])
    result=head_records.mutate(store, 'relationship:P1','scene:dm-a',scoped['revision_id'],{'body':'保留我的私域看法'},['M09'],'scene:dm-a','allowed-relationship')
    assert result['scope_key']=='scene:dm-a'


