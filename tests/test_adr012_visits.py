"""ADR-012 MongoDB tests: her places at home, a visit to a group, the owner's /heartbeat, the task page's view."""
from datetime import datetime, timedelta, timezone
import json

import pytest

from asuna import places
from asuna.coordinator import Coordinator
from asuna.ingress import persist_input
from asuna.lanes import FakeLane, FakeTurn
from asuna.policy import PolicyStore
from asuna.state import Denied, now
from test_adr009_p5_rhythm import fire, scheduler
from test_engineering_m1 import THINK

PLACE = places.place_id('g1')


def group_world(store, quiet_hours=()):
    """g1 is a QQ-like group she is routed to; g2 is blocked."""
    service = scheduler(store)
    store.config['persona_model']['heartbeat'].update(visits=True, quiet_min=30, after_own_min=360, visits_per_day=4)
    store.config['channels'] = {'qq': {'account_id': 'acct', 'blocked_groups': ['G2'], 'routes': {
        'r1': {'scene_id': 'g1', 'target': {'type': 'group', 'id': 'G1'}, 'members': {'s-a': {'person_id': 'A'},
                                                                                      's-b': {'person_id': 'B'}},
               'proactive': {'enabled': True, 'quiet_hours': [list(pair) for pair in quiet_hours]}},
        'r2': {'scene_id': 'g2', 'target': {'type': 'group', 'id': 'G2'}, 'members': {'s-a': {'person_id': 'A'}}}}}}
    store.db.scenes.update_many({'_id': {'$in': ['g1', 'g2']}}, {'$set': {'channel_id': 'qq', 'channel_account_id': 'acct'}})
    service.ensure_presence()
    service.app.coordinator = None
    return service


def line(store, scene, key, text, minutes_ago, author='B', wake=None):
    sequence = store.db.scenes.find_one_and_update({'_id': scene}, {'$inc': {'sequence': 1}}, return_document=True)['sequence']
    at = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
    store.db.messages.insert_one({'_id': key, 'schema_version': 1, 'scene_id': scene, 'policy_epoch': 1, 'scene_seq': sequence,
        'direction': 'inbound', 'author': author, 'text': text, 'received_at': at, 'occurred_at': at,
        'event': {'group_context': {'wake_reason': wake}}})


def view(store, service):
    model, plan = store.config['persona_model'], store.db.plans.find_one({'_id': 'plan-asuna-presence'})
    moment = datetime.now(timezone.utc)
    return places.places_block(store, 'P1', model, {}, plan, moment, places.local_date(store.config, model, {}, moment))


def home_beat(store, key='presence:s-p5:9'):
    return {'event_id': key, 'scene_id': 'dm-a', 'person_id': 'A', 'adapter_id': 'presence', 'episode_kind': 'presence',
            'text': '心跳'}


def test_her_places_read_in_words_and_each_says_whether_she_can_go(store):
    service = group_world(store)
    line(store, 'g1', 'm-old', 'GROUP_LINE_NEVER_SHOWN_AT_HOME', minutes_ago=120)
    block = view(store, service)
    [row] = block['items']                                        # the blocked group is not a place
    assert row['place'] == PLACE and row['can_visit'] == '可以去' and block['left_today'] == 4
    assert '零星有人说话' not in row['now'] and '小时前' in row['now'] and row['your_notes'] == '你还没写过这个群的笔记'
    assert 'GROUP_LINE_NEVER_SHOWN_AT_HOME' not in json.dumps(block, ensure_ascii=False)
    line(store, 'g1', 'm-now', '在吗', minutes_ago=1, wake='mentioned_account')
    [row] = view(store, service)['items']
    assert row['can_visit'].startswith('正有人在聊：可以去看看') and row['called_you'] and '零星有人说话' in row['now']
    beat = {'_id': 'ep-home', 'source_event_id': 'presence:s-p5:1'}
    with pytest.raises(ValueError, match='起话头或发图等安静下来'):
        service.visit(beat, PLACE, 'start_topic', None, None)        # talking: no new topic over them
    assert service.visit(beat, PLACE, 'write_notes', None, None)['going_to']   # but she may go and look
    service = group_world(store, quiet_hours=[('00:00', '23:59')])
    assert '夜里' in view(store, service)['items'][0]['can_visit']
    PolicyStore(store, 'P1', store.config['persona_model']).set([{'key': 'heartbeat.visits', 'value': False, 'what': 'x'}],
        base_revision_id=None, reason='不出门', author='character', mutation_id='visits-off')
    model = store.config['persona_model']
    assert places.places_block(store, 'P1', model, PolicyStore(store, 'P1', model).params(), {}, datetime.now(timezone.utc),
                               '2026-01-01') is None


