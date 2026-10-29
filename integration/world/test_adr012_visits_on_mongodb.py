"""ADR-012 on MongoDB, kept by ADR-104 decision 9 (a break would leak private data): at home other people's group lines
do not arrive live; she sees what she herself did elsewhere and nothing anyone said; a heartbeat sends her to a
group with only her category and topic."""
from datetime import datetime, timedelta, timezone
import json

import pytest

from asuna import places
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn
from asuna.state import now

from turn_parts import scheduler

THINK = ('think', {'thought': 'PRIVATE_INTERNAL_THOUGHT_TEST_ONLY'})

pytestmark = pytest.mark.world                # `store` is the fixture world

PLACE = places.place_id('g1')


def group_world(store):
    """g1 is a QQ-like group she is routed to; g2 is blocked."""
    service = scheduler(store)
    store.config['persona_model']['heartbeat'].update(visits=True, visits_per_day=4)
    store.config['channels'] = {'qq': {'account_id': 'acct', 'blocked_groups': ['G2'], 'routes': {
        'r1': {'scene_id': 'g1', 'target': {'type': 'group', 'id': 'G1'}, 'members': {'s-a': {'person_id': 'A'},
                                                                                      's-b': {'person_id': 'B'}},
               'proactive': {'enabled': True}},
        'r2': {'scene_id': 'g2', 'target': {'type': 'group', 'id': 'G2'}, 'members': {'s-a': {'person_id': 'A'}},
               'proactive': {'enabled': True}}}}}
    store.raw.scenes.update_many({'_id': {'$in': ['g1', 'g2']}}, {'$set': {'channel_id': 'qq', 'channel_account_id': 'acct'}})
    service.ensure_presence()
    service.app.coordinator = None
    return service


def line(store, scene, key, text, minutes_ago, author='B', wake=None):
    sequence = store.raw.scenes.find_one_and_update({'_id': scene}, {'$inc': {'sequence': 1}}, return_document=True)['sequence']
    at = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
    store.raw.messages.insert_one({'_id': key, 'schema_version': 1, 'scene_id': scene, 'policy_epoch': 1, 'scene_seq': sequence,
        'direction': 'inbound', 'author': author, 'text': text, 'received_at': at, 'occurred_at': at,
        'event': {'group_context': {'wake_reason': wake}}})


def home_beat(store, key='presence:s-p5:9'):
    return {'event_id': key, 'scene_id': 'dm-a', 'person_id': 'A', 'adapter_id': 'presence', 'episode_kind': 'presence',
            'text': '心跳'}


