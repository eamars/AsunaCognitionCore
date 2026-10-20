"""ADR-070 and ADR-071: her weekly tools and her exchanges, read back as facts with their sources, judged by nobody.

The tools reading comes once a week in self evaluation, and when nine days pass without it any home heartbeat carries
it. The exchanges put her line beside the thought she wrote in that turn and what followed; at least half of them are a
sample chosen by the day, so the reading is not a record of the lines that got an answer. Her own sections, tagged by
her persona's `self_review.tag`, come whole once a week and as one dated heading otherwise, and not at all when gone.
"""
import json
from datetime import datetime, timedelta, timezone

from asuna import self_review, tools_week

NOW = datetime.now(timezone.utc).replace(microsecond=0)          # audit records carry the real clock


def at(minutes):
    return (NOW - timedelta(hours=6) + timedelta(minutes=minutes)).isoformat()


def group(store, scene_id='grp1'):
    store.db.scenes.insert_one({'_id': scene_id, 'schema_version': 1, 'scene_id': scene_id, 'kind': 'group', 'policy_epoch': 1,
                                'scope_key': 'scene:' + scene_id, 'sequence': 0})


def mine(store, key, scene_id, seq, minute, text='我说的一句'):
    store.db.messages.insert_one({'_id': key, 'schema_version': 1, 'scene_id': scene_id, 'scene_seq': seq,
                                  'direction': 'outbound', 'phase': 'SPEAK', 'text': text, 'author': 'character',
                                  'platform_message_id': 'p-' + key, 'receipt_at': at(minute)})


def theirs(store, key, scene_id, seq, minute, text, author='B', reply=None, reaction=None):
    event = {'group_context': {'reply_message_id': reply}, 'person_id': author}
    if reaction:
        event['raw'] = {'asuna_notice': {'kind': 'reaction', 'line': {'message_id': reaction, 'mine': True}}}
    store.db.messages.insert_one({'_id': key, 'schema_version': 1, 'scene_id': scene_id, 'scene_seq': seq,
                                  'direction': 'inbound', 'text': text, 'author': author, 'occurred_at': at(minute),
                                  'event': event})


def test_an_exchange_is_her_line_the_turns_thought_and_what_followed_as_facts(store):
    group(store)
    mine(store, 'm1', 'grp1', 10, 0)
    theirs(store, 'r1', 'grp1', 11, 2, '回你这句' + '长' * 100, reply='m1')
    theirs(store, 'x1', 'grp1', 12, 3, '', reaction='p-m1')
    out = self_review.exchanges(store, 'P1', 'UTC', NOW)
    [item] = out['items']
    assert item['said'] == '我说的一句' and item['thought_that_turn'] == '那一回合没有留下心里话'
    assert item['after'][0].startswith('回了这句的：') and len(item['after'][0]) < 100, 'others cut to 60 in public'
    assert any(line.startswith('对这句点了反应的') for line in item['after'])
    assert out['note'] == self_review.EXCHANGES_NOTE and 'others' in out and 'reply_message_id' in out['sources']
    assert not any(word in str(out) for word in ('被无视', '好评', '差评', '分数')), 'nothing judges'


def test_at_least_half_are_the_days_sample_so_lines_that_drew_nothing_are_kept(store):
    for n in range(6):
        group(store, 'grp%d' % n)
        mine(store, 'q%d' % n, 'grp%d' % n, 10, n * 10, '群%d 没人接的' % n)
        mine(store, 'a%d' % n, 'grp%d' % n, 20, n * 10 + 1, '群%d 有人接的' % n)
        theirs(store, 'ra%d' % n, 'grp%d' % n, 21, n * 10 + 2, '回', reply='a%d' % n)
    items = self_review.exchanges(store, 'P1', 'UTC', NOW)['items']
    assert len(items) == self_review.EXCHANGES
    unanswered = [item for item in items if not any(line.startswith('回了这句的') for line in item['after'])]
    assert len({item['said'].split(' ')[0] for item in items}) >= 4, 'the sample keeps its half: four conversations at least'
    assert unanswered, 'lines that drew nothing stay in the reading'
    assert len(items) - len(unanswered) <= self_review.EXCHANGES // 2 + 2, 'explicit lines are at most half (+ sampled)'


def test_the_window_runs_from_the_last_showing_and_an_empty_one_says_so_in_one_line(store):
    group(store)
    mine(store, 'm1', 'grp1', 10, 0)
    assert len(self_review.exchanges(store, 'P1', 'UTC', NOW)['items']) == 1
    assert self_review.exchanges(store, 'P1', 'UTC', NOW + timedelta(minutes=1))['items'] == [self_review.NOTHING_SAID]