def test_a_heartbeat_at_home_sends_her_to_a_group_and_only_her_category_and_topic_go_with_her(store):
    service = group_world(store)
    line(store, 'g1', 'm-old', '周末大家都在干嘛', minutes_ago=120)
    store.db.messages.insert_one({'_id': 'home-secret', 'schema_version': 1, 'scene_id': 'dm-a', 'policy_epoch': 1,
        'scene_seq': 999, 'direction': 'inbound', 'author': 'A', 'text': 'HOME_SECRET_LINE', 'received_at': now()})
    home = FakeLane(store, [FakeTurn([THINK, ('visit', {'place': PLACE, 'intent': 'start_topic', 'topic': '周末去哪儿玩'}),
                                      ('visit', {'place': PLACE, 'intent': 'check_in'}),
                                      ('stay_silent', {'reason': '出门了'})], '')])
    coordinator = Coordinator(store, home)
    coordinator.scheduler = service
    ep = coordinator.ingest(home_beat(store))
    assert ep['state'] == 'COMMITTED', ep.get('failure')
    assert 'visit' in home.calls[0]['tools'] and ep['context']['places_from_program']['items'][0]['place'] == PLACE
    results = [row for row in home.tool_results if row[2] == 'visit']
    assert results[0][5] and not results[1][5] and '已经出过一次门' in results[1][4]
    kind, event_id, scene_id, person = service.controller.offers[-1]
    envelope = service.controller.envelopes[-1]
    assert (kind, scene_id) == ('visit', 'g1') and event_id == 'visit:g1:presence:s-p5:9'
    # Her own moment there, not a platform input: no channel envelope, so no member is shown saying it.
    assert envelope['group_context']['wake_reason'] == 'visit' and envelope['scene_tick'] is True and 'channel' not in envelope
    assert envelope['visit'] == {'intent': 'start_topic', 'topic': '周末去哪儿玩', 'artifact_id': None, 'from': ep['_id']}
    plan = store.db.plans.find_one({'_id': 'plan-asuna-presence'})
    assert plan['visits'][-1]['scene_id'] == 'g1' and places.today(store, plan, plan['visits'][-1]['date']) == 1
    # The visit itself: a public turn in g1 that sees the room and her topic, and nothing from home.
    visit_event = {'event_id': event_id, 'scene_id': 'g1', 'person_id': person, 'adapter_id': 'visit',
                   'episode_kind': 'visit', 'text': service.controller.texts[-1], **envelope}
    group = FakeLane(store, [FakeTurn([THINK], '周末大家打算去哪儿玩？')])
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
    assert not {'visit', 'understand_person', 'set_policy', 'update_self'} & set(group.calls[0]['tools'])
    said = store.db.messages.find_one({'episode_id': visit['_id'], 'direction': 'outbound'})
    assert said['scene_id'] == 'g1' and said['target'] == {'type': 'group', 'id': 'G1'}
    # Brought home: what happened, then a second visit there waits (she was just there).
    plan = store.db.plans.find_one({'_id': 'plan-asuna-presence'})
    assert places.outcome(store, plan['visits'][-1]) == 'sending'
    store.db.messages.update_one({'_id': said['_id']}, {'$set': {'delivery_state': 'DELIVERED', 'receipt_at': now()}})
    assert places.outcome(store, plan['visits'][-1]) == 'unanswered'
    line(store, 'g1', 'm-reply', '去爬山！', minutes_ago=0)
    assert places.outcome(store, plan['visits'][-1]) == 'answered'
    with pytest.raises(ValueError, match='VISIT_NOT_NOW'):
        service.visit({'_id': 'ep-x', 'source_event_id': 'presence:s-p5:10'}, PLACE, 'check_in', None, None)


def test_a_plan_of_hers_due_at_home_may_send_her_out_but_one_due_in_a_group_may_not(store):
    service = group_world(store)
    line(store, 'g1', 'm-old', '周末大家都在干嘛', minutes_ago=120)
    due = []
    service.controller.receive = due.append
    for scene in ('dm-a', 'g1'):
        ep = {'_id': 'ep-plan-' + scene, 'scene_id': scene, 'person_id': 'A', 'scope_key': 'scene:' + scene,
              'policy_epoch': store.db.scenes.find_one({'_id': scene})['policy_epoch']}
        fire(service, service.create(ep, {'intent': '过二十分钟去群里答那三问', 'after_seconds': 60}))
    home_due, group_due = due
    home = FakeLane(store, [FakeTurn([THINK, ('visit', {'place': PLACE, 'intent': 'check_in'}),
                                      ('stay_silent', {'reason': '出门了'})], '')])
    coordinator = Coordinator(store, home)
    coordinator.scheduler = service
    ep = coordinator.ingest(home_due)
    assert ep['state'] == 'COMMITTED', ep.get('failure')
    assert 'visit' in home.calls[0]['tools'] and ep['context']['places_from_program']['items'][0]['place'] == PLACE
    [result] = [row for row in home.tool_results if row[2] == 'visit']
    assert result[5], result[4]
    kind, event_id, scene_id, _ = service.controller.offers[-1]
    assert (kind, scene_id, event_id) == ('visit', 'g1', 'visit:g1:' + home_due['event_id'])
    group = FakeLane(store, [FakeTurn([THINK, ('stay_silent', {'reason': '没什么要说'})], '')])
    ep = Coordinator(store, group).ingest(group_due)
    assert 'visit' not in group.calls[0]['tools'] and 'places_from_program' not in ep['context']


