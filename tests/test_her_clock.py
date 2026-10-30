"""Her one clock (ADR-106): where it comes from, that nothing a room carries changes it, that no zone name reaches a
model, and the one-off that takes the scenes' zones away."""
import itertools
import json
from datetime import datetime, timezone

import pytest

from asuna import dbread, schedule_rules
from asuna.records import plans as plan_records
from asuna.records import scenes as scene_records
from asuna.store.words import Set

ZONE = 'Europe/Berlin'            # personal-scan: ok (unrelated demo DST zone)
ROOM_ZONE = 'Etc/GMT-9'           # what a room used to carry
SENTINEL = 'Pacific/Chatham'      # personal-scan: ok (a distinctive zone: its name must never appear in what she reads)
NOW = datetime(2026, 9, 24, 5, 0, tzinfo=timezone.utc)      # 07:00 in ZONE on a Thursday
TURNS = itertools.count(1)


def test_her_zone_is_the_setting_else_the_machines_else_utc(monkeypatch):
    assert schedule_rules.her_zone({})['source'] == 'unset' and schedule_rules.her_zone({})['name'] == 'UTC'
    monkeypatch.setenv('TZ', ROOM_ZONE)
    assert (schedule_rules.her_zone({})['name'], schedule_rules.her_zone({})['source']) == (ROOM_ZONE, 'machine')
    monkeypatch.setenv('ASUNA_HOST_TIMEZONE', ZONE)
    assert schedule_rules.her_zone({})['name'] == ZONE, 'what the Host reports comes before TZ'
    set_up = schedule_rules.her_zone({'timezone': SENTINEL})
    assert (set_up['name'], set_up['source'], set_up['setting_unreadable']) == (SENTINEL, 'setting', False)
    monkeypatch.setenv('ASUNA_HOST_TIMEZONE', 'Not/AZone')
    assert schedule_rules.her_zone({})['name'] == ROOM_ZONE, 'a name that does not load is passed over'


def test_a_setting_that_does_not_load_is_read_as_not_set_and_says_so(monkeypatch):
    broken = schedule_rules.her_zone({'timezone': 'Mars/Olympus'})
    assert (broken['source'], broken['name'], broken['setting_unreadable']) == ('unset', 'UTC', True)
    monkeypatch.setenv('ASUNA_HOST_TIMEZONE', ZONE)
    on_the_machine = schedule_rules.her_zone({'timezone': 'Mars/Olympus'})
    assert (on_the_machine['source'], on_the_machine['name'], on_the_machine['setting_unreadable']) == ('machine', ZONE, True)
    assert schedule_rules.her_zone({'timezone': ''})['setting_unreadable'] is False, 'an empty setting is not set'


def prepared(world, monkeypatch, scene_id, event_extra=None, moment=NOW):
    from asuna.context import ContextBuilder
    from asuna.ingress import episode_id
    monkeypatch.setattr(schedule_rules, 'now_utc', lambda: moment)
    scene = scene_records.get(world, scene_id)
    event = {'event_id': 'evt-%d' % next(TURNS), 'scene_id': scene_id, 'person_id': scene['members'][0], 'text': 'hi',
             **(event_extra or {})}
    line = {'scene_id': scene_id, 'scope_key': scene['scope_key'], 'policy_epoch': scene['policy_epoch'],
            'direction': 'inbound', 'author': event['person_id'], 'text': 'hi', 'revision': 1}
    if not world.collection('messages').get('earlier-' + scene_id):          # a line said before this turn's own
        world.put('messages', {**line, '_id': 'earlier-' + scene_id, 'scene_seq': 1, 'platform_event_id': 'earlier-' + scene_id,
                               'occurred_at': '2026-09-24T04:30:00+00:00', 'received_at': '2026-09-24T04:30:00+00:00'})
    world.put('messages', {**line, '_id': 'in-' + episode_id(event), 'scene_seq': 2, 'platform_event_id': event['event_id'],
                           'occurred_at': '2026-09-24T04:59:00+00:00', 'received_at': '2026-09-24T04:59:00+00:00'})
    return ContextBuilder(world, retrieval=None).prepare(event)[1]


