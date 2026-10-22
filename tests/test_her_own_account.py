"""Her own account is her (2026-10-22). A group's roster had filed her own QQ account as another person ("沈小满 #4",
in 11 groups since 10-06): a task result carried its request's @-list, and the check "is this number me" compared it
with that row's own envelope, which a program line does not have. The member list then showed her own row as a
stranger. Now the account her channel speaks with in a scene is her wherever an account becomes a person, a program
line carries nothing of the line it is about but its thread, and the member list tells her her own names there."""
from datetime import datetime, timedelta, timezone

from asuna import attend, group_members, places, questions, understanding
from asuna.coordinator import Coordinator
from asuna.ingress import PROGRAM_AUTHOR, program_group_context
from asuna.lanes import FakeLane, FakeTurn
from asuna.people import People
from test_engineering_m6 import task_setup
from test_group_members import NOW, channel, member
from test_people import BOT, GROUP, SCENE, row, setup

REQUEST = {'wake_reason': 'mentioned_account', 'topic_id': 'topic-1', 'reply_to': '555', 'reply_message_id': 'in-mine',
           'mentioned_account_ids': [BOT]}


def program_line(seq, group=None, at='2026-10-04T02:00:00+00:00'):
    """A task result as it was stored before: the request's group context copied whole, no channel envelope."""
    return {'_id': 'in-ep-%d' % seq, 'scene_id': SCENE, 'scene_seq': seq, 'author': PROGRAM_AUTHOR,
            'direction': 'inbound', 'text': '你交给行动脑的事有了结果。', 'received_at': at, 'policy_epoch': 1,
            'schema_version': 1,
            'event': {'episode_kind': 'task_feedback', 'person_id': 'qq:20001',
                      'group_context': dict(group or REQUEST), 'raw': {}}}


def numbered(store):
    return sorted(d['handle'] for d in store.db.scene_people.find({'scene_id': SCENE}))


# ---- one definition: her account is her ------------------------------------------------------------------------

def test_an_at_of_her_account_on_a_program_line_files_nobody_and_reads_as_her(store):
    scene = setup(store)
    people = People(store, 'demo')
    before = numbered(store)
    people.transcript(scene, program_line(5))
    assert not store.db.scene_people.find_one({'person': 'qq:' + BOT}), 'her own account became a person'
    assert numbered(store) == before
    assert people.account_person(SCENE, BOT) == people.self_id
    assert people.mentions(scene, '@%s 你看' % BOT) == '@演示 你看'               # on any row, whoever carries it
    assert people.heard(scene, '@%s 在吗' % BOT) == '@演示 在吗'


def test_her_entry_takes_no_number_or_name_anywhere(store):
    setup(store)
    store.put('scenes', {'_id': 'qq:%s:private:20001' % BOT, 'kind': 'dm', 'scope_key': 'scene:dm-qq',
                         'channel_account_id': BOT, 'policy_epoch': 1, 'sequence': 0})
    dm = store.db.scenes.find_one({'_id': 'qq:%s:private:20001' % BOT})
    people = People(store, 'demo')
    doc = people.entry(dm, people.account_person(dm['_id'], BOT), profile={'nickname': '沈小满'})
    assert doc['handle'] == 0 and doc['nickname'] == '' and not store.db.scene_people.find_one({'scene_id': dm['_id']})


def test_another_account_with_a_like_name_stays_a_person(store):
    scene = setup(store)
    people = People(store, 'demo')
    sister = people.entry(scene, 'qq:20077', row(20077, '我也是小满', nickname='沈小满姐姐'))
    assert sister['handle'] > 0 and sister['person'] == 'qq:20077'
    assert people.account_person(SCENE, '20077') != people.self_id


# ---- she is told her own names --------------------------------------------------------------------------------

def test_the_member_list_names_her_as_herself_and_find_member_says_it_is_her(store):
    scene = setup(store)
    channel(store)
    mine = {'user_id': BOT, 'nickname': '沈小满', 'card': '', 'role': 'member', 'last_sent_time': NOW - 60}
    others = [member(n, ago_hours=n) for n in range(1, 4)] + [
        {'user_id': '20077', 'nickname': '沈小满姐姐', 'card': '', 'role': 'member', 'last_sent_time': NOW - 3600}]
    group_members.receive(store, 'qq', {'group_id': GROUP, 'members': [mine] + others})
    block = group_members.block(store, scene, 'demo')
    assert block['you'] == '你自己在这个群里的号：昵称「沈小满」，没设群名片；你的发言在这里标作「演示」。你还没在这里说过话。'
    assert all('沈小满」' not in item['who'] and item['who'] != '沈小满' for item in block['items'])
    assert len(block['items']) == 4 and 'not_shown' not in block                 # five members, she is not one shown
    found = group_members.find(store, scene, 'demo', '小满')
    assert found['you'] == '这是你自己（昵称「沈小满」，没设群名片）。'
    assert found['count'] == 1 and found['found'][0]['who'].startswith('[沈小满姐姐 #')
    alone = group_members.find(store, scene, 'demo', '沈小满')
    assert alone['note'] == '名单里叫这个名字的有 1 人，列了最近说过话的 1 个。'           # the sister; she is told apart
    assert not store.db.scene_people.find_one({'person': 'qq:' + BOT})


