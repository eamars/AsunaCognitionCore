"""What she did after each thought (ADR-043): read back from the turn's records, her words as written, actions in
plain first-person words, one per line; lookups are not actions; what follows her next thought belongs to it."""
from asuna import reasons


def episode(store, ep_id, speech=None):
    store.db.episodes.insert_one({'_id': ep_id, 'schema_version': 1, 'scene_id': 'local', 'source_event_id': ep_id,
                                  **({'speech': speech} if speech else {})})


def call(store, ep_id, call_id, tool, args, refused=False):
    store.audit(ep_id, 'role_tool', {'call_id': call_id, 'tool': tool, 'args': args,
                                     **({'refused': 'no'} if refused else {'result': 'ok'})}, 'scene:local')


def test_a_thought_leads_to_what_she_did_before_her_next_thought(store):
    episode(store, 'ep-1', speech='好，那我明天提醒你，别熬夜了')
    call(store, 'ep-1', 'c1', 'think', {'thought': '他明天要早起'})
    call(store, 'ep-1', 'c2', 'recall', {'query': '明天'})                                  # a lookup: not an action
    call(store, 'ep-1', 'c3', 'plan', {'intent': '明早七点叫他起床', 'at': '2026-10-12T07:00'})
    call(store, 'ep-1', 'c4', 'delegate', {'title': '查明天天气', 'brief': '…'}, refused=True)   # refused: nothing happened
    call(store, 'ep-1', 'c5', 'think', {'thought': '还是顺口提醒一句'})
    call(store, 'ep-1', 'c6', 'watch', {'op': 'on', 'person': '[他 #2]'})
    first = {'_id': 'mono-ep-1:c1', 'episode_id': 'ep-1'}
    second = {'_id': 'mono-ep-1:c5', 'episode_id': 'ep-1'}
    assert reasons.then(store, first) == ['所以我定了个计划：明早七点叫他起床']
    assert reasons.then(store, second) == ['所以我开始留意[他 #2]', '所以我说了「好，那我明天提醒你，别熬夜了」']


def test_silence_is_an_action_with_its_reason_as_she_wrote_it(store):
    episode(store, 'ep-2')
    call(store, 'ep-2', 'k1', 'think', {'thought': '他们在吵，我不掺和'})
    call(store, 'ep-2', 'k2', 'stay_silent', {'reason': '这事轮不到我开口'})
    assert reasons.then(store, {'_id': 'mono-ep-2:k1', 'episode_id': 'ep-2'}) == ['所以我没说话：这事轮不到我开口']
    assert reasons.then(store, {'_id': 'mono-ep-2:missing', 'episode_id': 'ep-2'}) == []
