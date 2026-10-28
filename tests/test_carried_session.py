"""ADR-028: a conversation that no longer fits the model's window continues in a new session carrying its last
summary. These tests use an in-memory Mongo; they create no database."""
from types import SimpleNamespace

import mongomock
import pytest

from asuna import config as asuna_config, host, channel_admission, native_worker, native_settings
from asuna.chat import Chat
from asuna.context_budget import CARRIED_CHARS, carried_block
from asuna.coordinator import Coordinator, SessionCarried
from asuna.native_worker import BusinessWorker, ContextOverflow, NativeLane
from asuna.records import episodes as episode_records
from asuna.state import Store


@pytest.fixture
def local(tmp_path, monkeypatch):
    for module in (asuna_config, host, channel_admission, native_worker, native_settings):
        monkeypatch.setattr(module, 'DATA', tmp_path / '.runtime')
    config = {'chat': {'scene_id': 'local', 'person_id': 'owner', 'persona': 'xiaoman',
                       'workspace': str(tmp_path / 'local')}, 'workflow_timeout_seconds': 5,
              'character': {'model': 'native-host'}, 'channels': {}}
    db = Store.__new__(Store)
    db.config, db.name, db.fail_audit = config, 'in-memory', False
    db.client = mongomock.MongoClient()
    db.db = db.client[db.name]
    db.put('scenes', {'_id': 'local', 'scope_key': 'scene:local', 'policy_epoch': 1,
                      'kind': 'dm', 'members': ['owner'], 'sequence': 0})
    app = SimpleNamespace(store=db, config=config, evidence=SimpleNamespace(record=lambda *_: None))
    worker = BusinessWorker()
    worker.app, worker.controller = app, Chat(app, config['chat'])
    worker.navigation = worker.prepare_navigation([])
    worker.navigation_ready.set()
    hosted = []

    def emit(request):
        # The Host's side of a carry: answered at once, as the plugin does after preparing the session.
        if request['kind'] == 'host_request':
            hosted.append(request)
            worker.dispatch('host_result', {'request_id': request['request_id'], 'value': {'session_id': 'x'}})
        elif worker.stages is not None:
            worker.stages.append(request)
            worker.answer(request)

    worker.emit, worker.stages, worker.hosted = emit, None, hosted
    role = worker.navigation['entries'][0]['session_id']
    return SimpleNamespace(worker=worker, store=db, config=config, role=role, hosted=hosted)


def test_a_carry_moves_the_scene_to_a_new_session_and_keeps_it_after_a_restart(local):
    worker, store, old = local.worker, local.store, local.role
    successor = worker.carry_session(old, {'summary': '## 对话脉络\n- 早先的事'})
    assert successor and successor != old
    scene = store.db.scenes.find_one({'_id': 'local'})
    assert scene['character_context'].startswith('carried-') and scene['sequence'] == 0
    retired = store.db.sessions.find_one({'_id': old})
    assert retired['successor_id'] == successor and retired['retired'] and not retired['main_conversation']
    assert 'character_context' in retired, 'a row without a context would match any context at navigation'
    fresh = store.db.sessions.find_one({'_id': successor})
    assert fresh['main_conversation'] and fresh['carry'] == {'from_session_id': old, 'summary': '## 对话脉络\n- 早先的事',
                                                             'delivered': None}
    assert fresh['native_title'] == retired['native_title'] and fresh['source_session_id'] is None
    [request] = local.hosted
    assert request['method'] == 'carry_session' and request['args']['session_id'] == old
    assert request['args']['plan']['entries'][0]['session_id'] == successor
    assert request['args']['plan']['archive_ids'] == [] and not request['args']['plan']['first']
    assert store.db.audit_events.find_one({'type': 'native.context.carried', 'payload.successor_id': successor})
    assert worker.continued_session(old) == successor
    # A restart's navigation keeps the new session as her local conversation; the old one stays retired.
    plan = worker.prepare_navigation([{'id': old, 'createdAt': 1}, {'id': successor, 'createdAt': 2}])
    assert [entry['session_id'] for entry in plan['entries']] == [successor]
    assert store.db.sessions.find_one({'_id': old})['successor_id'] == successor


