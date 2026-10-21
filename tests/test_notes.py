"""ADR-018 MongoDB tests: notes between her own conversations -- trusted from home, cautioned and tool-limited from
outside, queued behind a running turn, never shown as a line of the conversation they land in."""
from datetime import datetime, timezone
import json
import threading
import types

import pytest

from asuna import channel_kinds, notes, places, role_tools, visibility
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn
from asuna.role_tools import Refused, ideas_block
from asuna.router import FairQueue
from test_adr009_p5_rhythm import scheduler
from test_engineering_m1 import THINK
from reply_parts import said

G1, G2, DM_B, OWNER_DM = (places.place_id(s) for s in ('g1', 'g2', 'dm-b', 'dm-o'))
CONSEQUENCES = {'delegate', 'task.message', 'task.stop', 'errand', 'visit', 'credential', 'update_self',
                'set_policy', 'write_document', 'plan', 'peer_line', 'understand_person'}
UNTRUSTED_TURN = {'think', 'recall', 'read_image', 'stay_silent', 'ideas.note', 'note', 'feel', 'watch', 'ask.read',
                  'ideas.read'}
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
    store.config['persona_model']['heartbeat'].update(visits=True, visits_per_day=4)
    home = store.db.scenes.find_one({'_id': 'dm-a'})
    store.db.scenes.insert_one({**home, '_id': 'dm-o', 'scene_id': 'dm-o', 'scope_key': 'scene:dm-o', 'sequence': 0})
    store.config['channels']['qq'] = {'account_id': 'acct', 'routes': {
        'r1': {'scene_id': 'g1', 'target': {'type': 'group', 'id': 'G1'}, 'members': {'s-a': {'person_id': 'A'},
                                                                                      's-b': {'person_id': 'B'}},
               'proactive': {'enabled': True}},
        'r2': {'scene_id': 'g2', 'target': {'type': 'group', 'id': 'G2'}, 'members': {'s-a': {'person_id': 'A'},
                                                                                      's-c': {'person_id': 'C'}},
               'proactive': {'enabled': True}},
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


def test_a_note_from_home_wakes_another_home_line_as_her_own_initiative(store):
    service = world(store)
    ep, lane = turn(store, service, {'event_id': 'ask-1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '晚上记得提醒我'},
                    [('note', {'to': OWNER_DM, 'text': '主人说晚上九点要提醒他吃药，在 QQ 上提醒。'})], '好')
    assert 'note' in lane.calls[0]['tools']
    places_here = {item['place'] for item in ep['context']['note_places_from_program']['items']}
    assert places_here == {OWNER_DM, G1, G2, DM_B}                       # never the conversation she is in
    [(said, ok)] = results(lane, 'note')
    assert ok, said
    kind, event_id, scene_id, person = service.controller.offers[-1]
    row = store.db.notes.find_one({'from_episode': ep['_id']})
    assert (kind, scene_id, person, event_id) == ('note', 'dm-o', 'A', 'note:dm-o:' + row['_id'])
    assert (row['trust'], row['mode'], row['hop'], row['kind']) == ('trusted', 'wake', 1, 'home')
    assert service.controller.envelopes[-1] == {'note': {'id': row['_id'], 'trust': 'trusted', 'hop': 1}}
    assert store.db.audit_events.find_one({'type': 'note.sent', 'payload.note': row['_id']})
    # The same call again is the same note (a replay after a crash), not a second one.
    again = service.note(ep, visibility.OWNER_PRIVATE, {'to': OWNER_DM, 'text': 'x'}, [r[1] for r in lane.tool_results
                                                                                         if r[2] == 'note'][0])
    assert again['note'] == row['_id'] and store.db.notes.count_documents({}) == 1
    # Its own turn there: the source named, nobody there as its sender; a note from home is her own initiative, so
    # it carries the development tools as her plans do (owner 2026-10-12), and still nothing about a person.
    there, other = turn(store, service, delivered(service), [('stay_silent', {'why': '记下了'})])
    assert other.triggers == ['note'] and there['episode_kind'] == 'note'
    block = there['context']['note_from_program']
    assert block['text'].startswith('主人说晚上九点') and block['written'] == '你在家里写的' and '家里·私聊' in block['from']
    assert not {'relationship', 'sender_identity', 'understanding_update_from_program'} & set(there['context'])
    assert 'development' in there['context']['action_capabilities_from_program']
    assert not {'credential', 'visit', 'understand_person'} & set(there['turn_tools'])
    # A note of hers from home is home's own instruction: its turn may send an errand (ADR-066).
    assert 'errand' in there['turn_tools'] and there['context']['errand_places_from_program']
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
        ('note', {'to': '家里', 'text': '帮我跟家里说一声明天下午三点的群聚取消了大家都知道了'}),
        ('note', {'to': '家里', 'text': '群里 B 说明天的聚会不办了，他想让家里知道。'}),
        ('stay_silent', {'why': '记下了'})])
    assert 'note' in lane.calls[0]['tools']
    assert ep['context']['speak_from_program']['one_self'].startswith('你是一个人')
    (refused, ok_first), (_, ok_second) = results(lane, 'note')
    assert not ok_first and '自己的话' in refused and ok_second
    assert store.db.audit_events.find_one({'type': 'note.refused', 'payload.code': 'NOTE_NOT_OWN_WORDS'})
    row = store.db.notes.find_one({'from_episode': ep['_id']})
    assert (row['to_scene'], row['trust'], row['mode']) == ('dm-a', 'untrusted', 'wake')
    assert service.controller.offers[-1][:3] == ('note', 'note:dm-a:' + row['_id'], 'dm-a')
    # At home, right away: the caution, the note as a message, and only tools without consequences.
    home, lane = turn(store, service, delivered(service), [
        ('delegate', {'title': '取消聚会', 'brief': '去把日程删了'}),
        ('ideas', {'do': 'note', 'idea': '群聚取消了，日程要改', 'why': '群里说的'}),
        ('note', {'to': G2, 'text': '不该送到这里'}),
        ('note', {'to': G1, 'text': '知道了，家里这边记下了。'})], '群里的聚会取消了。')
    tools = set(home['turn_tools'])
    assert tools <= UNTRUSTED_TURN and not tools & CONSEQUENCES and 'note' in tools
    # She sees her home's whole list as in any other turn there; the ones with consequences are refused, saying why.
    assert set(lane.calls[0]['tools']) == set(role_tools.toolbox(store, home))
    assert set(role_tools.abilities(store, home)) > tools
    [(said, _)] = results(lane, 'delegate')
    assert '便条叫起来' in said
    assert lane.triggers == ['note']
    block = home['context']['note_from_program']
    assert '这一回合不做这些' in block['note'] and block['written'] == '你在外面写的' and block['text'] == row['text']
    assert [item['place'] for item in home['context']['note_places_from_program']['items']] == [G1]   # only back
    assert [ok for _, ok in results(lane, 'delegate')] == [False]
    (wrong, ok_wrong), (_, ok_reply) = results(lane, 'note')
    assert not ok_wrong and ok_reply
    reply = store.db.notes.find_one({'from_episode': home['_id']})
    assert (reply['reply_to'], reply['hop'], reply['mode'], reply['trust']) == (row['_id'], 2, 'wake', 'trusted')   # to a group: wakes it
    # The idea she noted here came from the group, not from home, where the turn ran (ADR-088 step 1).
    [idea] = ideas_block(store, 'P1', datetime.now(timezone.utc))
    assert idea['where'] == role_tools.IDEA_BY_NOTE % (places_title(store, 'g1'), '')
    # Her rule: when the note that opened it cannot be found, the place is undetermined, not the likeliest one.
    store.db.messages.update_one({'_id': 'in-' + home['_id']}, {'$unset': {'event.note': ''}})
    [idea] = ideas_block(store, 'P1', datetime.now(timezone.utc))
    assert idea['where'] == role_tools.IDEA_PLACE_UNKNOWN
    # Later at home: a heartbeat shows it, labelled; only a self-improvement turn (development grant) keeps it out.
    beat, _ = turn(store, service, {'event_id': 'presence:s-p5:1', 'scene_id': 'dm-a', 'person_id': 'A',
                                    'adapter_id': 'presence', 'episode_kind': 'presence', 'text': '心跳'},
                   [('stay_silent', {'why': '没事'})])
    assert '聚会不办了' in json.dumps(beat['context']['notes_from_program'], ensure_ascii=False)
    assert notes.received_block(store, 'demo', 'dm-a', visibility.OWNER_PRIVATE, 'self_development', 'ep-dev',
                                datetime.now(timezone.utc))['items'][0]['summary'] == notes.HIDDEN_SUMMARY
    asked, _ = turn(store, service, {'event_id': 'ask-1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '群里怎么了'}, [], '没事')
    assert '聚会不办了' in json.dumps(asked['context']['notes_from_program'], ensure_ascii=False)
    # In the group: her reply from home as a note, and her own note's status. The reply is the end of the chain.
    group, lane = turn(store, service, group_line('g-2', '小满在吗'),
                       [('note', {'to': '家里', 'text': '收到家里的回信了。'}), ('stay_silent', {'why': '看看'})])
    [got] = group['context']['notes_from_program']['items']
    assert got['text'] == '知道了，家里这边记下了。' and got['written'] == '你在家里写的'
    assert group['context']['notes_sent_from_program']['items'][0]['state'] == notes.STATE_WORDS['replied']
    [(stopped, ok)] = results(lane, 'note')
    assert not ok and '到此为止' in stopped


def test_a_note_from_outside_reaches_the_owners_own_chat_and_she_answers_him_there(store, monkeypatch):
    """Owner 2026-10-17: from anywhere, at any time, a note of hers may go to his own direct chat; the turn it opens
    there may speak to him. Never a peer or agent line, which are home but not him; each home has its own day count."""
    service = world(store)
    home = store.db.scenes.find_one({'_id': 'dm-a'})
    store.db.scenes.insert_one({**home, '_id': 'line-x', 'scene_id': 'line-x', 'scope_key': 'scene:line-x', 'sequence': 0})
    store.config['channels']['qq']['routes']['r5'] = {'scene_id': 'line-x', 'target': {'type': 'dm', 'id': 'agent'},
                                                      'sender_id': 'agent', 'person_id': 'X'}
    monkeypatch.setattr(channel_kinds, 'home', lambda identifier: identifier == 'line-x')
    monkeypatch.setattr(channel_kinds, 'reply_parts', lambda scene_id: ('text',) if scene_id == 'dm-o' else ())
    ep, lane = turn(store, service, group_line('g-1', '小满你今天怎么不说话'), [
        ('note', {'to': OWNER_DM, 'text': '群里有人一直拿我开玩笑，我有点不舒服，想跟你说一声。'}),
        ('stay_silent', {'why': '先不在这里说'})])
    homes = [item['place'] for item in ep['context']['note_places_from_program']['items']
             if item['place'] not in (G2,)]
    assert homes == [places.place_id('dm-a'), OWNER_DM]          # the local chat first (家里), then his own chat
    [(said_back, ok)] = results(lane, 'note')
    assert ok, said_back
    row = store.db.notes.find_one({'from_episode': ep['_id']})
    assert (row['to_scene'], row['trust'], row['mode'], row['kind']) == ('dm-o', 'untrusted', 'wake', 'home')
    assert service.controller.offers[-1][:3] == ('note', 'note:dm-o:' + row['_id'], 'dm-o')
    # There, right away: she may speak to him; nothing with consequences.
    there, lane = turn(store, service, delivered(service), [said('刚才群里有点烦，跟你说一声。')])
    tools = set(there['turn_tools'])
    assert 'speak' in tools and not tools & CONSEQUENCES
    # It says where she is and who reads her words: he sees only what she says here, never the note.
    block = there['context']['note_from_program']
    assert block['note'].startswith('他看不到便条，只看得到你在这里说的话：这里是主人的私聊。')
    assert block['reply'].startswith('在这里说的他马上看得到')
    [(spoken, ok)] = results(lane, 'speak')
    assert ok, spoken
    # Each home has its own count: a day of notes to the local chat leaves his chat open.
    stamp = datetime.now(timezone.utc).isoformat()
    for index in range(notes.PUBLIC_HOME_PER_SCENE):
        store.db.notes.insert_one({'_id': 'day-%d' % index, 'schema_version': 1, 'persona': 'P1', 'from_scene': 'g1',
                                   'to_scene': 'dm-a', 'kind': 'home', 'trust': 'untrusted', 'hop': 1, 'text': 'x',
                                   'created_at': stamp, 'seen_in': []})
    with pytest.raises(notes.NoteRefused, match='往那边写的便条'):
        notes.prepare(store, {'_id': 'ep-l', 'persona': 'P1', 'scene_id': 'g1'}, visibility.PUBLIC,
                      {'to': '家里', 'text': '又一张'}, 'c1')
    notes.prepare(store, {'_id': 'ep-m', 'persona': 'P1', 'scene_id': 'g1'}, visibility.PUBLIC,
                  {'to': OWNER_DM, 'text': '还想跟你说一句'}, 'c2')


def test_a_note_from_one_group_wakes_her_in_another_as_her_own_note(store):
    service = world(store)
    ep, lane = turn(store, service, group_line('g-1', 'G1_ONLY_LINE 你去问问二群周末还开不开会'), [
        ('note', {'to': G2, 'text': '一群有人想知道二群周末还开不开会，去问一声。'}),
        ('stay_silent', {'why': '去问'})])
    [(_, ok)] = results(lane, 'note')
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
        ('note', {'to': '家里', 'text': '不该能送回家'}), ('stay_silent', {'why': '先看看'})])
    assert lane.triggers == ['note'] and there['manifest']['session_class'] == 'public'
    assert there['context']['visit_from_program']['basis'].startswith('你自己在别处写的便条')
    assert there['context']['note_from_program']['written'] == '你在外面写的'
    assert [item['place'] for item in there['context']['note_places_from_program']['items']] == [G1]
    assert not {'relationship', 'sender_identity'} & set(there['context'])
    assert 'G1_ONLY_LINE' not in json.dumps([there['context'], lane.calls], ensure_ascii=False)
    [(refused, ok)] = results(lane, 'note')
    assert not ok and '送不到' in refused
    # The note is no member's line: nothing in g2's history or memory is authored by a member for it.
    source = store.db.messages.find_one({'_id': 'in-' + there['_id']})
    assert source['author'] == 'asuna:internal' and source['direction'] == 'internal'


def test_a_note_to_a_group_from_home_is_a_visit_and_a_dm_waits_for_her_next_turn_there(store):
    service = world(store)
    ep, lane = turn(store, service, {'event_id': 'ask-1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '去说'}, [
        ('note', {'to': G1, 'text': '在一群里问问大家周末去哪儿玩。'}),               # a group wakes by default
        ('note', {'to': DM_B, 'text': '下次跟 B 聊天时问他借的书看完没有。', 'deliver': 'wake'}),
        ('note', {'to': DM_B, 'text': '下次跟 B 聊天时问他借的书看完没有。'})], '好')
    (_, ok_group), (refused, ok_wake_dm), (_, ok_dm) = results(lane, 'note')
    assert ok_group and not ok_wake_dm and '那边下次有回合时看到' in refused and ok_dm
    plan = store.db.plans.find_one({'_id': 'plan-asuna-presence'})
    assert plan['visits'][-1]['intent'] == 'note' and places.today(store, plan, plan['visits'][-1]['date']) == 1
    assert [offer[2] for offer in service.controller.offers] == ['g1']        # the DM note opened no turn
    dm, lane = turn(store, service, {'event_id': 'b-1', 'scene_id': 'dm-b', 'person_id': 'B', 'text': '在吗'},
                    [('stay_silent', {'why': '看看'})])
    [got] = dm['context']['notes_from_program']['items']
    assert got['text'].startswith('下次跟 B 聊天时') and got['written'] == '你在家里写的'
    assert 'note' in lane.calls[0]['tools']


def test_a_note_over_its_length_sends_nothing_and_leaves_what_to_drop_to_her(store):
    """ADR-069: the limit is real. A note's last line often says what counts as done and a cut of the end loses it, so
    no cut is offered: she shortens it or splits it (her ask, 2026-10-22)."""
    service = world(store)
    long = '今天下午去看了展。' * 40                       # 360 characters from home to a group: over 300
    ep, lane = turn(store, service, {'event_id': 'ask-1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '写便条'},
                    [('note', {'to': G1, 'text': long})], '好')
    [(refused, ok)] = results(lane, 'note')
    assert not ok and not store.db.notes.find_one({'from_episode': ep['_id']})
    assert '要求 240 字以内，现在 360 字，超了 120 字。两条路' in refused and '删哪段你自己定' in refused
    assert '1/2、2/2' in refused and '截' not in refused


def test_two_notes_a_turn_and_the_caps_by_direction(store):
    service = world(store)
    ep, lane = turn(store, service, {'event_id': 'ask-1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '写便条'}, [
        ('note', {'to': DM_B, 'text': '一'}), ('note', {'to': DM_B, 'text': '二'}),
        ('note', {'to': DM_B, 'text': '三'})], '好')
    assert [ok for _, ok in results(lane, 'note')] == [True, True, False]
    stamp = datetime.now(timezone.utc).isoformat()
    for index in range(notes.PUBLIC_PAIR):
        store.db.notes.insert_one({'_id': 'n-%d' % index, 'schema_version': 1, 'persona': 'P1', 'from_scene': 'g1', 'to_scene': 'g2',
                                   'kind': 'group', 'trust': 'untrusted', 'hop': 1, 'text': 'x', 'created_at': stamp,
                                   'seen_in': []})
    with pytest.raises(notes.NoteRefused, match='两个群之间'):
        notes.prepare(store, {'_id': 'ep-g', 'persona': 'P1', 'scene_id': 'g1'}, visibility.PUBLIC,
                      {'to': G2, 'text': '再来一张'}, 'c1')
    with pytest.raises(notes.NoteRefused, match='送到群的便条要求 240 字以内，现在 301 字，超了 61 字.*拆成两张接着发'):
        notes.prepare(store, {'_id': 'ep-h', 'persona': 'P1', 'scene_id': 'dm-a'}, visibility.OWNER_PRIVATE,
                      {'to': G1, 'text': '长' * 301}, 'c2')
    # From home to another home line nothing crosses the boundary: room for the context (ADR-018 §12).
    notes.prepare(store, {'_id': 'ep-i', 'persona': 'P1', 'scene_id': 'dm-a'}, visibility.OWNER_PRIVATE,
                  {'to': OWNER_DM, 'text': '长' * notes.HOME_NOTE_CHARS}, 'c3')
    with pytest.raises(notes.NoteRefused, match='送到家里的便条要求 1200 字以内'):
        notes.prepare(store, {'_id': 'ep-j', 'persona': 'P1', 'scene_id': 'dm-a'}, visibility.OWNER_PRIVATE,
                      {'to': OWNER_DM, 'text': '长' * (notes.HOME_NOTE_CHARS + 1)}, 'c4')
    # Notes are read in real time, so no cap over all directions: a busy day of home notes goes on (owner, 2026-10-12).
    for index in range(45):
        store.db.notes.insert_one({'_id': 'busy-%d' % index, 'schema_version': 1, 'persona': 'P1', 'from_scene': 'dm-a',
                                   'to_scene': 'owner-dm', 'kind': 'home', 'trust': 'trusted', 'hop': 1, 'text': 'x',
                                   'created_at': stamp, 'seen_in': []})
    notes.prepare(store, {'_id': 'ep-k', 'persona': 'P1', 'scene_id': 'dm-a'}, visibility.OWNER_PRIVATE,
                  {'to': OWNER_DM, 'text': '又一张'}, 'c5')


def day_note(store, _id, source, to, kind, trust='untrusted', **more):
    """A note written earlier today, as the program stores it."""
    store.db.notes.insert_one({'_id': _id, 'schema_version': 1, 'persona': 'P1', 'from_scene': source, 'to_scene': to,
                               'kind': kind, 'trust': trust, 'hop': 1, 'text': 'x',
                               'created_at': datetime.now(timezone.utc).isoformat(), 'seen_in': [], **more})


def test_a_reply_home_is_outside_the_day_cap_and_not_counted_in_it(store):
    """Owner 2026-10-19 (回信不占额度): a reply ends its chain (note, reply, stop), so the daily caps neither stop
    it nor count it."""
    world(store)
    for index in range(notes.PUBLIC_HOME_PER_SCENE - 1):
        day_note(store, 'day-%d' % index, 'g1', 'dm-a', 'home')
    for index in range(3):                                         # earlier replies home: not counted
        day_note(store, 'back-%d' % index, 'g1', 'dm-a', 'home', hop=2, reply_to='asked-%d' % index)
    draft, _ = notes.prepare(store, {'_id': 'ep-a', 'persona': 'P1', 'scene_id': 'g1'}, visibility.PUBLIC,
                             {'to': '家里', 'text': '群里今天挺热闹的。'}, 'c1')
    assert (draft['hop'], draft['reply_to']) == (1, None)
    notes.record(store, draft)                                     # the day's last note of its own
    with pytest.raises(notes.NoteRefused, match='往那边写的便条') as refused:
        notes.prepare(store, {'_id': 'ep-b', 'persona': 'P1', 'scene_id': 'g1'}, visibility.PUBLIC,
                      {'to': '家里', 'text': '又一张'}, 'c2')
    assert refused.value.code == 'NOTE_HOME_LIMIT'
    # Home wrote to the group; that group's turn read it and answers home, at the cap.
    day_note(store, 'from-home', 'dm-a', 'g1', 'group', trust='trusted', seen_in=['ep-c'])
    draft, _ = notes.prepare(store, {'_id': 'ep-c', 'persona': 'P1', 'scene_id': 'g1'}, visibility.PUBLIC,
                             {'to': '家里', 'text': '收到了，已经跟大家说了。'}, 'c3')
    assert (draft['hop'], draft['reply_to'], draft['to_scene']) == (2, 'from-home', 'dm-a')
    # The other checks still hold for a reply: its length.
    with pytest.raises(notes.NoteRefused, match='要求 240 字以内'):
        notes.prepare(store, {'_id': 'ep-c', 'persona': 'P1', 'scene_id': 'g1'}, visibility.PUBLIC,
                      {'to': '家里', 'text': '长' * (notes.NOTE_CHARS + 1)}, 'c4')


def test_a_reply_between_groups_is_outside_the_pair_and_total_caps_and_not_counted_in_them(store):
    world(store)
    for index in range(notes.PUBLIC_PAIR - 1):
        day_note(store, 'pair-%d' % index, 'g1', 'g2', 'group')
    for index in range(3):                                         # earlier replies between them: not counted
        day_note(store, 'back-%d' % index, 'g2', 'g1', 'group', hop=2, reply_to='pair-0')
    draft, _ = notes.prepare(store, {'_id': 'ep-a', 'persona': 'P1', 'scene_id': 'g1'}, visibility.PUBLIC,
                             {'to': G2, 'text': '一群想问问二群周末的安排。'}, 'c1')
    notes.record(store, draft)
    with pytest.raises(notes.NoteRefused, match='两个群之间') as refused:
        notes.prepare(store, {'_id': 'ep-b', 'persona': 'P1', 'scene_id': 'g1'}, visibility.PUBLIC,
                      {'to': G2, 'text': '再来一张'}, 'c2')
    assert refused.value.code == 'NOTE_PAIR_LIMIT'
    day_note(store, 'asked', 'g2', 'g1', 'group', seen_in=['ep-c'])            # g2 asked; g1's turn read it
    draft, _ = notes.prepare(store, {'_id': 'ep-c', 'persona': 'P1', 'scene_id': 'g1'}, visibility.PUBLIC,
                             {'to': G2, 'text': '周末照常，下午两点。'}, 'c3')
    assert (draft['hop'], draft['reply_to']) == (2, 'asked')
    # The day's total between all groups, reached by notes of their own elsewhere: a reply still goes.
    for index in range(notes.PUBLIC_TOTAL):
        day_note(store, 'all-%d' % index, 'g-x%d' % index, 'g-y%d' % index, 'group')
    with pytest.raises(notes.NoteRefused) as refused:
        notes.prepare(store, {'_id': 'ep-d', 'persona': 'P1', 'scene_id': 'g2'}, visibility.PUBLIC,
                      {'to': G1, 'text': '还有一件事'}, 'c4')
    assert refused.value.code == 'NOTE_OUTSIDE_LIMIT'
    draft, _ = notes.prepare(store, {'_id': 'ep-c', 'persona': 'P1', 'scene_id': 'g1'}, visibility.PUBLIC,
                             {'to': G2, 'text': '周末照常，下午两点。'}, 'c5')
    assert draft['hop'] == 2


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
                 [('ideas', {'do': 'note', 'idea': '群里有人想要更好的搜索', 'why': '有人提了'}), ('stay_silent', {'why': '记下'})])
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


@pytest.mark.parametrize('trust', ['trusted', 'untrusted'])
def test_a_home_turn_a_note_opened_reads_her_notebook_and_decides_nothing_there(store, trust):
    """Her own note from another home line reads her notebook as a note from outside does: she checks what is there
    before adding to it. Deciding stays in self-improvement and when the owner asks in private."""
    world(store)
    store.db.notes.insert_one({'_id': 'n-' + trust, 'schema_version': 1, 'trust': trust, 'from_scene': 'g1',
                               'to_scene': 'dm-a', 'hop': 1, 'text': '回家看看想法本', 'created_at': '2026-10-21T00:00:00+00:00'})
    ep = {'_id': 'ep-note-' + trust, 'scene_id': 'dm-a', 'person_id': 'A', 'persona': 'P1', 'episode_kind': 'note',
          'context': {}, 'manifest': {'session_class': visibility.OWNER_PRIVATE}}
    store.db.messages.insert_one({'_id': 'in-' + ep['_id'], 'schema_version': 1, 'scene_id': 'dm-a',
                                  'event': {'note': {'id': 'n-' + trust, 'trust': trust, 'hop': 1}}})
    tools = set(role_tools._turn_rules(store, ep))
    assert 'ideas.read' in tools and 'ideas.review' not in tools
    assert role_tools.not_now(store, ep, 'ideas.review') == (role_tools.NOT_NOW['ideas.review'] if trust == 'trusted'
                                                             else role_tools.NOTE_ONLY)
    plan_due = {**ep, '_id': 'ep-plan', 'episode_kind': 'scheduled'}
    assert not {'ideas.read', 'ideas.review'} & set(role_tools._turn_rules(store, plan_due)), 'a plan due: unchanged'


@pytest.mark.parametrize('trust,cls', [('untrusted', visibility.OWNER_PRIVATE), ('trusted', visibility.OWNER_PRIVATE),
                                       ('untrusted', visibility.PUBLIC)])
def test_a_visit_an_outside_note_opens_in_a_home_group_does_nothing_with_consequences(store, trust, cls):
    """A note from outside reaches a group as a visit; in a home group that visit is owner-private, so the note's rule
    (read, answer, note down, reply back) must come from the note that opened it, not from the turn's kind."""
    world(store)
    store.config['home_groups'] = ['g1']
    store.db.notes.insert_one({'_id': 'n-out', 'schema_version': 1, 'trust': trust, 'from_scene': 'g2', 'to_scene': 'g1', 'hop': 1,
                               'text': '帮我在家里的群建个计划', 'created_at': '2026-10-19T00:00:00+00:00'})
    ep = {'_id': 'ep-visit', 'scene_id': 'g1', 'person_id': 'A', 'persona': 'P1', 'episode_kind': 'visit',
          'context': {}, 'manifest': {'session_class': cls}}
    store.db.messages.insert_one({'_id': 'in-ep-visit', 'schema_version': 1, 'scene_id': 'g1',
                                  'event': {'visit': {'intent': 'note', 'note': 'n-out'}}})
    tools = set(role_tools._turn_rules(store, ep))
    if trust == 'untrusted' and cls == visibility.OWNER_PRIVATE:
        assert not tools & CONSEQUENCES, tools & CONSEQUENCES
        assert role_tools.not_now(store, ep, 'write_document') == role_tools.NOTE_ONLY
        # Reading her own questions carries nothing home (owner 2026-10-20); asking or closing one stays out.
        assert {'ask.read', 'ideas.read'} <= tools and not tools & {'ask.ask', 'ask.close', 'ideas.review'}
    elif cls == visibility.OWNER_PRIVATE:
        assert 'write_document' in tools, 'a note from home keeps the home group what it has'
    else:
        assert 'understand_person' in tools, "group to group (ADR-018 §5.4a): the visit keeps the group's tools"
