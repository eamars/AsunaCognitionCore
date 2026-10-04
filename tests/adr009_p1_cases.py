"""ADR-009 P1 offline cases (T1.2 worker half, T1.4). No MongoDB, model or network."""
import copy
import json
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src')]
DEMO = ROOT / 'tests/fixtures/personas/demo'
CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def demo_model():
    return json.loads((DEMO / 'persona-model.json').read_text(encoding='utf-8'))


def rejected(model, persona='demo'):
    from asuna.persona_model import PersonaModelError, validate
    try:
        validate(model, persona)
    except PersonaModelError as exc:
        return str(exc)
    return None


@case
def t1_2_invalid_model_or_id_is_refused_readably():
    from asuna.persona_model import validate, load, PersonaModelError
    assert validate(demo_model(), 'demo')['persona']['id'] == 'demo'
    bad = demo_model(); bad['speak']['max_messages'] = 'many'
    assert rejected(bad).startswith('PERSONA_MODEL_INVALID: speak/max_messages'), rejected(bad)
    assert rejected(demo_model(), 'other').startswith('PERSONA_ID_MISMATCH'), rejected(demo_model(), 'other')
    enabled = demo_model(); del enabled['affect']['clamp']
    assert rejected(enabled).startswith('PERSONA_MODEL_INVALID'), 'affect.enabled requires clamp'
    try:
        load(ROOT / 'tests/fixtures/personas/missing-model.json', 'demo')
        raise AssertionError('missing model accepted')
    except PersonaModelError as exc:
        assert str(exc).startswith('PERSONA_MODEL_UNREADABLE')
    # The installed persona package ships a neutral, valid model.
    xiaoman = json.loads((ROOT / 'packages/xiaoman/persona-model.json').read_text(encoding='utf-8'))
    assert rejected(xiaoman, xiaoman['persona']['id']) is None
    assert set(xiaoman) == {'model_version', 'persona'}, 'only neutral defaults in the package'


@case
def t1_4_private_keys_cannot_be_defaulted_or_declared():
    for key, value in (('timezone', 'Etc/UTC'), ('sleep_window', '01:00-07:00'), ('public_clock', True)):
        model = demo_model(); model['rhythm'][key] = value
        assert rejected(model), 'package defaulted rhythm.' + key
    for key in ('rhythm.timezone', 'rhythm.sleep_window', 'rhythm.public_clock', 'render.budget_tokens'):
        model = demo_model(); model['policy_keys'][key] = {'type': 'string', 'what': 'x'}
        assert rejected(model), 'package declared core key ' + key
    model = demo_model(); model['policy_keys']['no.such.key'] = {'type': 'integer', 'what': 'x'}
    assert rejected(model), 'declared key without any value'


@case
def t1_4_effective_value_precedence():
    from asuna.persona_model import effective, validate, neutral
    model = validate(demo_model(), 'demo')
    bare = neutral('demo', '演示')
    assert effective(bare, 'speak.max_messages') == 1                       # core default
    assert effective(model, 'dossier.inject_last') == 3                     # model default over core 0
    policy = {'dossier.inject_last': {'value': 7, 'what': 'x', 'class': 'param'}}
    assert effective(model, 'dossier.inject_last', policy) == 7             # policy over model
    assert effective(bare, 'heartbeat.enabled') is False and effective(bare, 'affect.enabled') is False
    assert effective(bare, 'render.max_window_share') == 0.25 and effective(bare, 'render.budget_tokens') is None
    assert effective(model, 'affect.kinds.calm.half_h') == 12


@case
def t1_4_timezone_and_self_development_precedence():
    from asuna.persona_model import timezone, self_development_minutes, validate, neutral
    model, bare = validate(demo_model(), 'demo'), neutral('demo', '演示')
    tz = {'rhythm.timezone': {'value': 'Etc/GMT-2', 'what': 'x', 'class': 'param'}}
    assert timezone(bare, tz, {'timezone': 'Etc/GMT+5'}) == ('Etc/GMT-2', 'policy')
    assert timezone(bare, {}, {'timezone': 'Etc/GMT+5'}) == ('Etc/GMT+5', 'config')
    assert timezone(bare, {}, {}) == ('UTC', 'unset')
    every = {'self_development.every_min': {'value': 90, 'what': 'x', 'class': 'param'}}
    legacy = {'self_development': {'every_seconds': 7200}}
    assert self_development_minutes(model, every, legacy) == (90, 'policy')
    assert self_development_minutes(model, {}, legacy) == (120, 'config')
    assert self_development_minutes(model, {}, {}) == (1440, 'model')
    assert self_development_minutes(bare, {}, {}) == (1440, 'core')


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    for fn in CASES:
        try:
            fn()
            print('PASS', fn.__name__)
        except Exception as exc:
            detail = str(exc) or traceback.format_exc().strip().splitlines()[-1]
            print('FAIL', fn.__name__, detail[:300].replace('\n', ' '))


if __name__ == '__main__':
    main()
