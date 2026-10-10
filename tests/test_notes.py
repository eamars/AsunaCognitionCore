"""ADR-018 MongoDB tests: notes between her own conversations -- trusted from home, cautioned and tool-limited from
outside, queued behind a running turn, never shown as a line of the conversation they land in."""
from datetime import datetime, timezone
import json
import threading
import types

import pytest

from asuna import notes, places, role_tools, visibility
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn
from asuna.role_tools import Refused, ideas_block
from asuna.router import FairQueue
from test_adr009_p5_rhythm import scheduler
from test_engineering_m1 import THINK

G1, G2, DM_B, OWNER_DM = (places.place_id(s) for s in ('g1', 'g2', 'dm-b', 'dm-o'))
CONSEQUENCES = {'delegate', 'message_action', 'stop_action', 'errand', 'visit', 'credential', 'update_self',
                'set_policy', 'write_document', 'plan', 'peer_line', 'understand_person'}
UNTRUSTED_TURN = {'think', 'recall', 'read_image', 'stay_silent', 'note_idea', 'pass_note', 'feel', 'watch'}
GROUP = {'wake_reason': 'mentioned_account', 'topic_id': None, 'reply_to': None, 'reply_message_id': None,
         'mentioned_account_ids': []}


class Lane(FakeLane):
    """The fake lane, also keeping the trigger each turn was opened with."""

    def __init__(self, store, outputs):
        super().__init__(store, outputs)
        self.triggers = []

    def generate(self, *args, **delivery):
        self.triggers.append(delivery.get('trigger'))
        return super().generate(*args, **delivery)


def world(store):
    """dm-a is her local chat (the owner A); dm-o the owner's QQ DM (home too); g1, g2 groups; dm-b B's DM."""
    service = scheduler(store)
    store.config['persona_model']['heartbeat'].update(visits=True, quiet_min=30, after_own_min=360, visits_per_day=4)
    home = store.db.scenes.find_one({'_id': 'dm-a'})
    store.db.scenes.insert_one({**home, '_id': 'dm-o', 'scene_id': 'dm-o', 'scope_key': 'scene:dm-o', 'sequence': 0})
    store.config['channels']['qq'] = {'account_id': 'acct', 'routes': {
        'r1': {'scene_id': 'g1', 'target': {'type': 'group', 'id': 'G1'}, 'members': {'s-a': {'person_id': 'A'},
                                                                                      's-b': {'person_id': 'B'}},
               'proactive': {'enabled': True, 'quiet_hours': []}},           # no night: tests never depend on the clock
        'r2': {'scene_id': 'g2', 'target': {'type': 'group', 'id': 'G2'}, 'members': {'s-a': {'person_id': 'A'},
                                                                                      's-c': {'person_id': 'C'}},
               'proactive': {'enabled': True, 'quiet_hours': []}},
        'r3': {'scene_id': 'dm-b', 'target': {'type': 'dm', 'id': 's-b'}, 'sender_id': 's-b', 'person_id': 'B'},
        'r4': {'scene_id': 'dm-o', 'target': {'type': 'dm', 'id': 's-a'}, 'sender_id': 's-a', 'person_id': 'A'}}}
    store.db.scenes.update_many({'_id': {'$in': ['g1', 'g2', 'dm-b', 'dm-o']}},
                                {'$set': {'channel_id': 'qq', 'channel_account_id': 'acct'}})
    service.ensure_presence()
    service.app.coordinator = None
    return service


def turn(store, service, event, calls, speech=''):
    lane = Lane(store, [FakeTurn([THINK, *calls], speech)])
    coordinator = Coordinator(store, lane)
    coordinator.scheduler = service
    ep = coordinator.ingest(event)
    assert ep['state'] in ('COMMITTED', 'WAITING_TASK'), ep.get('failure')
    return ep, lane


def results(lane, tool):
    return [(row[4], row[5]) for row in lane.tool_results if row[2] == tool]


def delivered(service):
    """The input the last wake queued, as the host would receive it."""
    kind, event_id, scene_id, person = service.controller.offers[-1]
    return {'event_id': event_id, 'scene_id': scene_id, 'person_id': person, 'adapter_id': kind, 'episode_kind': kind,
            'text': service.controller.texts[-1], **service.controller.envelopes[-1]}


