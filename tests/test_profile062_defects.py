"""Defects the ADR-062 prompt profile found in her live notices (2026-10-13): a block that changes every turn with
nothing new in it is sent again every turn, so what it says must change only with its content."""
from datetime import datetime, timedelta, timezone

from asuna.context import ContextBuilder
from asuna.rhythm import recent_phrasing
from asuna.schedule_rules import line_stamp, scene_timezone


def test_her_repeated_phrases_read_in_the_same_order_whatever_their_counts():
    a, b, c = '今天天气', '一起去吧', '晚安好梦'           # one 4-gram each
    first = recent_phrasing([a, a, a, a, b, b, b, c, c, c])
    second = recent_phrasing([a, a, a, b, b, b, b, b, c, c, c, c])
    assert first == second == sorted(first)


def test_her_recent_thoughts_say_when_on_her_clock_not_how_long_ago(store):
    scene = store.db.scenes.find_one({'_id': 'dm-a'})
    formed = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    store.db.memory_units.delete_many({'kind': 'monologue'})
    store.db.memory_units.insert_one({'_id': 'mono-ep:1', 'schema_version': 1, 'scope_key': scene['scope_key'],
                                      'policy_epoch': 1, 'character_id': 'demo', 'status': 'active', 'kind': 'monologue',
                                      'body_markdown': '想再烤一次松饼', 'formed_at': formed})
    zone = scene_timezone(store.config, scene)
    [item] = ContextBuilder(store).recent_thoughts(scene['scope_key'], zone)
    assert item['when'] == line_stamp(zone, formed), 'a stamp that stays the same from turn to turn'
