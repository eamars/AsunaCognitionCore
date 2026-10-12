"""ADR-049: condensing a quiet group's conversation on her choice, and phrases for a note-writing visit."""
from datetime import datetime, timedelta, timezone

import pytest

from asuna import condense, role_tools
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)       # midday on the Host's UTC clock


def group(store, name='g-a', **extra):
    store.config['timezone'] = 'UTC'
    store.put('scenes', {'_id': name, 'kind': 'group', 'scope_key': 'scene:' + name, 'policy_epoch': 1, 'members': [],
                         'sequence': 0, **extra}, stream=name)
    return store.db.scenes.find_one({'_id': name})


def lines(store, scene_id, count, *, last_minutes_ago, authors=('p1', 'p2', 'p3'), text='闲聊', days=1):
    for index in range(count):
        at = NOW - timedelta(days=index % days, minutes=last_minutes_ago + index)
        store.db.messages.insert_one({'_id': '%s-m-%d-%s' % (scene_id, index, text if isinstance(text, str) else 'v'), 'schema_version': 1, 'scene_id': scene_id,
                                      'direction': 'inbound', 'author': authors[index % len(authors)],
                                      'text': text if isinstance(text, str) else text[index % len(text)],
                                      'received_at': at.isoformat()})


def test_how_long_quiet_follows_how_busy_the_group_is(store):
    busy, middling, quiet = group(store, 'g-busy'), group(store, 'g-mid'), group(store, 'g-quiet')
    lines(store, 'g-busy', 800, last_minutes_ago=12)       # over 100 a day
    lines(store, 'g-mid', 300, last_minutes_ago=12)        # 30 to 100 a day
    lines(store, 'g-quiet', 50, last_minutes_ago=12)       # under 30 a day
    assert [condense.quiet_minutes(store, name, NOW) for name in ('g-busy', 'g-mid', 'g-quiet')] == [10, 15, 30]
    assert condense.due(store, busy, NOW) and not condense.due(store, middling, NOW)
    assert not condense.due(store, quiet, NOW)
    assert condense.due(store, quiet, datetime(2026, 10, 12, 2, 0, tzinfo=timezone.utc))   # night there


def test_her_own_line_does_not_restart_the_wait(store):
    scene = group(store)
    lines(store, 'g-a', 50, last_minutes_ago=40)
    store.db.messages.insert_one({'_id': 'mine', 'schema_version': 1, 'scene_id': 'g-a', 'direction': 'outbound', 'author': 'demo',
                                  'text': '我说一句', 'received_at': (NOW - timedelta(minutes=1)).isoformat()})
    assert condense.due(store, scene, NOW)


def test_condensing_is_her_choice_on_a_visit_or_at_home_never_mid_conversation(store):
    scene = group(store)
    coordinator = Coordinator(store, FakeLane(store, []))
    tools = role_tools.RoleTools(coordinator)
    talking = {'_id': 'ep-1', 'persona': 'P1', 'scene_id': 'g-a', 'scope_key': 'scene:g-a', 'episode_kind': 'external'}
    with pytest.raises(role_tools.Refused, match='有人在等你说话'):
        tools.tool_group_focus(talking, 'c1', {'op': 'condense'})
    # A turn a plan of hers woke counts at home (nobody is waiting for her there), never in a group or a DM.
    planned_home = {**talking, '_id': 'ep-p', 'episode_kind': 'scheduled', 'manifest': {'session_class': 'owner_private'}}
    planned_out = {**planned_home, '_id': 'ep-q', 'manifest': {'session_class': 'public'}}
    with pytest.raises(role_tools.Refused, match='有人在等你说话'):
        tools.tool_group_focus(planned_out, 'c0', {'op': 'condense'})
    tools.tool_group_focus(planned_home, 'c0b', {'op': 'keep'})   # the rule passes; where is the turn's own group here
    visiting = {**talking, '_id': 'ep-2', 'episode_kind': 'visit'}
    answer, _ = tools.tool_group_focus(visiting, 'c2', {'op': 'condense'})
    assert '安静' in answer['done'] and store.db.scenes.find_one({'_id': 'g-a'})['condense_wanted']
    assert [row['_id'] for row in condense.marked(store)] == ['g-a']
    tools.tool_group_focus(visiting, 'c3', {'op': 'keep'})
    assert not condense.marked(store)


