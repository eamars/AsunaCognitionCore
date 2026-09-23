"""Local contracts; real DSH/model/Web evidence is in ADR003-CONSULT-REPORT.md."""
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, LaneResult
from asuna.state import Denied
from test_workspace_tasks import setup_workspace


def bind(store, lane):
    work, ep, service, broker = setup_workspace(store)
    task = service.claim(ep['task_id'])
    broker.bind('caller', task, work)
    broker.consult_character = Coordinator(store, lane).consult
    return ep, task, service, broker


def test_consult_uses_bound_role_context_without_publication_or_new_task(store):
    calls=[]
    class Role:
        def generate(self, binding, operation, phase, text, system):
            calls.append((binding, operation, phase, text))
            return LaneResult('资料不足；不知道菜单。建议先给结论。')
    ep, task, service, broker = bind(store, Role())
    ep=store.put('episodes',{**ep,'character_context':'original-role-context'},expected=ep['revision'])
    before={c:store.db[c].count_documents({}) for c in ('episodes','messages','tasks','sink_receipts','memory_units')}
    try:
        result=broker.call('caller','question','consult_character',{'question':'按当前关系怎么呈现？','context':'计算结果 323'})
        assert result['internal'] and result['kind']=='character_interpretation'
        assert '资料不足' in result['judgment']
        assert calls[0][0]=='xiaoman:dm-a:1:P1:original-role-context'
        assert calls[0][2]=='CONSULT' and '323' in calls[0][3]
        assert 'scene:dm-b' not in calls[0][3]
        assert store.db.episodes.find_one({'_id':ep['_id']})==ep
        assert before=={c:store.db[c].count_documents({}) for c in before}
        assert service.valid(task)['goal']==task['goal']
        assert broker.call('caller','question','consult_character',{'question':'按当前关系怎么呈现？','context':'计算结果 323'})==result
        assert len(calls)==1
        broker.call('caller','continue','task_status',{'status':'partial'})
        assert service.valid(task)['state']=='RUNNING'
    finally:broker.close()


def test_wait_releases_effects_lock_for_renewal_and_cancellation(store):
    entered, release = threading.Event(), threading.Event()
    class Role:
        def generate(self,*args):
            entered.set()
            assert release.wait(8)
            return LaneResult('迟到的内部建议不能重新授权。')
    ep,task,service,broker=bind(store,Role())
    pool=ThreadPoolExecutor(2)
    try:
        with service.keepalive(task,interval=.05):
            consult=pool.submit(broker.call,'caller','waiting','consult_character',{'question':'请判断'})
            assert entered.wait(5)
            old=service.valid(task)['revision']
            # Another thread can acquire the exact cross-process effects lock.
            def acquire():
                with service.lock:return service.valid(task)['revision']
            assert pool.submit(acquire).result(timeout=2)>=old
            renewed=threading.Event()
            def observe_renewal():
                for _ in range(30):
                    if service.valid(task)['revision']>old:renewed.set();return
                    renewed.wait(.05)
            pool.submit(observe_renewal).result(timeout=3)
            assert renewed.is_set()
            pool.submit(service.cancel,task['_id'],person_id='A').result(timeout=2)
            release.set()
            with pytest.raises(Denied,match='STALE_TASK_FENCE'):consult.result(timeout=5)
        assert store.db.tasks.find_one({'_id':task['_id']})['state']=='CANCELLED'
        with pytest.raises(Denied,match='STALE_TASK_FENCE'):
            broker.call('caller','later','task_status',{'status':'done'})
    finally:release.set();pool.shutdown();broker.close()


def test_native_tool_http_error_returns_original_diagnostic_and_loop_can_continue(store):
    class BrokenRole:
        def generate(self,*args):raise RuntimeError('original role provider unavailable')
    ep,task,service,broker=bind(store,BrokenRole())
    try:
        with httpx.Client(trust_env=False) as client:
            response=client.post(f'http://127.0.0.1:{broker.server.server_port}/tool',
                headers={'Authorization':'Bearer '+broker.token},
                json={'session':'caller','call_id':'broken','tool':'consult_character','args':{'question':'判断'}})
        assert response.status_code==409
        assert response.json()['error_type']=='RuntimeError'
        assert 'original role provider unavailable' in response.json()['traceback']
        broker.call('caller','next','task_status',{'status':'partial'})
        assert service.valid(task)['state']=='RUNNING'
        assert store.db.tasks.count_documents({})==1
    finally:broker.close()


@pytest.mark.parametrize('failure',['foreign_episode','missing_source','foreign_argument','revoked','bad_output'])
def test_context_and_output_failures_stay_in_original_call(store,failure):
    lane=FakeLane(store,[LaneResult('',finish_reason='length',diagnostic={'error':'original context limit'})])
    ep,task,service,broker=bind(store,lane)
    args={'question':'判断'}
    try:
        if failure=='foreign_episode':
            store.db.episodes.update_one({'_id':ep['_id']},{'$set':{'person_id':'B','scene_id':'dm-b'}})
        elif failure=='missing_source':store.db.messages.delete_one({'_id':task['raw_input_refs'][0]})
        elif failure=='foreign_argument':args['scene_id']='dm-b'
        elif failure=='revoked':store.db.scenes.update_one({'_id':task['scene_id']},{'$inc':{'policy_epoch':1}})
        with pytest.raises((ValueError,Denied,RuntimeError)) as caught:
            broker.call('caller','invalid','consult_character',args)
        if failure=='bad_output':assert 'original context limit' in str(caught.value)
        assert len(lane.calls)==(1 if failure=='bad_output' else 0)
        assert store.db.tasks.find_one({'_id':task['_id']})['state']=='RUNNING'
        assert store.db.messages.count_documents({'direction':'outbound'})==0
    finally:broker.close()
