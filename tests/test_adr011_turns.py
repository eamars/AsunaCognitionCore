"""ADR-011: one character turn per episode, her mind's tools, and her work with the action brain."""


def test_the_reads_that_may_come_before_a_thought_are_a_closed_list_of_calls_with_no_consequences():
    from asuna import reasons
    for tool, args in [('recall', {'query': 'x'}), ('read_image', {}), ('task', {'op': 'page'}), ('ideas', {'op': 'read'}),
                       ('ask', {'op': 'read'}), ('find_member', {}), ('restart', {'op': 'preview'}),
                       ('group_focus', {'op': 'list'}), ('place_timezone', {'op': 'list'}),
                       ('private_words', {'op': 'summary'}), ('read_report', {})]:
        assert reasons.before_thought(tool, args) and not reasons.consequential(tool, args), tool
    for tool, args in [('feel', {'kind': '开心'}), ('task', {'op': 'answer'}), ('task', {'op': 'message'}),
                       ('restart', {'op': 'request'}), ('group_focus', {'op': 'active'}), ('place_timezone', {'op': 'set'}),
                       ('private_words', {'op': 'add'}), ('plan', {'op': 'create'}), ('speak', {}), ('stay_silent', {}),
                       ('ideas', {'op': 'note'}), ('ask', {'op': 'ask'}), ('note', {}), ('sticker', {'op': 'shelf'})]:
        assert not reasons.before_thought(tool, args), tool


