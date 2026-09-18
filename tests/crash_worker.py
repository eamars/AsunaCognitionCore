import json
import os
import sys
from asuna.config import load
from asuna.state import Store
from asuna.lanes import FakeLane,LaneResult
from asuna.coordinator import Coordinator

store=Store(load(),sys.argv[1])
lane=FakeLane(store,[LaneResult('内部。'),LaneResult(json.dumps({'next':'speak','goal':'回应','constraints':[],'recall_query':'','speak_before_action':False})),LaneResult('回来啦。')])
def crash(point):
    if point=='after_send_before_receipt':os._exit(77)
Coordinator(store,lane,crash=crash).ingest({'event_id':'crash','scene_id':'dm-a','person_id':'A','text':'你好'})
