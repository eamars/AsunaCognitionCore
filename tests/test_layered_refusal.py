"""ADR-108 D4b and D4c: a call is checked in layers and one refusal names every problem the layers that ran can find,
numbered, her call's own first thought first, her words in none of them. A permission refusal stops alone. A handler
that collects ends its check part before its first effect, so a call with problems writes nothing."""
import inspect
import re
from types import SimpleNamespace

import pytest

from asuna import memory_tiers, role_tools, tool_schema
from asuna.documents import DocumentStore
from asuna.records import episodes as episode_records
from asuna.records import scenes as scene_records
from asuna.role_tools import Refused, RoleTools
from test_people import BOT, SCENE

HOME_TOOLS = ['think', 'recall', 'write_document', 'ideas.note', 'ideas.read', 'delegate', 'task.message', 'feel', 'plan']


@pytest.fixture
def world(store):
    store.config['chat'] = {**store.config.get('chat', {}), 'person_id': 'local-user', 'persona': 'demo', 'display_name': '演示'}
    store.config.pop('persona_model', None)
    scene_records.save(store, {'_id': SCENE, 'kind': 'group', 'scope_key': 'scene:' + SCENE, 'channel_account_id': BOT,
                               'policy_epoch': 1, 'sequence': 0, 'members': ['local-user']})
    coordinator = SimpleNamespace(store=store, scheduler=None, context=SimpleNamespace(),
                                  _update=lambda ep, **changes: store.put('episodes', {**ep, **changes}, expected=ep['revision'],
                                                                         stream=ep['_id']))
    return SimpleNamespace(store=store, tools=RoleTools(coordinator), serial=[0])


def turn(world, *, thought=True, tools=None, session='owner_private'):
    world.serial[0] += 1
    ep_id = 'ep-%d' % world.serial[0]
    return world.store.put('episodes', {
        '_id': ep_id, 'scene_id': SCENE, 'scope_key': 'scene:' + SCENE, 'policy_epoch': 1, 'persona': 'demo',
        'person_id': 'local-user', 'episode_kind': 'external', 'state': 'TURN', 'source_event_id': 'evt-' + ep_id,
        'monologue_refs': [], 'context': {}, 'manifest': {'session_class': session}, 'turn_tools': tools or HOME_TOOLS,
        'turn_thought': thought, 'tool_calls': {}}, stream=ep_id)


def call(world, ep, name, args):
    """('ok', result) or ('refused', her words, codes); the audit row of the call is read by `audit`."""
    call_id = '%s:%d' % (ep['_id'], len(episode_records.get(world.store, ep['_id'])['tool_calls']))
    try:
        return ('ok', world.tools.call(ep['_id'], call_id, name, args)[0])
    except Refused as exc:
        return ('refused', str(exc), exc.codes)


def numbered(text):
    return re.findall(r'^\d+\. (.+)$', text, re.M)


def test_every_problem_of_the_layers_that_ran_is_named_once_her_calls_own_first(world):
    ep = turn(world, thought=False)
    outcome, said, codes = call(world, ep, 'write_document', {
        'doc': 'notes', 'section': 'meeting', 'content': '明天开会', 'why': '因为这样。' * 500, 'from': '瞎写'})
    assert outcome == 'refused'
    assert said.startswith('这次调用有 4 处要改，改好一起再调用一次：\n1. ' + role_tools.THINK_FIRST), said
    lines = numbered(said)
    assert [bool(line) for line in lines] == [True] * 4
    assert '只能是' in lines[1] and '瞎写' in lines[1], 'the enum the strict schema keeps, with the short value she wrote'
    assert lines[2].startswith('why 太长了：2500 字，过了 2000 字的线 500 字（要求 1600 字以内）。')
    assert '不存在' in lines[3], 'the state check, found beside the rest'
    assert codes[0] == 'THINK_FIRST' and 'TEXT_TOO_LONG' in codes and 'ARGS_ENUM' in codes and 'DOC_NOT_FOUND' in codes
    assert not any(chunk in said for chunk in ('因为这样。因为这样。因为这样。',)), 'none of her words'
    assert DocumentStore(world.store, 'demo').read('notes') == (None, None), 'nothing was written'
    record = list(episode_records.get(world.store, ep['_id'])['tool_calls'].values())[-1]
    assert record['refused'] == said and record['code'] == 'THINK_FIRST'


def test_one_problem_stands_alone_without_numbers(world):
    ep = turn(world)
    outcome, said, codes = call(world, ep, 'think', {'thought': ''})
    assert outcome == 'refused' and said == 'thought 要写内容（120 字以内）。' and codes == ('TEXT_EMPTY',)
    outcome, said, codes = call(world, ep, 'think', {})
    assert said.startswith('缺 thought（') and codes == ('ARGS_MISSING',), 'named by the schema once, not again by the handler'