def test_her_tagged_sections_come_dated_and_go_when_she_takes_them_away(store):
    from asuna.documents import DocumentStore
    from asuna import memory_tiers
    assert self_review.cared(store, 'P1', None) is None and self_review.cared(store, 'P1', '标签') is None
    docs = DocumentStore(store, 'P1')
    docs.apply(memory_tiers.SELF_DOC, {'op': 'append_section', 'heading': '我在乎的', 'reason': '写下',
                                       'tags': ['标签'], 'visibility': 'owner_private', 'inject': 'on_demand'},
               '在乎的事。\n不要的事。', base_revision_id=docs.read(memory_tiers.SELF_DOC)[0], author='character',
               mutation_id='cared-1')
    [line] = self_review.cared(store, 'P1', '标签')
    assert line.startswith('我在乎的（') and line.endswith('你自己写的）')
    [whole] = self_review.cared(store, 'P1', '标签', whole=True)
    assert whole['text'] == '在乎的事。\n不要的事。', 'the whole section, the half about what she does not want too'
    sid = docs.read(memory_tiers.SELF_DOC)[1]['sections'][-1]['sid']
    docs.apply(memory_tiers.SELF_DOC, {'op': 'set_tags', 'sid': sid, 'tags': [], 'reason': '划掉'}, None,
               base_revision_id=docs.read(memory_tiers.SELF_DOC)[0], author='character', mutation_id='cared-2')
    assert self_review.cared(store, 'P1', '标签') is None, 'gone, and no line stands in for it'


def test_the_tools_week_comes_once_a_week_and_its_floor_is_nine_days(store):
    assert tools_week.due(store, 'P1', NOW) == 'week', 'never shown: waits for a roll, the floor counts from now'
    first = tools_week.block(store, 'P1', NOW)
    assert first and first['note'] == tools_week.NOTE and first['sources']
    assert set(first) >= {'last_time', 'refused', 'calls', 'looking_things_up', 'list_change'}
    assert tools_week.block(store, 'P1', NOW + timedelta(days=3)) is None
    assert tools_week.due(store, 'P1', NOW + timedelta(days=7, hours=1)) == 'week'
    assert tools_week.due(store, 'P1', NOW + timedelta(days=9, hours=1)) == 'floor'


def test_refusals_say_what_they_cost_and_a_lookup_task_is_counted(store):
    since = (NOW - timedelta(days=1)).isoformat()
    for seq, (tool, refused) in enumerate([('ideas', 'idea 太长了：600 字'), ('ideas', None), ('plan', '没有这条线；照抄')]):
        store.db.audit_events.insert_one({'_id': 'a%d' % seq, 'schema_version': 1, 'type': 'role_tool', 'stream_id': 'ep-1', 'seq': seq,
                                          'occurred_at': since, 'payload': {'tool': tool, 'args': {'idea': 'x'},
                                                                            **({'refused': refused} if refused else {})}})
    store.db.tasks.insert_one({'_id': 't1', 'schema_version': 1, 'request_key': 't1', 'created_at': since, 'state': 'RETURNED'})
    store.db.artifacts.insert_one({'_id': 'f1', 'schema_version': 1, 'task_id': 't1', 'tool': 'development_database_read', 'state': 'DONE'})
    out = tools_week.block(store, 'P1', NOW)
    ideas = next(item for item in out['refused'] if item['tool'] == 'ideas')
    assert ideas['times'] == 1 and ideas['retried'] == 1 and out['lengths']['over'] == {'ideas': 1}
    assert out['looking_things_up'] == {'this_week': 1, 'week_before': 0}
    assert out['turn_shape']['usual'] == 9 and out['turn_shape']['hard'] == 24, 'the lines at their current values'


def test_a_self_evaluation_beat_carries_the_review_and_nine_days_bring_it_to_any_home_beat(store, monkeypatch):
    from asuna.context import ContextBuilder
    from test_adr009_p2 import owner
    owner(store)
    beat = {'event_id': 'presence:r1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': 'beat', 'episode_kind': 'presence'}
    _, rolled, _ = ContextBuilder(store).prepare({**beat, 'dice': 'self_evaluation'})
    assert 'exchanges' in rolled['self_review_from_program'] and 'tools_week_from_program' in rolled
    _, plain, _ = ContextBuilder(store).prepare({**beat, 'event_id': 'presence:r2'})
    assert 'self_review_from_program' not in plain and 'tools_week_from_program' not in plain
    monkeypatch.setattr(tools_week, 'due', lambda *args, **kwargs: 'floor')
    _, floor, _ = ContextBuilder(store).prepare({**beat, 'event_id': 'presence:r3'})
    assert 'self_review_from_program' in floor, 'nine days without it: any home beat carries it'


