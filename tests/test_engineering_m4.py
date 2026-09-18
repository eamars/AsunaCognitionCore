import pytest
from asuna.context import ContextBuilder
from asuna.state import Denied,Conflict
from asuna.memory import MemoryService
from test_engineering_m1 import normal,event


def test_E18_same_source_not_new_experience(store):
    head,base=store.head('relationship:A','scene:dm-a')
    rev=store.mutate('relationship:A','scene:dm-a',base['_id'],{'body':'一次新的理解。','trust':3},['M01'],'scene:dm-a','once')
    for _ in range(10):ContextBuilder(store).prepare(event())
    for i in range(5):
        with pytest.raises(Conflict):store.mutate('relationship:A','scene:dm-a',rev['_id'],{'body':'再加一次。','trust':4},['M01'],'scene:dm-a','retry-'+str(i))
    assert store.head('relationship:A','scene:dm-a')[1]['content']['trust']==3


def test_E19_bounded_proposal_and_next_context(store):
    coordinator,lane=normal(store);old_ep=coordinator.ingest(event())
    head,base=store.head('relationship:A','scene:dm-a')
    proposal={'entity_key':'relationship:A','scope_key':'scene:dm-a','base_revision_id':base['_id'],'change_class':'relationship','changes':[{'path':'/body','old':base['content']['body'],'new':'我可以先选择可逆方案，再听林的反馈。'}],'reason':'保留自主选择偏好','source_ids':['M02']}
    result=MemoryService(store).proposal(proposal,'scene:dm-a','bounded')
    assert result['_id']!=base['_id']
    _,ctx,manifest=ContextBuilder(store).prepare(event('next'))
    assert ctx['relationship']['body']==proposal['changes'][0]['new']
    assert old_ep['manifest']['relationship_revision']==base['_id']
    proposal['scope_key']='global-safe'
    with pytest.raises(Denied):MemoryService(store).proposal(proposal,'scene:dm-a','denied')


def test_E12_chunk_sources_and_scope(store):
    coordinator,lane=normal(store);coordinator.ingest(event())
    chunks=MemoryService(store).chunk('dm-a')
    assert chunks and all(c['scope_key']=='scene:dm-a' for c in chunks)
    assert all(2<=len(c['source_event_ids'])<=6 for c in chunks)
    assert all(len(c['body_markdown'].encode())<=1024 for c in chunks)
    assert not MemoryService(store).chunk('dm-a')
    assert not MemoryService(store).chunk('g1')
