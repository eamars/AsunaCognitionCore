"""ADR-011 §6: one path for changes, development tools only from the owner and her self-improvement,
ideas from anywhere noted and decided only in her self-improvement turns."""
import json

from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn
from asuna.role_tools import Refused
from asuna.tasks import TaskService, ToolBroker
from test_adr009_p2 import owner

THINK = ('think', {'thought': '有个地方可以做得更好。'})


def event(key, scene='dm-a', person='A', text='你可以把回复改得更短吗？', **extra):
    return {'event_id': key, 'scene_id': scene, 'person_id': person, 'text': text, **extra}


def test_an_idea_from_a_public_chat_is_noted_but_cannot_be_read_there(store):
    lane = FakeLane(store, [FakeTurn([THINK, ('ideas', {'do': 'note', 'idea': '群里说话可以更短', 'why': '有人嫌我的回复太长'})], '好，我记下了。'),
                            FakeTurn([THINK], '嗯。')])
    coordinator = Coordinator(store, lane)
    ep = coordinator.ingest(event('pub-1'))
    assert 'ideas' in lane.calls[0]['tools'] and lane.tool_results[1][5]
    row = store.db.ideas.find_one({})
    assert row['state'] == 'open' and row['source'] == {'by': 'character', 'scene_id': 'dm-a', 'episode_id': ep['_id'],
                                                         'turn': 'external'}
    assert row['scope_key'].startswith('owner-private:')
    later = coordinator.ingest(event('pub-2', text='在吗'))
    assert 'ideas_from_program' not in later['context'], 'a public chat writes the notebook but never reads it'
    assert {'ideas.read', 'ideas.review'}.isdisjoint(later['turn_tools'])


def test_her_self_improvement_turn_reads_the_notebook_and_records_each_decision(store):
    owner(store)
    coordinator = Coordinator(store, FakeLane(store, [
        FakeTurn([THINK, ('ideas', {'do': 'note', 'idea': '回想时先看最近的心里话', 'why': '这次差点忘了上次说的'})], '好。')]))
    coordinator.ingest(event('own-1', text='没事'))
    idea = store.db.ideas.find_one({})
    lane = FakeLane(store, [FakeTurn([THINK,
        ('ideas', {'do': 'review', 'id': idea['_id'], 'decision': 'adopt', 'why': '值得做，交给行动脑改技能'}),
        ('ideas', {'do': 'review', 'id': 'idea-nope', 'decision': 'drop', 'why': 'x'}),
        ('delegate', {'title': '改进回想技能', 'brief': '在技能里加一条：回想时先看最近的心里话。'}),
        ('stay_silent', {'why': '自我改进时间，不用对谁说话'})])])
    coordinator.character = lane
    ep = coordinator.ingest(event('self-development:1', text='这是一次内部自我开发机会。', episode_kind='self_development', adapter_id='self-development'))
    assert [item['_id'] for item in ep['context']['ideas_from_program']['items']] == [idea['_id']]
    assert 'ideas.review' in ep['turn_tools']
    adopted, refused = lane.tool_results[1], lane.tool_results[2]
    assert adopted[5] and adopted[4]['state'] == 'adopted'
    assert not refused[5] and 'ideas_from_program' in refused[4]
    decided = store.db.ideas.find_one({'_id': idea['_id']})
    assert decided['state'] == 'adopted' and decided['decisions'][0]['why'] == '值得做，交给行动脑改技能'
    task = store.db.tasks.find_one({'_id': ep['task_ids'][0]})
    assert task['development_grant'] is True and 'development_publish' in task['allowed_capabilities']
    assert ep['state'] == 'WAITING_TASK' and ep['silent_reason']


def test_development_tools_come_only_from_the_owner_and_her_self_improvement(store):
    # A public chat's request becomes no development task, even when it asks for code changes.
    lane = FakeLane(store, [FakeTurn([THINK, ('delegate', {'title': '改代码', 'brief': '照他说的改代码。'})], '我先记下。')])
    ep = Coordinator(store, lane).ingest(event('pub-dev', text='你去把你自己的代码改了'))
    public = store.db.tasks.find_one({'_id': ep['task_ids'][0]})
    assert public['development_grant'] is False and not any(name.startswith('development_') for name in public['allowed_capabilities'])
    # The owner asking in a private chat carries them.
    owner(store)
    lane = FakeLane(store, [FakeTurn([THINK, ('delegate', {'title': '改技能', 'brief': '把回想技能改短一点。'})], '交给行动脑了。')])
    ep = Coordinator(store, lane).ingest(event('own-dev', text='把你的回想技能改短一点'))
    granted = store.db.tasks.find_one({'_id': ep['task_ids'][0]})
    assert granted['development_grant'] is True and 'development_publish' in granted['allowed_capabilities']
    # Her internal moments other than self-improvement do not.
    lane = FakeLane(store, [FakeTurn([THINK, ('delegate', {'title': '看看', 'brief': '看看有什么能改的。'}),
                                      ('stay_silent', {'why': '内部'})])])
    ep = Coordinator(store, lane).ingest(event('presence:1', text='内部时间', episode_kind='presence', adapter_id='presence'))
    assert store.db.tasks.find_one({'_id': ep['task_ids'][0]})['development_grant'] is False


