"""ADR-070 and ADR-071: her weekly tools and her exchanges, read back as facts with their sources, judged by nobody.

The tools reading comes once a week in self evaluation, and when nine days pass without it any home heartbeat carries
it. The exchanges put her line beside the thought she wrote in that turn and what followed; at least half of them are a
sample chosen by the day, so the reading is not a record of the lines that got an answer. Her own sections, tagged by
her persona's `self_review.tag`, come whole once a week and as one dated heading otherwise, and not at all when gone.
"""
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
    assert out['turn_shape']['cap'] > 0, 'a limit is shown at its current value'


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
