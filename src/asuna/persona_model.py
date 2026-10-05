"""Persona model: validation and effective parameter values (ADR-009 PERSONA_CONTRACT §3).

The model is persona data shipped by a persona package. The core supplies a
neutral default for every parameter, meaning "feature off" or "as before".
Effective value = policy store > persona model default > core default.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema

from .config import schema

SCHEMA = schema('persona-model.schema.json')
# Values that belong to the deployer or the persona herself: a package may not
# default or declare them; they are set only on this machine (policy store).
PRIVATE_KEYS = {
    'rhythm.timezone': {'type': 'string', 'what': '节律、沉淀与本地时刻所用的 IANA 时区'},
    'rhythm.sleep_window': {'type': 'string', 'what': '作息声明 HH:MM-HH:MM；是输入，不是闸门'},
    'rhythm.public_clock': {'type': 'boolean', 'what': '是否在 public 会话中给出本地时刻（会暴露时区）'},
}
# Core-writable keys: a package may default them without declaring them.
CORE_WRITABLE_KEYS = {
    'render.budget_tokens': {'type': 'integer', 'min': 256, 'max': 200000, 'what': '人格渲染的绝对 token 预算'},
    # Her heartbeat's pace is hers; the heartbeat itself belongs to the program (ADR-012 §4.3).
    'heartbeat.every_min': {'type': 'integer', 'min': 15, 'max': 240, 'what': '心跳间隔（分钟）'},
    'heartbeat.min_gap_min': {'type': 'integer', 'min': 0, 'max': 720,
                              'what': '没有找你的新事时，两次心跳回合之间至少隔多久（分钟）'},
    'heartbeat.skip_in_sleep': {'type': 'boolean', 'what': '睡眠窗里是否跳过心跳'},
    'heartbeat.pause_min': {'type': 'integer', 'min': 0, 'max': 720,
                            'what': '让心跳安静一阵（分钟，0 = 马上恢复）；到时自动恢复'},
    'heartbeat.visits': {'type': 'boolean', 'what': '心跳时可以出门，去你在的群里看看'},
    'heartbeat.quiet_min': {'type': 'integer', 'min': 0, 'max': 240, 'what': '群里安静多久，才去那儿起话头（分钟）'},
    'heartbeat.after_own_min': {'type': 'integer', 'min': 30, 'max': 1440,
                                'what': '在一个群说过话或去看过以后，多久内不再去（分钟）'},
    'heartbeat.visits_per_day': {'type': 'integer', 'min': 0, 'max': 8, 'what': '每天最多出门几次'},
}
# Only the owner turns her heartbeat on or off: a package may default it, never offer it to her as a policy key.
OWNER_KEYS = {'heartbeat.enabled'}
HEARTBEAT_EVERY_MIN = (15, 240)
CORE_DEFAULTS = {
    'render': {'budget_tokens': None, 'max_window_share': 0.25, 'values_tag': 'values', 'action_persona': 'values'},
    'recall_protocol': {'order': None},
    'affect': {'enabled': False, 'close_mode': 'from_close', 'require_cost': False, 'allow_untyped': True,
               'max_delta': {'val': 100, 'arl': 100}, 'proposal_ttl_h': 24, 'kind_floor': 0,
               'kinds': {}, 'bands': [], 'policy': []},
    'dossier': {'inject_last': 0, 'index_size': 30},
    'rhythm': {'settle_at': None, 'timezone': None, 'sleep_window': None, 'public_clock': False},
    'heartbeat': {'enabled': False, 'every_min': 60, 'min_gap_min': 120, 'skip_in_sleep': False, 'pause_min': 0,
                  'visits': False, 'quiet_min': 30, 'after_own_min': 360, 'visits_per_day': 4},
    'memory': {'forgetting': {'half_life_days': 30, 'half_life_messages': 1500, 'step_back_below': 0.1}, 'coverage_floor': 0,
               'promotion': {'daily_quota': 0, 'min_roots': 2, 'min_dates': 2, 'window_days': 7}},
    'speak': {'max_messages': 1, 'split_marker': '---split---', 'chars_per_second': 12, 'min_gap_s': 1, 'max_gap_s': 5},
    'phrasing': {'window': 20},
    'self_development': {'every_min': None},
    # How people read in group and private chats (people.py): her word for the owner, and other names she answers to;
    # familiarity.py names how well she knows someone, and a persona may word each level and give its stance.
    'people': {'owner_label': '本机用户', 'self_names': [], 'familiarity': {}},
}
SELF_DEVELOPMENT_DEFAULT_MIN = 1440


class PersonaModelError(ValueError):
    pass


def validate(model: dict, persona_id: str) -> dict:
    """Return a validated copy or raise PersonaModelError with a readable code and detail."""
    try:
        jsonschema.validate(model, SCHEMA)
    except jsonschema.ValidationError as exc:
        path = '/'.join(str(p) for p in exc.absolute_path) or '<root>'
        raise PersonaModelError(f'PERSONA_MODEL_INVALID: {path}: {exc.message}') from None
    if model['persona']['id'] != persona_id:
        raise PersonaModelError(f"PERSONA_ID_MISMATCH: model {model['persona']['id']!r} != registered {persona_id!r}")
    declared = set(model.get('policy_keys', {}))
    reserved = declared & (set(PRIVATE_KEYS) | set(CORE_WRITABLE_KEYS) | OWNER_KEYS)
    if reserved:
        raise PersonaModelError('PERSONA_MODEL_INVALID: policy_keys may not declare core keys: ' + ', '.join(sorted(reserved)))
    for key in PRIVATE_KEYS:
        if lookup(model, key) is not _MISSING:
            raise PersonaModelError('PERSONA_MODEL_INVALID: a package may not default the private key ' + key)
    for key in declared:
        if lookup(model, key) is _MISSING and lookup(CORE_DEFAULTS, key) is _MISSING:
            raise PersonaModelError('PERSONA_MODEL_INVALID: declared policy key has no model or core value: ' + key)
    return copy.deepcopy(model)


def load(path, persona_id: str) -> dict:
    try:
        model = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise PersonaModelError(f'PERSONA_MODEL_UNREADABLE: {type(exc).__name__}: {exc}') from None
    return validate(model, persona_id)


def neutral(persona_id: str, display_name: str) -> dict:
    """Model used for a v1 contribution that ships none: every feature at its core default."""
    return {'model_version': 1, 'persona': {'id': persona_id, 'display_name': display_name}}


_MISSING = object()


def lookup(tree, key: str):
    node = tree
    for part in key.split('.'):
        if not isinstance(node, dict) or part not in node:
            return _MISSING
        node = node[part]
    return node


def key_spec(model: dict, key: str):
    """Type/range declaration for a writable key, or None when the key is not writable."""
    if key in OWNER_KEYS:
        return None
    return PRIVATE_KEYS.get(key) or CORE_WRITABLE_KEYS.get(key) or (model.get('policy_keys') or {}).get(key)


def check_value(spec: dict, value):
    kind = spec['type']
    ok = {'boolean': lambda v: isinstance(v, bool),
          'integer': lambda v: isinstance(v, int) and not isinstance(v, bool),
          'number': lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
          'string': lambda v: isinstance(v, str),
          'object': lambda v: isinstance(v, dict)}[kind](value)
    if not ok:
        raise ValueError(f'POLICY_VALUE_TYPE: expected {kind}')
    if 'enum' in spec and value not in spec['enum']:
        raise ValueError('POLICY_VALUE_NOT_IN_ENUM')
    if kind in ('integer', 'number'):
        if 'min' in spec and value < spec['min']:
            raise ValueError(f"POLICY_VALUE_RANGE: < {spec['min']}")
        if 'max' in spec and value > spec['max']:
            raise ValueError(f"POLICY_VALUE_RANGE: > {spec['max']}")
    return value


def effective(model: dict, key: str, policy: dict | None = None):
    """policy store > persona model default > core default (None when nothing applies)."""
    if policy and key in policy:
        return policy[key]['value']
    for tree in (model or {}, CORE_DEFAULTS):
        value = lookup(tree, key)
        if value is not _MISSING:
            return copy.deepcopy(value)
    return None


def timezone(model: dict, policy: dict | None, config: dict) -> tuple:
    """(zone, source) for rhythm: policy rhythm.timezone > existing global config timezone > UTC.

    A scene-level ``timezone`` still governs only that scene's plan timing (schedule_rules).
    """
    zone = effective(model, 'rhythm.timezone', policy)
    if zone:
        return zone, 'policy'
    if (config or {}).get('timezone'):
        return config['timezone'], 'config'
    return 'UTC', 'unset'


def self_development_minutes(model: dict, policy: dict | None, config: dict) -> tuple:
    """policy > existing local self_development.every_seconds (compat until P7) > model > 1440."""
    if policy and 'self_development.every_min' in policy:
        return policy['self_development.every_min']['value'], 'policy'
    seconds = ((config or {}).get('self_development') or {}).get('every_seconds')
    if isinstance(seconds, int) and not isinstance(seconds, bool) and seconds > 0:
        return max(1, round(seconds / 60)), 'config'
    value = lookup(model or {}, 'self_development.every_min')
    if value is not _MISSING and value:
        return value, 'model'
    return SELF_DEVELOPMENT_DEFAULT_MIN, 'core'
