"""ADR-132 D3: one refusal names every problem the program can find, for every tool, by default. No declared field is
required (the worker names a missing field with the rest); every handler collects and ends its check part before its
first effect, so a call with a problem pending writes nothing."""
import copy
from types import SimpleNamespace

import pytest

from asuna import reasons, role_tools, tool_schema
from asuna.records import episodes as episode_records
from asuna.records import scenes as scene_records
from asuna.role_tools import OPS, TOOLS, Refused, RoleTools
from test_people import BOT, SCENE

ABILITIES = [name for name in TOOLS if name not in OPS] + ['%s.%s' % (name, op) for name in OPS for op in OPS[name]]
# What a handler may leave behind on a refused call: the turn's own record of the call and the audit row.
RECORDS_OF_THE_CALL = {'episodes', 'audit_events'}
# Calls that need no thought first: the thought itself, and the end of the turn (ADR-131: nothing but NOT_NOW).
NO_THOUGHT = {'think', role_tools.END_TURN}


@pytest.fixture
def world(store):
    store.config['chat'] = {**store.config.get('chat', {}), 'person_id': 'local-user', 'persona': 'demo',
                            'display_name': '演示', 'scene_id': SCENE}
    store.config.pop('persona_model', None)
    scene_records.save(store, {'_id': SCENE, 'kind': 'group', 'scope_key': 'scene:' + SCENE, 'channel_account_id': BOT,
                               'policy_epoch': 1, 'sequence': 0, 'members': ['local-user']})
    coordinator = SimpleNamespace(store=store, scheduler=None, context=SimpleNamespace(), restart_pending=None,
                                  tasks=None,
                                  _update=lambda ep, **changes: store.put('episodes', {**ep, **changes},
                                                                         expected=ep['revision'], stream=ep['_id']))
    return SimpleNamespace(store=store, tools=RoleTools(coordinator), serial=[0])


def turn(world, *, thought=True):
    world.serial[0] += 1
    ep_id = 'ep-%d' % world.serial[0]
    return world.store.put('episodes', {
        '_id': ep_id, 'scene_id': SCENE, 'scope_key': 'scene:' + SCENE, 'policy_epoch': 1, 'persona': 'demo',
        'person_id': 'local-user', 'episode_kind': 'external', 'state': 'TURN', 'source_event_id': 'evt-' + ep_id,
        'monologue_refs': [], 'context': {}, 'manifest': {'session_class': 'owner_private'}, 'turn_tools': ABILITIES,
        'turn_thought': thought, 'tool_calls': {}}, stream=ep_id)


def call(world, ep, name, args):
    call_id = '%s:%d' % (ep['_id'], len(episode_records.get(world.store, ep['_id'])['tool_calls']))
    try:
        return ('ok', world.tools.call(ep['_id'], call_id, name, args)[0], ())
    except Refused as exc:
        return ('refused', str(exc), tuple(exc.codes))


def records(store):
    return {name: copy.deepcopy(rows) for name, rows in store.adapter.data.records.items()
            if name not in RECORDS_OF_THE_CALL}


def test_no_declared_field_is_required_and_her_mark_is_on_each_field_the_program_cannot_fill():
    def walk(strict, declared, tool, path):
        for name, field in strict.items():
            shown = declared[name]
            assert 'required' not in shown and 'enum' not in shown, '%s %s' % (tool, path + [name])
            marks = shown.get('description', '').count(tool_schema.REQUIRED_MARK)
            fills = not path and (tool, name) in tool_schema.REQUIRED_FILLED
            assert marks == (1 if field.get('required') and not fills else 0), '%s %s' % (tool, path + [name])
            if field.get('required') and not fills:
                assert shown['description'].endswith(tool_schema.REQUIRED_MARK)
            if fills:
                assert shown['description'].endswith(tool_schema.REQUIRED_FILLED[(tool, name)])
            if (tool, name) in tool_schema.JSON_FIELDS:
                continue
            if isinstance(field.get('properties'), dict):
                walk(field['properties'], shown['properties'], tool, path + [name])
            if isinstance((field.get('items') or {}).get('properties'), dict):
                walk(field['items']['properties'], shown['items']['properties'], tool, path + [name, '[]'])
    for spec in role_tools.declared_specs(role_tools.all_specs()):
        strict = next((s for s in role_tools.all_specs() if s['name'] == spec['name']), None)['parameters']
        walk(strict, spec['parameters'], spec['name'], [])