def test_a_heartbeat_at_home_sends_her_to_a_group_and_only_her_category_and_topic_go_with_her(store):
    service = group_world(store)
    line(store, 'g1', 'm-old', '周末大家都在干嘛', minutes_ago=120)
    store.raw.messages.insert_one({'_id': 'home-secret', 'schema_version': 1, 'scene_id': 'dm-a', 'policy_epoch': 1,
        'scene_seq': 999, 'direction': 'inbound', 'author': 'A', 'text': 'HOME_SECRET_LINE', 'received_at': now()})
    home = FakeLane(store, [FakeTurn([THINK, ('visit', {'place': PLACE, 'intent': 'start_topic', 'topic': '周末去哪儿玩'}),
                                      ('visit', {'place': PLACE, 'intent': 'check_in'}),
                                      ('stay_silent', {'why': '出门了'})], '')])
    coordinator = Coordinator(store, home)
    coordinator.scheduler = service
    ep = coordinator.ingest(home_beat(store))
    assert ep['state'] == 'COMMITTED', ep.get('failure')
    assert 'visit' in home.calls[0]['tools'] and ep['context']['places_from_program']['items'][0]['place'] == PLACE
    results = [row for row in home.tool_results if row[2] == 'visit']
    assert results[0][5] and not results[1][5] and '已经出过 1 次门' in results[1][4]
    kind, event_id, scene_id, person = service.controller.offers[-1]
    envelope = service.controller.envelopes[-1]
    assert (kind, scene_id) == ('visit', 'g1') and event_id == 'visit:g1:presence:s-p5:9'
    # Her own moment there, not a platform input: no channel envelope, so no member is shown saying it.
    assert envelope['group_context']['wake_reason'] == 'visit' and envelope['scene_tick'] is True and 'channel' not in envelope
    assert envelope['visit'] == {'intent': 'start_topic', 'topic': '周末去哪儿玩', 'artifact_id': None, 'from': ep['_id']}
    plan = store.raw.plans.find_one({'_id': 'plan-asuna-presence'})
    assert plan['visits'][-1]['scene_id'] == 'g1' and places.today(store, plan, plan['visits'][-1]['date']) == 1
    # The visit itself: a public turn in g1 that sees the room and her topic, and nothing from home.
    visit_event = {'event_id': event_id, 'scene_id': 'g1', 'person_id': person, 'adapter_id': 'visit',
                   'episode_kind': 'visit', 'text': service.controller.texts[-1], **envelope}
    # ADR-082 D6: on a visit she may write about anyone whose lines it shows, naming whom (the visit's event person
    # only authorizes the visit); a write that names nobody is refused and the turn goes on.
    unnamed = ('understand_person', {'layer': 'here', 'content': '周末爱聊出去玩。', 'short': '爱聊周末'})
    group = FakeLane(store, [FakeTurn([THINK, unnamed], '周末大家打算去哪儿玩？')])
    visit = Coordinator(store, group).ingest(visit_event)
    assert visit['state'] in ('COMMITTED', 'WAITING_TASK'), visit.get('failure')
    assert visit['manifest']['session_class'] == 'public'
    context = visit['context']
    assert context['visit_from_program']['topic'] == '周末去哪儿玩' and '起个话头' in context['visit_from_program']['why']
    assert context['visit_from_program']['basis'].startswith('没人叫你')
    for home_only in ('rhythm_from_program', 'recent_experience_from_program', 'places_from_program',
                      'last_visits_from_program', 'relationship',
                      'understanding_update_from_program', 'sender_identity'):
        assert home_only not in context, home_only
    seen = json.dumps([context, group.calls], ensure_ascii=False)
    assert 'HOME_SECRET_LINE' not in seen and '周末大家都在干嘛' in seen
    assert not {'visit', 'set_policy', 'update_self'} & set(group.calls[0]['tools'])     # home's tools: not listed here
    assert 'understand_person' in visit['turn_tools']                                   # the room's lines are in front of her
    [written] = [row for row in group.tool_results if row[2] == 'understand_person']
    assert not written[5] and '串门时要写 person' in written[4]
    assert not store.raw.state_revisions.find_one({'mutation_id': {'$regex': '^' + visit['_id'] + ':understanding'}})
    said = store.raw.messages.find_one({'episode_id': visit['_id'], 'direction': 'outbound'})
    assert said['scene_id'] == 'g1' and said['target'] == {'type': 'group', 'id': 'G1'}
    # Brought home: what happened; a second visit there is hers to choose (no gap after her own).
    plan = store.raw.plans.find_one({'_id': 'plan-asuna-presence'})
    assert places.outcome(store, plan['visits'][-1]) == 'sending'
    store.raw.messages.update_one({'_id': said['_id']}, {'$set': {'delivery_state': 'DELIVERED', 'receipt_at': now()}})
    assert places.outcome(store, plan['visits'][-1]) == 'unanswered'
    line(store, 'g1', 'm-reply', '去爬山！', minutes_ago=0)
    assert places.outcome(store, plan['visits'][-1]) == 'answered'
    assert service.visit({'_id': 'ep-x', 'source_event_id': 'presence:s-p5:10'}, PLACE, 'check_in', None, None)['going_to']


