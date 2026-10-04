"""ADR-009 P1 MongoDB tests: T1.3 policy store, T1.5 per-persona isolation (policy)."""
from concurrent.futures import ThreadPoolExecutor
import json
import threading

import pytest

from asuna.persona_model import validate
from asuna.policy import PolicyStore
from asuna.state import Conflict, Denied
from conftest import FIXTURES

MODEL = validate(json.loads((FIXTURES / 'personas/demo/persona-model.json').read_text(encoding='utf-8')), 'demo')


def item(key, value, what='测试参数', cls='param'):
    return {'key': key, 'value': value, 'what': what, 'class': cls}


def test_T1_3_policy_store_revisions_classes_and_cas(store):
    policy = PolicyStore(store, 'demo', MODEL)
    assert policy.read() == (None, {})
    first = policy.set([item('dossier.inject_last', 5)], base_revision_id=None, reason='初始值', author='operator',
                       mutation_id='p1-first')
    head, params = policy.read()
    assert head == first['_id'] and params['dossier.inject_last'] == {'value': 5, 'what': '测试参数', 'class': 'param'}
    assert first['parent_revision_id'] is None and first['author'] == 'operator' and first['reason'] == '初始值'
    # Replaying the same mutation is a no-op that returns the same revision.
    assert policy.set([item('dossier.inject_last', 5)], base_revision_id=None, reason='初始值', author='operator',
                      mutation_id='p1-first')['_id'] == first['_id']
    for cls in ('secret', 'counter'):
        with pytest.raises(Denied, match='POLICY_CLASS_REFUSED'):
            policy.set([item('dossier.inject_last', 1, cls=cls)], base_revision_id=head, reason='x', author='operator',
                       mutation_id='p1-' + cls)
    with pytest.raises(ValueError, match='POLICY_WHAT_REQUIRED'):
        policy.set([{'key': 'dossier.inject_last', 'value': 1}], base_revision_id=head, reason='x', author='operator',
                   mutation_id='p1-no-what')
    with pytest.raises(Denied, match='POLICY_KEY_UNDECLARED'):
        policy.set([item('speak.split_marker', '|')], base_revision_id=head, reason='x', author='operator', mutation_id='p1-undeclared')
    with pytest.raises(ValueError, match='POLICY_VALUE_RANGE'):
        policy.set([item('dossier.inject_last', 99)], base_revision_id=head, reason='x', author='operator', mutation_id='p1-range')
    # Core private and core-writable keys are always writable, with their own types.
    second = policy.set([item('rhythm.timezone', 'Etc/UTC'), item('render.budget_tokens', 4096)], base_revision_id=head,
                        reason='本机设置', author='operator', mutation_id='p1-core-keys')
    assert set(policy.params()) == {'dossier.inject_last', 'rhythm.timezone', 'render.budget_tokens'}
    assert second['parent_revision_id'] == head
    # Two writers on the same base: exactly one wins, the other is stale, no lost update.
    barrier = threading.Barrier(2)

    def write(value):
        barrier.wait()
        try:
            policy.set([item('dossier.inject_last', value)], base_revision_id=second['_id'], reason='并发',
                       author='operator', mutation_id='p1-race-%d' % value)
            return 'ok'
        except Conflict as exc:
            assert str(exc) == 'BASE_REVISION_STALE'
            return 'stale'

    with ThreadPoolExecutor(2) as pool:
        outcomes = sorted(pool.map(write, (2, 3)))
    assert outcomes == ['ok', 'stale'], outcomes
    winner = policy.params()['dossier.inject_last']['value']
    assert winner in (2, 3) and policy.params()['rhythm.timezone']['value'] == 'Etc/UTC'


def test_T1_5_policy_is_keyed_by_persona(store):
    other = validate({'model_version': 1, 'persona': {'id': 'second', 'display_name': '第二'},
                      'policy_keys': {'speak.max_messages': {'type': 'integer', 'min': 1, 'max': 5, 'what': '段数'}}}, 'second')
    PolicyStore(store, 'demo', MODEL).set([item('dossier.inject_last', 4)], base_revision_id=None, reason='a',
                                          author='operator', mutation_id='p1-demo')
    PolicyStore(store, 'second', other).set([item('speak.max_messages', 2)], base_revision_id=None, reason='b',
                                            author='operator', mutation_id='p1-second')
    assert set(PolicyStore(store, 'demo', MODEL).params()) == {'dossier.inject_last'}
    assert set(PolicyStore(store, 'second', other).params()) == {'speak.max_messages'}
    # A key declared only by the other persona's model is not writable here.
    with pytest.raises(Denied, match='POLICY_KEY_UNDECLARED'):
        PolicyStore(store, 'second', other).set([item('dossier.inject_last', 1)], base_revision_id=None, reason='c',
                                                author='operator', mutation_id='p1-cross')
