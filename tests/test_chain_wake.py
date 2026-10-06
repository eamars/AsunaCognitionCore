"""Owner 2026-10-06: a chain (跟队形) in any of her groups calls her once, even mid-burst and where unprompted
speaking is off; night quiet hours and a busy foreground still hold it."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from asuna import proactive
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn
from test_engineering_m1 import THINK
from test_group_admin import BOT, GROUP, SCENE, setup as group_setup

NOON = datetime(2026, 10, 6, 4, 0, tzinfo=timezone.utc)       # 12:00 at +8
EVIDENCE = SimpleNamespace(record=lambda *a, **k: None)


def world(store):
    scene = group_setup(store, 'member')
    route = store.config['channels']['qq']['routes']['g']
    route['members'] = {str(n): {'person_id': 'qq:%d' % n} for n in (20001, 20002, 20003, 20004)}
    assert not proactive.route_settings(store.config, scene)['enabled']        # unprompted speaking is off here
    return store.db.scenes.find_one({'_id': SCENE})


def line(store, n, author, text, *, media=None, outbound=False):
    seq = store.db.scenes.find_one_and_update({'_id': SCENE}, {'$inc': {'sequence': 1}}, return_document=True)['sequence']
    at = (NOON + timedelta(seconds=seq)).isoformat()
    row = {'_id': 'chain-%d' % n, 'scene_id': SCENE, 'policy_epoch': 1, 'scene_seq': seq, 'text': text,
           'received_at': at, 'occurred_at': at}
    if outbound:
        row.update(direction='outbound', author='demo', delivery_state='DELIVERED', receipt_at=at)
    else:
        row.update(direction='inbound', author='qq:%d' % author, event={
            'event_id': 'chain-%d' % n, 'scene_id': SCENE, 'person_id': 'qq:%d' % author, 'text': text,
            'group_context': {'mentioned_account_ids': []},
            'channel': {'id': 'qq', 'account_id': BOT, 'target': {'type': 'group', 'id': GROUP},
                        'sender_id': str(author), 'platform_event_id': 'pe-chain-%d' % n},
            **({'raw': {'asuna_media': {'items': [media]}}} if media else {})})
    store.put('messages', row)
    return row


def consider(store, scene, row, *, at=NOON, can_run=True):
    return proactive.consider(store, EVIDENCE, store.config, scene, row, now_ts=at.timestamp(), can_run=can_run)


def test_three_people_sending_the_same_line_call_her_once(store):
    scene = world(store)
    for n, author in enumerate((20001, 20002)):
        assert consider(store, scene, line(store, n, author, '吃饭了'))[1] is None
    decision, event = consider(store, scene, line(store, 2, 20003, '吃饭了'))
    assert decision['fire'] and decision['signals'] == ['chain']
    group = event['event']['group_context']
    assert group['wake_reason'] == 'chain' and group['chain'] == {'what': '吃饭了', 'people': 3, 'media': False}
    assert consider(store, scene, line(store, 3, 20004, '吃饭了'))[1] is None             # this chain already asked
    # Her own line ends the run: a new chain after it can call her again.
    line(store, 4, 0, '吃饭了', outbound=True)
    for n, author in ((5, 20001), (6, 20002)):
        assert consider(store, scene, line(store, n, author, '下班'))[1] is None
    assert consider(store, scene, line(store, 7, 20003, '下班'))[1] is not None


def test_two_people_or_the_same_person_are_not_a_chain(store):
    scene = world(store)
    for n, author in enumerate((20001, 20002, 20002, 20001)):
        assert consider(store, scene, line(store, n, author, '+1'))[1] is None


def test_the_same_sticker_is_a_chain_and_night_or_a_busy_foreground_hold_it(store):
    scene = world(store)
    sticker = {'type': 'image', 'file': 'A' * 32 + '.png', 'sub_type': '1', 'sticker': 'custom'}
    for n, author in enumerate((20001, 20002)):
        line(store, n, author, '[表情包]', media=sticker)
    row = line(store, 2, 20003, '[表情包]', media=sticker)
    night = NOON.replace(hour=16)                                  # 00:00 at +8, inside the default quiet hours
    store.config['channels']['qq']['routes']['g']['proactive'] = {'enabled': False, 'utc_offset_minutes': 480}
    decision, event = consider(store, scene, row, at=night)
    assert not decision['fire'] and decision['holds'] == ['quiet_hours'] and event is None
    assert consider(store, scene, row, can_run=False)[0]['holds'] == ['foreground_busy']
    decision, event = consider(store, scene, row)
    assert decision['fire'] and event['event']['group_context']['chain']['media'] is True


def test_her_turn_reads_the_chain(store):
    scene = world(store)
    for n, author in enumerate((20001, 20002)):
        line(store, n, author, '吃饭了')
    _, event = consider(store, scene, line(store, 2, 20003, '吃饭了'))
    lane = FakeLane(store, [FakeTurn([THINK], '吃饭了')])
    ep = Coordinator(store, lane).ingest(event['event'], persona='P1')
    chain = ep['context']['group_continuity_from_program']['chain_from_program']
    assert chain['what'] == '吃饭了' and chain['people'] == '3 个人接连发了这个'
