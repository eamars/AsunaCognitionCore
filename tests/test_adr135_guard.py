"""ADR-135 landing 2 (D8), on the fixture world in memory: one guard at the two doors. A call of hers that is not allowed
in an outside turn gets the plain sentence, whatever else is wrong with it and whatever the tool texts say, with its
code in the audit; after three sentences in a turn nothing more is evaluated, and speak and end_turn are untouched. At
home the program's own refusal stands, with the same code in the audit. A task's call outside its grant is the same at
the doing side. g1 is an outside group (A, the owner, and B), dm-a the owner's chat (home)."""
from itertools import count
from types import SimpleNamespace

import pytest

from asuna import guard, role_tools, switches, visibility
from asuna.records import scenes as scene_records
from asuna.records import tasks as task_records
from asuna.role_tools import Refused, RoleTools

PERSONA = 'P1'
SERIAL = count(1)
RULE_WORDS = ('家里', '外面', '主人', '只有', '只在', '回合', '权限', '工具', '开关')


@pytest.fixture
def her(world):
    world.config['chat'] = {**(world.config.get('chat') or {}), 'scene_id': 'dm-a', 'person_id': 'A',
                            'persona': PERSONA}
    world.config['channels']['qq'] = {'account_id': 'acct', 'routes': {
        'r1': {'scene_id': 'g1', 'target': {'type': 'group', 'id': 'G1'},
               'members': {'s-a': {'person_id': 'A'}, 's-b': {'person_id': 'B'}}}}}
    scene = scene_records.get(world, 'g1')
    scene_records.save(world, {**scene, 'channel_id': 'qq'}, expected=scene['revision'])     # a platform group
    coordinator = SimpleNamespace(store=world, context=SimpleNamespace(),
                                  _update=lambda ep, **changes: world.put('episodes', {**ep, **changes},
                                                                         expected=ep['revision'], stream=ep['_id']))
    return SimpleNamespace(store=world, tools=RoleTools(coordinator))


def turn(her, scene='g1', person='B', cls=visibility.PUBLIC, kind='external', tools=None):
    """A turn as the program prepares one (its tools: what the conversation lists and this turn may use), or with
    the tools given."""
    serial = next(SERIAL)
    ep = {'_id': 'ep-guard-%d' % serial, 'scene_id': scene, 'scope_key': 'scene:' + scene, 'policy_epoch': 1,
          'persona': PERSONA, 'person_id': person, 'episode_kind': kind, 'state': 'TURN',
          'source_event_id': 'evt-guard-%d' % serial, 'monologue_refs': [],
          'context': {'action_capabilities_from_program': {'available': True}},
          'manifest': {'session_class': cls}, 'turn_thought': True, 'tool_calls': {}}
    ep['turn_tools'] = tools if tools is not None else role_tools.exposed(her.store, ep)
    her.store.put('episodes', ep, stream=ep['_id'])
    return ep


def call(her, ep, name, args):
    n = len((her.store.collection('episodes').get(ep['_id']) or {}).get('tool_calls') or {})
    return her.tools.call(ep['_id'], '%s:%d' % (ep['_id'], n), name, args)


def denied(her, ep, name, args):
    with pytest.raises(Refused) as caught:
        call(her, ep, name, args)
    return caught.value


def audits(her, ep):
    rows = her.store.collection('audit_events').find({'type': 'guard.denied', 'stream_id': ep['_id']})
    return [row['payload'] for row in sorted(rows, key=lambda row: row['seq'])]


# Each row of D8's table that exists at this landing, met in the outside group: (the call, its code). A call of a rule
# is made in a turn whose tools include it, so that the rule, not the list, is what stops it.
ROWS = [
    ('set_policy', {'key': 'x', 'value': 1, 'reason': '想'}, 'not_listed', None),                 # a home ability
    ('no_such_tool', {}, 'not_listed', None),
    ('task', {'do': 'answer', 'task': 't', 'answer': '好'}, 'not_now', None),                     # a consult's option
    ('group_focus', {'do': 'mute'}, 'not_listed', ['group_focus']),
    ('group_focus', {'do': 'condense'}, 'not_now', ['group_focus']),
    ('write_document', {'doc': 'persona', 'op': 'append_section', 'heading': 'x', 'content': 'y', 'why': 'z'},
     'not_listed', ['write_document']),
    ('recall', {'person': '名单'}, 'not_listed', ['recall']),
    ('plan', {'do': 'create', 'intent': '看看', 'line': 'x', 'in_minutes': 5}, 'not_listed', ['plan']),
    ('watch', {'do': 'block'}, 'not_listed', ['watch']),                                    # the owner, speaking
]


