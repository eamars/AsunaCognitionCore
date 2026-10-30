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


def test_a_permission_refusal_ends_with_what_does_the_job_here_only_from_this_turns_tools(world):
    here = turn(world, thought=True, tools=['think', 'task.message', 'plan'])
    said = role_tools.not_now(world.store, here, 'task.answer')
    assert said.endswith('这一回合能做这件事的是：task 的 message（给行动脑补话、改目标）。'), said
    assert role_tools.not_now(world.store, turn(world, tools=['think']), 'task.answer') == role_tools._why_not_now(
        world.store, turn(world, tools=['think']), 'task.answer'), 'nothing here does it: when it can be used, as before'
    assert role_tools.instead_words(here, 'visit') == '这一回合能做这件事的是：plan（把这件事留到将来再想）。'
    assert role_tools.instead_words(turn(world, tools=['visit']), 'errand') == '这一回合能做这件事的是：visit（自己出门去那个群看看）。'
    assert role_tools.instead_words(here, 'recall') == '', 'an ability with no entry says nothing more'


def test_every_instead_entry_names_an_ability_that_exists():
    abilities = {name for name in role_tools.TOOLS}
    abilities |= {'%s.%s' % (tool, op) for tool, ops in role_tools.OPS.items() for op in ops}
    for refused, entries in role_tools.INSTEAD.items():
        assert refused in abilities, refused
        for ability, what in entries:
            assert ability in abilities and what, ability


def test_a_refusal_lists_who_she_may_name_in_the_forms_the_lookup_takes_back(world):
    from asuna.people import People
    from asuna.records import messages as message_records
    from test_people import row
    world.store.config['canonical_persons'] = {'qq:20001': 'local-user'}
    for number, card in ((20001, '阿杰'), (20002, '小林')):
        message_records.save(world.store, {**row(number, '在吗', card=card), 'scene_seq': number - 19999,
                                           'direction': 'inbound'}, stream='seed-%d' % number)
    scene = scene_records.get(world.store, SCENE)
    people = People(world.store, 'demo')
    docs = [doc for doc in people.ensure_roster(scene).values() if doc.get('person') != people.self_id]
    assert len(docs) == 2
    for doc in docs:
        form = people.copyable(scene, doc)
        assert [d['person'] for d in people.resolve(scene, form)] == [doc['person']], (form, doc)
    owner = next(doc for doc in docs if people.is_owner(doc))
    assert people.label(owner).startswith(people.owner_label + ' ['), 'the full label has the persona\'s word beside the bracket'
    assert people.resolve(scene, people.label(owner)) == [], 'which the lookup does not take back: it must never be offered'
    assert people.copyable(scene, owner) == '[阿杰 #%s]' % owner['handle']


def test_a_plan_with_a_long_intent_and_a_timing_that_does_not_parse_says_both_and_makes_nothing(world):
    world.tools.coordinator.scheduler = SimpleNamespace()          # a scheduler exists; nothing may reach it
    ep = turn(world)
    outcome, said, codes = call(world, ep, 'plan', {'do': 'create', 'intent': '之后再想。' * 300, 'at': '明天下午',
                                                    'after_seconds': 60})
    assert outcome == 'refused' and said.startswith('这次调用有 2 处要改'), said
    assert numbered(said)[0].startswith('intent 太长了：1500 字，过了 1000 字的线 500 字（要求 800 字以内）。')
    assert numbered(said)[1].startswith('没安排成：') and '给了' in numbered(said)[1]
    assert codes == ('TEXT_TOO_LONG', 'INVALID_SCHEDULE_SPEC'), codes
    outcome, said, codes = call(world, ep, 'plan', {'do': 'cancel'})
    assert said == 'plan_id 要写内容（160 字以内）。' and codes == ('TEXT_EMPTY',), (said, codes)


def test_a_task_reference_that_is_not_one_is_named_beside_a_message_that_is_too_long(world):
    ep = turn(world, thought=False)
    outcome, said, codes = call(world, ep, 'task', {'do': 'message', 'task': 'task-nope', 'message': '补充。' * 8000})
    assert outcome == 'refused' and said.startswith('这次调用有 3 处要改'), said
    lines = numbered(said)
    assert lines[0] == role_tools.THINK_FIRST
    assert any('「task-nope」不是这个对话里的任务' in line for line in lines)
    assert any(line.startswith('message 太长了：24000 字，最多 20000 字。') for line in lines), 'a failure catch: no aim, no band'
    assert set(codes) >= {'THINK_FIRST', 'TASK_UNKNOWN', 'TEXT_TOO_LONG'}


def test_a_delegate_past_the_hand_off_limit_and_with_no_brief_says_both(world):
    ep = turn(world)
    ep = world.store.put('episodes', {**ep, 'delegation_depth': role_tools.DELEGATION_DEPTH_MAX}, expected=ep['revision'], stream=ep['_id'])
    outcome, said, codes = call(world, ep, 'delegate', {'title': '查天气'})
    assert outcome == 'refused' and said.startswith('这次调用有 2 处要改')
    assert any('先停下来' in line for line in numbered(said)) and any(line.startswith('缺 brief') for line in numbered(said))
    assert codes == ('ARGS_MISSING', 'DELEGATION_DEPTH')