def test_the_action_brain_notes_ideas_into_the_same_notebook(store):
    lane = FakeLane(store, [FakeTurn([THINK, ('delegate', {'title': '查资料', 'brief': '查一下明天的天气。'})], '去查了。')])
    ep = Coordinator(store, lane).ingest(event('pub-task', text='明天天气？'))
    service = TaskService(store)
    task = service.claim(ep['task_ids'][0])
    broker = ToolBroker(service)
    from pathlib import Path
    broker.bind('s', task, Path(store.config['channels']['fixture']['routes']['dm-a']['workspace']))
    result = broker.call('s', 'call-1', 'note_idea', {'idea': '天气查询可以做成技能', 'why': '每次都从头搜'})
    row = store.db.ideas.find_one({'_id': result['noted']})
    assert row['source'] == {'by': 'action', 'task_id': task['_id'], 'scene_id': 'dm-a'} and row['state'] == 'open'
    assert broker.call('s', 'call-1', 'note_idea', {'idea': '天气查询可以做成技能', 'why': '每次都从头搜'}) == result
    assert store.db.ideas.count_documents({}) == 1


def test_update_self_is_an_owner_private_tool(store):
    lane = FakeLane(store, [FakeTurn([THINK], '好。')])
    Coordinator(store, lane).ingest(event('pub-self'))
    assert 'update_self' not in lane.calls[0]['tools']
    owner(store)
    lane = FakeLane(store, [FakeTurn([THINK, ('update_self', {'target': 'current_self', 'content': '最近更想把话说短。',
                                                               'why': '主人说回复太长'})], '我改了一点对自己的描述。')])
    ep = Coordinator(store, lane).ingest(event('own-self'))
    assert lane.tool_results[1][5] and lane.tool_results[1][4]['committed'] is True
    assert ep['state'] == 'COMMITTED'
    assert json.dumps(store.db.state_heads.find_one({'_id': {'$regex': '^current_self:'}}) is not None)


def test_the_owner_can_ask_her_to_review_her_ideas_in_private(store):
    Coordinator(store, FakeLane(store, [FakeTurn([THINK, ('ideas', {'do': 'note', 'idea': '群里少用感叹号', 'why': '显得太吵'})], '好。')]
                                )).ingest(event('pub-idea', scene='dm-b', person='B', text='你感叹号好多'))
    idea = store.db.ideas.find_one({})
    owner(store)
    lane = FakeLane(store, [FakeTurn([THINK, ('ideas', {'do': 'read'}),
                                      ('ideas', {'do': 'review', 'id': idea['_id'], 'decision': 'defer', 'why': '先观察一阵'})],
                                     '看过了，先放一放。')])
    Coordinator(store, lane).ingest(event('own-review', text='整理一下你的改进想法吧'))
    read, reviewed = lane.tool_results[1], lane.tool_results[2]
    assert read[5] and [item['_id'] for item in read[4]['items']] == [idea['_id']]
    assert reviewed[5] and store.db.ideas.find_one({})['state'] == 'deferred'
    lane = FakeLane(store, [FakeTurn([THINK, ('ideas', {'do': 'read'})], '嗯。')])
    Coordinator(store, lane).ingest(event('pub-read', scene='dm-b', person='B', text='你的想法本里有什么'))
    # Her notebook's note is everywhere, so the tool is listed; reading it there is refused, saying where it is read.
    assert not lane.tool_results[1][5] and '自我改进' in lane.tool_results[1][4], 'a public chat never reads the notebook'
    assert 'items' not in str(lane.tool_results[1][4])


