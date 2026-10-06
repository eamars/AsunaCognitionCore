"""Her watchlist (owner 2026-10-06): someone she watches speaks anywhere; she hears of it where they spoke."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import threading

import pytest

from asuna import attend, visibility, watches
from asuna.channels import Channels
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn
from test_engineering_m1 import THINK
from test_group_admin import BOT, GROUP, SCENE, setup as group_setup


def world(store):
    group_setup(store, 'member')
    store.config['channels']['qq']['routes']['g']['members'] = {
        '20002': {'person_id': 'qq:20002'}, '20003': {'person_id': 'qq:20003'}}
    persona = store.config['chat']['persona']
    scene = store.db.scenes.find_one({'_id': SCENE})
    ep = {'scene_id': SCENE, 'scope_key': scene['scope_key'], 'policy_epoch': scene['policy_epoch'], 'persona': persona}
    return persona, ep


def intake(store):
    """The channel intake with a controller that keeps what it was given."""
    given = []
    controller = SimpleNamespace(app=SimpleNamespace(store=store), ingress_lock=threading.Lock(), reconfiguring=False,
                                 stopping=threading.Event(), receive=lambda event: given.append(event) or {'status': 'ok'})
    channels = Channels(controller)

    def line(sender, key, mentions=()):
        channels._receive('qq', {'route_id': 'g', 'account_id': BOT, 'sender_id': sender, 'event_id': key,
                                 'text': '在吗', 'group_id': GROUP, 'mentioned_account_ids': list(mentions)})
        return given[-1]
    return line


def test_a_watched_person_speaking_gets_her_one_look_where_they_spoke(store):
    persona, ep = world(store)
    line = intake(store)
    assert 'watched' not in line('20002', 'e0') and line('20002', 'e0b')['group_context']['wake_reason'] is None
    added = watches.add(store, ep, persona, visibility.PUBLIC, {'person': 'qq:20002', 'hours': 3, 'why': '等他回图纸的事'})
    assert added['watching'] == '阿杰' and added['for'] == '3 小时'
    event = line('20002', 'e1')
    assert event['watched'] == added['id'] and event['group_context']['wake_reason'] == 'watched'
    assert attend.gated({'kind': 'group'}, event)
    assert 'watched' not in line('20002', 'e2')                       # once: the first time, then the watch is done
    assert 'watched' not in line('20003', 'e3')                       # someone else
    assert store.db.watches.find_one({'_id': added['id']})['state'] == 'done'
    # Addressed to her already: the line keeps its own wake reason, and her turn still knows who it is.
    watches.add(store, ep, persona, visibility.PUBLIC, {'person': 'qq:20002', 'hours': 3})
    event = line('20002', 'e4', mentions=[BOT])
    assert event['group_context']['wake_reason'] == 'mentioned_account' and event['watched']
    block = watches.watched_block(store, event, visibility.PUBLIC)
    assert block['who'] == '阿杰' and 'watch' in block['note']


def test_burst_watches_fire_again_only_after_a_silence_and_expire_into_one_line(store, monkeypatch):
    persona, ep = world(store)
    added = watches.add(store, ep, persona, visibility.OWNER_PRIVATE,
                        {'person': 'qq:20002', 'hours': 1, 'mode': 'burst', 'why': '主人让我留意他'})
    start = datetime.now(timezone.utc)
    fired = [bool(watches.seen(store, 'qq:20002', start + timedelta(minutes=m))) for m in (0, 1, 5, 16, 17)]
    assert fired == [True, False, False, True, False]                 # a burst is one look; 10 quiet minutes start a new one
    # A why written at home is read only at home.
    home = watches.watching_block(store, persona, visibility.OWNER_PRIVATE, start)
    public = watches.watching_block(store, persona, visibility.PUBLIC, start)
    assert home['items'][0]['why'] == '主人让我留意他' and 'why' not in public['items'][0]
    assert home['items'][0]['id'] == added['id'] and home['items'][0]['left'] == '不到一小时'
    # Expired: no turn of its own; her next turn has one line on how it went, once.
    later = start + timedelta(hours=2)
    assert watches.seen(store, 'qq:20002', later) is None
    ended = watches.watching_block(store, persona, visibility.PUBLIC, later)
    assert ended == {'ran_out': [{'who': '阿杰', 'ended': '到期了，盯着的这段时间他出现过两次'}]}
    assert watches.watching_block(store, persona, visibility.PUBLIC, later) is None
    # Limits: hours, someone not in this conversation, a full list; off by id.
    with pytest.raises(Exception, match='WATCH_HOURS_INVALID'):
        watches.add(store, ep, persona, visibility.PUBLIC, {'person': 'qq:20002', 'hours': 73})
    with pytest.raises(Exception, match='WATCH_PERSON_NOT_HERE'):
        watches.add(store, ep, persona, visibility.PUBLIC, {'person': 'qq:55555', 'hours': 2})
    monkeypatch.setattr(watches, 'WATCH_MAX', 1)
    first = watches.add(store, ep, persona, visibility.PUBLIC, {'person': 'qq:20002', 'hours': 2})
    with pytest.raises(Exception, match='WATCH_LIST_FULL'):
        watches.add(store, ep, persona, visibility.PUBLIC, {'person': 'qq:20003', 'hours': 2})
    assert watches.add(store, ep, persona, visibility.PUBLIC, {'person': 'qq:20002', 'hours': 5})['for'] == '5 小时'
    assert watches.stop(store, persona, first['id']) == {'stopped': '阿杰'}
    with pytest.raises(Exception, match='WATCH_NOT_FOUND'):
        watches.stop(store, persona, first['id'])


def test_she_adds_a_watch_from_her_turn_and_sees_her_list_after(store):
    world(store)
    persona = 'P1'                                                    # the fixture world's persona documents
    event = {'event_id': 'w-1', 'scene_id': SCENE, 'person_id': 'qq:20002', 'text': '@演示 帮我盯着老王',
             'group_context': {'wake_reason': 'mentioned_account', 'topic_id': 'w-1', 'mentioned_account_ids': [BOT]},
             'channel': {'id': 'qq', 'account_id': BOT, 'target': {'type': 'group', 'id': GROUP},
                         'sender_id': '20002', 'platform_event_id': 'w-1'}}
    lane = FakeLane(store, [FakeTurn([THINK, ('watch', {'op': 'on', 'person': 'qq:20003', 'hours': 6, 'why': '等他说打印机'})],
                                     '好，我盯着'),
                            FakeTurn([THINK], '还在盯')])
    coordinator = Coordinator(store, lane)
    first = coordinator.ingest(event, persona=persona)
    assert first['state'] in ('COMMITTED', 'WAITING_TASK'), first.get('failure')
    assert 'watch' in lane.calls[0]['tools']
    [result] = [row for row in lane.tool_results if row[2] == 'watch']
    assert result[5] is True, result
    second = coordinator.ingest({**event, 'event_id': 'w-2', 'group_context': {**event['group_context'], 'topic_id': 'w-2'},
                                 'channel': {**event['channel'], 'platform_event_id': 'w-2'}}, persona=persona)
    [item] = second['context']['watching_from_program']['items']
    assert item['who'] == '老王' and item['why'] == '等他说打印机'