def test_a_visit_belongs_to_a_group_and_a_heartbeat_to_home(store):
    group_world(store)
    with pytest.raises(Denied, match='INTERNAL_SOURCE_DENIED'):
        persist_input(store, {'event_id': 'visit:dm-a:x', 'scene_id': 'dm-a', 'person_id': 'A', 'adapter_id': 'visit',
                              'episode_kind': 'visit', 'text': 'x'})
    with pytest.raises(Denied, match='INTERNAL_SOURCE_DENIED'):
        persist_input(store, {'event_id': 'presence:g1:x', 'scene_id': 'g1', 'person_id': 'A', 'adapter_id': 'presence',
                              'episode_kind': 'presence', 'text': 'x'})


def test_visit_refusals_name_what_to_do(store):
    service = group_world(store)
    beat = {'_id': 'ep-home', 'source_event_id': 'presence:s-p5:1'}
    with pytest.raises(ValueError, match='VISIT_PLACE_UNKNOWN'):
        service.visit(beat, 'gnowhere', 'check_in', None, None)
    with pytest.raises(ValueError, match='VISIT_PICTURE_NOT_HERS'):
        service.visit(beat, PLACE, 'share_picture', None, 'artifact-from-someone-else')
    date = places.local_date(store.config, store.config['persona_model'], {}, datetime.now(timezone.utc))
    old = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    made = [{'scene_id': 'g-other', 'event_id': 'visit:g-other:%d' % n, 'intent': 'check_in', 'at': old, 'date': date}
            for n in range(4)]
    store.db.plans.update_one({'_id': 'plan-asuna-presence'}, {'$set': {'visits': made}})
    with pytest.raises(ValueError, match='次数用完'):
        service.visit(beat, PLACE, 'check_in', None, None)
    # A visit whose input failed never got there: it comes home as such and spends nothing.
    for visit in made:
        store.db.messages.insert_one({'_id': 'in-' + places.episode_key(visit), 'schema_version': 1,
                                      'ingress_state': 'FAILED'})
    assert places.outcome(store, made[0]) == 'failed'
    assert service.visit(beat, PLACE, 'check_in', None, None)['going_to']


def test_the_owner_can_give_a_heartbeat_now_and_see_when_the_next_is_due(store):
    service = scheduler(store)
    plan = service.ensure_presence()
    assert fire(service, plan)['last_outcome'] == 'ENQUEUED'
    assert fire(service, plan)['last_outcome'] == 'SKIPPED:MIN_GAP'
    result = service.beat_now()                                  # no gate holds the owner's knock
    assert result['state'] == 'ENQUEUED' and result['next_at'] == plan['scheduled_at']
    assert '手动提前' in service.controller.texts[-1] and len(service.controller.offers) == 2
    assert store.db.audit_events.count_documents({'stream_id': plan['_id'], 'type': 'presence.forced'}) == 1
    store.config['persona_runtime'] = {}
    service.ensure_presence()
    assert service.beat_now() == {'state': 'OFF'}


def test_her_rhythm_is_named_in_the_task_page_and_her_pace_holds_against_edits_there(store):
    service = scheduler(store)
    plan = service.ensure_presence()
    create = next(payload for path, payload in service.lane.calls if path == '/schedule/create')
    assert create['title'] == '心跳 · Heartbeat' and create['every_seconds'] == 1800
    # The owner retimes it to every 10 minutes in DSH's task page; the record is logged as updated.
    record = dict([e['data']['schedule'] for e in service.lane.events if e['data'].get('operation') == 'create'][-1])
    service.lane.events.append({'seq': len(service.lane.events) + 1, 'data': {'operation': 'update',
                                'schedule': {**record, 'everySeconds': 600}}})
    service.watch_rhythm(deep=True)
    updates = [payload for path, payload in service.lane.calls if path == '/schedule/update']
    assert updates[-1]['change'] == {'kind': 'every', 'every_seconds': 1800}
    assert store.db.audit_events.find_one({'stream_id': plan['_id'], 'type': 'rhythm.retimed', 'payload.drift': True})
    # Deleted there: the next deep check makes a new one.
    service.lane.events.append({'seq': len(service.lane.events) + 1, 'data': {'operation': 'delete', 'id': plan['schedule_id']}})
    service.watch_rhythm(deep=True)
    assert store.db.plans.find_one({'_id': plan['_id']})['schedule_id'] != plan['schedule_id']