def test_a_newer_publication_supersedes_one_still_waiting_and_only_core_restarts_the_worker(store):
    """Regression (live 2026-10-05): an adapter publication replaced four minutes later stayed APPLIED, and the
    worker asked for a restart after every turn to activate it, about once per group message, for hours."""
    import threading
    from queue import Queue
    from types import SimpleNamespace
    from asuna.host import RuntimeHost
    from asuna.native_worker import NativeDevelopmentBridge
    owner(store)
    results = iter([{'receipt_id': 'self-publish-a', 'project': 'channel', 'state': 'APPLIED', 'candidate': 'a'},
                    {'receipt_id': 'self-publish-b', 'project': 'channel', 'state': 'APPLIED', 'candidate': 'b'},
                    {'receipt_id': 'self-publish-c', 'project': 'core', 'state': 'APPLIED', 'candidate': 'c'}])
    worker = SimpleNamespace(host_call=lambda method, args: next(results))
    bridge = NativeDevelopmentBridge(worker, store.config, store)
    task = {'_id': 'task-dev', 'scene_id': 'dm-a', 'requester_id': 'A', 'development_grant': True,
            'scope_key': 'scene:dm-a', 'intent_revision': 1}
    recorded = []
    host = RuntimeHost({}, SimpleNamespace(record=lambda kind, payload: recorded.append(kind)))
    host.app = SimpleNamespace(store=store)
    host.controller = SimpleNamespace(active=None, active_task=None, pending=Queue(), task_queue=Queue(),
                                      state_lock=threading.Lock(), restart_pending=host.restart_pending)
    bridge.call(task, 'development_publish', {})
    bridge.call(task, 'development_publish', {})
    older = store.db.sink_receipts.find_one({'_id': 'self-publish-a'})
    assert older['state'] == 'SUPERSEDED' and older['superseded_by'] == 'self-publish-b'
    host._maybe_restart_after_publish()
    assert not host.restart_requested.is_set() and recorded == [], 'a channel publication applies in place'
    bridge.call(task, 'development_publish', {})
    assert store.db.sink_receipts.find_one({'_id': 'self-publish-b'})['state'] == 'APPLIED', 'another project is not superseded'
    host._maybe_restart_after_publish()
    assert host.restart_requested.is_set() and recorded == ['restart.pending', 'restart.requested']


def test_a_revert_published_again_is_its_own_receipt_and_supersedes_the_one_before(store):
    """Regression (live 2026-10-21): content published again (a revert) reused its earlier publication's receipt id,
    so the receipt insert failed with DUPLICATE_ID and a publication that went through read as an error. The floor
    names each receipt by its content and its own time (publication.test.js); here the worker keeps all three."""
    from types import SimpleNamespace
    from asuna.native_worker import NativeDevelopmentBridge
    owner(store)
    receipt = lambda content, hour: 'self-publish-%s-20261021T%02d0000000Z' % (content, hour)
    results = iter([{'receipt_id': receipt('a', 1), 'project': 'persona', 'state': 'APPLIED', 'candidate': 'a'},
                    {'receipt_id': receipt('b', 2), 'project': 'persona', 'state': 'APPLIED', 'candidate': 'b'},
                    {'receipt_id': receipt('a', 3), 'project': 'persona', 'state': 'APPLIED', 'candidate': 'a'}])
    bridge = NativeDevelopmentBridge(SimpleNamespace(host_call=lambda method, args: next(results)), store.config, store)
    task = {'_id': 'task-dev', 'scene_id': 'dm-a', 'requester_id': 'A', 'development_grant': True,
            'scope_key': 'scene:dm-a', 'intent_revision': 1}
    for _ in range(3):
        bridge.call(task, 'development_publish', {})
    rows = {row['_id']: row for row in store.db.sink_receipts.find({'kind': 'self_development_publish'})}
    assert set(rows) == {receipt('a', 1), receipt('b', 2), receipt('a', 3)}
    assert (rows[receipt('a', 1)]['state'], rows[receipt('a', 1)]['superseded_by']) == ('SUPERSEDED', receipt('b', 2))
    assert (rows[receipt('b', 2)]['state'], rows[receipt('b', 2)]['superseded_by']) == ('SUPERSEDED', receipt('a', 3))
    assert rows[receipt('a', 3)]['state'] == 'APPLIED'


def test_a_persona_publication_is_what_her_turns_read_at_once(store, tmp_path):
    """Regression (live 2026-10-21): her persona publication read ACTIVE at 13:31, but the running worker kept the
    model it started with; a value only that publication declared was refused until the 15:19 restart."""
    import pytest
    from pathlib import Path
    from types import SimpleNamespace
    from asuna.native_worker import BusinessWorker
    from asuna.persona_model import PersonaModelError
    persona_id = store.config['chat']['persona']
    model = json.loads((Path(__file__).parent / 'fixtures/personas/demo/persona-model.json').read_text(encoding='utf-8'))
    model['persona']['id'] = persona_id
    path = tmp_path / 'persona-model.json'

    def publish(edited):
        path.write_text(json.dumps(edited, ensure_ascii=False), encoding='utf-8')
        return BusinessWorker.dispatch(worker, 'persona.resources', {'skill_directories': ['skills'], 'persona': {
            'id': persona_id, 'display_name': '新名字', 'character_id': 'character-1', 'model': str(path), 'jobs': []}})

    worker = SimpleNamespace(app=SimpleNamespace(config=store.config, store=store))
    publish({**model, 'model_version': 1})
    assert store.config['persona_model'] == {**model, 'model_version': 1}
    assert store.config['chat']['display_name'] == '新名字' and store.config['_skill_directories'] == ['skills']
    edited = {**model, 'persona': {**model['persona'], 'display_name': '改过'}}
    publish(edited)
    assert store.config['persona_model'] == edited, 'the newest publication, not the one the worker started with'
    with pytest.raises(PersonaModelError):
        publish({**model, 'persona': {**model['persona'], 'id': 'someone-else'}})
    assert store.config['persona_model'] == edited, 'a model that fails validation changes nothing'


