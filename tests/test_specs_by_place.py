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
