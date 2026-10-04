"""ADR-009 P5 offline cases: T5.1 rhythm, T5.5 recent phrasing, T5.7 self-development interval, T5.8 (floor part)."""
from datetime import datetime, timezone
from pathlib import Path
import re
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src')]
CASES = []


def case(fn):
    CASES.append(fn)
    return fn


class Store:
    def __init__(self, config):
        self.config = config


def policy(**values):
    return {key.replace('__', '.'): {'value': value, 'what': 'x', 'class': 'param'} for key, value in values.items()}


@case
def t5_1_rhythm_block_windows_and_public_clock():
    from asuna.rhythm import rhythm_block, in_window
    model = {'model_version': 1, 'persona': {'id': 'demo', 'display_name': 'x'}}
    late = datetime(2026, 1, 1, 23, 30, tzinfo=timezone.utc)
    p = policy(rhythm__timezone='Etc/GMT-1', rhythm__sleep_window='23:00-07:00')      # local 00:30
    block = rhythm_block(Store({}), model, p, 'owner_private', moment=late, owner_last_at='2026-01-01T22:53:00+00:00')
    assert block['in_sleep_window'] is True and block['timezone'] == 'Etc/GMT-1' and block['since_owner_message_min'] == 37
    assert in_window(datetime(2026, 1, 1, 6, 59), '23:00-07:00') and not in_window(datetime(2026, 1, 1, 7, 0), '23:00-07:00')
    assert in_window(datetime(2026, 1, 1, 13, 0), '12:00-14:00') and not in_window(datetime(2026, 1, 1, 14, 0), '12:00-14:00')
    unset = rhythm_block(Store({}), model, {}, 'owner_private', moment=late)
    assert unset['timezone'] == 'UTC' and unset['note'] == '未设置时区，以 UTC 显示' and 'since_owner_message_min' not in unset
    assert rhythm_block(Store({}), model, p, 'public', moment=late) is None
    clock = rhythm_block(Store({}), model, {**p, **policy(rhythm__public_clock=True)}, 'public', moment=late)
    assert set(clock) == {'local_time'}


@case
def t5_2_heartbeat_rest_gate_only_when_the_persona_chose_it():
    from asuna.rhythm import heartbeat_rest_gate
    model = {'model_version': 1, 'persona': {'id': 'demo', 'display_name': 'x'}, 'heartbeat': {'skip_in_sleep': True}}
    night = datetime(2026, 1, 1, 23, 30, tzinfo=timezone.utc)
    p = policy(rhythm__timezone='Etc/GMT-1', rhythm__sleep_window='23:00-07:00')
    assert heartbeat_rest_gate(model, p, {}, night) is True
    assert heartbeat_rest_gate({**model, 'heartbeat': {'skip_in_sleep': False}}, p, {}, night) is False
    assert heartbeat_rest_gate(model, p, {}, datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)) is False


@case
def t5_1_sleep_window_is_input_not_gate():
    source = (ROOT / 'src/asuna/coordinator.py').read_text(encoding='utf-8') + (ROOT / 'src/asuna/chat.py').read_text(encoding='utf-8')
    assert 'in_sleep_window' not in source, 'no program path blocks a reply on the sleep window'


@case
def t5_5_recent_phrasing_is_deterministic():
    from asuna.rhythm import recent_phrasing
    texts = ['好的，我记下了，明天见', '好的，我记下了。', '嗯，好的，我记下了', '今天天气不错', 'see you all later', 'see you all soon',
             'okay see you all']
    once, twice = recent_phrasing(texts), recent_phrasing(texts)
    assert once == twice and once[0] == '好的我记' and 'see you all' not in once
    assert all(len(once) <= 5 for _ in [0])
    assert recent_phrasing(['一句话', '另一句不同的话', '第三句也不同']) == []


@case
def t5_7_self_development_interval_has_no_hardcoded_default():
    source = (ROOT / 'src/asuna/schedule.py').read_text(encoding='utf-8')
    assert '86400' not in source and 'self_development_minutes' in source


@case
def t5_8_floor_is_sixty_seconds_from_one_constant():
    from asuna import schedule_rules
    assert schedule_rules.MIN_INTERVAL_SECONDS == 60
    schedule_rules.normalize_rule({'intent': 'x', 'every_seconds': 60})
    try:
        schedule_rules.normalize_rule({'intent': 'x', 'every_seconds': 59})
        raise AssertionError('59 accepted')
    except ValueError as exc:
        assert 'INVALID_SCHEDULE_INTERVAL' in str(exc)
    coordinator = (ROOT / 'src/asuna/coordinator.py').read_text(encoding='utf-8')
    prompt = (ROOT / 'src/asuna/resources/prompts/stage_decide.md').read_text(encoding='utf-8')
    assert "'minimum':schedule_rules.MIN_INTERVAL_SECONDS" in coordinator and not re.search(r"'minimum':\s*300", coordinator)
    assert '{{min_interval_seconds}}' in prompt and '300 秒' not in prompt


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
