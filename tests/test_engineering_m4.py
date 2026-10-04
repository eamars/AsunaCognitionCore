from asuna.memory import MemoryService


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


