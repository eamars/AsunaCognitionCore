"""A platform line belongs to the first turn that had it in view (MongoDB, a real Chat worker, a scripted turn).

Two lines reach her in a QQ DM before her turn begins, or while it runs; that turn has both in view and answers
them. The second line must not get a turn of its own: the same words are never sent twice."""
import time
from types import SimpleNamespace

from asuna.chat import Chat
from asuna.coordinator import Coordinator
from asuna.evidence import Evidence
from asuna.lanes import FakeLane, FakeTurn
from asuna.router import Router
from test_engineering_m1 import THINK
from test_scheduled_channel_plans import platform_world


def line(key, text):
    return {'event_id': key, 'scene_id': 'dm-b', 'person_id': 'B', 'text': text,
            'channel': {'id': 'qq', 'account_id': 'acct', 'target': {'type': 'dm', 'id': 's-b'}, 'sender_id': 's-b',
                        'platform_event_id': 'p-' + key}}


def settled(store, chat, ids):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        rows = [store.db.messages.find_one({'_id': i}) for i in ids]
        if all(r.get('ingress_state') in ('COMPLETE', 'FAILED') for r in rows) and not chat.pending.unfinished_tasks:
            return rows
        time.sleep(.05)
    raise AssertionError([r.get('ingress_state') for r in rows])


def test_a_line_she_already_saw_gets_no_second_turn(store, tmp_path):
    platform_world(store)
    lane = FakeLane(store, [])
    app = SimpleNamespace(store=store, config=store.config, evidence=Evidence(tmp_path / 'evidence'),
                          character=lane, router=Router(store, Coordinator(store, lane)))
    chat = Chat(app, {'scene_id': 'dm-a', 'person_id': 'A', 'persona': 'P1', 'display_name': '演示'}, lambda _: None)
    first = chat.receive(line('l1', '谢谢小满，你最近回得好快！'))['episode_id']
    second = chat.receive(line('l2', 'Claude 还在教小满说话'))['episode_id']
    # Her turn for the first line had the second in view too, and answered both.
    lane.outputs = iter([FakeTurn([THINK], '他教没教我不好说。', said=['那必须的，被夸了我会更来劲。'],
                                  seen=['in-' + first, 'in-' + second])])
    chat.worker.start()
    try:
        rows = settled(store, chat, ['in-' + first, 'in-' + second])
    finally:
        chat.stop()
    assert rows[0]['result_state'] == 'COMMITTED'
    assert rows[1]['absorbed_by'] == first and rows[1]['result_state'] == 'SEEN_IN_TURN'
    assert len(lane.calls) == 1, 'one turn for the two lines'
    said = [m['text'] for m in store.db.messages.find({'scene_id': 'dm-b', 'direction': 'outbound', 'phase': 'SPEAK'})
            .sort('scene_seq', 1)]
    assert said == ['那必须的，被夸了我会更来劲。\n\n他教没教我不好说。']           # core default: one message
    assert store.db.audit_events.count_documents({'stream_id': first, 'type': 'input.absorbed'}) == 1


def test_a_reply_she_wrote_again_after_a_tool_leaves_once(store, tmp_path):
    platform_world(store)
    lane = FakeLane(store, [FakeTurn([THINK], '……叫错人了。我是カズサ。',
                                     said=['……叫错人了。我是カズサ。'])])
    Router(store, Coordinator(store, lane)).receive(line('l3', '小满？'))
    said = [m['text'] for m in store.db.messages.find({'scene_id': 'dm-b', 'direction': 'outbound', 'phase': 'SPEAK'})]
    assert said == ['……叫错人了。我是カズサ。']
