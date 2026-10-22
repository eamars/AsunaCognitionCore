"""ADR-089: a line's author is who wrote it. A task result and a due plan are the program's lines (PROGRAM_AUTHOR); the
person who authorized the turn stays on the event and the episode, and everything that decides who may do what reads
that. The program is never a person: no label number, no roster record, no voice, nobody present."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from asuna import condense, familiarity, places
from asuna.channels import Channels, addressees
from asuna.context import ContextBuilder
from asuna.coordinator import Coordinator
from asuna.discussion_digest import build_digest
from asuna.ingress import PROGRAM_AUTHOR, persist_input
from asuna.lanes import FakeLane, FakeTurn
from asuna.people import PROGRAM_LABEL, People
from asuna.state import Denied
from test_adr009_p2 import owner
from test_adr082_people import event as group_event, turn as group_turn
from test_engineering_m6 import task_setup


def plan_firing(key, scene='dm-a', person='A', group=False):
    """A due plan as schedule.py queues it: a core notice, no channel envelope."""
    ev = {'event_id': 'schedule:' + key, 'scene_id': scene, 'person_id': person, 'adapter_id': 'scheduler',
          'episode_kind': 'scheduled', 'scheduled_plan_id': 'plan-' + key, 'scene_tick': True,
          'text': '你之前安排的计划「喝水」现在到期了。请重新判断是否继续；到期本身不是新授权或已完成的行动。'}
    if group:
        ev['group_context'] = {'wake_reason': 'scheduled_plan', 'topic_id': ev['event_id'], 'reply_to': None,
                               'reply_message_id': None, 'mentioned_account_ids': []}
    return ev


def said(store, key, text, scene='dm-a', person='A'):
    return persist_input(store, {'event_id': key, 'scene_id': scene, 'person_id': person, 'text': text})[0]


def scene(store, scene_id):
    return store.db.scenes.find_one({'_id': scene_id})


# ---- the rule -------------------------------------------------------------------------------------------------------

def test_a_task_result_is_the_programs_line_and_its_turn_keeps_who_asked(store):
    service, task, broker, work = task_setup(store)
    try:
        current = store.db.tasks.find_one({'_id': task['_id']})
        done = store.put('tasks', {**current, 'state': 'RETURNED', 'feedback_state': 'READY', 'result': {
            'task_id': task['_id'], 'intent_revision': 1, 'text': '文件已查阅', 'facts': [], 'artifact_refs': []}},
            expected=current['revision'])
        ep = service.feedback(done, Coordinator(store, FakeLane(store, [FakeTurn([('think', {'thought': '结果到了。'})],
                                                                                 '查过了。')])))
    finally:
        broker.close()
    assert ep['state'] == 'COMMITTED' and ep['episode_kind'] == 'task_feedback'
    row = store.db.messages.find_one({'_id': 'in-' + ep['_id']})
    assert (row['author'], row['direction'], row['event']['person_id']) == (PROGRAM_AUTHOR, 'inbound', 'A')
    asked = store.db.messages.find_one({'_id': task['raw_input_refs'][0]})
    assert asked['author'] == 'A'                                       # the request itself stays his line
    # She still reads who authorized the turn: the episode, its header and its session class follow the person.
    assert ep['person_id'] == 'A' and ep['manifest']['session_class'] == 'owner_private'
    assert ep['context']['speaker'] == People(store, ep['persona']).speaker(scene(store, 'dm-a'), 'A') != PROGRAM_LABEL


def test_a_due_plan_is_the_programs_line_once_and_authorization_still_reads_the_person(store):
    row, created = persist_input(store, plan_firing('p1'))
    assert created and (row['author'], row['direction'], row['event']['person_id']) == (PROGRAM_AUTHOR, 'inbound', 'A')
    again, created = persist_input(store, plan_firing('p1'))
    assert not created and again['_id'] == row['_id']                    # the same firing is stored once
    assert said(store, 'hello', '在吗')['author'] == 'A'                  # a person's own line keeps its author
    with pytest.raises(Denied, match='SCENE_MEMBERSHIP_DENIED'):
        persist_input(store, plan_firing('p2', person='C'))              # who may: the event's person, never the author
    # Its own turn's header still names who authorized it (her line: the plan's person, never 程序).
    owner(store)
    dm = scene(store, 'dm-a')
    store.db.plans.insert_one({'_id': 'plan-p3', 'scene_id': 'dm-a', 'scope_key': dm['scope_key'], 'person_id': 'A',
                               'policy_epoch': dm['policy_epoch'], 'status': 'ACTIVE', 'intent': '喝水',
                               'rule': {'after_seconds': 3600}, 'schema_version': 1, 'revision': 1})
    ep = Coordinator(store, FakeLane(store, [FakeTurn([('think', {'thought': '到点了。'})], '嗯。')])).ingest(plan_firing('p3'))
    assert ep['episode_kind'] == 'scheduled' and ep['person_id'] == 'A'
    assert ep['context']['speaker'] == People(store, ep['persona']).speaker(scene(store, 'dm-a'), 'A') != PROGRAM_LABEL
    # A row stored under the old rule (the requester as author) conflicts: the correction runs before this code.
    store.db.messages.update_one({'_id': row['_id']}, {'$set': {'author': 'A'}})
    with pytest.raises(Denied, match='INPUT_IDENTITY_OR_CONTENT_CONFLICT'):
        persist_input(store, plan_firing('p1'))


# ---- the program is never a person ----------------------------------------------------------------------------------

def test_the_program_reads_as_the_program_and_takes_no_label(store):
    g1 = scene(store, 'g1')
    row = persist_input(store, plan_firing('g', scene='g1', group=True))[0]
    people = People(store, 'P1')
    assert people.speaker(g1, PROGRAM_AUTHOR) == PROGRAM_LABEL == people.row_head(row)
    assert people.transcript(g1, row).splitlines()[0].startswith(PROGRAM_LABEL)
    assert people._author(None, PROGRAM_AUTHOR) == PROGRAM_LABEL
    people.ensure_roster(g1)
    assert not store.db.scene_people.find_one({'person': PROGRAM_AUTHOR})
    line, why = people.line_of(g1, 'ep-none', str(row['scene_seq']))
    assert line is None and why                                          # no quote, reaction or recall of it


def test_a_stored_program_record_keeps_its_number_taken_and_out_of_every_roster(store):
    g1 = scene(store, 'g1')
    said(store, 'a-1', '大家好', scene='g1')
    people = People(store, 'P1')
    first = people.entry(g1, 'A')
    store.put('scene_people', {'_id': 'g1|' + PROGRAM_AUTHOR, 'scene_id': 'g1', 'scope_key': 'scene:g1',
                               'person': PROGRAM_AUTHOR, 'author': PROGRAM_AUTHOR, 'handle': first['handle'] + 1,
                               'card': '', 'nickname': '', 'role': '', 'previous': [], 'seen_at': '',
                               'created_at': '2026-10-01T00:00:00+00:00'}, stream='people:g1')
    people = People(store, 'P1')
    assert PROGRAM_AUTHOR not in {doc['person'] for doc in people.roster('g1').values()}
    assert people.entry(g1, 'B')['handle'] == first['handle'] + 2         # its number is never given again
    assert people.resolve(g1, '#%d' % (first['handle'] + 1)) == []
    assert people.speaker(g1, PROGRAM_AUTHOR) == PROGRAM_LABEL


# ---- readers --------------------------------------------------------------------------------------------------------

def test_her_task_results_are_nobodys_lines_to_count(store):
    for n in range(familiarity.MET_LINES):
        persist_input(store, plan_firing('c-%d' % n, scene='g2', person='C', group=True))
    assert familiarity.level(store, 'C') == 'new'
    for n in range(familiarity.MET_LINES):
        said(store, 'c-line-%d' % n, '随便聊聊', scene='g2', person='C')
    assert familiarity.level(store, 'C') == 'met'                       # his own lines count, the program's never
    g1 = scene(store, 'g1')
    persist_input(store, plan_firing('g', scene='g1', group=True))
    said(store, 'a-1', '今天好热', scene='g1')
    room = places.room(store, g1, datetime.now(timezone.utc))
    assert (room['lines'], room['voices']) == (1, 1)
    rows = list(store.db.messages.find({'scene_id': 'g1', 'direction': 'inbound'}, {'author': 1, 'text': 1}))
    assert all(PROGRAM_AUTHOR not in who for who in condense._speakers(rows, 'demo').values())


def test_a_group_turn_never_lists_the_program_as_present(store):
    persist_input(store, plan_firing('g', scene='g1', group=True))
    said(store, 'by-b', '今天好热', scene='g1', person='B')
    ep, _ = group_turn(store, group_event('t-1'))
    assert {'A', 'B'} <= set(ep['manifest']['present']) and PROGRAM_AUTHOR not in ep['manifest']['present']


def test_her_answer_to_a_task_result_is_addressed_to_nobody(store):
    g1 = scene(store, 'g1')
    notice = persist_input(store, plan_firing('g', scene='g1', group=True))[0]
    line = said(store, 'a-1', '谁在', scene='g1')
    assert addressees(store, g1, {'text': '好的', 'reply_to': notice['_id']}) == set()
    assert addressees(store, g1, {'text': '在', 'reply_to': line['_id']}) == {'A'}


def test_the_owners_last_line_is_his_own_words(store):
    owner(store)
    real = said(store, 'morning', '早')
    persist_input(store, plan_firing('later'))
    _, context, _ = ContextBuilder(store).prepare({'event_id': 'now', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '在'})
    assert context['rhythm_from_program']['owner_last_message_at'] == real['received_at']


def test_an_agent_line_shows_the_agent_only_what_the_owner_wrote(store, tmp_path):
    from test_agent_line import SCENE, with_lines
    with_lines(store, tmp_path)
    owner_id = store.config['chat']['person_id']
    store.db.scenes.update_one({'_id': SCENE}, {'$push': {'members': owner_id}})
    persist_input(store, plan_firing('line', scene=SCENE, person=owner_id))
    said(store, 'web-1', '这条线上的事我也看着', scene=SCENE, person=owner_id)
    shown = Channels(SimpleNamespace(app=SimpleNamespace(store=store))).owner_lines('agent', 'claude-code')
    assert [item['text'] for item in shown] == ['这条线上的事我也看着']


def test_a_digest_counts_no_program_participant():
    def hit(mid, seq, author, speaker, text):
        return {'message_id': mid, 'scene_id': 'g1', 'scene_seq': seq, 'at': '2026-09-22T12:0%d:00Z' % seq,
                'time_source': 'messages.occurred_at', 'author': author, 'direction': 'inbound', 'side': '他说',
                'speaker': speaker, 'text': text, 'person_match': True}
    digest = build_digest([hit('a1', 1, 'A', '[林 #1]', '明天去修吧？'),
                           hit('p1', 2, PROGRAM_AUTHOR, PROGRAM_LABEL, '你之前安排的计划「喝水」现在到期了。')],
                          {}, {'scene_id': 'g1'})
    assert [person['display'] for person in digest['participants']] == ['[林 #1]']
    assert digest['source_ids'] == ['a1', 'p1']                         # read and covered, just nobody's words
