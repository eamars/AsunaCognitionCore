"""ADR-009 情感投影参考实现（纯函数、只用标准库）。

这是规格的一部分：实现必须在合成夹具上与本文件逐点一致（误差 < 1e-6）。
它不是运行时代码，也不读写数据库。模型参数与事件形状见 ARCHITECTURE.md §6。
"""
from __future__ import annotations

from datetime import datetime, timezone

SECONDS_PER_HOUR = 3600.0


def parse_ts(value):
    """ISO-8601 → UTC datetime；必须带时区偏移（导入时的原始串保留在 ts_original）。"""
    if isinstance(value, datetime):
        moment = value
    else:
        moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if moment.tzinfo is None:
        raise ValueError('TIMESTAMP_REQUIRES_OFFSET: %s' % value)
    return moment.astimezone(timezone.utc)


def fold(events, amendments):
    """把修订折叠进事件副本：void / close / fix_ts / fix_kind。原事件不被修改。"""
    folded = {}
    for event in events:
        if event['id'] in folded:
            raise ValueError('DUPLICATE_EVENT_ID: %s' % event['id'])
        copy = dict(event)
        copy['_void'] = False
        copy['_closed_at'] = None
        folded[event['id']] = copy
    for amendment in sorted(amendments, key=lambda item: parse_ts(item['at'])):
        target = folded.get(amendment['target'])
        if target is None:
            raise KeyError('AMENDMENT_TARGET_UNKNOWN: %s' % amendment['target'])
        op = amendment['op']
        if op == 'void':
            if not str(amendment.get('why', '')).strip():
                raise ValueError('VOID_REQUIRES_WHY: %s' % amendment['target'])
            target['_void'] = True
        elif op == 'close':
            if not target.get('open'):
                raise ValueError('CLOSE_REQUIRES_OPEN: %s' % amendment['target'])
            if target['_closed_at'] is None:
                target['_closed_at'] = parse_ts(amendment['at'])
        elif op == 'fix_ts':
            target['ts'] = amendment['value']
        elif op == 'fix_kind':
            target['kind'] = amendment['value']
        else:
            raise ValueError('UNKNOWN_AMENDMENT_OP: %s' % op)
    return list(folded.values())


def half_life(event, model):
    """val 半衰期优先级：事件自带 > 种类表 > 缺省。"""
    own = event.get('half')
    if own:
        return float(own)
    kind = model.get('kinds', {}).get(event.get('kind') or '')
    if kind:
        return float(kind['half_h'])
    return float(model['default_half_h'])


def _clamp(value, bounds):
    low, high = bounds
    return max(float(low), min(float(high), value))


def project(model, events, amendments, at):
    """时刻 at 的投影：先求和再钳；ts > at 的事件不计入；void 视为从未计入。"""
    moment = parse_ts(at)
    mode = model.get('close_mode', 'from_close')
    if mode not in ('from_close', 'retroactive'):
        raise ValueError('UNKNOWN_CLOSE_MODE: %s' % mode)
    total_val = total_arl = 0.0
    held_count = 0
    rows = []
    for event in fold(events, amendments):
        start = parse_ts(event['ts'])
        if start > moment or event['_void']:
            continue
        half_v = half_life(event, model)
        half_a = float(event.get('half_arl') or model['arl_half_h'])
        age_h = (moment - start).total_seconds() / SECONDS_PER_HOUR
        closed_at = event['_closed_at']
        held = False
        if event.get('open') and closed_at is None:
            decay_v, held = 1.0, True
        elif event.get('open') and mode == 'from_close':
            if moment < closed_at:
                decay_v, held = 1.0, True
            else:
                decay_v = 0.5 ** (((moment - closed_at).total_seconds() / SECONDS_PER_HOUR) / half_v)
        else:
            decay_v = 0.5 ** (age_h / half_v)
        held_count += 1 if held else 0
        decay_a = 0.5 ** (age_h / half_a)
        contribution_v = float(event.get('val', 0.0)) * decay_v
        contribution_a = float(event.get('arl', 0.0)) * decay_a
        total_val += contribution_v
        total_arl += contribution_a
        if abs(contribution_v) >= 0.5 or abs(contribution_a) >= 0.5:
            rows.append({'event_id': event['id'], 'kind': event.get('kind') or '',
                         'val': contribution_v, 'arl': contribution_a,
                         'age_h': age_h, 'held': held, 'why': event.get('why', '')})
    state = {'val': _clamp(total_val, model['clamp']['val']),
             'arl': _clamp(total_arl, model['clamp']['arl'])}
    state['contributions'] = sorted(rows, key=lambda row: -(abs(row['val']) + abs(row['arl'])))
    state['open_count'] = held_count
    return state


_COMPARE = {
    'val_gte': lambda s, c: s['val'] >= c, 'val_gt': lambda s, c: s['val'] > c,
    'val_lte': lambda s, c: s['val'] <= c, 'val_lt': lambda s, c: s['val'] < c,
    'arl_gte': lambda s, c: s['arl'] >= c, 'arl_gt': lambda s, c: s['arl'] > c,
    'arl_lte': lambda s, c: s['arl'] <= c, 'arl_lt': lambda s, c: s['arl'] < c,
}


def _first(rules, state):
    for rule in rules:
        if all(_COMPARE[key](state, float(value)) for key, value in rule.get('if', {}).items()):
            return rule
    return None


def describe(model, state, session_class):
    """投影 → 注入用描述。public 会话不含原因、数值与私密倾向（ARCHITECTURE.md §6.5）。"""
    band = _first(model.get('bands', []), state)
    weights = {}
    for row in state['contributions']:
        weights[row['kind']] = weights.get(row['kind'], 0.0) + abs(row['val'])
    total = sum(weights.values()) or 1.0
    kinds = model.get('kinds', {})
    top = []
    for kind, weight in sorted(weights.items(), key=lambda item: -item[1])[:3]:
        spec = kinds.get(kind, {})
        visible = spec.get('tendency_visibility', 'owner_private') == 'public' or session_class == 'owner_private'
        top.append({'kind': kind, 'share': weight / total, 'tendency': spec.get('tendency') if visible else None})
    policy = []
    for slot in model.get('policy', []):
        if slot.get('visibility', 'owner_private') != 'public' and session_class != 'owner_private':
            continue
        rule = _first(slot.get('rules', []), state)
        policy.append({'slot': slot['slot'], 'text': rule['text'] if rule else slot.get('default', '')})
    description = {'label': band['label'] if band else '', 'policy': policy,
                   'tendencies': [item['tendency'] for item in top if item['tendency']]}
    if session_class == 'owner_private':
        description.update(val=state['val'], arl=state['arl'], top_kinds=top,
                           open_count=state['open_count'], contributions=state['contributions'])
    return description
