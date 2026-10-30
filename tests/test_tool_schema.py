"""ADR-108 D4b and D4d: the strict check the worker runs on a call as she wrote it, and the shapes the program repairs
before it. The strict schema is the tool's parameters as the model is shown them; the root is open."""
from asuna import role_tools, tool_schema
from asuna.role_tools import infer_doc_op

PARTS = role_tools.tools()['speak']['parameters']
WRITE = role_tools.tools()['write_document']['parameters']
FEEL = role_tools.tools()['feel']['parameters']
PLAN = role_tools.tools()['plan']['parameters']


def said(tool, parameters, args):
    return [(code, text) for code, text, _ in tool_schema.violations(tool, parameters, args)]


def test_a_missing_field_a_wrong_type_and_a_value_outside_the_list_are_each_one_problem():
    found = said('write_document', WRITE, {'do': 'rewrite', 'why': 5, 'section': ['x']})
    assert [code for code, _ in found] == ['ARGS_ENUM', 'ARGS_TYPE', 'ARGS_TYPE']
    assert found[0][1].startswith('do 只能是 replace_section、append_section、correction、set_tags、adopt_seed、let_go 之一（给的是「rewrite」）')
    assert said('think', role_tools.tools()['think']['parameters'], {}) == [('ARGS_MISSING', '缺 thought（心里话）')]
    assert said('think', role_tools.tools()['think']['parameters'], {'thought': None}) == [('ARGS_TYPE', 'thought 要是一段文字')], \
        'a required field written as null is a value of the wrong type, not an absent one'


def test_the_root_is_open_an_optional_null_is_not_written_and_yes_no_takes_true_and_false():
    assert said('write_document', WRITE, {'doc': 'd', 'do': 'set_tags', 'why': 'y', 'nobody_declared_this': 1}) == []
    assert said('write_document', WRITE, {'doc': 'd', 'do': 'set_tags', 'why': 'y', 'heading': None}) == []
    assert said('write_document', WRITE, {'doc': 'd', 'do': 'set_tags', 'why': 'y', 'pin': True}) == []
    assert said('write_document', WRITE, {'doc': 'd', 'do': 'set_tags', 'why': 'y', 'pin': 'yes'}) == []
    assert said('write_document', WRITE, {'doc': 'd', 'do': 'set_tags', 'why': 'y', 'pin': 'maybe'})[0][0] == 'ARGS_ENUM'


def test_a_part_is_named_by_its_place_and_its_undeclared_key_is_a_problem():
    found = said('speak', PARTS, {'parts': [{'kind': 'text', 'text': 'a'}, {'kind': 'text', 'text': 3, 'odd': 1}, {'text': 'b'}]})
    assert ('ARGS_TYPE', 'parts 第 2 条的 text 要是一段文字') in found
    assert ('ARGS_MISSING', '缺 parts 第 3 条的 kind（哪一种）') in found
    assert any(code == 'ARGS_UNDECLARED' and '第 2 条' in text and 'odd' in text for code, text in found), found
    assert said('speak', PARTS, {'parts': 'not a list'}) == [('ARGS_TYPE', 'parts 要是一个列表')]
    assert [top for _, _, top in tool_schema.violations('speak', PARTS, {'parts': [{'text': 'b'}]})] == ['parts']


def test_an_old_name_that_still_works_is_read_as_the_new_one_for_the_check():
    # `op` is the old name of `do`, `reason` of `why`, `body` of `content`: taken for a week, so not missing.
    assert said('write_document', WRITE, {'doc': 'd', 'op': 'set_tags', 'reason': 'y'}) == []
    assert said('write_document', WRITE, {'doc': 'd', 'reason': 'y'}) == [('ARGS_MISSING', '缺 do（操作）')]


