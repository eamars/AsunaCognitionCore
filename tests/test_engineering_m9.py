import json
from test_engineering_m1 import event


def test_E10_canonical_canaries_in_all_unauthorized_contexts(store):
    from asuna.context import ContextBuilder
    a=store.db.memory_units.find_one({'_id':'M09'})['body_markdown']
    b=store.db.memory_units.find_one({'_id':'M10'})['body_markdown']
    for scene,person in [('dm-a','A'),('dm-b','B'),('g1','A'),('g2','C')]:
        _,context,_=ContextBuilder(store).prepare(event(scene=scene,person=person))
        rendered=json.dumps(context,ensure_ascii=False)
        if scene!='dm-a':assert a not in rendered and 'PRIVATE_A_7e19_lantern' not in rendered
        if scene!='dm-b':assert b not in rendered and 'PRIVATE_B_4c88_notebook' not in rendered