def test_a_carried_session_is_not_carried_again_before_its_first_notice_got_through(local):
    worker, store = local.worker, local.store
    first = worker.carry_session(local.role, {'summary': 'S'})
    assert worker.carry_session(first, {'summary': 'S'}) is None, 'no loop'
    assert worker.carry_session(local.role, {'summary': 'S'}) == first, 'the old session already continues there'
    row = store.db.sessions.find_one({'_id': first})
    store.put('sessions', {**row, 'carry': {**row['carry'], 'delivered': 'op'}}, expected=row['revision'],
              stream='native-binding:' + first)
    second = worker.carry_session(first, {'summary': 'T'})
    assert second not in (None, first) and worker.continued_session(local.role) == second
    assert worker.earlier_sessions(second) == [second, first, local.role]


def test_an_overflowed_turn_runs_again_in_the_new_session_with_the_summary_once(local):
    worker, store = local.worker, local.store
    store.put('episodes', {'_id': 'ep-1', 'source_event_id': 'ep-1', 'episode_kind': 'external', 'scene_id': 'local', 'person_id': 'owner', 'scope_key': 'scene:local',
                           'policy_epoch': 1, 'persona': 'xiaoman', 'native_session_id': local.role}, stream='ep-1')
    worker.stages = []

    def answer(request):
        if request['session_id'] == local.role:
            worker.dispatch('result', {'token': request['token'], 'error': 'LlmError: context window exceeded',
                                       'carry': {'summary': '旧会话的总结'}})
        else:
            worker.dispatch('result', {'token': request['token'], 'result': {'content': '好', 'request_refs': []}})
    worker.answer = answer
    lane = NativeLane(worker, local.config, store, None)
    context = {'scene': {'kind': 'dm'}, 'event': {'text': '在吗'}}
    with pytest.raises(SessionCarried) as raised:
        lane.generate('b', 'ep-1:TURN', 'TURN', 'tail', 'system', context=context, tail='tail')
    successor = raised.value.successor
    assert isinstance(raised.value.__cause__, ContextOverflow)
    assert 'carried_from_program' not in worker.stages[0]['context']
    # The coordinator runs the turn again; its episode still names the old session, which now continues.
    result = lane.generate('b', 'ep-1:TURN:resume:1', 'TURN', 'tail', 'system', context=context, tail='tail')
    assert result.content == '好' and worker.stages[1]['session_id'] == successor
    carried = worker.stages[1]['context']['carried_from_program']
    assert carried['summary'] == '旧会话的总结' and list(worker.stages[1]['context'])[0] == 'carried_from_program'
    assert store.db.sessions.find_one({'_id': successor})['carry']['delivered'] == 'ep-1:TURN:resume:1'
    assert store.db.sessions.find_one({'_id': successor})['character_context'].startswith('carried-')
    lane.generate('b', 'ep-1:TURN:resume:2', 'TURN', 'tail', 'system', context=context, tail='tail')
    assert 'carried_from_program' not in worker.stages[2]['context'], 'sent once'


def test_an_overflow_elsewhere_is_an_ordinary_failure(local):
    worker, store = local.worker, local.store
    successor = worker.carry_session(local.role, {'summary': 'S'})
    store.put('episodes', {'_id': 'ep-2', 'source_event_id': 'ep-2', 'episode_kind': 'external', 'scene_id': 'local', 'person_id': 'owner', 'scope_key': 'scene:local',
                           'policy_epoch': 1, 'persona': 'xiaoman', 'native_session_id': successor}, stream='ep-2')
    worker.stages = []
    worker.answer = lambda request: worker.dispatch('result', {'token': request['token'], 'error': 'too long',
                                                               'carry': {'summary': ''}})
    lane = NativeLane(worker, local.config, store, None)
    with pytest.raises(ContextOverflow):     # its first notice never got through: no second carry
        lane.generate('b', 'ep-2:TURN', 'TURN', 'tail', 'system', context={'event': {}}, tail='tail')
    assert worker.continued_session(local.role) == successor and len(local.hosted) == 1


def test_the_carried_block_is_bounded_and_says_when_there_was_no_summary():
    assert carried_block('')['note'] and 'summary' not in carried_block('')
    long = carried_block('字' * (CARRIED_CHARS + 500))['summary']
    assert long.startswith('字' * CARRIED_CHARS) and '500' in long[CARRIED_CHARS:]


