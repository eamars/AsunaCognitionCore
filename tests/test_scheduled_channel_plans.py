"""Her plans that come due in a platform conversation (a group or a QQ DM): MongoDB, a real Chat worker, a
scripted turn. A due plan is a core notice, not a platform input: it must reach her, and must not be shown
in that conversation's session as something a member said."""
import time
from types import SimpleNamespace

import pytest

from asuna.chat import Chat
from asuna.coordinator import Coordinator
from asuna.evidence import Evidence
from asuna.lanes import FakeLane, FakeTurn
from asuna.router import Router
from test_adr009_p5_rhythm import fire, scheduler
from test_engineering_m1 import THINK


def platform_world(store):
    store.config['channels'] = {'qq': {'account_id': 'acct', 'routes': {
        'r-group': {'scene_id': 'g1', 'target': {'type': 'group', 'id': 'G1'},
                    'members': {'s-a': {'person_id': 'A'}, 's-b': {'person_id': 'B'}}},
        'r-dm': {'scene_id': 'dm-b', 'target': {'type': 'dm', 'id': 's-b'}, 'sender_id': 's-b', 'person_id': 'B'}}}}
    store.db.scenes.update_many({'_id': {'$in': ['g1', 'dm-b']}}, {'$set': {'channel_id': 'qq', 'channel_account_id': 'acct'}})


@pytest.mark.parametrize('scene, person, target', [('g1', 'A', {'type': 'group', 'id': 'G1'}),
                                                   ('dm-b', 'B', {'type': 'dm', 'id': 's-b'})])
def test_a_plan_due_in_a_platform_conversation_reaches_her_and_is_said_there(store, tmp_path, scene, person, target):
    service = scheduler(store)
    platform_world(store)
    lane = FakeLane(store, [FakeTurn([THINK], '到点啦，记得喝水。')])
    app = SimpleNamespace(store=store, config=store.config, evidence=Evidence(tmp_path / 'evidence'),
                          character=lane, router=Router(store, Coordinator(store, lane)))
    chat = Chat(app, {'scene_id': 'dm-a', 'person_id': 'A', 'persona': 'P1', 'display_name': '演示'}, lambda _: None)
    projected = []
    # What the native worker projects into a platform conversation as a member's message (project_input).
    chat.on_input_received = lambda row: projected.append(row) if row.get('event', {}).get('channel') else None
    service.controller = chat
    ep = {'_id': 'ep-made-the-plan', 'scene_id': scene, 'person_id': person, 'scope_key': 'scene:' + scene,
          'policy_epoch': store.db.scenes.find_one({'_id': scene})['policy_epoch']}
    plan = service.create(ep, {'intent': '提醒大家喝水', 'after_seconds': 60})
    fire(service, plan)
    row = store.db.messages.find_one({'event.episode_kind': 'scheduled', 'scene_id': scene})
    assert row and not projected                     # a core notice, never shown as a member's message
    chat.worker.start()
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            row = store.db.messages.find_one({'_id': row['_id']})
            # Settled, and the worker has let go of it (it marks the input before it clears its turn).
            if row.get('ingress_state') in ('COMPLETE', 'FAILED') and not chat.pending.unfinished_tasks:
                break
            time.sleep(.05)
    finally:
        chat.stop()
    assert row['ingress_state'] == 'COMPLETE', row.get('failure')
    said = store.db.messages.find_one({'scene_id': scene, 'direction': 'outbound', 'phase': 'SPEAK'})
    assert said and said['text'] == '到点啦，记得喝水。'
    assert said['delivery_state'] == 'QUEUED_EXTERNAL' and said['target'] == target and said['platform_reply_to'] is None