def test_speak_keeps_its_nothing_was_sent_framing_for_one_problem_and_for_several(world):
    ep = turn(world, tools=['think', 'speak'])
    outcome, said, codes = call(world, ep, 'speak', {'parts': [{'text': ''}]})
    assert said == '这次一条都没发：第 1 条是空的。改好再调用一次 speak。' and codes == ('SPEAK_PART',)
    outcome, said, codes = call(world, ep, 'speak', {'parts': [{'text': ''}, {'text': '好'}], 'quote': '3', 'wait': 'no'})
    assert said.startswith('这次调用有 2 处要改，这次一条都没发，改好一起再调用一次：') and 'quote：' in said, said
    outcome, said, codes = call(world, ep, 'speak', {'parts': '[{"text": "好"}, {"name": ""}]'})
    assert 'sticker 要写 name' in said, 'a string of parts is read, a part with no kind is completed, then checked'


def test_the_document_stores_problems_contain_what_apply_would_raise(world):
    """apply stays the authority and refuses at the first it meets; `problems` finds them together and has that one
    among them, in the same words."""
    from asuna.documents import DocumentError
    docs = DocumentStore(world.store, 'demo')
    docs.apply('ledger-a', {'op': 'append_section', 'heading': '第一节', 'reason': '开', 'kind': 'ledger'}, '正文',
               base_revision_id=None, author='character', mutation_id='m-a')
    base = docs.read('ledger-a')[0]
    bad = [
        ({'op': 'replace_section', 'sid': 'nope', 'reason': 'r'}, '改后的正文'),
        ({'op': 'replace_section', 'sid': '第一节', 'reason': 'r', 'visibility': 'secret'}, '改'),
        ({'op': 'replace_section', 'sid': '第一节', 'reason': 'r'}, '   '),
        ({'op': 'append_section', 'reason': 'r'}, '正文'),
        ({'op': 'append_section', 'heading': 'h', 'reason': 'r', 'tags': ['place:nowhere']}, '正文'),
        ({'op': 'set_tags', 'sid': 'nope', 'reason': 'r', 'inject': 'sometimes'}, None),
        ({'op': 'correction', 'sid': '第一节', 'reason': 'r', 'kind': 'working'}, '更正'),
    ]
    for intent, body in bad:
        found = docs.problems('ledger-a', intent, body)
        with pytest.raises(DocumentError) as raised:
            docs.apply('ledger-a', intent, body, base_revision_id=base, author='character', mutation_id='m-bad')
        assert str(raised.value) in [str(error) for error in found], (intent, found, raised.value)
    # Independent problems come back together; a check whose input a problem spoiled is not run on a guess.
    found = docs.problems('ledger-a', {'op': 'replace_section', 'sid': 'nope', 'reason': 'r', 'visibility': 'secret',
                                       'inject': 'sometimes', 'kind': 'working'}, '   ')
    assert [error.code for error in found] == ['DOC_BODY_REQUIRED', 'DOC_TAGS_INVALID', 'DOC_TAGS_INVALID', 'DOC_KIND_FIXED',
                                               'DOC_SECTION_NOT_FOUND'], found
    assert docs.problems('ledger-a', {'op': 'set_tags', 'sid': '第一节', 'reason': 'r', 'visibility': 'public'}) == []
    assert docs.problems('nobody', {'op': 'replace_section', 'sid': 'x', 'reason': 'r'}, 'x')[0].code == 'DOC_NOT_FOUND'


def test_a_layered_refusal_passes_the_workers_timed_dispatch_unchanged(world):
    """Where the two meet (ADR-109 times a character call where the worker dispatches it, around `RoleTools.call`): the
    refusal reaches the reply as the same `Refused` with every code, the call is timed as failed, and the timing row holds
    none of her words; a call that works is timed as done."""
    from concurrent.futures import Future
    from queue import Queue
    from asuna import audit
    from asuna.native_worker import BusinessWorker, NativeLane
    from test_data_child import Recorded
    ep = turn(world, thought=False)
    worker = BusinessWorker()
    worker.calls.attach(world.store, Recorded(), lambda stage, error: None)
    future = Future()
    future.asuna_calls = Queue()
    secret = '明天开会的内容'
    bad = {'doc': 'notes', 'section': 'meeting', 'content': secret, 'why': '因为这样。' * 500, 'from': '瞎写'}

    def handler(call_id, tool, args, **extra):
        if tool == 'last':
            future.set_result({'ended': True})
            return {'ok': True}, False
        return world.tools.call(ep['_id'], call_id, tool, args)
    future.asuna_handler = handler
    replies = [Future(), Future(), Future()]
    for call_id, tool, args, reply in (('c1', 'write_document', bad, replies[0]), ('c2', 'think', {'thought': '想一想'}, replies[1]),
                                       ('c3', 'last', {}, replies[2])):
        future.asuna_calls.put(({'call_id': call_id, 'tool': tool, 'args': args}, reply))
    try:
        row = episode_records.get(world.store, ep['_id'])
        assert NativeLane.wait(SimpleNamespace(worker=worker), future, 10, row) == {'ended': True}
        refused = replies[0].exception()
        assert isinstance(refused, Refused) and refused.codes[0] == 'THINK_FIRST' and 'TEXT_TOO_LONG' in refused.codes
        assert numbered(str(refused)) and secret not in str(refused)
        timed = sorted(audit.events(world.store, 'tool.time', stream=ep['_id']).rows(), key=lambda r: r['seq'])
        assert [(r['payload']['call_id'], r['payload']['outcome']) for r in timed] == [('c1', 'failed'), ('c2', 'done'), ('c3', 'done')]
        assert secret not in repr([r['payload'] for r in timed])
    finally:
        worker.calls.close()