def test_the_coordinator_runs_a_carried_turn_once_more_and_says_why(monkeypatch):
    runs, updates, audits = [], [], []
    coordinator = Coordinator.__new__(Coordinator)
    episode = {'_id': 'ep', 'scope_key': 'scene:local', 'revision': 1}
    coordinator.store = SimpleNamespace(audit=lambda *args: audits.append(args))
    monkeypatch.setattr(episode_records, 'get', lambda store, episode_id, fields=None, **fence: episode)
    coordinator.character = SimpleNamespace()
    coordinator._update = lambda ep, **changes: updates.append(changes) or {**ep, **changes}

    def run(ep):
        runs.append(ep.get('resume_diagnostic'))
        if len(runs) == 1:
            raise SessionCarried('overflow', 'new-session')
        return {'state': 'COMMITTED'}
    coordinator._run_turn = run
    assert coordinator._turn(episode) == {'state': 'COMMITTED'}
    assert runs[0] is None and '新会话' in runs[1]
    assert audits[0][1] == 'turn.carried' and audits[0][2] == {'successor': 'new-session'}
    coordinator._run_turn = lambda ep: (_ for _ in ()).throw(SessionCarried('again', 'third'))
    with pytest.raises(SessionCarried):
        coordinator._turn(episode)


def test_a_conversation_opened_in_tool_mode_goes_on_in_a_new_session_in_thinking_mode(local):
    """ADR-099: DSH keeps a session's first tools and system text at the head of every request, so a session opened
    with think is carried, not reused, once her thoughts come from the model's thinking."""
    from asuna.context_budget import CARRIED_WHY
    worker, store = local.worker, local.store
    store.put('episodes', {'_id': 'ep-1', 'source_event_id': 'ep-1', 'episode_kind': 'external', 'scene_id': 'local', 'person_id': 'owner', 'scope_key': 'scene:local',
                           'policy_epoch': 1, 'persona': 'xiaoman', 'native_session_id': local.role}, stream='ep-1')
    worker.stages = []
    worker.answer = lambda request: worker.dispatch('result', {'token': request['token'],
                                                               'result': {'content': '好', 'request_refs': []}})
    lane = NativeLane(worker, local.config, store, None)
    context = {'scene': {'kind': 'dm'}, 'event': {'text': '在吗'}}
    lane.generate('b', 'ep-1:TURN', 'TURN', 'tail', 'system', context=context, tail='tail')
    assert store.db.sessions.find_one({'_id': local.role})['thoughts'] == 'tool', 'the default, recorded at bind'
    store.config['thoughts'] = 'thinking'
    with pytest.raises(SessionCarried) as raised:
        lane.generate('b', 'ep-1:TURN:resume:1', 'TURN', 'tail', 'system', context=context, tail='tail')
    successor = raised.value.successor
    assert raised.value.note == native_worker.MODE_CARRY_NOTE and len(worker.stages) == 1, 'nothing was sent'
    assert store.db.sessions.find_one({'_id': successor})['thoughts'] == 'thinking'
    assert store.db.audit_events.find_one({'type': 'native.context.carried', 'payload.why': 'thoughts'})
    lane.generate('b', 'ep-1:TURN:resume:2', 'TURN', 'tail', 'system', context=context, tail='tail')
    assert worker.stages[1]['session_id'] == successor
    assert worker.stages[1]['context']['carried_from_program'] == {'note': CARRIED_WHY['thoughts']}, 'says why, not "too long"'
    lane.generate('b', 'ep-1:TURN:resume:3', 'TURN', 'tail', 'system', context=context, tail='tail')
    assert worker.stages[2]['session_id'] == successor and 'carried_from_program' not in worker.stages[2]['context']


def test_a_session_from_before_the_setting_is_a_tool_mode_session_and_stays(local):
    worker, store = local.worker, local.store
    assert 'thoughts' not in (store.db.sessions.find_one({'_id': local.role}) or {})
    store.put('episodes', {'_id': 'ep-1', 'source_event_id': 'ep-1', 'episode_kind': 'external', 'scene_id': 'local', 'person_id': 'owner', 'scope_key': 'scene:local',
                           'policy_epoch': 1, 'persona': 'xiaoman', 'native_session_id': local.role}, stream='ep-1')
    worker.stages = []
    worker.answer = lambda request: worker.dispatch('result', {'token': request['token'],
                                                               'result': {'content': '好', 'request_refs': []}})
    lane = NativeLane(worker, local.config, store, None)
    lane.generate('b', 'ep-1:TURN', 'TURN', 'tail', 'system', context={'event': {'text': '在吗'}}, tail='tail')
    assert worker.stages[0]['session_id'] == local.role and not local.hosted, 'no carry in tool mode'
