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
    lane = FakeLane(store, [FakeTurn([THINK, ('note_idea', {'idea': '群里说话可以更短', 'why': '有人嫌我的回复太长'})], '好，我记下了。'),
                            FakeTurn([THINK], '嗯。')])
    coordinator = Coordinator(store, lane)
    ep = coordinator.ingest(event('pub-1'))
    assert 'note_idea' in lane.calls[0]['tools'] and lane.tool_results[1][5]
    row = store.db.ideas.find_one({})
    assert row['state'] == 'open' and row['source'] == {'by': 'character', 'scene_id': 'dm-a', 'episode_id': ep['_id'],
                                                         'turn': 'external'}
    assert row['scope_key'].startswith('owner-private:')
    later = coordinator.ingest(event('pub-2', text='在吗'))
    assert 'ideas_from_program' not in later['context'], 'a public chat writes the notebook but never reads it'
    assert 'review_idea' not in lane.calls[1]['tools']


def test_her_self_improvement_turn_reads_the_notebook_and_records_each_decision(store):
    owner(store)
    coordinator = Coordinator(store, FakeLane(store, [
        FakeTurn([THINK, ('note_idea', {'idea': '回想时先看最近的心里话', 'why': '这次差点忘了上次说的'})], '好。')]))
    coordinator.ingest(event('own-1', text='没事'))
    idea = store.db.ideas.find_one({})
    lane = FakeLane(store, [FakeTurn([THINK,
        ('review_idea', {'idea': idea['_id'], 'decision': 'adopt', 'why': '值得做，交给行动脑改技能'}),
        ('review_idea', {'idea': 'idea-nope', 'decision': 'drop', 'why': 'x'}),
        ('delegate', {'title': '改进回想技能', 'brief': '在技能里加一条：回想时先看最近的心里话。'}),
        ('stay_silent', {'reason': '自我改进时间，不用对谁说话'})])])
    coordinator.character = lane
    ep = coordinator.ingest(event('self-development:1', text='这是一次内部自我开发机会。', episode_kind='self_development', adapter_id='self-development'))
    assert [item['_id'] for item in ep['context']['ideas_from_program']['items']] == [idea['_id']]
    assert 'review_idea' in lane.calls[0]['tools']
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
                                      ('stay_silent', {'reason': '内部'})])])
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
    lane = FakeLane(store, [FakeTurn([THINK, ('update_self', {'target': 'current_self', 'body': '最近更想把话说短。',
                                                               'reason': '主人说回复太长'})], '我改了一点对自己的描述。')])
    ep = Coordinator(store, lane).ingest(event('own-self'))
    assert lane.tool_results[1][5] and lane.tool_results[1][4]['committed'] is True
    assert ep['state'] == 'COMMITTED'
    assert json.dumps(store.db.state_heads.find_one({'_id': {'$regex': '^current_self:'}}) is not None)


def test_the_owner_can_ask_her_to_review_her_ideas_in_private(store):
    Coordinator(store, FakeLane(store, [FakeTurn([THINK, ('note_idea', {'idea': '群里少用感叹号', 'why': '显得太吵'})], '好。')]
                                )).ingest(event('pub-idea', scene='dm-b', person='B', text='你感叹号好多'))
    idea = store.db.ideas.find_one({})
    owner(store)
    lane = FakeLane(store, [FakeTurn([THINK, ('read_ideas', {}),
                                      ('review_idea', {'idea': idea['_id'], 'decision': 'defer', 'why': '先观察一阵'})],
                                     '看过了，先放一放。')])
    Coordinator(store, lane).ingest(event('own-review', text='整理一下你的改进想法吧'))
    read, reviewed = lane.tool_results[1], lane.tool_results[2]
    assert read[5] and [item['_id'] for item in read[4]['items']] == [idea['_id']]
    assert reviewed[5] and store.db.ideas.find_one({})['state'] == 'deferred'
    lane = FakeLane(store, [FakeTurn([THINK, ('read_ideas', {})], '嗯。')])
    Coordinator(store, lane).ingest(event('pub-read', scene='dm-b', person='B', text='你的想法本里有什么'))
    assert lane.tool_results[1][4] == 'NOT_EXPOSED', 'a public chat never reads the notebook'