@pytest.mark.parametrize('name, args, code, tools', ROWS)
def test_G1_every_row_gives_the_plain_sentence_in_an_outside_turn_and_its_code_in_the_audit(her, name, args, code,
                                                                                            tools):
    person = 'A' if name == 'watch' else 'B'
    ep = turn(her, person=person, tools=['think', 'recall', *tools] if tools else None)
    refusal = denied(her, ep, name, args)
    assert str(refusal) == guard.NOT_DONE and list(refusal.codes) == [code]
    assert not any(word in str(refusal) for word in RULE_WORDS) and name not in str(refusal)
    [event] = audits(her, ep)
    assert (event['code'], event['tool'], event['class'], event['sentence']) == (code, name, visibility.PUBLIC, True)
    recorded = next(iter(her.store.collection('episodes').get(ep['_id'])['tool_calls'].values()))
    assert (recorded['refused'], recorded['code']) == (guard.NOT_DONE, code)


def test_G1_another_member_s_task_is_not_granted_outside(her):
    task_records.save(her.store, {'_id': 'task-of-a', 'scene_id': 'g1', 'requester_id': 'A', 'scope_key': 'scene:g1',
                                  'policy_epoch': 1, 'state': 'RUNNING', 'title': 't', 'goal': 'g',
                                  'request_key': 'rk-of-a'}, stream='task-of-a')
    ep = turn(her, tools=['think', 'recall', 'task.message'])
    refusal = denied(her, ep, 'task', {'do': 'message', 'task': 'task-of-a', 'message': '快点'})
    assert str(refusal) == guard.NOT_DONE and list(refusal.codes) == ['not_granted']


def test_G1_a_switched_off_tool_is_not_listed(her):
    switches.set_switch(her.store, {'_id': 'ep-home', 'persona': PERSONA, 'scope_key': 'scene:dm-a'}, 'tools_off',
                        label='一群', scene_id='g1', tools=['delegate'])
    ep = turn(her)
    assert list(denied(her, ep, 'delegate', {'title': '查', 'brief': '查天气'}).codes) == ['not_listed']


def test_G1_the_same_call_at_home_keeps_the_program_s_own_words_and_the_same_code(her):
    outside = denied(her, turn(her), 'task', {'do': 'answer', 'task': 't', 'answer': '好'})
    home_ep = turn(her, scene='dm-a', person='A', cls=visibility.OWNER_PRIVATE)
    at_home = denied(her, home_ep, 'task', {'do': 'answer', 'task': 't', 'answer': '好'})
    assert str(outside) == guard.NOT_DONE and str(at_home) == role_tools.not_now(her.store, home_ep, 'task.answer')
    assert not isinstance(at_home, guard.Guarded) and list(at_home.codes) == ['NOT_NOW']
    [event] = audits(her, home_ep)
    assert (event['code'], event['sentence'], event['class']) == ('not_now', False, visibility.OWNER_PRIVATE)


def test_G2_the_same_denials_with_every_tool_description_emptied(her, monkeypatch):
    emptied = {name: {**spec, 'description': ''} for name, spec in role_tools.TOOLS.items()}
    monkeypatch.setattr(role_tools, 'TOOLS', emptied)
    for name, args, code, tools in ROWS:
        ep = turn(her, person='A' if name == 'watch' else 'B', tools=['think', 'recall', *tools] if tools else None)
        refusal = denied(her, ep, name, args)
        assert (str(refusal), list(refusal.codes)) == (guard.NOT_DONE, [code]), name


