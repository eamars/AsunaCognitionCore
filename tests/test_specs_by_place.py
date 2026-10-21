"""ADR-087 §4.3: each conversation's tool specs leave out an option only when no turn it can host can use it, errand
turns and ADR-088's outside-note turns included. One spec per place and class: `deliver` where the class has a choice,
`question` in groups, `ideas` with the options the conversation lists, write_document whole."""
from asuna import places, role_tools
from test_group_admin import SCENE
from test_reply_actions import world

DM = 'qq:90000:dm:20002'


def by_name(specs):
    return {spec['name']: spec for spec in specs}


def shared():
    return by_name(role_tools.all_specs())


def private_chat(store):
    store.config['channels']['qq']['routes']['d'] = {'scene_id': DM, 'sender_id': '20002', 'person_id': 'qq:20002',
                                                     'target': {'type': 'dm', 'id': '20002'}}
    store.put('scenes', {'_id': DM, 'kind': 'dm', 'channel_id': 'qq', 'members': ['qq:20002'], 'scope_key': 'scene:' + DM,
                         'policy_epoch': 1, 'sequence': 0})


def local_chat(store):
    chat = store.config['chat']
    if not store.db.scenes.find_one({'_id': chat['scene_id']}):
        store.put('scenes', {'_id': chat['scene_id'], 'kind': 'dm', 'members': [chat['person_id']],
                             'scope_key': 'scene:' + chat['scene_id'], 'policy_epoch': 1, 'sequence': 0})
    return chat['scene_id']


def test_a_public_groups_note_has_no_deliver_and_its_ideas_only_note(store):
    world(store)
    specs = by_name(role_tools.session_specs(store, SCENE))
    note, ideas = specs['note'], specs['ideas']
    assert 'deliver' not in note['parameters'] and role_tools.NOTE_DELIVER not in note['description']
    assert 'question' in note['parameters'], 'a group answers its questions home'
    assert set(ideas['parameters']) == {'idea', 'why'}, 'only note: no do, nothing read or review takes'
    assert ideas['description'].startswith('你的「改进想法」本：记下一个改进自己的想法')
    assert 'read' not in ideas['description'] and 'review' not in ideas['description']


def test_a_conversation_that_hosts_errands_keeps_what_an_errand_there_can_use(store):
    """An errand in a group writes home documents (write_document follows home's class there, ADR-066), and every
    group with turns hosts errands: its write_document is the shared one, every op included."""
    world(store)
    assert SCENE in {scene_id for scene_id, _, _ in places.errand_targets(store.config)}
    write = by_name(role_tools.session_specs(store, SCENE))['write_document']
    assert write == shared()['write_document']
    assert {'correction', 'adopt_seed'} <= set(write['parameters']['do']['enum'])


def test_a_private_chat_with_someone_else_has_neither_deliver_nor_question(store):
    world(store)
    private_chat(store)
    note = by_name(role_tools.session_specs(store, DM, 'qq:20002'))['note']
    assert not {'deliver', 'question'} & set(note['parameters'])
    assert set(by_name(role_tools.session_specs(store, DM, 'qq:20002'))['ideas']['parameters']) == {'idea', 'why'}


def test_home_keeps_deliver_and_its_notebook_whole(store):
    world(store)
    home = by_name(role_tools.session_specs(store, local_chat(store)))
    assert 'deliver' in home['note']['parameters'] and role_tools.NOTE_DELIVER in home['note']['description']
    assert 'question' not in home['note']['parameters'], 'no turn at home answers a group question'
    assert home['ideas'] == shared()['ideas']


def test_a_home_group_keeps_deliver_and_question_and_writes_only_notes_in_its_notebook(store):
    """A home group's turns write notes with home's class (a choice of deliver); a note from outside visiting it
    (ADR-088) may answer a question asked there."""
    world(store)
    store.config['home_groups'] = [SCENE]
    specs = by_name(role_tools.session_specs(store, SCENE))
    assert {'deliver', 'question'} <= set(specs['note']['parameters'])
    assert set(specs['ideas']['parameters']) == {'idea', 'why'}


def test_one_spec_per_place_and_class(store):
    world(store)
    other = SCENE.replace('group:', 'group:9')
    store.config['channels']['qq']['routes']['g2'] = {'scene_id': other, 'target': {'type': 'group', 'id': '9'},
                                                      'members': {}}
    store.put('scenes', {**store.db.scenes.find_one({'_id': SCENE}), '_id': other, 'scope_key': 'scene:' + other})
    assert role_tools.session_specs(store, other) == role_tools.session_specs(store, SCENE)


def test_the_words_left_out_are_the_shared_definitions_own():
    note, ideas = shared()['note'], shared()['ideas']
    assert role_tools.NOTE_DELIVER in note['description'] and role_tools.IDEAS_CHOOSE in ideas['description']
    assert all(words in ideas['description'] for words in role_tools.IDEAS_OP_WORDS.values())
