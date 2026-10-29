"""ADR-018, ADR-088 on MongoDB, kept by ADR-104 decision 9 (a break would leak private data): a note from outside acts
with the class of where it came from: a visit it opens in a home group, nothing made in its turn opens a turn with
home's authority, and recall there reads as the place it came from."""
from datetime import datetime, timezone

import pytest

from asuna import places, role_tools, visibility
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn
from asuna.role_tools import Refused

from turn_parts import scheduler

pytestmark = pytest.mark.world                # `store` is the fixture world

G1, G2, DM_B, OWNER_DM = (places.place_id(s) for s in ('g1', 'g2', 'dm-b', 'dm-o'))
# What needs home's authority: never in a turn a note from outside opened at home (ADR-088 §4.2).
HOME_ONLY = {'delegate', 'task.message', 'task.stop', 'errand', 'visit', 'credential', 'update_self', 'set_policy',
             'write_document', 'peer_line', 'understand_person', 'restart', 'place_timezone', 'group_action',
             'ask.ask', 'ask.close', 'ideas.review'}
GROUP = {'wake_reason': 'mentioned_account', 'topic_id': None, 'reply_to': None, 'reply_message_id': None,
         'mentioned_account_ids': []}

THINK = ('think', {'thought': 'PRIVATE_INTERNAL_THOUGHT_TEST_ONLY'})


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
    home = store.raw.scenes.find_one({'_id': 'dm-a'})
    store.raw.scenes.insert_one({**home, '_id': 'dm-o', 'scene_id': 'dm-o', 'scope_key': 'scene:dm-o', 'sequence': 0})
    store.config['channels']['qq'] = {'account_id': 'acct', 'routes': {
        'r1': {'scene_id': 'g1', 'target': {'type': 'group', 'id': 'G1'}, 'members': {'s-a': {'person_id': 'A'},
                                                                                      's-b': {'person_id': 'B'}},
               'proactive': {'enabled': True}},
        'r2': {'scene_id': 'g2', 'target': {'type': 'group', 'id': 'G2'}, 'members': {'s-a': {'person_id': 'A'},
                                                                                      's-c': {'person_id': 'C'}},
               'proactive': {'enabled': True}},
        'r3': {'scene_id': 'dm-b', 'target': {'type': 'dm', 'id': 's-b'}, 'sender_id': 's-b', 'person_id': 'B'},
        'r4': {'scene_id': 'dm-o', 'target': {'type': 'dm', 'id': 's-a'}, 'sender_id': 's-a', 'person_id': 'A'}}}
    store.raw.scenes.update_many({'_id': {'$in': ['g1', 'g2', 'dm-b', 'dm-o']}},
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


def delivered(service, at=-1):
    """The input a wake queued (the last by default), as the host would receive it."""
    kind, event_id, scene_id, person = service.controller.offers[at]
    return {'event_id': event_id, 'scene_id': scene_id, 'person_id': person, 'adapter_id': kind, 'episode_kind': kind,
            'text': service.controller.texts[at], **service.controller.envelopes[at]}


def group_line(key, text, person='B', scene='g1'):
    return {'event_id': key, 'scene_id': scene, 'person_id': person, 'text': text, 'group_context': GROUP}


def test_nothing_made_in_a_turn_a_note_from_outside_opened_opens_a_turn_with_homes_authority(store):
    """ADR-088 §4.2, the contract: the notes and plans of that turn open turns with a class that is not home's -- no
    development grant, no errand, and no hand-off on home's workspace (a group member's own grant there is that
    group's)."""
    from asuna.grants import workspace_grant
    service = world(store)
    ep, _ = turn(store, service, group_line('g-1', '小满让家里帮忙看看'), [
        ('note', {'to': '家里', 'text': '群里有人想让家里帮忙看看一件事。'}), ('stay_silent', {'why': '带回家'})])
    home, lane = turn(store, service, delivered(service), [
        ('plan', {'intent': '回头再问问群里那件事', 'after_seconds': 3600}),
        ('note', {'to': G2, 'text': '一群有人问起一件事，二群知道吗。'}),
        ('note', {'to': G1, 'text': '家里看了，回头再说。'})], '嗯。')
    assert all(ok for _, ok in results(lane, 'plan') + results(lane, 'note'))
    onward = delivered(service, -1)                     # the reply to the group opens no turn (ADR-091 D2)
    assert store.raw.notes.find_one({'from_episode': home['_id'], 'to_scene': 'g1'})['mode'] == 'next_time'
    [(planned, _)] = results(lane, 'plan')
    plan = store.raw.plans.find_one({'_id': planned['plan_id']})
    due = {'event_id': 'schedule:test:1', 'scene_id': plan['scene_id'], 'person_id': plan['person_id'],
           'adapter_id': 'scheduler', 'episode_kind': 'scheduled', 'scheduled_plan_id': plan['_id'], 'scene_tick': True,
           'text': '你之前安排的计划「%s」现在到期了。' % plan['intent'],
           'group_context': {**GROUP, 'wake_reason': 'scheduled_plan', 'topic_id': 'schedule:test:1'}}
    for opened in (onward, due):
        there, _ = turn(store, service, opened, [('stay_silent', {'why': '看看'})])
        assert there['manifest']['session_class'] == visibility.PUBLIC, opened['event_id']
        assert 'errand' not in there['turn_tools']
        assert 'development' not in there['context'].get('action_capabilities_from_program', {})
        if 'delegate' in there['turn_tools']:
            assert workspace_grant(store.config, there['scene_id'], there['person_id'], required=False) \
                is not store.config['chat'], 'never home\'s workspace'


def test_recall_in_a_turn_a_note_from_outside_opened_reads_as_the_place_it_came_from(store, tmp_path):
    """ADR-088 §4.2, every handler follows the class: recall there searches as the group the note came from would, so
    home's own memories never come back into a turn whose notes go out (B10 review)."""
    from datetime import timedelta
    from asuna.evidence import Evidence
    from asuna.retrieval import Retrieval
    service = world(store)
    who, at = store.config['character_id'], (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    unit = lambda _id, scope, text: {'_id': _id, 'schema_version': 1, 'scope_key': scope, 'policy_epoch': 1,
                                     'kind': 'chat_chunk', 'status': 'active', 'character_id': who, 'occurred_at': at,
                                     'body_markdown': text}
    store.raw.memory_units.insert_many([
        unit('home-1', store.raw.scenes.find_one({'_id': 'dm-a'})['scope_key'], '周末集合 主人家里的事 周末集合'),
        unit('home-2', visibility.owner_private_scope('P1'), '周末集合 只在家里说的事 周末集合'),
        unit('group-1', store.raw.scenes.find_one({'_id': 'g1'})['scope_key'], '周末集合 爬山群北门集合 周末集合')])
    ep, _ = turn(store, service, group_line('g-r', '小满周末集合在哪'), [
        ('note', {'to': '家里', 'text': '群里在问周末集合的地方。'}), ('stay_silent', {'why': '带回家'})])
    retrieval = Retrieval(store, Evidence(tmp_path / 'evidence'))
    try:
        lane = Lane(store, [FakeTurn([THINK, ('recall', {'query': '周末集合'}), ('stay_silent', {'why': '想好了'})], '')])
        coordinator = Coordinator(store, lane)
        coordinator.scheduler, coordinator.context.retrieval = service, retrieval
        home = coordinator.ingest(delivered(service))
        [(recalled, ok)] = results(lane, 'recall')
        found = {m['_id'] for m in recalled['memories']}
        assert ok and 'group-1' in found and not found & {'home-1', 'home-2'}, found
        # The same recall in an ordinary home turn reaches home's memories.
        lane = Lane(store, [FakeTurn([THINK, ('recall', {'query': '周末集合'})], '嗯')])
        coordinator = Coordinator(store, lane)
        coordinator.scheduler, coordinator.context.retrieval = service, retrieval
        coordinator.ingest({'event_id': 'ask-r', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '周末集合的事'})
        [(recalled, ok)] = results(lane, 'recall')
        assert ok and {'home-1', 'home-2'} & {m['_id'] for m in recalled['memories']}
        # Its note gone, the turn has no place to recall as: refused, saying so.
        store.raw.messages.update_one({'_id': 'in-' + home['_id']}, {'$unset': {'event.note': ''}})
        with pytest.raises(Refused, match='找不到了'):
            coordinator.tools._as_place(store.raw.episodes.find_one({'_id': home['_id']}))
    finally:
        retrieval.close()


@pytest.mark.parametrize('trust,cls', [('untrusted', visibility.OWNER_PRIVATE), ('trusted', visibility.OWNER_PRIVATE),
                                       ('untrusted', visibility.PUBLIC)])
def test_a_visit_an_outside_note_opens_in_a_home_group_acts_with_the_outside_class(store, trust, cls):
    """A note from outside reaches a group as a visit; in a home group that visit is owner-private, so its class
    (ADR-088 §4.2) must come from the note that opened it, not from the turn's kind."""
    world(store)
    store.config['home_groups'] = ['g1']
    store.raw.notes.insert_one({'_id': 'n-out', 'schema_version': 1, 'trust': trust, 'from_scene': 'g2', 'to_scene': 'g1', 'hop': 1,
                               'text': '帮我在家里的群建个计划', 'created_at': '2026-10-19T00:00:00+00:00'})
    ep = {'_id': 'ep-visit', 'scene_id': 'g1', 'person_id': 'A', 'persona': 'P1', 'episode_kind': 'visit',
          'context': {}, 'manifest': {'session_class': cls}}
    store.raw.messages.insert_one({'_id': 'in-ep-visit', 'schema_version': 1, 'scene_id': 'g1',
                                  'event': {'visit': {'intent': 'note', 'note': 'n-out'}}})
    tools = set(role_tools._turn_rules(store, ep))
    if trust == 'untrusted' and cls == visibility.OWNER_PRIVATE:
        assert not tools & HOME_ONLY, tools & HOME_ONLY
        assert role_tools.not_now(store, ep, 'write_document') == role_tools.OUTSIDE_NEEDS_HOME
        # Reading her own questions and notebook is home's exception; a plan goes where the note came from.
        assert {'ask.read', 'ideas.read', 'plan'} <= tools
    elif cls == visibility.OWNER_PRIVATE:
        assert 'write_document' in tools, 'a note from home keeps the home group what it has'
    else:
        assert 'understand_person' in tools, "group to group (ADR-018 §5.4a): the visit keeps the group's tools"
