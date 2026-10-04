"""Local contracts; real DSH/model/Web evidence is in ADR003-CONSULT-REPORT.md."""
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from asuna.coordinator import Coordinator
from asuna.lanes import LaneResult
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
        assert calls[0][0]=='demo:dm-a:1:P1:original-role-context'
        assert calls[0][2]=='CONSULT' and '323' in calls[0][3]
        assert 'scene:dm-b' not in calls[0][3]
        assert store.db.episodes.find_one({'_id':ep['_id']})==ep
        assert before=={c:store.db[c].count_documents({}) for c in before}
        assert service.valid(task)['goal']==task['goal']
        assert broker.call('caller','question','consult_character',{'question':'按当前关系怎么呈现？','context':'计算结果 323'})==result
        assert len(calls)==1
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


