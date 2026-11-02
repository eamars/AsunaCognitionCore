"""ADR-087 §4.3: each conversation's tool specs leave out an option only when no turn it can host can use it, errand
turns and ADR-088's outside-note turns included. One spec per place and class: `deliver` where the class has a choice,
`question` in groups, `ideas` with the options the conversation lists, write_document whole."""
from asuna import role_tools


def by_name(specs):
    return {spec['name']: spec for spec in specs}


def shared():
    return by_name(role_tools.all_specs())


def test_the_words_left_out_are_the_shared_definitions_own():
    note, ideas = shared()['note'], shared()['ideas']
    assert role_tools.NOTE_DELIVER in note['description'] and role_tools.IDEAS_CHOOSE in ideas['description']
    assert all(words in ideas['description'] for words in role_tools.IDEAS_OP_WORDS.values())


def test_delegate_for_by_class_and_kind():
    """ADR-111 §2.5: at home `for` names an outside place, in a public group a person in the turn; elsewhere none."""
    from asuna import visibility
    delegate = shared()['delegate']
    home = role_tools.placed_spec(delegate, visibility.OWNER_PRIVATE, 'dm', ())
    group = role_tools.placed_spec(delegate, visibility.PUBLIC, 'group', ())
    theirs = role_tools.placed_spec(delegate, visibility.PUBLIC, 'dm', ())
    assert home['parameters']['for']['description'] == role_tools.FOR_HOME
    assert home['description'].endswith(role_tools.DELEGATE_FOR_HOME)
    assert group['parameters']['for']['description'] == role_tools.FOR_GROUP and group['description'] == delegate['description']
    assert theirs == delegate and 'for' not in delegate['parameters']


def test_a_home_group_names_only_an_outside_place():
    """ADR-111, the owner (11-03): a home group is private but not where outside work is handled; `for` there names an
    outside place (that work runs on the Web chat), never a person in the turn."""
    from asuna import visibility
    delegate = shared()['delegate']
    home_group = role_tools.placed_spec(delegate, visibility.OWNER_PRIVATE, 'group', ())
    assert home_group['parameters']['for']['description'] == role_tools.FOR_HOME
