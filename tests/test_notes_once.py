"""ADR-091: a note is answered once, and a reply to a group arrives there next time.

A note shown in a finished turn of the conversation it went to was answered there; 30 notes in the record still
opened a turn of their own and were answered twice (one re-set a watch on her own account). And a reply from home to a
group's note opened a public turn told "nobody here is speaking"; it is now read in her next turn there."""
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from asuna import notes, places, visibility
from asuna.chat import Chat
from asuna.coordinator import Coordinator
from asuna.evidence import Evidence
from asuna.lanes import FakeLane, FakeTurn
from asuna.router import Router
from asuna.state import now
from test_engineering_m1 import THINK
from test_notes import G1, day_note, delivered, results, turn, world
from test_turn_lines import settled


def a_note(store, to_scene='dm-a', note_id='note-once-1'):
    return store.put('notes', {'_id': note_id, 'persona': 'P1', 'from_scene': 'dm-b', 'from_class': visibility.OWNER_PRIVATE,
                               'from_episode': 'ep-elsewhere', 'to_scene': to_scene, 'kind': 'home', 'place': 'x',
                               'text': '晚上记得给主人回个电话。', 'trust': notes.TRUSTED, 'mode': notes.WAKE, 'hop': 1,
                               'reply_to': None, 'tables_version': notes.TABLES_VERSION, 'created_at': now(),
                               'seen_in': []}, stream='notes:P1')


