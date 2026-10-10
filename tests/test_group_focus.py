"""Her active and resting groups (ADR-039): in a resting group only what is meant for her wakes her, nothing is
summarized, and an @ brings the group's recent lines; she chooses, an admin group stays active, and the usual number
of active groups is a soft limit that says what going past it costs."""
from datetime import datetime, timedelta, timezone

import pytest

from asuna import focus
from asuna.context import catch_up
from asuna.places import place_id

GROUPS = ('g-quiet', 'g-mine', 'g-admin', 'g-four', 'g-five')


def world(store, limit=2):
    store.config['active_groups'] = limit
    store.config['channels'] = {'qq': {'account_id': 'bot', 'routes': {
        name: {'scene_id': name, 'sender_id': '*', 'person_id': 'qq:A', 'target': {'type': 'group', 'id': name}}
        for name in GROUPS}}}
    for name in GROUPS:
        if not store.db.scenes.find_one({'_id': name}):
            store.put('scenes', {'_id': name, 'kind': 'group', 'scope_key': 'scene:' + name, 'policy_epoch': 1,
                                 'members': [], 'sequence': 7, 'summary_start_seq': 0}, stream=name)
    store.db.scene_people.insert_one({'_id': 'g-admin|demo', 'schema_version': 1, 'scene_id': 'g-admin',
                                      'person': 'demo', 'handle': 0, 'role': 'admin'})
    mine = store.db.scenes.find_one({'_id': 'g-mine'})
    store.put('scenes', {**mine, 'focus_active': True}, expected=mine['revision'], stream='g-mine')
    return {name: store.db.scenes.find_one({'_id': name}) for name in GROUPS}


def test_a_resting_group_wakes_her_only_for_what_is_meant_for_her(store):
    scenes = world(store)
    quiet, mine, admin = scenes['g-quiet'], scenes['g-mine'], scenes['g-admin']
    assert not focus.active(store, quiet) and focus.active(store, mine) and focus.active(store, admin)
    for reason in focus.RESTING_WAKES:
        assert focus.wake(store, quiet, reason) == reason
    for reason in ('proactive_unprompted', 'name_called', 'reply_in_active_topic', 'chain'):
        assert focus.wake(store, quiet, reason) is None
        assert focus.wake(store, mine, reason) == reason and focus.wake(store, admin, reason) == reason
    assert focus.active(store, {'_id': 'dm', 'kind': 'dm'})          # only groups rest


def test_she_chooses_an_admin_group_stays_and_the_usual_number_is_a_soft_limit(store):
    scenes = world(store, limit=2)
    with pytest.raises(ValueError, match='管理员'):
        focus.set_focus(store, {}, scenes['g-admin'], False, 'P1')
    # Active now: g-mine and g-admin (the usual 2). One more works and says what it costs.
    more = focus.set_focus(store, {}, scenes['g-four'], True, 'P1')
    assert 'over_the_usual' in more and '半分钟' in more['over_the_usual']
    assert {item['place'] for item in more['groups']['active']} == {place_id(name) for name in ('g-mine', 'g-admin', 'g-four')}
    # Its summaries start from now: the resting days stay as kept lines, not a backlog.
    assert store.db.scenes.find_one({'_id': 'g-four'})['summary_start_seq'] == 7
    rest = focus.set_focus(store, {}, store.db.scenes.find_one({'_id': 'g-four'}), False, 'P1')
    assert 'over_the_usual' not in rest and '歇着' in rest['done']
    assert not focus.active(store, store.db.scenes.find_one({'_id': 'g-four'}))


def test_an_at_in_a_resting_group_brings_the_last_days_lines(store):
    scenes = world(store)
    now = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)
    rows = [{'scene_seq': 50 - index, 'received_at': (now - timedelta(hours=index)).isoformat(), 'text': str(index)}
            for index in range(30)]                                   # newest first, one an hour
    rested = catch_up(store, scenes['g-quiet'], rows, now_ts=now.timestamp())
    followed = catch_up(store, scenes['g-mine'], rows, now_ts=now.timestamp())
    assert [row['text'] for row in rested] == [str(index) for index in range(25)]   # the last day
    assert len(followed) == 12                                         # an active group: the usual window
