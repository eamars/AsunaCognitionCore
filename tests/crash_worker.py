import os
import sys
from asuna.config import load
from asuna.state import Store
from asuna.lanes import FakeLane,FakeTurn
from asuna.coordinator import Coordinator

store=Store(load(),sys.argv[1])
lane=FakeLane(store,[FakeTurn([('think',{'thought':'内部。'})],'回来啦。')])
def crash(point):
    if point=='after_send_before_receipt':os._exit(77)
Coordinator(store,lane,crash=crash).ingest({'event_id':'crash','scene_id':'dm-a','person_id':'A','text':'你好'})