def test_her_own_line_says_when_she_last_spoke_here_and_how_much_today_in_words(store):
    """Her shape (2026-10-22): bands, never a bare time; the day on the conversation's clock; today's count in the
    same words as elsewhere. Only her delivered lines count."""
    from asuna.local_time import zone_of
    setup(store)
    tz = zone_of(store, SCENE)['tz']
    now = datetime(2026, 10, 22, 21, 0, tzinfo=tz).astimezone(timezone.utc)

    def said(*local_times, state='DELIVERED'):
        for at in local_times:
            seq = store.db.messages.count_documents({}) + 1
            store.db.messages.insert_one({'_id': 'out-%d' % seq, 'schema_version': 1, 'scene_id': SCENE,
                                          'direction': 'outbound', 'delivery_state': state, 'scene_seq': seq,
                                          'receipt_at': at.astimezone(timezone.utc).isoformat()})

    def heard():
        return group_members._spoken(store, SCENE, now)

    local = lambda *at: datetime(*at, tzinfo=tz)
    assert heard() == '你还没在这里说过话。'
    said(local(2026, 10, 19, 9, 0))
    assert heard() == '你上次在这里说话：好几天前；今天在这里还没说话。'
    said(local(2026, 10, 21, 22, 30))
    assert heard() == '你上次在这里说话：昨天；今天在这里还没说话。'
    said(local(2026, 10, 22, 10, 0))
    assert heard() == '你上次在这里说话：今天早先；今天在这里说了一句。'
    said(local(2026, 10, 22, 19, 0), local(2026, 10, 22, 19, 5))
    assert heard() == '你上次在这里说话：今晚早先；今天在这里说了几句。'
    said(local(2026, 10, 22, 20, 45))
    assert heard() == '你上次在这里说话：半小时内；今天在这里说了几句。'
    said(local(2026, 10, 22, 20, 58))
    said(local(2026, 10, 22, 20, 59, 30), state='FAILED')                      # not delivered: not a line here
    assert heard() == '你上次在这里说话：刚说过；今天在这里说了十来句。'
    assert not any(ch.isdigit() for ch in heard()), 'no number reaches her'


# ---- a program line carries only its thread -------------------------------------------------------------------

def test_a_program_line_keeps_the_thread_and_nothing_of_its_requests_envelope():
    group = program_group_context({'event': {'group_context': REQUEST}})
    assert group == {'wake_reason': None, 'topic_id': 'topic-1', 'reply_to': None, 'reply_message_id': None,
                     'mentioned_account_ids': []}
    scene = {'kind': 'group'}
    assert attend.gated(scene, {'group_context': REQUEST}) and not attend.gated(scene, {'group_context': group})
    assert program_group_context({'event': {}}) is None and program_group_context(None) is None


def test_a_task_result_row_is_stored_with_only_its_thread_and_still_names_who_asked(store):
    service, task, broker, work = task_setup(store)
    try:
        asked = store.db.messages.find_one({'_id': task['raw_input_refs'][0]})
        store.db.messages.update_one({'_id': asked['_id']}, {'$set': {'event.group_context': REQUEST}})
        current = store.db.tasks.find_one({'_id': task['_id']})
        done = store.put('tasks', {**current, 'state': 'RETURNED', 'feedback_state': 'READY', 'result': {
            'task_id': task['_id'], 'intent_revision': 1, 'text': '复制好了', 'facts': [], 'artifact_refs': []}},
            expected=current['revision'])
        ep = service.feedback(done, Coordinator(store, FakeLane(store, [FakeTurn([('think', {'thought': '好。'})],
                                                                                 '复制好了。')])))
        short = service._short_event(task, done, source=asked)
    finally:
        broker.close()
    stored = store.db.messages.find_one({'_id': 'in-' + ep['_id']})
    assert stored['event']['group_context'] == {'wake_reason': None, 'topic_id': 'topic-1', 'reply_to': None,
                                                'reply_message_id': None, 'mentioned_account_ids': []}
    assert stored['event']['person_id'] == 'A' and stored['author'] == PROGRAM_AUTHOR   # who asked stays (ADR-089)
    assert short['trusted_context_events'][0]['original_input'] == asked['text']        # the short one names it too
    assert short['trusted_context_events'][0]['original_input_id'] == asked['_id']


def test_a_program_line_is_nobody_calling_waiting_or_answering(store):
    scene = setup(store)
    mine = {'_id': 'in-mine', 'scene_id': SCENE, 'scene_seq': 3, 'author': 'demo', 'direction': 'outbound',
            'phase': 'SPEAK', 'episode_id': 'ep-q', 'delivery_state': 'DELIVERED', 'text': '谁有空？',
            'receipt_at': '2026-10-04T01:30:00+00:00', 'policy_epoch': 1, 'schema_version': 1}
    store.db.messages.insert_many([mine, program_line(5)])
    room = places.room(store, scene, datetime(2026, 10, 4, 3, tzinfo=timezone.utc) + timedelta(0))
    assert room['called'] is False                                                       # a task result calls nobody
    assert questions._group_answers(store, {'scene_id': SCENE, 'episode': 'ep-q'}, mine) == []
    _, shown = understanding.group_people(store, scene, {'person_id': 'qq:20001'}, 'demo', {'scene_seq': 4})
    assert PROGRAM_AUTHOR not in shown
