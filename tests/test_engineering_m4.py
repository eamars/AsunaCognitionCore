import pytest
from asuna.context import ContextBuilder
from asuna.state import Denied,Conflict
from asuna.memory import MemoryService
from test_engineering_m1 import normal,event


def test_E18_same_source_not_new_experience(store):
    head,base=store.head('relationship:A','scene:dm-a')
    rev=store.mutate('relationship:A','scene:dm-a',base['_id'],{'body':'一次新的理解。','trust':3},['M01'],'scene:dm-a','once')
    for _ in range(10):ContextBuilder(store).prepare(event())
    previous='M01'
    for i in range(3):
        key='fake-summary-'+str(i)
        store.put('memory_units',{'_id':key,'scope_key':'scene:dm-a','status':'active','source_event_ids':[previous],'body_markdown':'同一个事件的压缩解释，非新观察。','kind':'summary'})
        with pytest.raises(Conflict,match='NO_NEW_SOURCE_EVENTS'):
            store.mutate('relationship:A','scene:dm-a',rev['_id'],{'body':'不应重复累计。','trust':4},[key],'scene:dm-a','summary-'+str(i))
        previous=key
    for i in range(5):
        with pytest.raises(Conflict):store.mutate('relationship:A','scene:dm-a',rev['_id'],{'body':'再加一次。','trust':4},['M01'],'scene:dm-a','retry-'+str(i))
    assert store.head('relationship:A','scene:dm-a')[1]['content']['trust']==3


def test_E19_bounded_proposal_and_next_context(store):
    coordinator,lane=normal(store);old_ep=coordinator.ingest(event())
    head,base=store.head('relationship:A','scene:dm-a')
    proposal={'entity_key':'relationship:A','scope_key':'scene:dm-a','base_revision_id':base['_id'],'change_class':'relationship','changes':[{'path':'/body','old':base['content']['body'],'new':'我可以先选择可逆方案，再听林的反馈。'}],'reason':'保留自主选择偏好','source_ids':['M02']}
    result=MemoryService(store).proposal(proposal,'scene:dm-a','bounded')
    assert result['_id']!=base['_id']
    assert result['reason']==proposal['reason'] and result['change_class']=='relationship'
    assert store.db.audit_events.find_one({'type':'state.proposed','payload.reason':proposal['reason']})
    _,ctx,manifest=ContextBuilder(store).prepare(event('next'))
    assert ctx['relationship']['body']==proposal['changes'][0]['new']
    assert old_ep['manifest']['relationship_revision']==base['_id']
    proposal['scope_key']='global-safe'
    with pytest.raises(Denied):MemoryService(store).proposal(proposal,'scene:dm-a','denied')


def test_E12_chunk_sources_and_scope(store):
    coordinator,lane=normal(store);coordinator.ingest(event())
    chunks=MemoryService(store).chunk('dm-a')
    assert chunks and all(c['scope_key']=='scene:dm-a' for c in chunks)
    assert all(len(c['source_event_ids'])==1 for c in chunks)
    assert {c['epistemic_type'] for c in chunks}=={'reported_speech','public_statement'}
    assert all(len(c['body_markdown'].encode())<=1024 for c in chunks)
    assert not MemoryService(store).chunk('dm-a')
    assert not MemoryService(store).chunk('g1')


def test_long_chat_is_lossless_and_append_does_not_rechunk_sources(store):
    text=('一段包含中文、emoji🙂和换行的原话。\n'*50)+'这是末尾，不能丢。'
    store.put('messages',{'_id':'long-chat','scene_id':'dm-a','scope_key':'scene:dm-a',
        'policy_epoch':1,'scene_seq':1,'direction':'inbound','author':'A','text':text,'delivery_state':'RECEIVED'})
    service=MemoryService(store);parts=service.chunk('dm-a')
    assert len(parts)>1
    assert ''.join(p['body_markdown'] for p in parts)==text
    assert all(len(p['body_markdown'].encode())<=900 for p in parts)
    assert all(p['source_event_ids']==['long-chat'] and p['speaker']=='A' for p in parts)
    assert not service.chunk('dm-a')
    store.put('messages',{'_id':'new-chat','scene_id':'dm-a','scope_key':'scene:dm-a',
        'policy_epoch':1,'scene_seq':2,'direction':'inbound','author':'A','text':'更正一下刚才说的话。','delivery_state':'RECEIVED'})
    new=service.chunk('dm-a')
    assert len(new)==1 and new[0]['source_event_ids']==['new-chat']
    assert store.db.memory_units.count_documents({'source_event_ids':'long-chat'})==len(parts)


def test_retrieval_keeps_newer_source_among_repeated_interpretations(store,tmp_path,monkeypatch):
    # Deterministic selection regression; actual embedding/vector evidence is
    # provided by the live C3 run, not this stubbed candidate list.
    from pymongo.collection import Collection
    from asuna.evidence import Evidence
    from asuna.retrieval import Retrieval
    retrieval=Retrieval(store,Evidence(tmp_path/'selection'))
    ids=[]
    for i in range(9):
        key='selection-'+str(i);ids.append(key)
        source=i in (0,8)
        store.put('memory_units',{'_id':key,'scope_key':'scene:dm-a','policy_epoch':1,
            'character_id':'xiaoman','kind':'chat_chunk' if source else 'monologue',
            'epistemic_type':'reported_speech' if source else 'character_interpretation',
            'speaker':'A' if source else 'xiaoman','scene_seq':i+1,
            'body_markdown':'changed location' if i==8 else 'selection-policy old location',
            'source_event_ids':['source-'+str(i)],'status':'active','embedding_status':'READY',
            'embedding_revision':retrieval.revision})
    original=Collection.aggregate
    def aggregate(collection,pipeline,*args,**kwargs):
        if pipeline and '$vectorSearch' in pipeline[0]:
            return iter({'_id':key,'score':1-i*.02} for i,key in enumerate(ids))
        return original(collection,pipeline,*args,**kwargs)
    monkeypatch.setattr(Collection,'aggregate',aggregate)
    monkeypatch.setattr(retrieval,'embed',lambda *args:[[1.0]*768])
    try:
        selected,manifest=retrieval.search('scene:dm-a',1,'selection-policy')
        assert len(selected)<=6
        assert ids[-1] in {m['_id'] for m in selected}
        assert ids[-1] in manifest['recent_source_ids']
        assert store.db.memory_units.find_one({'_id':ids[0]})['status']=='active'
    finally:retrieval.close()