def test_what_a_room_used_to_carry_changes_nothing(world, monkeypatch):
    """A scene row that still has its `timezone` (the removal not run) is inert: the same moment reads the same in
    every room. The route keys cannot matter: `her_zone` takes only the setting (test_one_zone keeps it so)."""
    world.config['timezone'] = ZONE
    world.collection('scenes').update({'_id': 'g1'}, Set({'timezone': ROOM_ZONE}))
    for scene_id in ('dm-a', 'g1'):
        context = prepared(world, monkeypatch, scene_id)
        assert context['clock_from_program'] == {'now_local': '2026/9/24 07:00', 'weekday': '周四'}, scene_id
    dm = prepared(world, monkeypatch, 'dm-a')
    assert [row['at'] for row in dm['delivered_history']] == ['9/24 06:30'], \
        'a line said at 04:30 UTC reads 06:30 on her clock, not on a room\'s'


def test_no_zone_name_reaches_what_she_reads(world, monkeypatch):
    from asuna import rhythm, visibility
    world.config['timezone'] = SENTINEL
    world.collection('scenes').update({'_id': 'dm-a'}, Set({'timezone': ROOM_ZONE}))
    plan_records.save(world, {'_id': 'plan-1', 'scene_id': 'dm-a', 'scope_key': 'scene:dm-a', 'policy_epoch': 1,
                              'person_id': 'A', 'intent': 'x', 'rule': {'clock': {'time': '09:00'}}, 'timezone': ROOM_ZONE,
                              'status': 'ACTIVE', 'next_fire_at': '2026-09-25T00:00:00+00:00', 'revision': 1}, stream='plan-1')
    seen = [prepared(world, monkeypatch, 'dm-a'),
            prepared(world, monkeypatch, 'dm-a', {'episode_kind': 'scheduled', 'scheduled_plan_id': 'plan-1'}),
            rhythm.rhythm_block(world, {}, {}, visibility.OWNER_PRIVATE, moment=NOW),
            dbread.local_window('2026-09-24 08:00', zone=SENTINEL).asked]
    text = json.dumps(seen, ensure_ascii=False, default=str)
    assert SENTINEL not in text and ROOM_ZONE not in text, 'a zone name reached a model-visible block'
    assert 'tz_note' not in text and '"timezone"' not in text


def test_the_block_she_reads_when_a_plan_comes_due_gives_the_plan_in_words(world, monkeypatch):
    """Not its stored rule: a wall time in it is naive, and a naive time reads as UTC (the plan read nine hours late)."""
    world.config['timezone'] = ZONE
    plan_records.save(world, {'_id': 'plan-2', 'scene_id': 'dm-a', 'scope_key': 'scene:dm-a', 'policy_epoch': 1,
                              'person_id': 'A', 'intent': 'x', 'rule': {'at': '2026-09-25T20:00'}, 'timezone': ZONE,
                              'status': 'ACTIVE', 'next_fire_at': '2026-09-25T18:00:00+00:00', 'revision': 1}, stream='plan-2')
    context = prepared(world, monkeypatch, 'dm-a', {'episode_kind': 'scheduled', 'scheduled_plan_id': 'plan-2'})
    block = context['scheduled_plan_from_program']
    assert 'rule' not in block and block['description'] == '一次性：9/25 20:00' and block['intent'] == 'x', block


def test_clear_timezones_takes_the_field_off_every_scene_once(world):
    carrying = [row['_id'] for row in scene_records.of_kind(world, 'group')]
    for scene_id in carrying:
        world.collection('scenes').update({'_id': scene_id}, Set({'timezone': ROOM_ZONE}))
    before = {row['_id']: {k: v for k, v in row.items() if k != 'timezone'} for row in
              (scene_records.get(world, scene_id) for scene_id in carrying)}
    assert scene_records.timezones(world) == len(carrying) > 0
    assert scene_records.clear_timezones(world) == len(carrying) and scene_records.timezones(world) == 0
    assert scene_records.clear_timezones(world) == 0, 'a second run changes none'
    for scene_id in carrying:
        after = scene_records.get(world, scene_id)
        assert 'timezone' not in after
        assert {k: v for k, v in after.items() if k not in ('revision', '_last_op')} == \
            {k: v for k, v in before[scene_id].items() if k not in ('revision', '_last_op')}