def test_a_missing_field_is_named_with_think_first(world):
    """The owner's case (2026-11-16): credential without do and with no thought."""
    outcome, said, codes = call(world, turn(world, thought=False), 'credential', {'name': 'x'})
    assert outcome == 'refused' and codes[0] == 'THINK_FIRST' and 'ARGS_MISSING' in codes, said
    assert said.startswith('这次调用有 2 处要改') and '缺 do（做什么；只能是：keep、drop）' in said, said


def test_a_handlers_own_check_is_named_with_think_first(world, monkeypatch):
    """§6: credential with a bad note and no thought."""
    from asuna import credentials
    monkeypatch.setattr(credentials, '_call', lambda **_: pytest.fail('the vault was written to'))
    outcome, said, codes = call(world, turn(world, thought=False), 'credential',
                                {'do': 'keep', 'name': 'demo-key', 'note': '', 'env': {'DEMO_KEY': 'v'}})
    assert outcome == 'refused' and codes == ('THINK_FIRST', 'CREDENTIAL_NOTE_INVALID'), said


def filled(field):
    """A value the strict schema takes for `field`: its first enum value, else one of its type."""
    if field.get('enum'):
        return field['enum'][0]
    kind = field.get('type', 'string')
    if kind == 'object':
        return {key: filled(value) for key, value in (field.get('properties') or {}).items() if value.get('required')}
    if kind == 'array':
        return [filled(field['items'])] if isinstance(field.get('items'), dict) else []
    return {'integer': 1, 'number': 1, 'boolean': False}.get(kind, '测试')


def arguments(name, op, how):
    """A call's arguments: none, or every field the strict schema requires filled in (`filled`)."""
    args = {} if how == 'empty' else {key: filled(field) for key, field in TOOLS[name]['parameters'].items()
                                      if field.get('required')}
    if (name, 'parts') in tool_schema.JSON_FIELDS and how == 'filled':
        args['parts'] = [{'kind': 'text', 'text': '测试'}]
    return {**args, 'do': op} if op else args


@pytest.mark.parametrize('how', ['empty', 'filled'])
@pytest.mark.parametrize('can', ABILITIES)
def test_every_handler_called_with_a_problem_pending_writes_nothing(world, can, how):
    """Every handler with no thought first, its arguments none or every required one filled in, on the in-memory
    store: refused with what is pending (THINK_FIRST; a read, which needs no thought, only when something else is
    wrong), and nothing written."""
    name, _, op = can.partition('.')
    args = arguments(name, op, how)
    free = name in NO_THOUGHT or reasons.before_thought(name, {**args, 'op': op or args.get('do')})
    before = records(world.store)
    outcome, said, codes = call(world, turn(world, thought=False), name, args)
    if free and outcome == 'ok':
        return                                        # a read with nothing pending reads
    assert outcome == 'refused', '%s ran: %s' % (can, said)
    assert free or 'THINK_FIRST' in codes, (can, codes, said)
    assert records(world.store) == before, '%s wrote while refused: %s' % (can, codes)


def test_a_valid_call_with_think_first_pending_does_not_reach_its_effect(world, monkeypatch):
    """D2's real risk: a handler that no longer stops before it runs must not write while a problem is pending."""
    from asuna import credentials
    monkeypatch.setattr(credentials, '_call', lambda **_: pytest.fail('the vault was written to'))
    outcome, said, codes = call(world, turn(world, thought=False), 'credential',
                                {'do': 'keep', 'name': 'demo-key', 'note': '演示', 'env': {'DEMO_KEY': 'v'}})
    assert outcome == 'refused' and codes == ('THINK_FIRST',), said


def test_a_missing_fields_words_close_every_bracket_and_say_its_values_once():
    """Her 0555: `ideas.do` cut inside a bracket, `private_words.do` with its values twice. Every field of every tool."""
    for name, spec in TOOLS.items():
        for field, value in spec['parameters'].items():
            words = tool_schema._head(value)
            assert words.count('（') == words.count('）') and words.count('只能是') <= 1, (name, field, words)
