"""ADR-066 MongoDB tests: an errand carries home. The errand turn runs in its own copy of the destination's
conversation with home's authority; what she says goes out there; the destination hears once that home sent her and
what she said, never the request; a late errand is not sent and an interrupted one is not redone."""
from datetime import datetime, timedelta, timezone
import json

from asuna import errands, notes, places, role_tools, visibility
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn
from asuna.native_worker import BusinessWorker
from asuna.state import now
from test_adr012_visits import PLACE, group_world, line
from test_engineering_m1 import THINK


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
    return home_ep, store.db.episodes.find_one({'_id': errand_ep['_id']}), lane, coordinator


def group_turn(store, key):
    """The group's own next turn (here a visit of hers: it publishes without a platform envelope)."""
    event = {'event_id': 'visit:g1:' + key, 'scene_id': 'g1', 'person_id': 'A', 'adapter_id': 'visit',
             'episode_kind': 'visit', 'text': 'x', 'scene_tick': True,
             'group_context': {'wake_reason': places.WAKE_REASON, 'topic_id': key, 'reply_to': None,
                               'reply_message_id': None, 'mentioned_account_ids': []},
             'visit': {'intent': 'start_topic', 'topic': None, 'artifact_id': None, 'from': None}}
    return Coordinator(store, FakeLane(store, [FakeTurn([THINK], '嗯')])).ingest(event)


def deliver(store, episode_id):
    for row in store.db.messages.find({'episode_id': episode_id, 'direction': 'outbound'}):
        store.db.messages.update_one({'_id': row['_id']}, {'$set': {'delivery_state': 'DELIVERED', 'receipt_at': now()}})


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
    thought = store.db.memory_units.find_one({'_id': ref})
    assert (thought['scope_key'], thought['policy_epoch']) == (home_ep['scope_key'], home_ep['policy_epoch'])
    # Every result in the turn says which layer of her acted.
    results = [row[4] for row in lane.tool_results if row[5]]
    assert results and all(row.get('turn') == errands.MARK for row in results), lane.tool_results


def test_a_task_begun_on_an_errand_is_homes_and_its_report_comes_home(store):
    """Owner and her, 2026-10-20: home's authority lasts the turn, so the task is home's; its report comes home and
    names the place, so she can carry the result back with another errand. Steering that conversation's tasks stays out."""
    service = group_world(store)
    home_ep, ep, lane, _ = sent_on_errand(store, service, calls=[('delegate', {'title': '查开会的地方', 'brief': '查一下'})])
    assert 'delegate' in ep['turn_tools'] and not set(role_tools.STEERING) & set(ep['turn_tools'])
    assert role_tools.not_now(store, ep, 'task.message') == errands.NO_STEER
    [(result, ok)] = [(row[4], row[5]) for row in lane.tool_results if row[2] == 'delegate']
    assert ok and result['note'] == errands.HOME_TASK, result
    task = store.db.tasks.find_one({'_id': result['task']})
    assert (task['scene_id'], task['scope_key'], task['policy_epoch']) == (
        home_ep['scene_id'], home_ep['scope_key'], home_ep['policy_epoch'])
    assert task['requester_id'] == ep['errand']['person_id'] and task['errand_place'] == places.place_id(ep['scene_id'])
    # Its report opens a turn at home, saying where the errand was.
    from asuna.tasks import TaskService
    service_tasks = TaskService(store)
    claimed = service_tasks.claim(task['_id'])
    done = store.put('tasks', {**claimed, 'state': 'RETURNED', 'feedback_state': 'READY',
                               'result': {'task_id': task['_id'], 'intent_revision': 1, 'text': '在三楼会议室。',
                                          'facts': [], 'artifact_refs': []}}, expected=claimed['revision'])
    report = service_tasks.feedback(done, Coordinator(store, FakeLane(store, [FakeTurn([THINK], '查到了。')])))
    assert report['state'] == 'COMMITTED' and report['scene_id'] == home_ep['scene_id'], report.get('failure')
    said = store.db.messages.find_one({'_id': 'in-' + report['_id']})
    assert '托话的那边是 %s' % task['errand_place'] in said['text']


def test_the_destination_hears_once_what_she_said_never_the_request(store):
    service = group_world(store)
    _, ep, _, _ = sent_on_errand(store, service, request='HOME_ONLY_WORDS 今晚开会', said='今晚八点开会，大家记得')
    deliver(store, ep['_id'])
    said = store.db.messages.find_one({'episode_id': ep['_id'], 'direction': 'outbound'})
    assert said['errand'] is True                          # her own line, marked where she reads it back
    store.db.messages.update_one({'_id': 'in-' + ep['_id']}, {'$set': {'ingress_state': 'COMPLETE'}})
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