def test_a_field_the_schema_named_is_not_named_twice_and_a_wrong_type_is_a_problem_beside_the_rest(world):
    ep = turn(world, thought=False)
    outcome, said, codes = call(world, ep, 'think', {'thought': 12})
    assert said == 'thought 要是一段文字' and codes == ('ARGS_TYPE',), 'think itself needs no earlier thought; named once'
    outcome, said, codes = call(world, ep, 'ideas', {'do': 'note', 'idea': 5, 'why': ['x']})
    assert outcome == 'refused' and codes == ('THINK_FIRST', 'ARGS_TYPE', 'ARGS_TYPE'), (said, codes)
    assert numbered(said)[0] == role_tools.THINK_FIRST and 'idea 要是一段文字' in said and 'why 要是一段文字' in said


def test_a_permission_refusal_stops_alone(world):
    ep = turn(world, thought=False, tools=['think'])
    outcome, said, codes = call(world, ep, 'write_document', {'doc': 'x', 'why': 1})
    assert outcome == 'refused' and '这一回合用不了' in said and '处要改' not in said and not codes, said


def test_a_call_with_problems_does_none_of_its_effect(world):
    ep = turn(world, thought=False)
    outcome, said, _ = call(world, ep, 'ideas', {'do': 'note', 'idea': '想法', 'why': '因为'})
    assert outcome == 'refused' and said == role_tools.THINK_FIRST
    assert list(role_tools.idea_rows(world.store, 'demo')) == [], 'the idea was not written'
    done = turn(world)
    outcome, result, *_ = call(world, done, 'ideas', {'do': 'note', 'idea': '想法', 'why': '因为'})
    assert outcome == 'ok' and result['noted']


def test_the_write_documents_do_and_doc_are_inferred_and_say_so(world):
    docs = DocumentStore(world.store, 'demo')
    ep = turn(world)
    outcome, result = call(world, ep, 'write_document', {'heading': '会议', 'content': '明天开会', 'why': '记一下', 'kind': 'ledger',
                                                          'doc': 'notes'})
    assert outcome == 'ok' and result['do'] == '没写 do：按你写的字段当作 append_section 办了。', result
    sid = result['sid']
    ep = turn(world)
    outcome, result = call(world, ep, 'write_document', {'section': sid, 'content': '改到后天', 'why': '改期'})
    assert outcome == 'ok' and result['doc_note'] == '没写 doc：按 section 当作 notes 写了' and result['op'] == 'replace_section', result
    assert docs.read('notes')[1]['sections'][0]['body'] == '改到后天'
    ep = turn(world)
    outcome, said, codes = call(world, ep, 'write_document', {'section': 'no-such', 'content': 'x', 'why': 'y'})
    assert outcome == 'refused' and '没写 doc' in said and '也没有哪份文档有「no-such」这一节' in said and 'notes' in said
    assert codes == ('DOC_NAME_NEEDED',)


def test_filled_fields_are_not_required_by_the_declared_schema_and_no_field_declares_an_enum():
    strict = role_tools.tools()
    declared = {name: tool_schema.declared(name, spec['parameters']) for name, spec in strict.items()}

    def walk(node, path):
        if isinstance(node, dict):
            assert 'enum' not in node, 'enum left in the declared schema at %s' % path
            for key, value in node.items():
                walk(value, path + '.' + key)
    for name, params in declared.items():
        walk(params, name)
    for (tool, field), words in tool_schema.REQUIRED_FILLED.items():
        assert not declared[tool][field].get('required') and declared[tool][field]['description'].endswith(words)
        assert strict[tool]['parameters'][field].get('required'), 'strict still asks for it'
    assert declared['speak']['parts']['type'] == 'json' and declared['speak']['parts'].get('required')
    for tool, field in tool_schema.JSON_FIELDS:
        assert 'kind' in declared[tool][field]['description']
    # An enum's values are in its field's description, so the model still reads them.
    assert 'visibility' in declared['write_document'] and 'owner_private' in declared['write_document']['visibility']['description']
    assert declared['note']['to'].get('required') and declared['note']['text'].get('required'), 'what the program cannot infer stays required'


def test_every_collecting_handler_ends_its_check_part_before_its_first_effect():
    """The structural guard: a handler in SPLIT calls checkpoint(), or none of its problems could stop it."""
    for name in sorted(RoleTools.SPLIT):
        source = inspect.getsource(getattr(RoleTools, name))
        assert 'self.checkpoint()' in source or 'raise self.combined(' in source, name + ' never ends its check part'


def test_a_long_refusal_cuts_each_candidate_list_and_drops_no_problem(world):
    tools = world.tools
    tools.problems = [('A', '先说甲：' + '、'.join('文档%d' % n for n in range(400)) + '。', '先说甲：文档0、文档1、文档2…（还有 397 个）。'),
                      ('B', '再说乙。')]
    said = tools.combined().args[0]
    assert len(numbered(said)) == 2 and said.count('文档399') == 0 and '还有 397 个' in said and '2. 再说乙。' in said
    tools.problems = [('A', '短。', '短。'), ('B', '再说乙。')]
    assert tools.combined().args[0] == '这次调用有 2 处要改，改好一起再调用一次：\n1. 短。\n2. 再说乙。'
