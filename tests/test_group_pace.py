"""A group's pace in words (places.pace): how old the talk is and how much was said since a pause."""
from datetime import datetime, timedelta, timezone

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
    assert value['last_line'].startswith('上一句是刚才')
    assert value['this_stretch'] == '眼下这一段从 %s 开始，到现在说了一二十句' % line_stamp(zone, (NOW - timedelta(minutes=20)).isoformat())
    before = line_stamp(zone, (NOW - timedelta(minutes=282)).isoformat())
    assert value['before'].startswith('再往前停过 4 小时（%s 到' % before)
    assert value['before'].endswith('%s 那句之后又说了一二十句' % before)


def test_talk_without_a_pause_says_so(store):
    scene = group(store, [25, 20, 15, 10, 5])
    value = places.pace(store, scene, NOW, scene_timezone(store.config, scene))
    assert value['this_stretch'].endswith('说了几句') and value['before'] == '往前看的这些话中间没停过'


def test_a_silent_group_has_no_stretch(store):
    store.put('scenes', {'_id': SCENE, 'kind': 'group', 'scope_key': 'scene:' + SCENE, 'policy_epoch': 1,
                         'sequence': 0})
    scene = store.db.scenes.find_one({'_id': SCENE})
    assert places.pace(store, scene, NOW, scene_timezone(store.config, scene)) == {'last_line': '还没见过有人说话'}
