"""A group's pace in words (places.pace): how old the talk is and how much was said since a pause."""
from datetime import datetime, timedelta, timezone

import pytest

from asuna import places
from asuna.schedule_rules import line_stamp, scene_timezone

SCENE = 'qq:90000:group:80000'
NOW = datetime(2026, 10, 5, 5, 10, tzinfo=timezone.utc)


def group(store, minutes_ago):
    store.put('scenes', {'_id': SCENE, 'kind': 'group', 'scope_key': 'scene:' + SCENE, 'policy_epoch': 1,
                         'sequence': 0})
    store.db.messages.insert_many([
        {'_id': 'in-%d' % seq, 'schema_version': 1, 'scene_id': SCENE, 'policy_epoch': 1, 'direction': 'inbound', 'scene_seq': seq,
         'received_at': (NOW - timedelta(minutes=ago)).isoformat()}
        for seq, ago in enumerate(minutes_ago, start=1)])
    return store.db.scenes.find_one({'_id': SCENE})


def test_an_old_question_reads_as_old_and_buried(store):
    # Three lines about five hours ago, a pause, then eight lines over the last twenty minutes.
    scene = group(store, [290, 285, 282, 20, 18, 15, 12, 9, 6, 4, 2])
    zone = scene_timezone(store.config, scene)
    value = places.pace(store, scene, NOW, zone)
    assert value['last_line'] == '上一句在 %s' % line_stamp(zone, (NOW - timedelta(minutes=2)).isoformat())
    assert places.pace(store, scene, NOW + timedelta(minutes=30), zone) == value, 'nothing said, nothing changes'
    assert value['this_stretch'] == '眼下这一段从 %s 开始，到现在说了一二十句' % line_stamp(zone, (NOW - timedelta(minutes=20)).isoformat())
    before = line_stamp(zone, (NOW - timedelta(minutes=282)).isoformat())
    assert value['before'].startswith('再往前停过 4 小时（%s 到' % before)
    assert value['before'].endswith('%s 那句之后又说了一二十句' % before)


def test_talk_without_a_pause_says_so(store):
    scene = group(store, [25, 20, 15, 10, 5])
    value = places.pace(store, scene, NOW, scene_timezone(store.config, scene))
    assert value['this_stretch'].endswith('说了几句') and value['before'] == '往前看的这些话中间没停过'


def talk(store, scene_id, theirs, mine, days_ago=1):
    """Others' lines here of these lengths (a day ago by default) and her delivered lines of these lengths."""
    rows = [{'_id': '%s-in-%d' % (scene_id, n), 'schema_version': 1, 'scene_id': scene_id, 'policy_epoch': 1,
             'direction': 'inbound', 'scene_seq': 1000 + n, 'text': '话' * size,
             'received_at': (NOW - timedelta(days=days_ago, minutes=n)).isoformat()} for n, size in enumerate(theirs)]
    rows += [{'_id': '%s-out-%d' % (scene_id, n), 'schema_version': 1, 'scene_id': scene_id, 'policy_epoch': 1,
              'direction': 'outbound', 'delivery_state': 'DELIVERED', 'scene_seq': 2000 + n, 'text': '我' * size}
             for n, size in enumerate(mine)]
    if rows:
        store.db.messages.insert_many(rows)


@pytest.mark.parametrize('mine,band', [(5, 0), (10, 1), (13, 1), (20, 2), (30, 3)])
def test_how_long_she_talks_here_against_the_people_here_comes_as_words(store, mine, band):
    """Her ask: her last lines here against the usual length of the others' lines here (median of 10), in words."""
    scene = group(store, [5])
    talk(store, SCENE, [10] * 20, [mine] * 20)
    value = places.pace(store, scene, NOW, scene_timezone(store.config, scene))
    assert value['your_length'] == places.LENGTH_WORDS[band][1]
    assert not any(ch.isdigit() for ch in value['your_length']), 'no number reaches her'


def test_too_few_lines_of_either_say_nothing(store):
    scene = group(store, [5])
    talk(store, SCENE, [10] * 19, [30] * 20)
    assert 'your_length' not in places.pace(store, scene, NOW, scene_timezone(store.config, scene))
    store.db.messages.delete_many({'_id': {'$regex': '-(in|out)-'}})
    talk(store, SCENE, [10] * 20, [30] * 4)
    assert 'your_length' not in places.pace(store, scene, NOW, scene_timezone(store.config, scene))


def test_only_this_groups_lines_of_the_last_days_count(store):
    scene = group(store, [5])
    talk(store, SCENE, [10] * 20, [10] * 20)
    talk(store, 'qq:90000:group:80001', [100] * 40, [100] * 20)               # another group: long lines both ways
    old =[{'_id': 'old-%d' % n, 'schema_version': 1, 'scene_id': SCENE, 'policy_epoch': 1, 'direction': 'inbound',
            'scene_seq': 500 + n, 'text': '话' * 2, 'received_at': (NOW - timedelta(days=8, minutes=n)).isoformat()}
           for n in range(40)]
    store.db.messages.insert_many(old)                                          # short, but older than 7 days
    value = places.pace(store, scene, NOW, scene_timezone(store.config, scene))
    assert value['your_length'] == places.LENGTH_WORDS[1][1]


def test_a_silent_group_has_no_stretch(store):
    store.put('scenes', {'_id': SCENE, 'kind': 'group', 'scope_key': 'scene:' + SCENE, 'policy_epoch': 1,
                         'sequence': 0})
    scene = store.db.scenes.find_one({'_id': SCENE})
    assert places.pace(store, scene, NOW, scene_timezone(store.config, scene)) == {'last_line': '还没见过有人说话'}