def test_a_late_errand_is_not_sent_and_an_interrupted_one_says_what_it_did(store):
    service = group_world(store)
    old = (datetime.now(timezone.utc) - timedelta(minutes=errands.PATIENCE_MINUTES + 1)).isoformat()
    assert errands.late({'received_at': old, 'event': {'episode_kind': 'visit', 'visit': {'intent': 'errand'}}})
    assert not errands.late({'received_at': now(), 'event': {'episode_kind': 'visit', 'visit': {'intent': 'errand'}}})
    assert not errands.late({'received_at': old, 'event': {'episode_kind': 'visit', 'visit': {'intent': 'share_picture'}}})
    errand = {'episode_kind': 'visit', 'visit': {'intent': 'errand'}}
    assert errands.skipped(errand, {'received_at': old, 'event': errand}, None) == 'ERRAND_LATE'
    assert errands.skipped(errand, {'received_at': now(), 'event': errand}, {'_id': 'ep', 'state': 'TURN'})         == 'ERRAND_INTERRUPTED'
    assert errands.skipped(errand, {'received_at': now(), 'event': errand}, {'_id': 'ep', 'state': 'COMMITTED'}) is None
    assert errands.skipped(errand, {'received_at': now(), 'event': errand}, None) is None
    assert errands.skipped({'episode_kind': 'external'}, {'received_at': old}, {'_id': 'ep'}) is None
    _, ep, _, _ = sent_on_errand(store, service)
    deliver(store, ep['_id'])
    store.db.messages.update_one({'_id': 'in-' + ep['_id']}, {'$set': {'result_state': 'ERRAND_INTERRUPTED'}})
    moment = datetime.now(timezone.utc)
    [item] = places.errands_block(store, 'P1', moment)['items']
    assert '中途断了' in item['state'] and '1 句' in item['state'] and '别重办' in item['state']
    store.db.messages.update_one({'_id': 'in-' + ep['_id']}, {'$set': {'result_state': 'ERRAND_LATE'}})
    [item] = places.errands_block(store, 'P1', moment)['items']
    assert item['state'] == errands.STATES['late']


def test_a_note_home_carries_the_owners_own_line_and_its_turn_may_send_an_errand(store):
    group_world(store)
    store.config['chat']['person_id'] = 'A'                       # the owner is A, here in the group too
    ep = {'_id': 'ep-g', 'episode_kind': 'external', 'person_id': 'A', 'scene_id': 'g1'}
    store.db.messages.insert_one({'_id': 'in-ep-g', 'schema_version': 1, 'text': '小满，把那张图私聊发我',
                                  'event': {'channel': {'id': 'qq'}}})
    assert notes.owner_line(store, ep) == '小满，把那张图私聊发我'
    assert notes.owner_line(store, {**ep, 'person_id': 'B'}) is None               # someone else's words
    assert notes.owner_line(store, {**ep, 'episode_kind': 'visit'}) is None        # nobody woke her there
    context = {'errand_places_from_program': [{'place': PLACE}], 'note_places_from_program': {'items': [{}]}}
    turn = {'_id': 'ep-home', 'turn_kind': 'note', 'scene_id': 'dm-a', 'context': context,
            'manifest': {'session_class': 'owner_private'}}
    store.db.notes.insert_one({'_id': 'note-x', 'schema_version': 1, 'trust': notes.UNTRUSTED,
                               'owner_line': '小满，把那张图私聊发我'})
    store.db.messages.insert_one({'_id': 'in-ep-home', 'schema_version': 1, 'event': {'note': {'id': 'note-x'}}})
    assert 'errand' in role_tools.exposed(store, turn)
    store.db.notes.update_one({'_id': 'note-x'}, {'$unset': {'owner_line': 1}})
    assert 'errand' not in role_tools.exposed(store, turn)
    assert role_tools.not_now(store, turn, 'errand') == role_tools.ERRAND_NOTE


def test_the_errand_runs_in_its_own_copy_and_later_turns_never_do(store):
    """The worker asks the Host for the copy; a plan begun on the errand comes back to the conversation itself, and a
    Host start never takes the copy for the conversation."""
    import threading, types
    service = group_world(store)
    hosted = []
    worker = BusinessWorker()
    worker.app = types.SimpleNamespace(store=store, config=store.config)
    worker.navigation_ready = threading.Event()
    worker.navigation_ready.set()
    worker.host_call = lambda method, args: hosted.append((method, args)) or {'forked': True}
    main = {'_id': 'asuna-role-main', 'native_host': True, 'main_conversation': True, 'lane': 'character',
            'scene_id': 'g1', 'persona': 'P1', 'policy_epoch': 1, 'character_context': None, 'cwd': 'work/qq',
            'person_id': 'A'}
    store.put('sessions', main, stream='native-binding:asuna-role-main')
    _, ep, _, _ = sent_on_errand(store, service)
    proto = {'_id': ep['_id'], 'scene_id': 'g1', 'person_id': ep['person_id'], 'persona': 'P1', 'policy_epoch': 1,
             'scope_key': ep['scope_key']}
    copy = worker.resolve_role_session(proto)
    assert copy == errands.session_id(ep['_id']) and copy.startswith(errands.SESSION_PREFIX)
    [(method, args)] = hosted
    assert method == 'errand_session' and args['source_session_id'] == 'asuna-role-main' and args['cwd'] == 'work/qq'
    row = store.db.sessions.find_one({'_id': copy})
    assert row['errand']['forked'] is True and not row['main_conversation']
    assert worker.side_session(copy) and not worker.side_session('asuna-role-main')
    # A plan made in the errand turn: when it fires it runs in the conversation, not in the copy.
    store.db.episodes.update_one({'_id': ep['_id']}, {'$set': {'native_session_id': copy}})
    store.db.plans.insert_one({'_id': 'plan-e', 'schema_version': 1, 'source_episode_id': ep['_id']})
    store.db.messages.insert_one({'_id': 'in-ep-plan', 'schema_version': 1, 'event': {'scheduled_plan_id': 'plan-e'}})
    assert worker.resolve_role_session({**proto, '_id': 'ep-plan'}) == 'asuna-role-main'
    # The copy is not offered again for a repeat, and a fresh copy is not made.
    assert worker.resolve_role_session(proto) == copy and len(hosted) == 1


