import json
import pytest
from asuna.context import ContextBuilder
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn
from asuna.memory import MemoryService


def setup_turn(store, reflection):
    store.config['task_mode']='workspace'
    understand=('understand_person',{'body':reflection})
    lane=FakeLane(store,[
        FakeTurn([('think',{'thought':'这是当前人物明确的反馈，不代表所有人。'}),understand],'知道了。'),
        # The resumed turn is told which calls already took effect (think); the interrupted one is not among them.
        FakeTurn([understand],'知道了。')])
    event={'event_id':'understanding-feedback','scene_id':'dm-a','person_id':'A','text':'我希望结论先说。'}
    return Coordinator(store,lane),lane,event


def test_role_update_survives_interruption_without_double_commit_or_scope_leak(store,monkeypatch):
    text='我此前过多解释过程；A 更看重先听结论。这只适用于与 A 的这段关系。'
    coordinator,lane,event=setup_turn(store,text)
    before=store.head('relationship:A','scene:dm-a')[1]
    original=MemoryService.commit_understanding
    def interrupted(service,ep,body):
        result=original(service,ep,body)
        raise RuntimeError('after state commit, before episode marker')
    monkeypatch.setattr(MemoryService,'commit_understanding',interrupted)
    with pytest.raises(RuntimeError):coordinator.ingest(event)
    ep=store.db.episodes.find_one({'source_event_id':event['event_id']})
    assert ep['state']=='TURN' and 'understanding_update' not in ep
    assert store.db.messages.count_documents({'episode_id':ep['_id'],'direction':'outbound'})==0
    monkeypatch.setattr(MemoryService,'commit_understanding',original)
    done=coordinator.advance(ep['_id'])
    assert done['state']=='COMMITTED' and done['speech']=='知道了。'
    assert [c['phase'] for c in lane.calls]==['TURN','TURN']
    assert '这一回合中断前已经生效的工具调用（不用再做一遍）：think' in lane.calls[1]['messages'][-1]['content']
    assert done['understanding_update']['state']=='COMMITTED'
    revision=store.head('relationship:A','scene:dm-a')[1]
    assert revision['content']['body']==text
    assert revision['parent_revision_id']==before['_id']
    assert revision['source_ids']==done['monologue_refs']
    assert store.db.state_revisions.count_documents({'mutation_id':ep['_id']+':understanding'})==1
    assert done['manifest']['relationship_revision']==before['_id']
    _,current,manifest=ContextBuilder(store).prepare({**event,'event_id':'later'})
    assert current['relationship']['understanding']==text
    assert manifest['relationship_revision']==revision['_id']
    _,foreign,_=ContextBuilder(store).prepare({'event_id':'other','scene_id':'dm-b','person_id':'B','text':'你好'})
    assert text not in json.dumps(foreign,ensure_ascii=False)