def test_a_look_condenses_a_due_group_once_and_her_next_turn_there_is_told(store):
    scene = group(store, character_context='ctx-1')
    store.db.sessions.insert_one({'_id': 'role-g-a', 'schema_version': 1, 'native_host': True, 'main_conversation': True, 'scene_id': 'g-a',
                                  'persona': 'P1', 'policy_epoch': 1, 'character_context': 'ctx-1', 'cwd': 'C:/w/g-a'})
    lines(store, 'g-a', 40, last_minutes_ago=45)
    condense.mark(store, scene, {'_id': 'ep-v', 'scope_key': 'scene:g-a', 'episode_kind': 'visit'}, NOW)
    asked = []
    busy = lambda session_id, scene_id, cwd: asked.append((session_id, cwd)) or {'compacted': False, 'reason': 'busy'}
    assert condense.look(store, 'P1', busy, NOW) == [] and condense.marked(store)       # tried again next look
    done = lambda session_id, scene_id, cwd: asked.append((session_id, cwd)) or {'compacted': True, 'items': 12}
    assert condense.look(store, 'P1', done, NOW) == ['g-a'] and asked == [('role-g-a', 'C:/w/g-a')] * 2
    assert not condense.marked(store)
    scene = store.db.scenes.find_one({'_id': 'g-a'})
    told = condense.condensed_block(store, scene, 'ev-1', NOW + timedelta(days=3))
    assert '按你的选择压过了' in told and '开头那段摘要' in told, 'told even days later, where the summary is'
    scene = store.db.scenes.find_one({'_id': 'g-a'})
    assert condense.condensed_block(store, scene, 'ev-1', NOW), 'the same turn prepared again still has it'
    assert condense.condensed_block(store, scene, 'ev-2', NOW) is None, 'once per condensing'


def routed(store, *names):
    store.config['channels'] = {'qq': {'routes': {name: {'scene_id': name, 'target': {'type': 'group', 'id': name}}
                                                  for name in names}}}


def test_a_group_past_the_size_floor_gets_a_notes_visit_first_then_is_condensed_at_a_quiet_spell(store):
    from asuna import places
    group(store, character_context='ctx-1')
    routed(store, 'g-a')
    store.db.sessions.insert_one({'_id': 'role-g-a', 'schema_version': 1, 'native_host': True, 'main_conversation': True, 'scene_id': 'g-a',
                                  'persona': 'P1', 'policy_epoch': 1, 'character_context': 'ctx-1', 'cwd': 'C:/w/g-a'})
    lines(store, 'g-a', 40, last_minutes_ago=45)
    measured, compacted, offered = [], [], []
    size = lambda session_id, scene_id, cwd: measured.append(session_id) or {'tokens': 120000, 'floor': 100000}
    compact = lambda session_id, scene_id, cwd: compacted.append(session_id) or {'compacted': True, 'items': 900}
    offer = lambda scene: offered.append(scene['_id']) or 'visit:g-a:condense-1'
    assert condense.look(store, 'P1', compact, NOW, size=size, offer_notes=offer) == []
    assert offered == ['g-a'] and not compacted, 'notes first'
    # Her notes turn has not run yet: nothing is condensed, nothing measured again.
    assert condense.look(store, 'P1', compact, NOW, size=size, offer_notes=offer) == [] and not compacted
    assert measured == ['role-g-a'] and offered == ['g-a']
    store.db.episodes.insert_one({'_id': places.episode_key({'scene_id': 'g-a', 'event_id': 'visit:g-a:condense-1'}),
                                  'schema_version': 1, 'state': 'COMMITTED', 'tool_calls': {}})
    assert condense.look(store, 'P1', compact, NOW, size=size, offer_notes=offer) == ['g-a'] and compacted == ['role-g-a']
    scene = store.db.scenes.find_one({'_id': 'g-a'})
    assert scene['condensed_by'] == 'floor' and 'condense_floor' not in scene
    assert '长度线' in condense.condensed_block(store, scene, 'ev-next', NOW)
    # Condensed and still quiet: the conversation is measured again, not judged by the reading from before the condense
    # (a quiet group was offered a notes visit and condensed again every ten minutes, 10-13).
    size = lambda session_id, scene_id, cwd: measured.append(session_id) or {'tokens': 40000, 'floor': 100000}
    later = NOW + timedelta(minutes=10)
    assert condense.look(store, 'P1', compact, later, size=size, offer_notes=offer) == []
    assert offered == ['g-a'] and compacted == ['role-g-a'] and measured == ['role-g-a'] * 2