def test_at_home_other_peoples_group_lines_do_not_arrive_live(store):
    """ADR-017 (owner 2026-10-06): public words reach home only through her own review, never in a heartbeat."""
    from asuna.config import character_id
    service = group_world(store)
    line(store, 'g1', 'm-theirs', 'GROUP_MEMBER_LINE', minutes_ago=5)
    store.raw.messages.insert_one({'_id': 'm-mine', 'schema_version': 1, 'scene_id': 'g1', 'policy_epoch': 1, 'scene_seq': 998,
        'direction': 'outbound', 'author': character_id(store.config), 'text': 'HER_OWN_GROUP_LINE',
        'delivery_state': 'DELIVERED', 'received_at': now()})
    store.raw.messages.insert_one({'_id': 'home-line', 'schema_version': 1, 'scene_id': 'dm-a', 'policy_epoch': 1,
        'scene_seq': 999, 'direction': 'inbound', 'author': 'A', 'text': 'OWNER_HOME_LINE', 'received_at': now()})
    home = FakeLane(store, [FakeTurn([THINK, ('stay_silent', {'why': '看看'})], '')])
    coordinator = Coordinator(store, home)
    coordinator.scheduler = service
    ep = coordinator.ingest(home_beat(store, 'presence:s-p5:21'))
    texts = [row['text'] for row in ep['context']['recent_experience_from_program']['messages']]
    assert 'OWNER_HOME_LINE' in texts and 'HER_OWN_GROUP_LINE' in texts and 'GROUP_MEMBER_LINE' not in texts


def test_at_home_she_sees_what_she_herself_did_elsewhere_and_nothing_anyone_said(store):
    """Owner 2026-10-06: shown pictures she made in a group, a home turn took them for someone else's."""
    from asuna.config import character_id
    group_world(store)
    me = character_id(store.config)
    for n, extra in enumerate(({}, {'attachment': {'artifact_id': 'blob-x'}})):
        store.raw.messages.insert_one({'_id': 'mine-%d' % n, 'schema_version': 1, 'scene_id': 'g1', 'policy_epoch': 1,
            'scene_seq': 700 + n, 'direction': 'outbound', 'author': me, 'delivery_state': 'DELIVERED',
            'text': 'MY_OWN_LINE', 'receipt_at': now(), **extra})
    line(store, 'g1', 'm-theirs', 'SOMEONE_ELSES_LINE', minutes_ago=0)
    store.raw.tasks.insert_one({'_id': 'task-draw', 'schema_version': 1, 'scene_id': 'g1', 'title': '画一张自画像',
                               'state': 'RETURNED', 'created_at': now()})
    ep = Coordinator(store, FakeLane(store, [FakeTurn([THINK], '嗯')])).ingest(
        {'event_id': 'home-look', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '你在群里画画了？'})
    block = ep['context']['elsewhere_from_program']
    [item] = block['items']
    assert '一句' in item['you'] and '1张你自己画的图' in item['you'] and item['handed_over'] == ['画一张自画像（跑完了）']
    assert '都是你' in block['note']
    # Her other home lines too: seen from another home conversation, what she did in this one is listed as home.
    store.raw.messages.insert_one({'_id': 'mine-home', 'schema_version': 1, 'scene_id': 'dm-a', 'policy_epoch': 1,
        'scene_seq': 800, 'direction': 'outbound', 'author': me, 'delivery_state': 'DELIVERED',
        'text': 'MY_HOME_LINE', 'receipt_at': now()})
    from asuna import places as _places, visibility
    assert 'dm-a' in visibility.owner_private_scenes(store.config)
    again = _places.elsewhere(store, 'P1', datetime.now(timezone.utc), {'another-home-line'},
                              visibility.owner_private_scenes(store.config))
    assert any(item['where'].endswith('（家里）') for item in again['items'])
    text = json.dumps(block, ensure_ascii=False)
    assert 'SOMEONE_ELSES_LINE' not in text and 'MY_OWN_LINE' not in text


