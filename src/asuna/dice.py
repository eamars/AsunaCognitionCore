"""The heartbeat's die (ADR-058): before a heartbeat reaches her, the program rolls one of four outcomes.

- nothing: the beat does not reach her (no model call), unless something only a heartbeat shows is waiting for her:
  someone she is waiting for in a group, a line of her sister's not answering her, a group where someone called her
  since she last spoke there. Then it reaches her with the roll said, and those things in it.
- interesting: the heartbeat as it always was.
- self_development: the beat runs as a self-improvement turn (her notebook, development tools), as a night stage does.
- self_evaluation: the heartbeat with the raw readings of her own day (self_review.py).

Two weight tables, awake and asleep, chosen by her declared sleep window; both are her policy keys (`set_policy`),
four whole numbers in this order: nothing / interesting / self development / self evaluation. A weight of 0 removes
an outcome. The roll is seeded by the beat's occurrence, so a record names its outcome and can be replayed. The roll
is shown to her as one line of text: hers to follow, change or ignore; nothing asks for an answer.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

OUTCOMES = ('nothing', 'interesting', 'self_development', 'self_evaluation')
WORDS = {'nothing': '歇着', 'interesting': '做点有意思的', 'self_development': '自我开发', 'self_evaluation': '自我评估'}
DEFAULTS = {'awake': '40/35/10/15', 'asleep': '70/0/20/10'}        # her review, 2026-10-12: run a week, then tune
KEYS = {'awake': 'heartbeat.dice_awake', 'asleep': 'heartbeat.dice_asleep'}
PERIOD_WORDS = {'awake': '醒着', 'asleep': '睡着'}
SHAPE = re.compile(r'\s*(\d{1,3})\s*/\s*(\d{1,3})\s*/\s*(\d{1,3})\s*/\s*(\d{1,3})\s*')
DEV_TEXT = '这是一次内部自我开发机会，不是用户消息或新授权；无需公开回复。'
HINTS = {
    'nothing': '这一拍本来不叫你；叫你是因为有只在心跳里看得到的事在等你（见下面的资料）。',
    'interesting': '想说一句、出门看看、写点什么，都算。',
    'self_development': '翻翻想法本、接着做手上的改进，或者交一件给行动脑。',
    'self_evaluation': 'self_review_from_program 是你今天的原始读数，带出处，没替你总结。',
}


def parse(value):
    """'40/35/10/15' -> {outcome: weight}; ValueError(words) when it is not four whole numbers with a positive sum."""
    match = SHAPE.fullmatch(str(value or ''))
    if not match:
        raise ValueError('分布要写成四个整数，用 / 隔开，依次是：歇着/有趣/自我开发/自我评估（比如 40/35/10/15）。')
    weights = dict(zip(OUTCOMES, (int(n) for n in match.groups())))
    if not sum(weights.values()):
        raise ValueError('四个数不能全是 0。')
    return weights


def table(model, policy, config, moment=None):
    """(period, weights) for now: asleep inside her declared sleep window, awake otherwise."""
    from zoneinfo import ZoneInfo
    from .persona_model import effective, timezone as persona_timezone
    from .rhythm import in_window
    moment = moment or datetime.now(timezone.utc)
    zone, _ = persona_timezone(model, policy, config)
    try:
        local = moment.astimezone(ZoneInfo(zone))
        asleep = in_window(local, effective(model, 'rhythm.sleep_window', policy))
    except Exception:                            # no zone or no window: she is awake
        asleep = False
    period = 'asleep' if asleep else 'awake'
    try:
        weights = parse(effective(model, KEYS[period], policy) or DEFAULTS[period])
    except ValueError:
        weights = parse(DEFAULTS[period])
    return period, weights


def roll(occurrence, weights):
    """The outcome for this beat: the occurrence seeds it, so the same beat always rolls the same."""
    total = sum(weights.values())
    point = int(hashlib.sha256(str(occurrence).encode()).hexdigest()[:12], 16) % total
    for outcome in OUTCOMES:
        if point < weights[outcome]:
            return outcome
        point -= weights[outcome]
    return OUTCOMES[-1]


def line(outcome, period, weights):
    """The one line her heartbeat opens with."""
    shown = '、'.join('%s %d' % (WORDS[o], weights[o]) for o in OUTCOMES)
    return ('这一拍掷到：%s（%s的分布：%s）。%s照做、换一件、或者不理，都行。'
            % (WORDS[outcome], PERIOD_WORDS[period], shown, HINTS[outcome]))


def waiting(store, persona, moment, zone):
    """Whether something only a heartbeat shows is waiting for her (her review: a 'nothing' beat must not hide it)."""
    from . import lines, places, waiting as _waiting
    groups = [scene_id for scene_id, _, _ in places.groups(store.config)]
    if _waiting.pending(store, groups, moment, persona):
        return True
    if lines.asides(store, zone):
        return True
    for scene_id in groups:
        scene = store.db.scenes.find_one({'_id': scene_id})
        if scene and places.room(store, scene, moment).get('called'):
            return True
    return False
