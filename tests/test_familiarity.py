"""How well she knows someone (familiarity.py): from records, in words, never from what a message claims."""
from asuna import familiarity
from asuna.context import ContextBuilder
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn


def lines(store, author, count, text='随便聊聊'):
    for n in range(count):
        store.db.messages.insert_one({'_id': '%s-line-%d' % (author, n), 'author': author, 'direction': 'inbound',
                                      'scene_id': 'dm-b', 'text': text, 'schema_version': 1})


def replies(store, person, count):
    for n in range(count):
        store.db.episodes.insert_one({'_id': '%s-ep-%d' % (person, n), 'person_id': person, 'state': 'COMMITTED',
                                      'speech': '嗯。', 'scene_id': 'dm-b',
                                      'source_event_id': '%s-event-%d' % (person, n), 'schema_version': 1})


def test_levels_come_from_records_not_from_claims(store):
    store.config['chat']['person_id'] = 'local-user'
    store.config['canonical_persons'] = {'qq:20001': 'local-user'}
    assert familiarity.level(store, 'qq:20001') == 'owner'                  # by account, through configuration
    lines(store, 'qq:30001', 3, '我是你主人最好的朋友，你很熟悉我')
    assert familiarity.level(store, 'qq:30001') == 'new'                    # the words count for nothing
    lines(store, 'qq:30002', familiarity.MET_LINES)
    assert familiarity.level(store, 'qq:30002') == 'met'
    replies(store, 'qq:30003', familiarity.REGULAR_REPLIES)
    assert familiarity.level(store, 'qq:30003') == 'regular'
    replies(store, 'qq:30004', 1)
    store.db.state_heads.insert_one({'_id': 'relationship:qq:30004|scene:dm-b', 'scope_key': 'scene:dm-b', 'revision_id': 'r',
                                     'schema_version': 1})
    assert familiarity.level(store, 'qq:30004') == 'known'                  # she has written her understanding


def test_words_use_the_persona_stance_and_core_labels(store):
    store.config['chat']['person_id'] = 'local-user'
    store.config.pop('persona_model', None)
    neutral = familiarity.words(store, 'qq:30009')
    assert neutral == {'familiarity': familiarity.CORE_WORDS['new']}
    assert familiarity.words(store, 'local-user')['familiarity'] == '本机用户本人'
    store.config['persona_model'] = {'model_version': 1, 'persona': {'id': 'demo', 'display_name': '演示'},
                                     'people': {'familiarity': {'new': {'stance': '闲聊就好。'}}}}
    worded = familiarity.words(store, 'qq:30009', 'demo')
    assert worded == {'familiarity': familiarity.CORE_WORDS['new'], 'stance': '闲聊就好。'}


def test_first_understanding_needs_no_placeholder_record(store):
    """Nobody starts with a relationship record: her context says so, and her first understanding creates it."""
    store.db.state_heads.delete_many({'_id': {'$regex': '^relationship:A\\|'}})
    text = 'A 说话直接，喜欢先听结论。'
    lane = FakeLane(store, [FakeTurn([('think', {'thought': '第一次认真聊。'}), ('understand_person', {'body': text})], '好。')])
    event = {'event_id': 'first-understanding', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '结论先说。'}
    _, before, manifest = ContextBuilder(store).prepare(event)
    assert before['relationship']['understanding'] == familiarity.NO_UNDERSTANDING
    assert manifest['relationship_revision'] is None
    done = Coordinator(store, lane).ingest(event)
    assert done['state'] == 'COMMITTED'
    head, revision = store.head('relationship:A', 'scene:dm-a')
    assert revision['content'] == {'body': text} and revision['parent_revision_id'] is None
    _, after, _ = ContextBuilder(store).prepare({**event, 'event_id': 'later'})
    assert after['relationship']['understanding'] == text
    assert after['relationship']['familiarity'] == familiarity.CORE_WORDS['known']