def test_an_errand_that_cannot_copy_reads_the_recent_lines(store):
    import threading, types
    service = group_world(store)
    line(store, 'g1', 'm-1', '最近在聊周末去哪', minutes_ago=3)
    worker = BusinessWorker()
    worker.app = types.SimpleNamespace(store=store, config=store.config)
    worker.navigation_ready = threading.Event()
    worker.navigation_ready.set()
    worker.host_call = lambda method, args: {'forked': False, 'reason': 'near_compaction'}
    store.put('sessions', {'_id': 'asuna-role-main', 'native_host': True, 'main_conversation': True, 'lane': 'character',
                           'scene_id': 'g1', 'persona': 'P1', 'policy_epoch': 1, 'character_context': None,
                           'cwd': 'work/qq', 'person_id': 'A'}, stream='native-binding:asuna-role-main')
    original = Coordinator.ingest

    def ingest(self, event, **kw):
        self.native_session_resolver = lambda ep: BusinessWorker.resolve_role_session(worker, ep)
        return original(self, event, **kw)
    try:
        Coordinator.ingest = ingest
        _, ep, _, _ = sent_on_errand(store, service)
    finally:
        Coordinator.ingest = original
    assert store.db.sessions.find_one({'_id': ep['native_session_id']})['errand']['reason'] == 'near_compaction'
    # Nothing is shown in the empty session, so the notice's own history brings the conversation's recent lines.
    assert any('周末' in (row.get('text') or '') for row in ep['context']['delivered_history'])


def test_a_task_begun_on_another_line_comes_home_in_the_home_conversation(store):
    """A development task she began on an agent line returns as a home turn: it runs in the home conversation, not in
    the line's session (whose binding would refuse the home scene)."""
    import threading, types
    worker = BusinessWorker()
    worker.app = types.SimpleNamespace(store=store, config=store.config)
    worker.navigation_ready = threading.Event()
    worker.navigation_ready.set()
    for sid, scene in (('asuna-role-home', 'dm-a'), ('asuna-role-line', 'agent:home:dm:x')):
        store.put('sessions', {'_id': sid, 'native_host': True, 'main_conversation': True, 'lane': 'character',
                               'scene_id': scene, 'persona': 'P1', 'policy_epoch': 1, 'character_context': None,
                               'cwd': 'work', 'person_id': 'A', 'binding_key': sid}, stream='native-binding:' + sid)
    store.db.episodes.insert_one({'_id': 'ep-line', 'schema_version': 1, 'native_session_id': 'asuna-role-line'})
    store.db.tasks.insert_one({'_id': 'task-1', 'schema_version': 1, 'episode_id': 'ep-line'})
    turn = {'_id': 'ep-back', 'task_id': 'task-1', 'scene_id': 'dm-a', 'person_id': 'A', 'persona': 'P1',
            'policy_epoch': 1, 'scope_key': 'scene:dm-a', 'context': {}}
    home = 'asuna-role-home'
    assert worker.resolve_role_session(turn) == home
    # A task begun in this same conversation still continues its own session there: one that is not the
    # conversation's main session, so only continuation (not the fallback to the main one) can return it.
    store.put('sessions', {'_id': 'asuna-role-home-2', 'native_host': True, 'main_conversation': False,
                           'lane': 'character', 'scene_id': 'dm-a', 'persona': 'P1', 'policy_epoch': 1,
                           'character_context': None, 'cwd': 'work', 'person_id': 'A',
                           'binding_key': 'asuna-role-home-2'}, stream='native-binding:asuna-role-home-2')
    store.db.episodes.update_one({'_id': 'ep-line'}, {'$set': {'native_session_id': 'asuna-role-home-2'}})
    assert worker.resolve_role_session({**turn, '_id': 'ep-again'}) == 'asuna-role-home-2'