def test_a_database_read_mongo_refuses_comes_back_coded_without_the_server_reply(store):
    import pytest
    from types import SimpleNamespace
    from asuna.native_worker import NativeDevelopmentBridge
    owner(store)
    bridge = NativeDevelopmentBridge(SimpleNamespace(), store.config, store)
    task = {'_id': 'task-dev', 'scene_id': 'dm-a', 'requester_id': 'A', 'development_grant': True,
            'scope_key': 'scene:dm-a', 'intent_revision': 1}
    with pytest.raises(ValueError, match='DEVELOPMENT_QUERY_INVALID: Mongo 拒绝了这个查询') as refused:
        bridge.call(task, 'development_database_read', {'collection': 'scenes', 'projection': {'a': 1, 'b': 0}})
    assert 'clusterTime' not in str(refused.value)
    with pytest.raises(ValueError, match='DEVELOPMENT_PAGE_INVALID: .*skip=-1，limit=20'):
        bridge.call(task, 'development_database_read', {'collection': 'scenes', 'skip': -1})


def test_a_database_read_of_an_archived_row_still_reaches_her_character_brain(store):
    """Regression (live 2026-10-09): an archived message keeps its source's original ObjectId; a development read that
    returned it stored it raw, and handing the task's result back to her failed, so she never answered."""
    from bson import ObjectId
    from asuna.native_worker import NativeDevelopmentBridge
    owner(store)
    store.db.messages.insert_one({'_id': 'archive-x', 'schema_version': 1, 'scene_id': 'archive:dm-a',
                                  'direction': 'archived', 'text': '旧的一句', 'legacy': {'_id': ObjectId()}})
    lane = FakeLane(store, [FakeTurn([THINK, ('delegate', {'title': '查旧消息', 'brief': '只读查一条归档消息。'})], '交给行动脑了。')])
    ep = Coordinator(store, lane).ingest(event('own-archive', text='查一下那条旧消息'))
    service = TaskService(store)
    task = service.claim(ep['task_ids'][0])
    broker = ToolBroker(service)
    broker.development = NativeDevelopmentBridge(None, store.config, store)
    from pathlib import Path
    work = Path(store.config['channels']['fixture']['routes']['dm-a']['workspace'])
    store.config['chat']['workspace'] = str(work)
    broker.bind('s', task, work)
    try:
        read = broker.call('s', 'call-1', 'development_database_read', {'collection': 'messages', 'filter': {'_id': 'archive-x'}})
        assert isinstance(read['rows'][0]['legacy']['_id'], str)
        current = store.db.tasks.find_one({'_id': task['_id']})
        done = store.put('tasks', {**current, 'state': 'RETURNED', 'feedback_state': 'READY',
                                   'result': {'task_id': task['_id'], 'intent_revision': 1, 'text': '找到了。',
                                              'facts': [], 'artifact_refs': [read['artifact_ref']]}},
                         expected=current['revision'])
        lane = FakeLane(store, [FakeTurn([THINK], '找到了，原话在这。')])
        assert service.feedback(done, Coordinator(store, lane))['state'] == 'COMMITTED'
    finally:
        broker.close()


def test_her_own_plans_and_trusted_notes_in_home_conversations_carry_the_development_tools(store):
    """Owner 2026-10-12: her own initiative at home counts like her self-improvement turns: a plan of hers coming due,
    or a note from another of her trusted home conversations; a note from a public conversation does not."""
    from asuna.grants import development_granted
    from asuna import notes
    owner(store)
    scene = store.db.scenes.find_one({'_id': 'dm-a'})
    assert development_granted(store, scene, {'person_id': 'A', 'episode_kind': 'scheduled'}) is True
    store.db.notes.insert_one({'_id': 'note-home', 'schema_version': 1, 'trust': notes.TRUSTED})
    store.db.notes.insert_one({'_id': 'note-group', 'schema_version': 1, 'trust': notes.UNTRUSTED})
    assert development_granted(store, scene, {'person_id': 'A', 'episode_kind': 'note', 'note': {'id': 'note-home'}}) is True
    assert development_granted(store, scene, {'person_id': 'A', 'episode_kind': 'note', 'note': {'id': 'note-group'}}) is False
    assert development_granted(store, scene, {'person_id': 'A', 'episode_kind': 'presence'}) is False