def test_G3_a_call_both_malformed_and_not_allowed_gets_the_plain_sentence(her):
    ep = turn(her)
    assert str(denied(her, ep, 'set_policy', 'not an object')) == guard.NOT_DONE
    assert str(denied(her, ep, 'set_policy', {'key': 3})) == guard.NOT_DONE         # wrong type, missing fields
    wrong = turn(her, tools=['think', 'recall', 'group_focus'])
    assert str(denied(her, wrong, 'group_focus', {'do': 'mute', 'hours': 'soon', 'place': 7})) == guard.NOT_DONE


def test_G4_after_three_sentences_a_fourth_call_is_not_evaluated_and_speak_and_end_turn_are_untouched(her, monkeypatch):
    ep = turn(her)
    for _ in range(3):
        denied(her, ep, 'set_policy', {'key': 'x', 'value': 1, 'reason': '想'})
    assert her.store.collection('episodes').get(ep['_id'])[guard.COUNT] == 3

    def evaluated(*args):
        raise AssertionError('the guard was asked after the limit')
    monkeypatch.setattr(guard, 'check', evaluated)
    fourth = denied(her, ep, 'recall', {'query': '天气'})                    # allowed in itself: not evaluated
    assert (str(fourth), list(fourth.codes)) == (guard.NOT_DONE, [guard.LIMITED])
    assert [event['code'] for event in audits(her, ep)] == ['not_listed'] * 3 + [guard.LIMITED]
    monkeypatch.undo()
    fresh = her.store.collection('episodes').get(ep['_id'])
    for name in guard.UNTOUCHED:                                             # past the limit, they reach their tool
        her.tools._guard(fresh, 'probe-' + name, name, {})


def test_G5_a_task_s_call_outside_its_grant_is_the_plain_sentence_in_an_outside_task_and_its_own_words_at_home(her):
    def task(task_id, scene, person):
        return task_records.save(her.store, {'_id': task_id, 'scene_id': scene, 'requester_id': person,
                                             'scope_key': 'scene:' + scene, 'policy_epoch': 1, 'state': 'RUNNING',
                                             'title': 't', 'goal': 'g', 'allowed_capabilities': ['read_file'],
                                             'request_key': 'rk-' + task_id},
                                 stream=task_id)
    outside, home = task('task-out', 'g1', 'B'), task('task-home', 'dm-a', 'A')
    with pytest.raises(guard.TaskGuarded) as caught:
        guard.guard_task(her.store, outside, 'sandbox_run', {'argv': ['python3', '-V']})
    assert str(caught.value) == guard.NOT_DONE and caught.value.code == 'not_granted'
    guard.guard_task(her.store, home, 'sandbox_run', {'argv': ['python3', '-V']})     # the broker's own words follow
    assert guard.deny_task(her.store, outside, 'not_granted', 'address', 'web_fetch') == guard.NOT_DONE
    events = [row['payload'] for row in sorted(her.store.collection('audit_events').find({'type': 'guard.denied'}),
                                               key=lambda row: row['seq'])]
    assert sorted((e['task'], e['code'], e['rule'], e['outside']) for e in events) == sorted([
        ('task-out', 'not_granted', 'tool', True), ('task-home', 'not_granted', 'tool', False),
        ('task-out', 'not_granted', 'address', True)])


def test_G5_the_broker_is_the_door_an_outside_task_s_call_outside_its_grant_meets(world, tmp_path):
    from asuna import tasks
    from test_data_child import Recorded, seeded
    task = seeded(world)                                     # a group's task, for a peer: an outside task
    broker = tasks.ToolBroker(tasks.TaskService(world), Recorded())
    broker.bindings['session'] = (task, type('Sandbox', (), {'task_dir': tmp_path, 'protected_paths': []})())
    with pytest.raises(guard.TaskGuarded) as caught:
        broker.call('session', 'call-1', 'sandbox_run', {'argv': ['python3', '-V']})
    assert str(caught.value) == guard.NOT_DONE
    [event] = [row['payload'] for row in world.collection('audit_events').find({'type': 'guard.denied'})]
    assert (event['code'], event['rule'], event['tool'], event['outside']) == ('not_granted', 'tool', 'sandbox_run', True)
