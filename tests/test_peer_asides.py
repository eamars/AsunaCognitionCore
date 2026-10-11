"""Her sister's lines that don't answer her stop waking her (ADR-045): the bridge marks them, the host keeps the
mark, the router records them without a turn, and her home heartbeat lists them until she speaks on that line."""
import threading
from types import SimpleNamespace

from asuna import lines
from asuna.channels import Channels
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane
from asuna.router import Router
from asuna.schedule_rules import scene_timezone
from test_peer_lines import SCENE, with_line


def test_the_channel_api_keeps_the_aside_mark_and_nothing_else_of_raw(store):
    with_line(store)
    received = []
    controller = SimpleNamespace(app=SimpleNamespace(store=store), stopping=threading.Event(), reconfiguring=False,
                                 receive=lambda event: received.append(event) or {'status': 'accepted'})
    body = {'route_id': 'peer-dm', 'account_id': 'home', 'sender_id': 'peer', 'event_id': 'e1', 'text': '今天天气不错'}
    Channels(controller)._receive('dsh', {**body, 'raw': {'asuna_aside': True, 'other': 1}})
    Channels(controller)._receive('dsh', {**body, 'event_id': 'e2', 'raw': {'asuna_aside': 'yes'}})
    assert received[0]['raw'] == {'asuna_aside': True} and 'asuna_aside' not in received[1]['raw']


def test_an_aside_is_recorded_without_a_turn(store):
    lane = FakeLane(store, [])                            # any turn would fail: none is scripted
    router = Router(store, Coordinator(store, lane))
    event = {'event_id': 'aside-1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '（自言自语）',
             'channel': {'id': 'fixture'}, 'raw': {'asuna_aside': True}}
    assert router.receive(event)['state'] == 'RECEIVED_NO_WAKE'
    row = store.db.messages.find_one({'platform_event_id': 'aside-1'})
    assert row['processing_outcome'] == 'RECORDED_NO_WAKE' and not lane.calls


def test_her_heartbeat_lists_the_asides_until_she_speaks_on_that_line(store):
    with_line(store)
    zone = scene_timezone(store.config, {'_id': 'local'})

    def line(seq, direction, text, aside=False):
        store.db.messages.insert_one({'_id': 'm%d' % seq, 'schema_version': 1, 'scene_id': SCENE, 'scene_seq': seq,
                                      'direction': direction, 'text': text, 'received_at': '2026-10-11T08:%02d:00+00:00' % seq,
                                      **({'phase': 'SPEAK'} if direction == 'outbound' else {}),
                                      **({'event': {'raw': {'asuna_aside': True}}} if aside else {})})
    line(1, 'inbound', '心跳：一切照旧', aside=True)
    assert lines.asides(store, zone)['lines'][0]['items'][0]['text'] == '心跳：一切照旧'
    line(2, 'outbound', '我在呢')
    line(3, 'inbound', '回你：好呀')                        # an answer to her: not an aside
    assert lines.asides(store, zone) is None, 'she spoke on the line after it'
    for seq in range(4, 12):
        line(seq, 'inbound', '心跳 %d' % seq, aside=True)
    out = lines.asides(store, zone)['lines'][0]
    assert [item['text'] for item in out['items']] == ['心跳 %d' % n for n in range(6, 12)] and out['more'] == '更早还有 2 条'