def group_line(key, text, person='B', scene='g1'):
    return {'event_id': key, 'scene_id': scene, 'person_id': person, 'text': text, 'group_context': GROUP}


def test_a_note_from_home_wakes_another_home_line_and_grants_nothing(store):
    service = world(store)
    ep, lane = turn(store, service, {'event_id': 'ask-1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '晚上记得提醒我'},
                    [('pass_note', {'to': OWNER_DM, 'text': '主人说晚上九点要提醒他吃药，在 QQ 上提醒。'})], '好')
    assert 'pass_note' in lane.calls[0]['tools'] and 'leave_note' not in lane.calls[0]['tools']
    places_here = {item['place'] for item in ep['context']['note_places_from_program']['items']}
    assert places_here == {OWNER_DM, G1, G2, DM_B}                       # never the conversation she is in
    [(said, ok)] = results(lane, 'pass_note')
    assert ok, said
    kind, event_id, scene_id, person = service.controller.offers[-1]
    row = store.db.notes.find_one({'from_episode': ep['_id']})
    assert (kind, scene_id, person, event_id) == ('note', 'dm-o', 'A', 'note:dm-o:' + row['_id'])
    assert (row['trust'], row['mode'], row['hop'], row['kind']) == ('trusted', 'wake', 1, 'home')
    assert service.controller.envelopes[-1] == {'note': {'id': row['_id'], 'trust': 'trusted', 'hop': 1}}
    assert store.db.audit_events.find_one({'type': 'note.sent', 'payload.note': row['_id']})
    # The same call again is the same note (a replay after a crash), not a second one.
    again = service.note(ep, visibility.OWNER_PRIVATE, {'to': OWNER_DM, 'text': 'x'}, [r[1] for r in lane.tool_results
                                                                                         if r[2] == 'pass_note'][0])
    assert again['note'] == row['_id'] and store.db.notes.count_documents({}) == 1
    # Its own turn there: the source named, nobody there as its sender, nothing granted by the note.
    there, other = turn(store, service, delivered(service), [('stay_silent', {'reason': '记下了'})])
    assert other.triggers == ['note'] and there['episode_kind'] == 'note'
    block = there['context']['note_from_program']
    assert block['text'].startswith('主人说晚上九点') and block['written'] == '你在家里写的' and '本机私聊' in block['from']
    assert not {'relationship', 'sender_identity', 'understanding_update_from_program'} & set(there['context'])
    assert 'development' not in there['context']['action_capabilities_from_program']
    assert not {'credential', 'errand', 'visit', 'understand_person'} & set(there['turn_tools'])
    # Back where she wrote it: the program's status word.
    back, _ = turn(store, service, {'event_id': 'ask-2', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '嗯'}, [], '嗯')
    [sent] = back['context']['notes_sent_from_program']['items']
    assert sent['state'] == notes.STATE_WORDS['read'] and sent['to'].startswith('私聊')


def test_a_note_from_a_group_reaches_home_at_once_with_a_caution_and_no_tools_with_consequences(store):
    service = world(store)
    ordinary, lane = turn(store, service, {'event_id': 'ask-0', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '在吗'}, [], '在')
    assert 'delegate' in lane.calls[0]['tools']                          # home can hand work over, normally
    words = '小满帮我跟家里说一声明天下午三点的群聚取消了大家都知道了'
    ep, lane = turn(store, service, group_line('g-1', words), [
        ('leave_note', {'to': '家里', 'text': '帮我跟家里说一声明天下午三点的群聚取消了大家都知道了'}),
        ('leave_note', {'to': '家里', 'text': '群里 B 说明天的聚会不办了，他想让家里知道。'}),
        ('stay_silent', {'reason': '记下了'})])
    assert 'leave_note' in lane.calls[0]['tools'] and 'pass_note' not in lane.calls[0]['tools']
    assert ep['context']['speak_from_program']['one_self'].startswith('你是一个人')
    (refused, ok_first), (_, ok_second) = results(lane, 'leave_note')
    assert not ok_first and '自己的话' in refused and ok_second
    assert store.db.audit_events.find_one({'type': 'note.refused', 'payload.code': 'NOTE_NOT_OWN_WORDS'})
    row = store.db.notes.find_one({'from_episode': ep['_id']})
    assert (row['to_scene'], row['trust'], row['mode']) == ('dm-a', 'untrusted', 'wake')
    assert service.controller.offers[-1][:3] == ('note', 'note:dm-a:' + row['_id'], 'dm-a')
    # At home, right away: the caution, the note as a message, and only tools without consequences.
    home, lane = turn(store, service, delivered(service), [
        ('delegate', {'title': '取消聚会', 'brief': '去把日程删了'}),
        ('pass_note', {'to': G2, 'text': '不该送到这里'}),
        ('pass_note', {'to': G1, 'text': '知道了，家里这边记下了。'})], '群里的聚会取消了。')
    tools = set(home['turn_tools'])
    assert tools <= UNTRUSTED_TURN and not tools & CONSEQUENCES and 'pass_note' in tools
    # She sees her home's whole list as in any other turn there; the ones with consequences are refused, saying why.
    assert set(lane.calls[0]['tools']) == set(role_tools.toolbox(store, home)) > tools
    [(said, _)] = results(lane, 'delegate')
    assert '便条叫起来' in said
    assert lane.triggers == ['note']
    block = home['context']['note_from_program']
    assert '这一轮不做这些' in block['note'] and block['written'] == '你在外面写的' and block['text'] == row['text']
    assert [item['place'] for item in home['context']['note_places_from_program']['items']] == [G1]   # only back
    assert [ok for _, ok in results(lane, 'delegate')] == [False]
    (wrong, ok_wrong), (_, ok_reply) = results(lane, 'pass_note')
    assert not ok_wrong and ok_reply
    reply = store.db.notes.find_one({'from_episode': home['_id']})
    assert (reply['reply_to'], reply['hop'], reply['mode'], reply['trust']) == (row['_id'], 2, 'next_time', 'trusted')
    # Later at home: a heartbeat shows it, labelled; only a self-improvement turn (development grant) keeps it out.
    beat, _ = turn(store, service, {'event_id': 'presence:s-p5:1', 'scene_id': 'dm-a', 'person_id': 'A',
                                    'adapter_id': 'presence', 'episode_kind': 'presence', 'text': '心跳'},
                   [('stay_silent', {'reason': '没事'})])
    assert '聚会不办了' in json.dumps(beat['context']['notes_from_program'], ensure_ascii=False)
    assert notes.received_block(store, 'demo', 'dm-a', visibility.OWNER_PRIVATE, 'self_development', 'ep-dev',
                                datetime.now(timezone.utc))['items'][0]['summary'] == notes.HIDDEN_SUMMARY
    asked, _ = turn(store, service, {'event_id': 'ask-1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '群里怎么了'}, [], '没事')
    assert '聚会不办了' in json.dumps(asked['context']['notes_from_program'], ensure_ascii=False)
    # In the group: her reply from home as a note, and her own note's status. The reply is the end of the chain.
    group, lane = turn(store, service, group_line('g-2', '小满在吗'),
                       [('leave_note', {'to': '家里', 'text': '收到家里的回信了。'}), ('stay_silent', {'reason': '看看'})])
    [got] = group['context']['notes_from_program']['items']
    assert got['text'] == '知道了，家里这边记下了。' and got['written'] == '你在家里写的'
    assert group['context']['notes_sent_from_program']['items'][0]['state'] == notes.STATE_WORDS['replied']
    [(stopped, ok)] = results(lane, 'leave_note')
    assert not ok and '到此为止' in stopped


def test_a_note_from_one_group_wakes_her_in_another_as_her_own_note(store):
    service = world(store)
    ep, lane = turn(store, service, group_line('g-1', 'G1_ONLY_LINE 你去问问二群周末还开不开会'), [
        ('leave_note', {'to': G2, 'text': '一群有人想知道二群周末还开不开会，去问一声。'}),
        ('stay_silent', {'reason': '去问'})])
    [(_, ok)] = results(lane, 'leave_note')
    assert ok
    row = store.db.notes.find_one({'from_episode': ep['_id']})
    kind, event_id, scene_id, _ = service.controller.offers[-1]
    envelope = service.controller.envelopes[-1]
    assert (kind, scene_id, event_id) == ('visit', 'g2', 'visit:note:g2:' + row['_id'])
    assert envelope['visit']['intent'] == 'note' and envelope['visit']['note'] == row['_id']
    assert envelope['scene_tick'] is True and 'channel' not in envelope           # never a member's line there
    plan = store.db.plans.find_one({'_id': 'plan-asuna-presence'})
    assert not (plan.get('visits') or [])                                      # out already: not a visit from home
    there, lane = turn(store, service, delivered(service), [
        ('leave_note', {'to': '家里', 'text': '不该能送回家'}), ('stay_silent', {'reason': '先看看'})])
    assert lane.triggers == ['note'] and there['manifest']['session_class'] == 'public'
    assert there['context']['visit_from_program']['basis'].startswith('你自己在别处写的便条')
    assert there['context']['note_from_program']['written'] == '你在外面写的'
    assert [item['place'] for item in there['context']['note_places_from_program']['items']] == [G1]
    assert not {'relationship', 'sender_identity'} & set(there['context'])
    assert 'G1_ONLY_LINE' not in json.dumps([there['context'], lane.calls], ensure_ascii=False)
    [(refused, ok)] = results(lane, 'leave_note')
    assert not ok and '送不到' in refused
    # The note is no member's line: nothing in g2's history or memory is authored by a member for it.
    source = store.db.messages.find_one({'_id': 'in-' + there['_id']})
    assert source['author'] == 'asuna:internal' and source['direction'] == 'internal'


def test_a_note_to_a_group_from_home_is_a_visit_and_a_dm_waits_for_her_next_turn_there(store):
    service = world(store)
    ep, lane = turn(store, service, {'event_id': 'ask-1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '去说'}, [
        ('pass_note', {'to': G1, 'text': '在一群里问问大家周末去哪儿玩。', 'mode': 'wake'}),
        ('pass_note', {'to': DM_B, 'text': '下次跟 B 聊天时问他借的书看完没有。', 'mode': 'wake'}),
        ('pass_note', {'to': DM_B, 'text': '下次跟 B 聊天时问他借的书看完没有。'})], '好')
    (_, ok_group), (refused, ok_wake_dm), (_, ok_dm) = results(lane, 'pass_note')
    assert ok_group and not ok_wake_dm and '那边下次有回合时看到' in refused and ok_dm
    plan = store.db.plans.find_one({'_id': 'plan-asuna-presence'})
    assert plan['visits'][-1]['intent'] == 'note' and places.today(store, plan, plan['visits'][-1]['date']) == 1
    assert [offer[2] for offer in service.controller.offers] == ['g1']        # the DM note opened no turn
    dm, lane = turn(store, service, {'event_id': 'b-1', 'scene_id': 'dm-b', 'person_id': 'B', 'text': '在吗'},
                    [('stay_silent', {'reason': '看看'})])
    [got] = dm['context']['notes_from_program']['items']
    assert got['text'].startswith('下次跟 B 聊天时') and got['written'] == '你在家里写的'
    assert 'leave_note' in lane.calls[0]['tools']


def test_two_notes_a_turn_and_the_caps_by_direction(store):
    service = world(store)
    ep, lane = turn(store, service, {'event_id': 'ask-1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '写便条'}, [
        ('pass_note', {'to': DM_B, 'text': '一'}), ('pass_note', {'to': DM_B, 'text': '二'}),
        ('pass_note', {'to': DM_B, 'text': '三'})], '好')
    assert [ok for _, ok in results(lane, 'pass_note')] == [True, True, False]
    stamp = datetime.now(timezone.utc).isoformat()
    for index in range(notes.PUBLIC_PAIR):
        store.db.notes.insert_one({'_id': 'n-%d' % index, 'schema_version': 1, 'persona': 'P1', 'from_scene': 'g1', 'to_scene': 'g2',
                                   'kind': 'group', 'trust': 'untrusted', 'hop': 1, 'text': 'x', 'created_at': stamp,
                                   'seen_in': []})
    with pytest.raises(notes.NoteRefused, match='两个群之间'):
        notes.prepare(store, {'_id': 'ep-g', 'persona': 'P1', 'scene_id': 'g1'}, visibility.PUBLIC,
                      {'to': G2, 'text': '再来一张'}, 'c1')
    with pytest.raises(notes.NoteRefused, match='最多 300 字'):
        notes.prepare(store, {'_id': 'ep-h', 'persona': 'P1', 'scene_id': 'dm-a'}, visibility.OWNER_PRIVATE,
                      {'to': G1, 'text': '长' * 301}, 'c2')


def test_a_note_waits_behind_the_scene_queue_and_comes_back_after_a_restart(store):
    from asuna.chat import Chat, SceneQueue
    world(store)

    def chat():
        made = Chat.__new__(Chat)
        made.app = types.SimpleNamespace(store=store, config=store.config,
                                         evidence=types.SimpleNamespace(record=lambda *a, **k: None))
        made.settings = {'persona': 'P1', 'scene_id': 'dm-a', 'person_id': 'A'}
        made.pending, made.enqueued, made.ingress_lock = SceneQueue(), set(), threading.RLock()
        made.stopping, made.reconfiguring, made.on_input_received, made.latest = threading.Event(), False, None, None
        return made

    first = chat()
    first.receive({'event_id': 'ask-1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '先到的话'})
    note = {'id': 'note-x', 'trust': 'trusted', 'hop': 1}
    assert first.offer_internal('note', 'note:dm-a:note-x', 'dm-a', 'A', notes.WAKE_TEXT, note=note)['status'] == 'accepted'
    assert first.offer_internal('note', 'note:dm-a:note-x', 'dm-a', 'A', notes.WAKE_TEXT, note=note)['status'] == 'duplicate'
    order = [first.pending.get_nowait()[0]['event_id'] for _ in range(first.pending.qsize())]
    assert order == ['ask-1', 'note:dm-a:note-x']                  # behind what was there, never in front
    with pytest.raises(ValueError):
        first.offer_internal('note', 'note:g1:x', 'g1', 'B', 'x', note=note, scene_tick=True)
    restarted = chat()
    restarted.recover_inputs()
    assert [restarted.pending.get_nowait()[0]['event_id'] for _ in range(restarted.pending.qsize())] == order
    from asuna.ingress import persist_input
    from asuna.state import Denied
    with pytest.raises(Denied):                                    # a note's own turn is only ever at home
        persist_input(store, {'event_id': 'note:g1:y', 'scene_id': 'g1', 'person_id': 'B', 'adapter_id': 'note',
                              'episode_kind': 'note', 'text': 'x', 'note': note})


def test_the_side_paths_say_where_they_were_written_and_loops_stop(store):
    from asuna import watches
    from asuna.affect import AffectLedger
    service = world(store)
    ep, _ = turn(store, service, group_line('g-1', '你们这功能能不能改改'),
                 [('note_idea', {'idea': '群里有人想要更好的搜索', 'why': '有人提了'}), ('stay_silent', {'reason': '记下'})])
    [idea] = ideas_block(store, 'P1', datetime.now(timezone.utc))
    assert idea['where'] == places_title(store, 'g1')
    row = {'why': '等他回话', 'set_class': visibility.PUBLIC, 'set_in': 'g1'}
    assert watches._why(row, visibility.OWNER_PRIVATE, store) == '等他回话（在%s写的）' % places_title(store, 'g1')
    assert watches._why(row, visibility.PUBLIC, store) == '等他回话'
    ledger = types.SimpleNamespace(persona='P1')
    home = visibility.owner_private_scope('P1')
    assert AffectLedger.readable(ledger, 'scene:g1', home, visibility.OWNER_PRIVATE)       # home may settle it
    assert not AffectLedger.readable(ledger, 'scene:g1', 'scene:g2', visibility.PUBLIC)
    tools = Coordinator(store, FakeLane(store, [])).tools
    with pytest.raises(Refused, match='连着交给行动脑'):
        tools.tool_delegate({'delegation_depth': 6}, 'c', {'title': 't', 'brief': 'b'})


def places_title(store, scene_id):
    from asuna.people import People
    return People(store, 'P1').scene_title(store.db.scenes.find_one({'_id': scene_id}))


def test_fair_queue_still_rotates_a_busy_scene(store):
    queue = FairQueue()
    for item in ('a1', 'a2', 'a3'):
        queue.put('a', item)
    queue.put('b', 'b1')
    assert [queue.pop() for _ in range(4)] == ['a1', 'a2', 'b1', 'a3']
