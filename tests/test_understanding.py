import json
import pytest
from asuna.context import ContextBuilder
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, LaneResult
from asuna.memory import MemoryService


def setup_turn(store, reflection):
    store.config['task_mode']='workspace'
    decision={'next':'speak','goal':'回应真实反馈','constraints':[],
              'recall_query':'','speak_before_action':False,'reflect_understanding':True}
    lane=FakeLane(store,[LaneResult('这是当前人物明确的反馈，不代表所有人。'),
        LaneResult(json.dumps(decision)),LaneResult(reflection),LaneResult('知道了。')])
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
    assert ep['state']=='DECISION_ACCEPTED'
    assert store.db.messages.count_documents({'episode_id':ep['_id'],'direction':'outbound'})==0
    monkeypatch.setattr(MemoryService,'commit_understanding',original)
    done=coordinator.advance(ep['_id'])
    assert done['state']=='COMMITTED'
    assert [c['phase'] for c in lane.calls]==['MONOLOGUE','DECIDE','REFLECT','SPEAK']
    revision=store.head('relationship:A','scene:dm-a')[1]
    assert revision['content']['body']==text
    assert revision['parent_revision_id']==before['_id']
    assert revision['source_ids']==ep['monologue_refs']
    assert store.db.state_revisions.count_documents({'mutation_id':ep['_id']+':understanding'})==1
    assert done['manifest']['relationship_revision']==before['_id']
    _,current,manifest=ContextBuilder(store).prepare({**event,'event_id':'later'})
    assert current['relationship']['body']==text
    assert manifest['relationship_revision']==revision['_id']
    _,foreign,_=ContextBuilder(store).prepare({'event_id':'other','scene_id':'dm-b','person_id':'B','text':'你好'})
    assert text not in json.dumps(foreign,ensure_ascii=False)


def test_no_change_does_not_manufacture_growth(store):
    coordinator,lane,event=setup_turn(store,'不更新')
    before=store.head('relationship:A','scene:dm-a')[0]['revision_id']
    done=coordinator.ingest(event)
    assert done['understanding_update']=={'state':'NO_CHANGE'}
    assert store.head('relationship:A','scene:dm-a')[0]['revision_id']==before
    assert store.db.state_revisions.count_documents({'mutation_id':done['_id']+':understanding'})==0
