"""Her own open/close of a peer line (ADR-013 §6): lines.py, the channel API gate, and her tool."""
import threading
from datetime import datetime, timezone
from types import SimpleNamespace

from asuna import channel_kinds, lines
from asuna.channels import Channels
from asuna.config import ROOT

channel_kinds.load([{'python': ROOT / 'packages' / 'channels' / 'dsh-peer' / 'python', 'module': 'dsh_peer'}])
SCENE = 'dsh:home:dm:peer'


def with_line(store):
    store.config['channels'] = {**store.config.get('channels', {}), 'dsh': {'account_id': 'home', 'token': 't' * 24,
        'routes': {'peer-dm': {'person_id': 'dsh:peer', 'scene_id': SCENE, 'sender_id': 'peer',
                               'target': {'type': 'dm', 'id': 'peer'}, 'workspace': str(ROOT / '.runtime/channels/x')}}}}
    return lines.peer_lines(store)


def test_she_closes_for_an_hour_until_morning_or_until_she_reopens(store):
    [line] = with_line(store)
    assert line == {'scene_id': SCENE, 'person_id': 'dsh:peer', 'label': 'dsh:peer'}
    moment = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)              # 21:00 in Etc/GMT-9 (+9)
    assert not lines.is_closed(store, SCENE, moment)
    assert lines.describe(None, 'UTC').startswith('开着')
    lines.set_line(store, SCENE, closed=True, choice='until_morning', zone='Etc/GMT-9', moment=moment)
    until = lines.closed_until(store, SCENE, moment)
    assert until == datetime(2026, 10, 5, 23, 0, tzinfo=timezone.utc)      # 08:00 the next local morning
    assert '10月6日 08:00' in lines.describe(until, 'Etc/GMT-9')
    assert not lines.is_closed(store, SCENE, datetime(2026, 10, 5, 23, 1, tzinfo=timezone.utc))   # it reopens by itself
    lines.set_line(store, SCENE, closed=True, choice='until_reopened', zone='UTC', moment=moment)
    assert lines.closed_until(store, SCENE, moment) == 'reopen' and '等你自己打开' in lines.describe('reopen', 'UTC')
    lines.set_line(store, SCENE, closed=False, moment=moment)
    assert not lines.is_closed(store, SCENE, moment)
    lines.set_line(store, SCENE, closed=True, choice='an_hour', zone='UTC', moment=moment)
    assert lines.closed_until(store, SCENE, moment) == datetime(2026, 10, 5, 13, 0, tzinfo=timezone.utc)


def test_the_channel_api_passes_a_closed_lines_messages_over(store):
    with_line(store)
    received = []
    controller = SimpleNamespace(app=SimpleNamespace(store=store), stopping=threading.Event(), reconfiguring=False,
                                 receive=lambda event: received.append(event) or {'status': 'accepted'})
    body = {'route_id': 'peer-dm', 'account_id': 'home', 'sender_id': 'peer', 'event_id': 'e1', 'text': 'night bell'}
    lines.set_line(store, SCENE, closed=True, choice='until_reopened')
    assert Channels(controller)._receive('dsh', body) == {'status': 'line_closed'} and received == []
    lines.set_line(store, SCENE, closed=False)
    assert Channels(controller)._receive('dsh', {**body, 'event_id': 'e2'}) == {'status': 'accepted'}
    assert received[0]['scene_id'] == SCENE and received[0]['person_id'] == 'dsh:peer'


def test_only_a_peer_line_kind_counts(store):
    store.config['channels'] = {'qq': {'account_id': '10001', 'token': 'q' * 24, 'routes': {}}}
    assert lines.peer_lines(store) == []


def test_in_the_line_she_sees_it_and_closes_it_herself(store):
    from asuna.coordinator import Coordinator
    from asuna.lanes import FakeLane, FakeTurn
    with_line(store)
    store.put('scenes', {'_id': SCENE, 'scene_id': SCENE, 'kind': 'dm', 'members': ['dsh:peer'],
                         'scope_key': 'scene:' + SCENE, 'policy_epoch': 1, 'sequence': 0,
                         'channel_id': 'dsh', 'channel_account_id': 'home'})
    turn = FakeTurn([('think', {'thought': '那边在值夜，我先睡。'}),
                     ('peer_line', {'line': 'dsh:peer', 'op': 'close', 'close_for': 'until_morning'})], '我先睡了，早上见。')
    lane = FakeLane(store, [turn])
    Coordinator(store, lane).ingest({'event_id': 'line-1', 'scene_id': SCENE, 'person_id': 'dsh:peer', 'text': '还醒着吗',
                                     'channel': {'id': 'dsh', 'account_id': 'home', 'platform_event_id': 'e1',
                                                 'target': {'type': 'dm', 'id': 'peer'}, 'sender_id': 'peer'}})
    assert lines.is_closed(store, SCENE)
    assert any('关着，到' in str(result) for result in lane.tool_results)


def test_from_home_she_plans_a_turn_in_a_peer_line(store):
    """Owner 2026-10-06: at home she can time a turn in the line (both ends are home); it fires there."""
    from asuna.coordinator import Coordinator
    from asuna.lanes import FakeLane, FakeTurn
    from test_adr009_p5_rhythm import fire, scheduler
    service = scheduler(store)
    with_line(store)
    store.put('scenes', {'_id': SCENE, 'scene_id': SCENE, 'kind': 'dm', 'members': ['dsh:peer'],
                         'scope_key': 'scene:' + SCENE, 'policy_epoch': 1, 'sequence': 0,
                         'channel_id': 'dsh', 'channel_account_id': 'home'})
    received = []
    service.controller.receive = received.append
    turn = FakeTurn([('think', {'thought': '晚点问她太阳能的事。'}),
                     ('plan', {'op': 'create', 'intent': '问她太阳能读数', 'after_seconds': 600, 'line': 'dsh:peer'})], '好')
    lane = FakeLane(store, [turn, FakeTurn([('think', {'thought': '嗯'})], '嗯')])
    coordinator = Coordinator(store, lane)
    coordinator.scheduler = service
    ep = coordinator.ingest({'event_id': 'home-1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '你想问旧居什么'})
    assert ep['state'] == 'COMMITTED', ep.get('failure')
    assert all(row[5] for row in lane.tool_results if row[2] == 'plan'), lane.tool_results
    plan = store.db.plans.find_one({'intent': '问她太阳能读数'})
    assert (plan['scene_id'], plan['person_id'], plan['from_scene_id']) == (SCENE, 'dsh:peer', 'dm-a')
    later = coordinator.ingest({'event_id': 'home-2', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '挂上了吗'})
    [item] = later['context']['lines_from_program']['items']
    assert item['your_plans_there'][0]['intent'] == '问她太阳能读数'
    fire(service, plan)
    assert received and received[-1]['scene_id'] == SCENE and received[-1]['episode_kind'] == 'scheduled'
