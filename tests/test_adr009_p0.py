"""ADR-009 P0 MongoDB tests: T0.4 (system_ref), T0.6 (action prompt carries no persona text)."""
import json
import re
import uuid

from bson import BSON

from asuna.config import ROOT
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, LaneResult
from asuna.render import render_system
from asuna.tasks import TaskService, ToolBroker, Executor
from conftest import FIXTURES
from test_engineering_m1 import event, decision


def test_T0_4_episode_keeps_system_ref_not_system_text(store):
    body = '# 合成大人格\n' + ''.join('第%05d句：这是只用于测试的合成人格正文，用来把渲染撑到七十千字节。\n' % i for i in range(1100))
    assert len(body.encode()) >= 70 * 1024
    store.init_head('persona:P70', 'global-safe', {'body': body}, [])
    lane = FakeLane(store, [LaneResult('想一想。'), decision(), LaneResult('回来了。')])
    ep = Coordinator(store, lane).ingest(event('big-persona'), persona='P70')
    assert ep['state'] == 'COMMITTED'
    doc = store.db.episodes.find_one({'_id': ep['_id']})
    assert 'system' not in doc
    ref = doc['system_ref']
    assert {'persona_doc_revision', 'common_sha256', 'render_sha256'} <= set(ref)
    assert ref['persona_doc_revision'] == store.head('doc:P70:persona', 'global-safe')[0]['revision_id']
    assert len(BSON.encode(doc)) <= 64 * 1024
    rendered, _ = render_system(store, 'P70')
    assert [call['messages'][0]['content'] for call in lane.calls] == [rendered] * 3
    # An episode prepared before the upgrade still carries its full system text and resumes with it.
    legacy = {k: v for k, v in doc.items() if k not in ('system_ref', 'decision', 'speech', 'revision', '_last_op',
                                                         'schema_version', 'native_session_id')}
    legacy.update(_id='ep-legacy-' + uuid.uuid4().hex[:8], source_event_id='legacy-in-flight', state='PREPARED',
                  monologue_refs=[], system='LEGACY_SYSTEM_TEXT_FROM_BEFORE_THE_UPGRADE')
    store.put('episodes', legacy, stream=legacy['_id'])
    old = FakeLane(store, [LaneResult('接着想。'), decision(), LaneResult('接着说。')])
    resumed = Coordinator(store, old).advance(legacy['_id'])
    assert resumed['state'] == 'COMMITTED'
    assert {call['messages'][0]['content'] for call in old.calls} == {'LEGACY_SYSTEM_TEXT_FROM_BEFORE_THE_UPGRADE'}


def test_T0_6_group_action_prompt_has_no_persona_sentence(store):
    work = ROOT / '.runtime/work' / ('adr009-t06-' + uuid.uuid4().hex)
    work.mkdir(parents=True)
    store.config.update(task_mode='workspace', chat={**store.config['chat'], 'display_name': '示例角色'},
                        channels={'fixture': {'routes': {'group': {
                            'scene_id': 'g1', 'target': {'type': 'group', 'id': 'fixture-group'},
                            'members': {'fixture-sender': {'person_id': 'A', 'workspace': str(work), 'read_only_paths': []}}}}}})
    plan = {'next': 'delegate', 'goal': '整理一份公开清单', 'constraints': [], 'recall_query': '', 'speak_before_action': False}
    ep = Coordinator(store, FakeLane(store, [LaneResult('交给行动脑。'), LaneResult(json.dumps(plan))])).ingest(
        event('group-task', scene='g1', person='A', text='帮忙整理一份公开清单'))
    assert ep['task_id']
    seen = []

    class ActionLane:
        def generate(self, binding, operation, phase, text, system):
            seen.append(system)
            return LaneResult('清单已整理。')

    service = TaskService(store)
    broker = ToolBroker(service)
    try:
        Executor(service, ActionLane(), broker).run(ep['task_id'], work)
    finally:
        broker.close()
    assert seen, 'the action lane was called'
    persona = (FIXTURES / 'personas/p1_demo.md').read_text(encoding='utf-8')
    sentences = [s.strip() for s in re.split(r'[。\n]', persona) if len(s.strip()) >= 6 and not s.startswith('#')]
    assert sentences
    for system in seen:
        assert not [s for s in sentences if s in system]
        assert '示例角色' in system
