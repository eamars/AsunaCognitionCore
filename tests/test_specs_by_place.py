"""ADR-087 §4.3: each conversation's tool specs leave out an option only when no turn it can host can use it, errand
turns and ADR-088's outside-note turns included. One spec per place and class: `deliver` where the class has a choice,
`question` in groups, `ideas` with the options the conversation lists, write_document whole."""
from asuna import role_tools, visibility


def by_name(specs):
    return {spec['name']: spec for spec in specs}


def shared():
    return by_name(role_tools.all_specs())


def test_the_words_left_out_are_the_shared_definitions_own():
    note, ideas = shared()['note'], shared()['ideas']
    assert role_tools.NOTE_DELIVER in note['description'] and role_tools.IDEAS_CHOOSE in ideas['description']
    assert all(words in ideas['description'] for words in role_tools.IDEAS_OP_WORDS.values())


def test_delegate_names_whose_work_in_the_form_the_conversation_can_use():
    """ADR-111: at home `for` names the outside place, in a group another person in the turn, in a home group either,
    elsewhere it is not shown."""
    spec = shared()['delegate']
    home = role_tools.placed_spec(spec, visibility.OWNER_PRIVATE, 'dm', [])
    home_group = role_tools.placed_spec(spec, visibility.OWNER_PRIVATE, 'group', [])
    assert home_group['description'] == spec['description']
    assert home_group['parameters']['for']['description'] == role_tools.FOR_IN_HOME_GROUP
    group = role_tools.placed_spec(spec, visibility.PUBLIC, 'group', [])
    dm = role_tools.placed_spec(spec, visibility.PUBLIC, 'dm', [])
    assert home == spec and role_tools.DELEGATE_OUTSIDE in spec['description']
    assert group['parameters']['for']['description'] == role_tools.FOR_IN_GROUP
    assert 'for' not in dm['parameters']
    assert role_tools.DELEGATE_OUTSIDE not in group['description'] + dm['description']