def test_a_group_under_the_floor_or_not_quiet_is_left_and_only_groups_are_looked_at(store):
    group(store, character_context='ctx-1')
    group(store, 'g-busy', character_context='ctx-1')
    store.put('scenes', {'_id': 'dm-floor', 'kind': 'dm', 'scope_key': 'scene:dm-floor', 'policy_epoch': 1, 'members': [],
                         'sequence': 0}, stream='dm-floor')
    routed(store, 'g-a', 'g-busy', 'dm-floor')
    for name in ('g-a', 'g-busy', 'dm-floor'):
        store.db.sessions.insert_one({'_id': 'role-' + name, 'schema_version': 1, 'native_host': True, 'main_conversation': True,
                                      'scene_id': name, 'persona': 'P1', 'policy_epoch': 1, 'character_context': 'ctx-1',
                                      'binding_key': 'bk-' + name})
    lines(store, 'g-a', 40, last_minutes_ago=45)
    lines(store, 'g-busy', 40, last_minutes_ago=1)
    measured = []
    size = lambda session_id, scene_id, cwd: measured.append(session_id) or {'tokens': 50000, 'floor': 100000}
    never = lambda *_: pytest.fail('nothing to condense or visit')
    assert condense.look(store, 'P1', never, NOW, size=size, offer_notes=never) == []
    assert measured == ['role-g-a'], 'the busy group is not quiet; a private chat is never condensed by size'
    assert condense.look(store, 'P1', never, NOW, size=size, offer_notes=never) == []
    assert measured == ['role-g-a'], 'measured again only after new lines'


def test_a_host_that_cannot_condense_takes_the_mark_back_instead_of_retrying(store):
    scene = group(store, character_context='ctx-1')
    store.db.sessions.insert_one({'_id': 'role-g-a', 'schema_version': 1, 'native_host': True, 'main_conversation': True,
                                  'scene_id': 'g-a', 'persona': 'P1', 'policy_epoch': 1, 'character_context': 'ctx-1'})
    lines(store, 'g-a', 40, last_minutes_ago=45)
    condense.mark(store, scene, {'_id': 'ep-v', 'scope_key': 'scene:g-a', 'episode_kind': 'visit'}, NOW)
    assert condense.look(store, 'P1', lambda *_: {'compacted': False, 'reason': 'no_compact_command'}, NOW) == []
    assert not condense.marked(store)


def test_size_reaches_her_as_words_only(store):
    assert condense.size_words({'conversation_tokens': 160000})['length'].endswith('很长')
    assert condense.size_words({'conversation_tokens': 30000})['length'].endswith('短')
    assert condense.size_words({}) is None


def test_a_note_writing_visit_gets_at_most_five_phrases_most_people_first(store):
    scene = group(store)
    others = group(store, 'g-other')
    text = ('我在摸鱼', '摸鱼真快乐，绝绝子', '这也太绝绝子了哈哈哈', '又摸鱼了，绝绝子', '哈哈哈 摸鱼中', '晚饭吃啥')
    # Over four days: a group's own words come back on different days.
    lines(store, 'g-a', 12, last_minutes_ago=5, authors=('p1', 'p2', 'p3', 'p4', 'p5', 'p6'), text=text, days=4)
    # A word the whole group used on one afternoon only is that day's topic.
    lines(store, 'g-a', 6, last_minutes_ago=30, authors=('q1', 'q2', 'q3', 'q4'), text='信用卡被盗刷')
    # Ordinary laughter is common in her other groups too: not this group's word.
    for name in ('g-o1', 'g-o2', 'g-o3'):
        group(store, name)
        lines(store, name, 3, last_minutes_ago=5, text='哈哈哈', days=3)
    found = condense.phrases(store, scene, 'P1', None, NOW)
    words = [item['phrase'] for item in found['items']]
    assert len(words) <= condense.PHRASES_SHOWN and '哈哈哈' not in words
    assert '绝绝子' in words and '摸鱼' in words and not any('盗刷' in word for word in words)
    assert {item['people'] for item in found['items']} <= {'三个人', '四五个人', '好几个人'}
