"""ADR-066 on MongoDB, kept by ADR-104 decision 9 (a break would leak private data): the errand turn acts with home's
authority and its thoughts stay home; the destination hears once what she said, never the request."""
import json

import pytest

from asuna import errands, places, role_tools, visibility
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn
from asuna.state import now

from test_adr012_visits_on_mongodb import PLACE, group_world

pytestmark = pytest.mark.world                # `store` is the fixture world

THINK = ('think', {'thought': 'PRIVATE_INTERNAL_THOUGHT_TEST_ONLY'})


def sent_on_errand(store, service, request='今晚八点开会', said='主人让我转告：今晚八点开会', calls=()):
    """Home asks; the errand turn runs in the group. Returns (home episode, errand episode, the errand's lane)."""
    home = FakeLane(store, [FakeTurn([THINK, ('errand', {'place': PLACE, 'request': request})], '好，我去说')])
    asking = Coordinator(store, home)
    asking.scheduler = service
    home_ep = asking.ingest({'event_id': 'ask-1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '帮我去群里说一声'})
    assert home_ep['state'] == 'COMMITTED', home_ep.get('failure')
    _, event_id, scene_id, person = service.controller.offers[-1]
    envelope = service.controller.envelopes[-1]
    lane = FakeLane(store, [FakeTurn([THINK, *calls], said)])
    coordinator = Coordinator(store, lane)
    coordinator.scheduler = service
    event = {'event_id': event_id, 'scene_id': scene_id, 'person_id': person, 'adapter_id': 'visit',
             'episode_kind': 'visit', 'text': service.controller.texts[-1], **envelope}
    from asuna.ingress import persist_input
    persist_input(store, event, managed=True)
    errand_ep = coordinator.ingest(event)
    assert errand_ep['state'] in ('COMMITTED', 'WAITING_TASK'), errand_ep.get('failure')
    return home_ep, store.raw.episodes.find_one({'_id': errand_ep['_id']}), lane, coordinator


def group_turn(store, key):
    """The group's own next turn (here a visit of hers: it publishes without a platform envelope)."""
    event = {'event_id': 'visit:g1:' + key, 'scene_id': 'g1', 'person_id': 'A', 'adapter_id': 'visit',
             'episode_kind': 'visit', 'text': 'x', 'scene_tick': True,
             'group_context': {'wake_reason': places.WAKE_REASON, 'topic_id': key, 'reply_to': None,
                               'reply_message_id': None, 'mentioned_account_ids': []},
             'visit': {'intent': 'start_topic', 'topic': None, 'artifact_id': None, 'from': None}}
    return Coordinator(store, FakeLane(store, [FakeTurn([THINK], '嗯')])).ingest(event)


def deliver(store, episode_id):
    for row in store.raw.messages.find({'episode_id': episode_id, 'direction': 'outbound'}):
        store.raw.messages.update_one({'_id': row['_id']}, {'$set': {'delivery_state': 'DELIVERED', 'receipt_at': now()}})


def test_the_errand_turn_acts_with_homes_authority_and_its_thoughts_stay_home(store):
    service = group_world(store)
    home_ep, ep, lane, coordinator = sent_on_errand(store, service)
    assert ep['errand']['from'] == home_ep['_id'] and ep['errand']['scope_key'] == home_ep['scope_key']
    # Home's authority on the tools this conversation lists; the place itself is still the group.
    assert coordinator.tools._cls(ep) == visibility.OWNER_PRIVATE and coordinator.tools._place(ep) == visibility.PUBLIC
    assert ep['manifest']['session_class'] == visibility.PUBLIC
    # The same tool list as the group's own turns (the cached prefix), and the turn opens saying what it carries.
    assert set(lane.calls[0]['tools']) == set(role_tools.toolbox(store, {**ep, 'turn_kind': 'external'}))
    assert ep['context']['visit_from_program']['carries'] == errands.OPENING
    # Her thought on the errand is kept in home's scope, where home recalls it.
    [ref] = ep['monologue_refs']
    thought = store.raw.memory_units.find_one({'_id': ref})
    assert (thought['scope_key'], thought['policy_epoch']) == (home_ep['scope_key'], home_ep['policy_epoch'])
    # Every result in the turn says which layer of her acted.
    results = [row[4] for row in lane.tool_results if row[5]]
    assert results and all(row.get('turn') == errands.MARK for row in results), lane.tool_results


def test_the_destination_hears_once_what_she_said_never_the_request(store):
    service = group_world(store)
    _, ep, _, _ = sent_on_errand(store, service, request='HOME_ONLY_WORDS 今晚开会', said='今晚八点开会，大家记得')
    deliver(store, ep['_id'])
    said = store.raw.messages.find_one({'episode_id': ep['_id'], 'direction': 'outbound'})
    assert said['errand'] is True                          # her own line, marked where she reads it back
    store.raw.messages.update_one({'_id': 'in-' + ep['_id']}, {'$set': {'ingress_state': 'COMPLETE'}})
    nxt = group_turn(store, 'next')
    block = nxt['context']['errand_from_program']
    assert block['items'][0]['you_said'] == ['今晚八点开会，大家记得'] and '主人' in block['items'][0]['from']
    assert 'HOME_ONLY_WORDS' not in json.dumps(nxt['context'], ensure_ascii=False)
    again = group_turn(store, 'again')
    assert 'errand_from_program' not in again['context']              # once
    # At home, her doings elsewhere say which lines were an errand.
    back = Coordinator(store, FakeLane(store, [FakeTurn([THINK], '嗯')])).ingest(
        {'event_id': 'ask-2', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '办了吗'})
    [there] = [item for item in back['context']['elsewhere_from_program']['items'] if '差事' in item['you']]
    assert there