def test_fields_the_program_fills_in_later_are_not_missing_at_layer_three():
    assert said('write_document', WRITE, {'do': 'append_section', 'why': 'y', 'heading': 'h'}) == []
    assert said('delegate', role_tools.tools()['delegate']['parameters'], {'brief': 'x'}) == []
    assert tool_schema.violations('delegate', role_tools.tools()['delegate']['parameters'], {}) == [
        ('ARGS_MISSING', '缺 brief（给行动脑的完整交代）', 'brief')]


def test_speak_parts_written_as_a_json_string_a_part_without_a_kind_and_its_own_keys_are_repaired():
    fixed, done = tool_schema.repair('speak', {'parts': '[{"text": "好"}, {"name": "笑"}, {"who": "A"}, {"face": "赞"}, '
                                               '{"why": "写错了", "line": "3"}]'})
    assert [part['kind'] for part in fixed['parts']] == ['text', 'sticker', 'poke', 'react', 'recall']
    assert done.count('part_kind') == 5 and done[0] == 'parts_json'
    fixed, done = tool_schema.repair('speak', {'parts': [{'kind': 'text', 'text': 'a', 'quote': '5', 'wait': 'no'}]})
    assert fixed['quote'] == '5' and fixed['wait'] == 'no' and fixed['parts'][0] == {'kind': 'text', 'text': 'a'}
    fixed, _ = tool_schema.repair('speak', {'quote': '9', 'parts': [{'kind': 'text', 'text': 'a', 'quote': '5'}]})
    assert fixed['quote'] == '9' and fixed['parts'][0]['quote'] == '5', 'the call\'s own is not overwritten; the rest is a problem'


def test_what_cannot_be_read_stays_as_written_and_a_copy_is_repaired_not_the_call():
    fixed, done = tool_schema.repair('speak', {'parts': '{not json'})
    assert fixed == {'parts': '{not json'} and done == []
    fixed, done = tool_schema.repair('speak', {'parts': [{'artifact_id': 'att-1'}, {'text': 'a', 'name': 'b'}, 7]})
    assert fixed['parts'] == [{'artifact_id': 'att-1'}, {'text': 'a', 'name': 'b'}, 7] and done == [], \
        'a picture or a file, and two telling fields, are not guessed'
    original = {'parts': [{'text': 'hi'}]}
    tool_schema.repair('speak', original)
    assert original == {'parts': [{'text': 'hi'}]}, 'the call as she wrote it is untouched'
    assert tool_schema.repair('speak', 'not a dict') == ('not a dict', [])


def test_a_title_is_the_briefs_first_sentence_cut_to_the_aim():
    brief = '帮我查一下明天本地的天气，看要不要带伞。邻近城市也顺带看一眼。'
    fixed, done = tool_schema.repair('delegate', {'brief': brief})
    assert fixed['title'] == '帮我查一下明天本地的天气，看要不要带伞' and done == ['title']
    assert tool_schema.repair('delegate', {'brief': brief, 'title': '  '})[0]['title'] == fixed['title']
    assert tool_schema.repair('delegate', {'brief': brief, 'title': '我的标题'}) == ({'brief': brief, 'title': '我的标题'}, [])
    assert len(tool_schema.title_of('字' * 200)) == tool_schema.TITLE_CHARS and tool_schema.title_of('') == ''
    assert tool_schema.repair('delegate', {}) == ({}, []), 'no brief: nothing to take it from'


def test_a_write_documents_do_is_what_its_fields_plainly_say():
    assert infer_doc_op({'heading': '标题'}) == 'append_section'
    assert infer_doc_op({'sid': 's', 'body': '正文'}) == 'replace_section'
    assert infer_doc_op({'sid': 's', 'tags': ['x']}) == 'set_tags' and infer_doc_op({'sid': 's', 'inject': 'never'}) == 'set_tags'
    assert infer_doc_op({'sid': 's'}) is None and infer_doc_op({}) is None
    assert infer_doc_op({'sid': 's', 'tags': ['x'], 'heading': 'h'}) is None, 'a heading with a section is not plainly one thing'
