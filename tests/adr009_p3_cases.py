"""ADR-009 P3 offline cases: T3.1 parity with the reference projection, T3.2 close modes and guards, T3.8 rule tables."""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import random
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src')]
EXAMPLES = ROOT / 'docs/development_plans/ADR-009-persona_residency/examples'
CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def reference():
    spec = importlib.util.spec_from_file_location('affect_reference', EXAMPLES / 'affect_reference.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def synthetic(seed=7):
    """≥30 events covering kind half-lives, own half-lives, the default, open/closed, void, clamp and offsets."""
    rng = random.Random(seed)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    kinds = ['joy', 'surprise', 'pride', 'calm', 'unknown-kind', '']
    offsets = ['+00:00', '+02:00', '-05:00', '+09:30', 'Z']
    events = []
    for i in range(36):
        moment = base + timedelta(hours=rng.uniform(0, 96))
        offset = offsets[i % len(offsets)]
        if offset == 'Z':
            ts = moment.strftime('%Y-%m-%dT%H:%M:%SZ')
        else:
            sign, hh, mm = (1 if offset[0] == '+' else -1), int(offset[1:3]), int(offset[4:6])
            local = moment.astimezone(timezone(sign * timedelta(hours=hh, minutes=mm)))
            ts = local.isoformat(timespec='seconds')
        events.append({'id': f'ev-{i}', 'ts': ts, 'ref': f'ref-{i}', 'why': f'合成 {i}', 'kind': kinds[i % len(kinds)],
                       'val': rng.uniform(-60, 60), 'arl': rng.uniform(-60, 60), 'open': i % 7 == 0,
                       'half': [None, 0, rng.uniform(0.5, 30)][i % 3], 'half_arl': [None, rng.uniform(0.5, 10)][i % 2]})
    amendments = [{'target': 'ev-0', 'op': 'close', 'at': '2026-01-03T00:00:00+00:00', 'why': '办完'},
                  {'target': 'ev-14', 'op': 'close', 'at': '2026-01-02T12:00:00-03:00', 'why': '办完'},
                  {'target': 'ev-5', 'op': 'void', 'at': '2026-01-02T00:00:00Z', 'why': '前提不成立'},
                  {'target': 'ev-6', 'op': 'fix_kind', 'value': 'joy', 'at': '2026-01-02T01:00:00Z', 'why': '改种类'},
                  {'target': 'ev-8', 'op': 'fix_ts', 'value': '2026-01-01T03:00:00+01:00', 'at': '2026-01-02T02:00:00Z', 'why': '改时间'}]
    return events, amendments


def model(close_mode):
    value = json.loads((EXAMPLES / 'persona-model.example.json').read_text(encoding='utf-8'))['affect']
    value['close_mode'] = close_mode
    value['clamp'] = {'val': [-80, 80], 'arl': [-60, 60]}            # the sums do hit the clamp
    return value


@case
def t3_1_projection_matches_reference_pointwise():
    from asuna import affect
    ref = reference()
    golden = json.loads((EXAMPLES / 'affect-events.example.json').read_text(encoding='utf-8'))
    for row in golden['expected']:
        base = json.loads((EXAMPLES / 'persona-model.example.json').read_text(encoding='utf-8'))['affect']  # golden['model'] points here
        state = affect.project({**base, 'close_mode': row['close_mode']}, golden['events'], golden['amendments'], row['at'])
        assert abs(state['val'] - row['val']) < 1e-6 and abs(state['arl'] - row['arl']) < 1e-6, row
        assert state['open_count'] == row['open_count'], row
    events, amendments = synthetic()
    start = datetime(2025, 12, 31, 12, tzinfo=timezone.utc)
    checked = 0
    for mode in ('from_close', 'retroactive'):
        for step in range(60):
            at = (start + timedelta(hours=step * 2.3)).isoformat()
            mine = affect.project(model(mode), events, amendments, at)
            theirs = ref.project(model(mode), events, amendments, at)
            assert abs(mine['val'] - theirs['val']) < 1e-6 and abs(mine['arl'] - theirs['arl']) < 1e-6, (mode, at)
            assert mine['open_count'] == theirs['open_count']
            assert [r['event_id'] for r in mine['contributions']] == [r['event_id'] for r in theirs['contributions']]
            for cls in ('owner_private', 'public'):
                assert affect.describe(model(mode), mine, cls) == ref.describe(model(mode), theirs, cls)
            checked += 1
    assert checked >= 100


@case
def t3_2_close_modes_future_events_negative_half_and_floor():
    from asuna import affect
    m = {'default_half_h': 10, 'arl_half_h': 5, 'clamp': {'val': [-100, 100], 'arl': [-100, 100]}, 'kinds': {}}
    held = [{'id': 'a', 'ts': '2026-01-01T00:00:00Z', 'val': 40, 'arl': 0, 'open': True}]
    closed = [{'target': 'a', 'op': 'close', 'at': '2026-01-01T10:00:00Z', 'why': '办完'}]
    at = '2026-01-01T20:00:00Z'
    from_close = affect.project({**m, 'close_mode': 'from_close'}, held, closed, at)['val']
    retro = affect.project({**m, 'close_mode': 'retroactive'}, held, closed, at)['val']
    assert abs(from_close - 20.0) < 1e-9 and abs(retro - 10.0) < 1e-9, (from_close, retro)   # 10 h vs 20 h of decay
    assert affect.project(m, held, [], at)['val'] == 40 and affect.project(m, held, [], at)['open_count'] == 1
    future = [{'id': 'f', 'ts': '2026-01-02T00:00:00Z', 'val': 50, 'arl': 50}]
    assert affect.project(m, future, [], at)['val'] == 0
    try:
        affect.project(m, [{'id': 'n', 'ts': '2026-01-01T00:00:00Z', 'val': 1, 'arl': 1, 'half': -2}], [], at)
        raise AssertionError('negative half-life accepted')
    except ValueError as exc:
        assert 'HALF_LIFE_MUST_BE_POSITIVE' in str(exc)
    two = [{'id': 'x', 'ts': '2026-01-01T19:00:00Z', 'val': 30, 'arl': 0, 'kind': 'joy'},
           {'id': 'y', 'ts': '2026-01-01T19:00:00Z', 'val': 1, 'arl': 0, 'kind': 'calm'}]
    kinds = {'joy': {'half_h': 10, 'tendency': 't1', 'tendency_visibility': 'public'},
             'calm': {'half_h': 10, 'tendency': 't2', 'tendency_visibility': 'public'}}
    state = affect.project({**m, 'kinds': kinds}, two, [], at)
    listed = [k['kind'] for k in affect.describe({**m, 'kinds': kinds, 'kind_floor': 5}, state, 'owner_private')['top_kinds']]
    assert listed == ['joy'], listed
    try:
        affect.parse_ts('2026-01-01T00:00:00')
        raise AssertionError('naive timestamp accepted')
    except ValueError as exc:
        assert 'TIMESTAMP_REQUIRES_OFFSET' in str(exc)


@case
def t3_8_rule_tables_first_match_at_boundaries():
    from asuna.affect import first_rule, describe
    bands = [{'if': {'val_gte': 25, 'arl_gte': 55}, 'label': 'A'}, {'if': {'val_gte': 25}, 'label': 'B'},
             {'if': {'val_gt': -10}, 'label': 'C'}, {'label': 'D'}]
    for val, arl, label in ((25, 55, 'A'), (25, 54.999, 'B'), (24.999, 99, 'C'), (-10, 0, 'D'), (-9.999, 0, 'C')):
        assert first_rule(bands, {'val': val, 'arl': arl})['label'] == label, (val, arl)
    policy = [{'slot': '话量', 'visibility': 'public', 'default': '常规', 'rules': [{'if': {'val_lte': -10}, 'text': '少说'}]},
              {'slot': '私密', 'visibility': 'owner_private', 'default': '先不提', 'rules': [{'if': {'arl_lt': 25}, 'text': '可以提'}]}]
    state = {'val': -10, 'arl': 25, 'contributions': [], 'open_count': 0}
    public = describe({'bands': bands, 'policy': policy}, state, 'public')
    private = describe({'bands': bands, 'policy': policy}, state, 'owner_private')
    assert public == {'label': 'D', 'policy': [{'slot': '话量', 'text': '少说'}], 'tendencies': []}, public
    assert [p['text'] for p in private['policy']] == ['少说', '先不提'] and 'val' in private and 'val' not in public


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
