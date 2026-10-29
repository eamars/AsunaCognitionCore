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
    'rhythm.sleep_window': {'type': 'string', 'what': '作息声明 HH:MM-HH:MM；是输入，不是闸门'},
    'rhythm.public_clock': {'type': 'boolean', 'what': '是否在 public 会话中给出本地时刻（会暴露时区）'},
}
# Core-writable keys: a package may default them without declaring them.
CORE_WRITABLE_KEYS = {
    # Her heartbeat's pace is hers; the heartbeat itself belongs to the program (ADR-012 §4.3).
    'heartbeat.every_min': {'type': 'integer', 'min': 15, 'max': 240, 'what': '心跳间隔（分钟）'},
    'heartbeat.min_gap_min': {'type': 'integer', 'min': 0, 'max': 720,
                              'what': '没有找你的新事时，两次心跳回合之间至少隔多久（分钟）'},
    'heartbeat.pause_min': {'type': 'integer', 'min': 0, 'max': 720,
                            'what': '让心跳安静一阵（分钟，0 = 马上恢复）；到时自动恢复'},
    'heartbeat.visits': {'type': 'boolean', 'what': '心跳时可以出门，去你在的群里看看'},
    'heartbeat.visits_per_day': {'type': 'integer', 'min': 0, 'max': 8, 'what': '每天最多出门几次'},
    'heartbeat.visits_per_beat': {'type': 'integer', 'min': 1, 'max': 3, 'what': '一拍里最多去几个群'},
    # The heartbeat's die (ADR-058): named weights, a name left out weighs 0.
    'heartbeat.dice_awake': {'type': 'string', 'what': '醒着时心跳掷骰子的分布，带名字写：歇着 40、有趣 31、自我开发 10、自我评估 12、复盘 2、找人 5、待着 0'},
    'heartbeat.dice_asleep': {'type': 'string', 'what': '作息窗里心跳掷骰子的分布，带名字写（含 待着），漏写的算 0；整夜安静就写 歇着 100'},
    # Her night self-development stages (ADR-021): when and how often; the owner can switch them off.
    'self_development.night_start_hour': {'type': 'integer', 'min': 0, 'max': 23,
                                          'what': '夜里分段自我开发从几点开始（你的钟面，整点）'},
    'self_development.night_hours': {'type': 'integer', 'min': 0, 'max': 8,
                                     'what': '夜里分段自我开发持续几个小时（0 = 不开）'},
    'self_development.night_every_min': {'type': 'integer', 'min': 20, 'max': 120,
                                         'what': '夜里两段自我开发之间隔多久（分钟）'},
}
# Only the owner turns her heartbeat on or off, and sets the ceiling of what each place carries of her identity: a
# package may default them, never offer them to her as policy keys.
OWNER_KEYS = {'heartbeat.enabled', 'render.identity_tokens'}
HEARTBEAT_EVERY_MIN = (15, 240)
# The core's neutral words where a persona words its own (persona-model keys, not hers to set_policy).
TIERS_TOLD = ('你的东西分三个地方：随身，每一回合都带着；手边，不进提示，聊到相关的事或用 recall 能找到；'
              '收着，默认不出现，recall 用字或标题才找得回来。'
              '被用到会让一条在随身多留一阵，改写出变化会把它带回随身，一阵子没用到就往下放；放手（let_go）是你自己的动作。'
              '群笔记的节可以置顶：笔记超长时置顶的节不折成标题，但它照样会因为一阵子没用到离开随身，也照样占随身的名额。'
              '往下放不是删掉，原话一直都在。事实只会被更正替换，不会因为没人用而退；记忆会淡。'
              '要说「没有、没答应过、没说过」之前，先 recall 一下，它会告诉你找了哪几层。')
EXCHANGES_NOTE = '这是你那天说过的原话、你那一回合写下的心里话，和之后那边发生了什么；程序没有给它打分，也没有替你下结论。'
IDLE_HINT = '这一拍没有指定的事。'
CORE_DEFAULTS = {
    # What each (place, class) pair carries of her identity every turn (common.md, persona, voice, self and core as
    # sent) has one ceiling in estimated tokens, each pair its own (carried.py, ADR-096). A package whose own seeds are
    # longer gets room for them on top (render.budget_limit).
    'render': {'identity_tokens': 12288, 'max_window_share': 0.25, 'values_tag': 'values', 'action_persona': 'core'},
    'recall_protocol': {'order': None},
    'affect': {'enabled': False, 'close_mode': 'from_close', 'require_cost': False, 'allow_untyped': True,
               'max_delta': {'val': 100, 'arl': 100}, 'proposal_ttl_h': 24, 'kind_floor': 0,
               'kinds': {}, 'bands': [], 'policy': []},
    'rhythm': {'settle_at': None, 'sleep_window': None, 'public_clock': False},
    'heartbeat': {'enabled': False, 'every_min': 60, 'min_gap_min': 120, 'pause_min': 0,
                  'visits': False, 'visits_per_day': 4, 'idle_hint': IDLE_HINT,
                  'visits_per_beat': 1, 'dice_awake': '歇着 40、有趣 31、自我开发 10、自我评估 12、复盘 2、找人 5、待着 0',
                  'dice_asleep': '歇着 66、自我开发 20、自我评估 8、复盘 2、找人 4、待着 0'},
    'memory': {'forgetting': {'half_life_days': 30, 'half_life_messages': 1500, 'step_back_below': 0.1}, 'coverage_floor': 0,
               'promotion': {'daily_quota': 0, 'min_roots': 2, 'min_dates': 2, 'window_days': 7},
               # How her memory's places are told once per conversation (block_guide); a persona words it.
               'tiers_told': TIERS_TOLD},
    'speak': {'max_messages': 1, 'chars_per_second': 12, 'min_gap_s': 1, 'max_gap_s': 5},
    'phrasing': {'window': 20},
    'self_development': {'every_min': None, 'night_start_hour': 1, 'night_hours': 5, 'night_every_min': 30},
    # How people read in group and private chats (people.py): her word for the owner, and other names she answers to;
    # familiarity.py names how well she knows someone, and a persona may word each level and give its stance.
    'people': {'owner_label': '本机用户', 'self_names': [], 'familiarity': {}},
    # Words a persona gives the core's readings (the way people.familiarity words its levels): her self-evaluation's
    # note on her exchanges (self_review.py) and the hint of an idle heartbeat (dice.py).
    'self_review': {'exchanges_note': EXCHANGES_NOTE},
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


def writable_keys(model: dict):
    """Every key set_policy accepts for this model, sorted."""
    return sorted(key for key in {*PRIVATE_KEYS, *CORE_WRITABLE_KEYS, *((model or {}).get('policy_keys') or {})}
                  if key not in OWNER_KEYS)


def value_words(spec: dict):
    """What a key takes, in words: its type and its bounds or choices."""
    kind = {'boolean': 'true 或 false', 'integer': '整数', 'number': '数字', 'string': '文字',
            'object': '对象'}.get(spec['type'], spec['type'])
    if 'enum' in spec:
        return '其中之一：' + '、'.join(json.dumps(item, ensure_ascii=False) for item in spec['enum'])
    if spec['type'] in ('integer', 'number') and ('min' in spec or 'max' in spec):
        return '%s，%s–%s' % (kind, spec.get('min', '…'), spec.get('max', '…'))
    return kind


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
