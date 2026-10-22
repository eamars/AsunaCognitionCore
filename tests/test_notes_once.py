"""ADR-091: a note is answered once, and a reply to a group arrives there next time.

A note shown in a finished turn of the conversation it went to was answered there; 30 notes in the record still
opened a turn of their own and were answered twice (one re-set a watch on her own account). And a reply from home to a
group's note opened a public turn told "nobody here is speaking"; it is now read in her next turn there."""
import time
from types import SimpleNamespace

from asuna import notes, places, visibility
from asuna.chat import Chat
from asuna.coordinator import Coordinator
from asuna.evidence import Evidence
from asuna.lanes import FakeLane, FakeTurn
from asuna.router import Router
from asuna.state import now
from test_engineering_m1 import THINK
from test_notes import G1, delivered, results, turn, world
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