def test_a_note_read_in_a_turn_ahead_of_its_own_opens_no_second_turn(store, tmp_path):
    world(store)                                                    # dm-a is her local chat (home)
    lane = FakeLane(store, [])
    app = SimpleNamespace(store=store, config=store.config, evidence=Evidence(tmp_path / 'evidence'),
                          character=lane, router=Router(store, Coordinator(store, lane)))
    chat = Chat(app, {'scene_id': 'dm-a', 'person_id': 'A', 'persona': 'P1', 'display_name': '演示'}, lambda _: None)
    # The owner's line is queued first; the note arrives behind it. His turn, prepared after the note was written,
    # shows it and marks it seen; the note's own turn then has nothing left to answer.
    first = chat.receive({'event_id': 'o-1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '在吗'})['episode_id']
    row = a_note(store)
    note_ep = chat.offer_internal('note', 'note:dm-a:' + row['_id'], 'dm-a', 'A', notes.WAKE_TEXT,
                                  note={'id': row['_id'], 'trust': notes.TRUSTED, 'hop': 1})['episode_id']
    lane.outputs = iter([FakeTurn([THINK], '在，晚上我提醒你回电话。')])
    chat.worker.start()
    try:
        rows = settled(store, chat, ['in-' + first, 'in-' + note_ep])
    finally:
        chat.stop()
    assert first in store.db.notes.find_one({'_id': row['_id']})['seen_in']
    assert rows[0]['result_state'] == 'COMMITTED'
    assert rows[1]['ingress_state'] == 'COMPLETE' and rows[1]['result_state'] == 'SEEN_IN_TURN'
    assert len(lane.calls) == 1, 'one turn answered the note'


def test_a_note_is_read_elsewhere_only_in_a_finished_turn_other_than_its_own(store):
    row = a_note(store)
    event = {'note': {'id': row['_id']}}
    assert not notes.read_elsewhere(store, event, 'ep-own')
    store.db.notes.update_one({'_id': row['_id']}, {'$set': {'seen_in': ['ep-own', 'ep-running']}})
    store.db.episodes.insert_one({'_id': 'ep-running', 'state': 'TURN', 'schema_version': 1})
    assert not notes.read_elsewhere(store, event, 'ep-own')                    # not answered yet: its own turn runs
    store.db.episodes.update_one({'_id': 'ep-running'}, {'$set': {'state': 'COMMITTED'}})
    assert notes.read_elsewhere(store, event, 'ep-own')
    assert notes.read_elsewhere(store, {'visit': {'note': row['_id']}}, 'ep-own')   # a note to a group is a visit
    assert not notes.read_elsewhere(store, {}, 'ep-own')


def test_a_visit_its_note_made_unneeded_is_neither_pending_nor_counted(store):
    visit = {'scene_id': 'g1', 'event_id': 'visit:note:g1:n-1', 'date': '2026-10-22'}
    key = places.episode_key(visit)
    store.db.messages.insert_one({'_id': 'in-' + key, 'scene_id': 'g1', 'schema_version': 1,
                                  'ingress_state': 'COMPLETE', 'result_state': 'SEEN_IN_TURN'})
    assert places.outcome(store, visit) == 'seen' and places.OUTCOMES['seen']
    plan = {'visits': [visit]}
    assert places.today(store, plan, '2026-10-22') == 0 and places.last_visit(store, plan, 'g1') is None


def test_a_note_read_in_another_turn_is_no_outing_and_its_sender_reads_it_may_be_undone(store):
    """Her review (10-22): a turn that had the note in view may have stayed silent, so read is not done. The visit it
    made unneeded is not listed as an outing, and the note's own line says so and how to check."""
    world(store)
    seen = {'scene_id': 'g1', 'event_id': 'visit:note:g1:n-seen', 'date': '2026-10-22', 'at': now(), 'intent': 'check_in'}
    store.db.messages.insert_one({'_id': 'in-' + places.episode_key(seen), 'scene_id': 'g1', 'schema_version': 1,
                                  'ingress_state': 'COMPLETE', 'result_state': 'SEEN_IN_TURN'})
    assert places.last_visits_block(store, 'P1', {'visits': [seen]}, None) is None
    went = {'scene_id': 'g1', 'event_id': 'visit:check:g1', 'date': '2026-10-22', 'at': now(), 'intent': 'check_in'}
    [row] = places.last_visits_block(store, 'P1', {'visits': [went, seen]}, None)['items']
    assert row['what'] == places.OUTCOMES['pending']
    # Home wrote the note; a finished turn there had it in view and said nothing about it.
    store.db.episodes.insert_one({'_id': 'ep-there', 'state': 'COMMITTED', 'schema_version': 1})
    store.db.notes.insert_one({'_id': 'n-seen', 'schema_version': 1, 'persona': 'P1', 'from_scene': 'dm-a', 'to_scene': 'g1',
                               'kind': 'group', 'trust': notes.TRUSTED, 'mode': notes.WAKE, 'hop': 1, 'reply_to': None,
                               'text': '帮我在群里问一句周末去不去。', 'created_at': now(), 'seen_in': ['ep-there']})
    [sent] = notes.sent_block(store, 'P1', 'dm-a', datetime.now(timezone.utc))['items']
    assert sent['state'] == '读了，没回（读到不等于办了：要确认，再写一张问一句）'


def test_a_turn_a_reply_opened_writes_no_note_and_is_told_why(store):
    world(store)
    store.db.notes.insert_one({'_id': 'n-back', 'schema_version': 1, 'persona': 'P1', 'from_scene': 'g1', 'to_scene': 'dm-a',
                               'kind': 'home', 'trust': notes.UNTRUSTED, 'mode': notes.WAKE, 'hop': notes.MAX_HOP,
                               'reply_to': 'n-first', 'text': '知道了', 'created_at': now(), 'seen_in': []})
    store.db.messages.insert_one({'_id': 'in-ep-back', 'scene_id': 'dm-a', 'schema_version': 1,
                                  'event': {'note': {'id': 'n-back', 'trust': notes.UNTRUSTED, 'hop': notes.MAX_HOP}}})
    with pytest.raises(notes.NoteRefused) as refused:
        notes.prepare(store, {'_id': 'ep-back', 'persona': 'P1', 'scene_id': 'dm-a'}, visibility.OWNER_PRIVATE,
                      {'to': G1, 'text': '再说一句'}, 'c1')
    assert (refused.value.code, str(refused.value)) == ('NOTE_HOP_LIMIT', notes.REPLY_ENDS)


def test_a_reply_home_still_wakes_and_a_new_chain_counts_against_the_day(store):
    world(store)
    # Home asked the group; the group's turn read it and answers home: a reply, hop 2, and it wakes home as before.
    day_note(store, 'asked', 'dm-a', 'g1', 'group', trust=notes.TRUSTED, seen_in=['ep-g'])
    draft, _ = notes.prepare(store, {'_id': 'ep-g', 'persona': 'P1', 'scene_id': 'g1'}, visibility.PUBLIC,
                             {'to': '家里', 'text': '问过了，大家都去。'}, 'c1')
    assert (draft['hop'], draft['reply_to'], draft['mode']) == (2, 'asked', notes.WAKE)
    # Home's reply to the group's own note, shown in a turn a person opened there: a note home from that turn starts
    # a new chain, and a new chain counts against the day's notes home like any first note.
    for index in range(notes.PUBLIC_HOME_PER_SCENE):
        day_note(store, 'day-%d' % index, 'g1', 'dm-a', 'home')
    day_note(store, 'home-back', 'dm-a', 'g1', 'group', trust=notes.TRUSTED, hop=2, reply_to='day-0', seen_in=['ep-p'])
    with pytest.raises(notes.NoteRefused) as refused:
        notes.prepare(store, {'_id': 'ep-p', 'persona': 'P1', 'scene_id': 'g1'}, visibility.PUBLIC,
                      {'to': '家里', 'text': '家里的回信收到了。'}, 'c2')
    assert refused.value.code == 'NOTE_HOME_LIMIT'


def test_a_reply_to_a_group_arrives_next_time_and_wake_stays_her_choice(store):
    service = world(store)
    group, _ = turn(store, service, {'event_id': 'g-ask', 'scene_id': 'g1', 'person_id': 'B', 'text': '小满帮我问问家里',
                                     'group_context': {'wake_reason': 'mentioned_account', 'topic_id': None,
                                                       'reply_to': None, 'reply_message_id': None,
                                                       'mentioned_account_ids': []}},
                    [('note', {'to': '家里', 'text': '群里有人想问家里一件事。'}), ('stay_silent', {'why': '带回家'})])
    offers = len(service.controller.offers)
    home, lane = turn(store, service, delivered(service), [('note', {'to': G1, 'text': '家里知道了。'})], '嗯。')
    [(sent, ok)] = results(lane, 'note')
    assert ok, sent
    reply = store.db.notes.find_one({'from_episode': home['_id']})
    assert (reply['hop'], reply['mode']) == (2, notes.NEXT_TIME) and sent['arrives'] == notes.MODE_WORDS[notes.NEXT_TIME]
    assert len(service.controller.offers) == offers                           # no turn opened in the group
    # From a trusted home turn too, and `wake` when she asks for it (a reply someone there is waiting on).
    home2, lane2 = turn(store, service, {'event_id': 'h-1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '嗯'},
                        [('note', {'to': G1, 'text': '再补一句：明天见。', 'deliver': 'wake'})], '好')
    [(sent2, ok2)] = results(lane2, 'note')
    assert ok2, sent2
    assert store.db.notes.find_one({'from_episode': home2['_id']})['mode'] == notes.WAKE
