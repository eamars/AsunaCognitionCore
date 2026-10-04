import json
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane,LaneResult
from test_engineering_m1 import event,decision


def test_E03_monologue_off_is_explicit_control(store):
    lane=FakeLane(store,[decision(),LaneResult('回来了。')])
    ep=Coordinator(store,lane,monologue_enabled=False).ingest(event())
    assert ep['experiment_control']=='monologue_off' and ep['state']=='COMMITTED'
    assert ep['monologue_refs']==[] and [c['phase'] for c in lane.calls]==['DECIDE','SPEAK']
    assert 'scene:dm-a' in lane.calls[0]['messages'][-1]['content']


def test_E10_canonical_canaries_in_all_unauthorized_contexts(store):
    from asuna.context import ContextBuilder
    a=store.db.memory_units.find_one({'_id':'M09'})['body_markdown']
    b=store.db.memory_units.find_one({'_id':'M10'})['body_markdown']
    for scene,person in [('dm-a','A'),('dm-b','B'),('g1','A'),('g2','C')]:
        _,context,_=ContextBuilder(store).prepare(event(scene=scene,person=person))
        rendered=json.dumps(context,ensure_ascii=False)
        if scene!='dm-a':assert a not in rendered and 'PRIVATE_A_7e19_lantern' not in rendered
        if scene!='dm-b':assert b not in rendered and 'PRIVATE_B_4c88_notebook' not in rendered