def test_a_reflection_runs_in_its_own_session_and_nothing_of_it_stays_at_home(store):
    """ADR-072 (owner 2026-10-16): more tokens for her reflection, none of them in her regular turns."""
    import threading, types
    from asuna.native_worker import BusinessWorker
    from test_adr009_p2 import owner
    owner(store)
    worker = BusinessWorker()
    worker.app = types.SimpleNamespace(store=store, config=store.config)
    worker.navigation_ready = threading.Event()
    worker.navigation_ready.set()
    worker.host_call = lambda method, args: (_ for _ in ()).throw(AssertionError('a reflection copies nothing'))
    store.put('sessions', {'_id': 'asuna-role-home', 'native_host': True, 'main_conversation': True, 'lane': 'character',
                           'scene_id': 'dm-a', 'persona': 'P1', 'policy_epoch': 1, 'character_context': None,
                           'cwd': 'work/home', 'person_id': 'A'}, stream='native-binding:asuna-role-home')
    turn = {'_id': 'ep-reflect', 'scene_id': 'dm-a', 'person_id': 'A', 'persona': 'P1', 'policy_epoch': 1,
            'scope_key': 'scene:dm-a', 'context': {'self_review_from_program': {}, 'tools_week_from_program': {}}}
    own = worker.resolve_role_session(turn)
    assert own == self_review.reflection_session_id('ep-reflect') and own.startswith(self_review.REFLECT_PREFIX)
    row = store.db.sessions.find_one({'_id': own})
    assert row['reflection']['home_session_id'] == 'asuna-role-home' and not row['main_conversation']
    assert worker.side_session(own) and not worker.side_session('asuna-role-home')
    assert worker.resolve_role_session({**turn, '_id': 'ep-chat', 'context': {'clock_from_program': {}}}) == 'asuna-role-home'
    # A plan she makes while reflecting fires at home, not in the reflection's session.
    store.db.episodes.insert_one({'_id': 'ep-reflect', 'schema_version': 1, 'native_session_id': own})
    store.db.plans.insert_one({'_id': 'plan-r', 'schema_version': 1, 'source_episode_id': 'ep-reflect'})
    store.db.messages.insert_one({'_id': 'in-ep-later', 'schema_version': 1, 'event': {'scheduled_plan_id': 'plan-r'}})
    assert worker.resolve_role_session({**turn, '_id': 'ep-later', 'context': {}}) == 'asuna-role-home'
    assert worker.resolve_role_session(turn) == own, 'the same turn finds its session again'
    # A job handed over in a reflection outlives its session (2026-10-17: such a job lost its parent and was blocked),
    # so it belongs to home's own session, where its thread is drawn and its report comes (owner and her, 2026-10-20).
    from asuna import role_tools
    from asuna.coordinator import Coordinator
    reflecting = {**turn, 'native_session_id': own}
    assert role_tools._one_shot(reflecting)
    assert Coordinator(store, None)._task_session(reflecting) == 'asuna-role-home'
    assert not role_tools._one_shot({**turn, 'context': {'clock_from_program': {}}})


def test_the_map_names_each_store_shows_her_changes_with_her_reasons_and_attention_as_counts(store):
    """ADR-073: one line per store, what she changed with the reason she gave, attention as numbers only; the window
    says when it was cut; no store fills the map."""
    from asuna import reflection_map
    from asuna.documents import DocumentStore
    first = reflection_map.block(store, 'P1', NOW)
    assert first['window'].startswith('这是第一张图') and first['note'] == reflection_map.NOTE
    # Her review: the first map has nothing to compare with, so what exists is a baseline, never "changed".
    assert first['changed'] == {'group_notes': [], 'documents': [], 'people': []}, 'all three stores, people too (her ask)'
    assert any(line.startswith('persona：') and '基线·首次入图' in line for line in first['index'])
    docs = DocumentStore(store, 'P1')
    docs.apply('persona', {'op': 'append_section', 'heading': '新学到的', 'reason': '今天才明白'}, '一句新的话。',
               base_revision_id=docs.read('persona')[0], author='character', mutation_id='map-1')
    store.audit('ep-gate', 'attend.verdict', {'choice': 'join', 'reason': 'x'}, 'scene:grp-a')
    store.audit('ep-gate', 'attend.verdict', {'choice': 'quiet', 'reason': 'y'}, 'scene:grp-a')
    out = reflection_map.block(store, 'P1', NOW + timedelta(minutes=1), tag='标签')
    assert 'window' not in out, 'within the look-back, nothing to say about it'
    assert any(line.startswith('persona：') and '改了 1 节' in line for line in out['index'])
    assert any('self_review.tag「标签」' in line for line in out['index']) and any(line.startswith('差事：') for line in out['index'])
    [persona] = [d for d in out['changed']['documents'] if d['doc'] == 'persona']
    assert persona['headings'] == ['新学到的'] and persona['your_reasons'] == ['今天才明白']
    assert out['attention'] == ['一个现在已经没有的对话：看了 2 行，叫你看了 1 行'], 'numbers only'
    assert not any(word in str(out['attention']) for word in ('放过', '忽略', '不够')), 'no verdict'
    again = reflection_map.block(store, 'P1', NOW + timedelta(days=21))
    assert again['window'].startswith('上次地图在 20 天前') and '最早的 6 天没进这张图' in again['window']
    many = [('2099', {'group': 'g%d' % n, 'your_reasons': [], 'sections': [{'heading': 'h', 'ref': {}, 'text': '字' * 1000}]})
            for n in range(9)]
    filled = reflection_map._fill([e for _, e in many], reflection_map.BUDGET['group_notes'], lambda e: {'group': e['group']},
                                  '另有 %d 个')
    assert len(json.dumps(filled, ensure_ascii=False)) <= reflection_map.BUDGET['group_notes'] + 20
