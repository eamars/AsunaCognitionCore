"""ADR-009 T5.9 on MongoDB, kept by ADR-104 decision 9 (a break would lose her data): a crash between her reply's parts
still sends what the reply queued."""
from types import SimpleNamespace
import threading

import pytest

from asuna.records import scenes as scene_records
from asuna import channel_kinds
from asuna.channels import Channels
from asuna.coordinator import Coordinator
from asuna.ingress import persist_input
from asuna.lanes import FakeLane, FakeTurn

from reply_parts import said

pytestmark = pytest.mark.world                # `store` is the fixture world

PARTS = ('第一段，先说这个。', '第二段。', '第三段收尾。')
TARGET = {'type': 'dm', 'id': 'peer'}

THINK = ('think', {'thought': '他说了一件小事，值得记下来。'})


def model(max_messages):
    return {'model_version': 1, 'persona': {'id': 'P1', 'display_name': 'x'},
            'speak': {'max_messages': max_messages, 'chars_per_second': 4, 'min_gap_s': 1, 'max_gap_s': 3}}


def channel_scene(store, monkeypatch=None):
    store.config['channels'] = {'replay': {'token': 'x' * 32, 'account_id': 'bot', 'routes': {
        'peer': {'scene_id': 'dm-a', 'sender_id': 'peer', 'person_id': 'A', 'target': TARGET}}}}
    scene = store.raw.scenes.find_one({'_id': 'dm-a'})
    scene_records.save(store, {**scene, 'channel_id': 'replay'}, expected=scene['revision'])
    if monkeypatch:
        # A kind where she speaks only through reply (the QQ kind declares this; the test channel stands in for it).
        monkeypatch.setattr(channel_kinds, 'reply_parts',
                            lambda scene_id: ('text', 'sticker', 'picture') if scene_id == 'dm-a' else ())


def turn(store, key='one', crash=None, calls=None, channel=True, content=''):
    lane = FakeLane(store, [FakeTurn([THINK, *(calls if calls is not None else [said(*PARTS)])], content)])
    coordinator = Coordinator(store, lane)
    event = {'event_id': key, 'scene_id': 'dm-a', 'person_id': 'A', 'text': '你好'}
    if channel:
        event['channel'] = {'id': 'replay', 'account_id': 'bot', 'target': TARGET, 'platform_event_id': 'p-' + key}
        persist_input(store, event, managed=True)
    if crash:
        coordinator.crash = crash
    return coordinator, coordinator.ingest(event), lane


def outbound(store, ep_id):
    return list(store.raw.messages.find({'episode_id': ep_id, 'phase': 'SPEAK'}).sort('scene_seq', 1))


def channels(store):
    return Channels(SimpleNamespace(app=SimpleNamespace(store=store), stopping=threading.Event(), reconfiguring=False))


def test_T5_9_a_crash_between_parts_still_sends_what_reply_queued(store, monkeypatch):
    store.config['persona_model'] = model(3)
    channel_scene(store, monkeypatch)
    calls = []

    def crash(point):
        if point == 'after_reply_part_publish' and not calls:
            calls.append(point)
            raise RuntimeError('crash between parts')
    with pytest.raises(RuntimeError, match='crash between parts'):
        turn(store, crash=crash)
    ep = store.raw.episodes.find_one({'state': 'TURN'})
    before = outbound(store, ep['_id'])
    assert [r['delivery_state'] for r in before] == ['QUEUED_EXTERNAL', 'READY', 'READY']
    coordinator = Coordinator(store, FakeLane(store, [FakeTurn([THINK, ('stay_silent', {'why': '说完了'})])]))
    coordinator.recover()
    after = outbound(store, ep['_id'])
    assert [r['_id'] for r in after] == [r['_id'] for r in before], 'no new rows on recovery'
    assert [r['delivery_state'] for r in after] == ['QUEUED_EXTERNAL'] * 3


