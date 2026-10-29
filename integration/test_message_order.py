"""On MongoDB: her lines leave in their order (ADR-009 T5.4). A reply of three parts is three lines numbered in order,
claimed by the channel one at a time, each only once the one before it is settled, all delivered in that order. On a
throwaway database holding the fixture world (conftest.py)."""
from types import SimpleNamespace
import threading

from asuna import channel_kinds
from asuna.channels import Channels
from asuna.coordinator import Coordinator
from asuna.ingress import persist_input
from asuna.lanes import FakeLane, FakeTurn
from asuna.records import messages as message_records
from asuna.records import scenes as scene_records
from reply_parts import said

PARTS = ('第一段，先说这个。', '第二段。', '第三段收尾。')
TARGET = {'type': 'dm', 'id': 'peer'}
THINK = ('think', {'thought': '他说了一件小事，值得记下来。'})


def model(max_messages):
    return {'model_version': 1, 'persona': {'id': 'P1', 'display_name': 'x'},
            'speak': {'max_messages': max_messages, 'chars_per_second': 4, 'min_gap_s': 1, 'max_gap_s': 3}}


def channel_scene(store, monkeypatch):
    store.config['channels'] = {'replay': {'token': 'x' * 32, 'account_id': 'bot', 'routes': {
        'peer': {'scene_id': 'dm-a', 'sender_id': 'peer', 'person_id': 'A', 'target': TARGET}}}}
    scene = scene_records.get(store, 'dm-a')
    scene_records.save(store, {**scene, 'channel_id': 'replay'}, expected=scene['revision'])
    # A kind where she speaks only through reply (the QQ kind declares this; the test channel stands in for it).
    monkeypatch.setattr(channel_kinds, 'reply_parts',
                        lambda scene_id: ('text', 'sticker', 'picture') if scene_id == 'dm-a' else ())


def turn(store):
    lane = FakeLane(store, [FakeTurn([THINK, said(*PARTS)], '')])
    coordinator = Coordinator(store, lane)
    event = {'event_id': 'one', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '你好',
             'channel': {'id': 'replay', 'account_id': 'bot', 'target': TARGET, 'platform_event_id': 'p-one'}}
    persist_input(store, event, managed=True)
    return coordinator.ingest(event)


def outbound(store, ep_id):
    return message_records.turn_parts(store, ep_id).rows()


def release(store, rows):
    """Move pacing into the past so the test does not sleep."""
    for row in rows:
        fresh = message_records.get(store, row['_id'])
        message_records.save(store, {**fresh, 'not_before': '2000-01-01T00:00:00+00:00'}, expected=fresh['revision'],
                             stream=fresh['episode_id'])


def test_T5_4_paced_parts_deliver_in_order_and_hold_the_line(world, monkeypatch):
    store = world
    store.config['persona_model'] = model(3)
    channel_scene(store, monkeypatch)
    ep = turn(store)
    rows = outbound(store, ep['_id'])
    bridge = Channels(SimpleNamespace(app=SimpleNamespace(store=store), stopping=threading.Event(), reconfiguring=False))
    for index in range(3):
        release(store, rows[index:index + 1])
        item = bridge.claim('replay')['items'][0]
        assert item['publication_id'] == rows[index]['_id']
        body = {'attempt_id': item['attempt_id'], 'status': 'platform_accepted', 'response': {},
                'platform_message_id': 'm-' + item['publication_id']}
        assert bridge.receipt('replay', item['publication_id'], body) == {'status': 'DELIVERED'}
    assert [row['delivery_state'] for row in outbound(store, ep['_id'])] == ['DELIVERED'] * 3
