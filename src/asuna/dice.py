"""The heartbeat's die (ADR-058): before a heartbeat reaches her, the program rolls one of seven outcomes.

- nothing: the beat does not reach her (no model call), unless something only a heartbeat shows would be lost by
  waiting an hour: someone she waits for in a group (her waiting list ends after an hour), or a peer line whose
  unseen asides already fill the list she is shown (one more would push the oldest out of her view). What stays
  until she answers (fewer asides; a group where someone called her, which woke her by its own path) is shown at
  the next beat that reaches her: late, never lost. Then it reaches her with the roll said, and those things in it.
- interesting: the heartbeat as it always was.
- self_development: the beat runs as a self-improvement turn (her notebook, development tools), as a night stage does.
- self_evaluation: the heartbeat with the raw readings of her own day (self_review.py).
- review_dice: the heartbeat with the raw readings of every roll since her last review and her two tables
  (dice_review_from_program), so the weights are something she can check, not only set.
- reach_out: the heartbeat, suggesting a word on one of her home lines (note), whom is hers to choose; counts as 0
  where she has no line.
- idle: the beat reaches her with nothing but its line and hint (her seventh face, 2026-10-14): no readings,
  no task, no output asked of it.

Two weight tables, awake and asleep, chosen by her declared sleep window (the only thing the window does to a
heartbeat: a fully quiet night is 歇着 100). Both are her policy keys (`set_policy`), written with names
(歇着 40、有趣 31、…); a name left out weighs 0, and set_policy shows the whole table it stored. The roll is seeded
by the beat's occurrence, so a record names its outcome and can be replayed. The roll is shown to her as one line
of text: hers to follow, change or ignore; nothing asks for an answer.
"""
from __future__ import annotations

import collections
import hashlib
import re
from datetime import datetime, timedelta, timezone

OUTCOMES = ('nothing', 'interesting', 'self_development', 'self_evaluation', 'review_dice', 'reach_out', 'idle')
NAMES = {'nothing': '歇着', 'interesting': '有趣', 'self_development': '自我开发', 'self_evaluation': '自我评估',
         'review_dice': '复盘', 'reach_out': '找人', 'idle': '待着'}
BY_NAME = {name: outcome for outcome, name in NAMES.items()}
# Her review, 2026-10-12: run them as they are; the review outcome brings the readings to retune from.
DEFAULTS = {'awake': '歇着 40、有趣 31、自我开发 10、自我评估 12、复盘 2、找人 5、待着 0',
            'asleep': '歇着 66、自我开发 20、自我评估 8、复盘 2、找人 4、待着 0'}
KEYS = {'awake': 'heartbeat.dice_awake', 'asleep': 'heartbeat.dice_asleep'}
PERIOD_WORDS = {'awake': '醒着', 'asleep': '睡着'}
ITEM = re.compile(r'(?P<name>[^\d\s]+?)\s*(?P<weight>\d{1,3})')
SEPARATORS = re.compile(r'[、,，;；/\n]+')
# Why a 'nothing' beat still reached her (dice review): what one more hour would have lost.
LOST_WORDS = {'waiting_groups': '有 %d 个群里有人在等你回，再等一小时就掉出你的等待单', 'asides_full': '旁白单满了，再来一条最早的就看不见'}
DEV_TEXT = '这是一次内部自我开发机会，不是有人跟你说话，也不带新授权；无需公开回复。'
HINTS = {
    'nothing': '这一拍本来不叫你；叫你是因为有只在心跳里看得到、再等一小时就会丢的事（见下面的资料）。',
    'interesting': '想说一句、出门看看、写点什么，都算。',
    'self_development': '翻翻想法本、接着做手上的改进，或者交一件给行动脑。',
    'self_evaluation': 'self_review_from_program 是你今天的原始读数，带出处，没替你总结。',
    'review_dice': 'dice_review_from_program 是上次复盘以来每一掷的原始读数和你现在的两张表；要调就 set_policy。',
    'reach_out': '从家里写便条（note）到你的一条线（%s），找谁、说不说，由你。',
}
# The idle beat's hint is the persona model's `heartbeat.idle_hint` (a persona words it; the core default is neutral).
REVIEW_ROLLS = 60
REVIEW_DAYS = 14
QUIET_CHARS = 80
REVIEW_NOTE = ('这是上次复盘以来每一掷的原始读数（最多最近 60 掷、14 天），没替你总结：at 几点，roll 掷到什么，'
               'reached 叫没叫你，mood 那拍你的心情档位，tools 那拍用了哪些工具几次，said 那拍说了几句，quiet 你安静时写的理由；'
               'counts 是各面掷到几次；tables 是你现在两张表。要调就 set_policy heartbeat.dice_awake 或 '
               'heartbeat.dice_asleep；想要一种新的拍，跟开发者说。')


def _problem(detail):
    return ValueError('%s分布写成「名字 权重」，用顿号隔开，比如 %s；能写的名字：%s；漏写的算 0。'
                      % (detail, DEFAULTS['awake'], '、'.join(NAMES.values())))


def parse(value):
    """'歇着 40、有趣 31' -> {outcome: weight} over all outcomes (a name left out weighs 0); ValueError(words) for an
    unknown or repeated name, a part without a whole number, or a table that is all 0."""
    parts = [part.strip() for part in SEPARATORS.split(str(value or '')) if part.strip()]
    if not parts:
        raise _problem('')
    weights = dict.fromkeys(OUTCOMES, 0)
    seen = set()
    for part in parts:
        match = ITEM.fullmatch(part)
        if not match:
            raise _problem('「%s」不是「名字 权重」。' % part[:20])
        outcome = BY_NAME.get(match.group('name').strip())
        if not outcome:
            raise _problem('没有「%s」这一面。' % match.group('name').strip()[:20])
        if outcome in seen:
            raise _problem('「%s」写了两次。' % NAMES[outcome])
        seen.add(outcome)
        weights[outcome] = int(match.group('weight'))
    if not sum(weights.values()):
        raise _problem('权重不能全是 0。')
    return weights


def words(weights):
    """The whole table as she reads it, every outcome named, zeros included."""
    return '、'.join('%s %d' % (NAMES[o], weights.get(o, 0)) for o in OUTCOMES)


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
    return period, weights_for(model, policy, period)


def weights_for(model, policy, period):
    from .persona_model import effective
    try:
        return parse(effective(model, KEYS[period], policy) or DEFAULTS[period])
    except ValueError:
        return parse(DEFAULTS[period])


def roll(occurrence, weights):
    """The outcome for this beat: the occurrence seeds it, so the same beat always rolls the same."""
    total = sum(weights.values())
    point = int(hashlib.sha256(str(occurrence).encode()).hexdigest()[:12], 16) % total
    for outcome in OUTCOMES:
        if point < weights[outcome]:
            return outcome
        point -= weights[outcome]
    return OUTCOMES[-1]


def line(outcome, period, weights, homes=(), model=None):
    """The one line her heartbeat opens with; `homes` names her lines for a reach_out, `model` (the persona model)
    words the idle beat."""
    from .persona_model import effective
    hint = (HINTS[outcome] % '、'.join(homes) if outcome == 'reach_out'
            else effective(model or {}, 'heartbeat.idle_hint') if outcome == 'idle' else HINTS[outcome])
    return ('这一拍掷到：%s（%s的分布：%s）。%s照做、换一件、或者不理，都行。'
            % (NAMES[outcome], PERIOD_WORDS[period], words(weights), hint))


def waiting(store, persona, moment):
    """Whether a 'nothing' beat would lose something only a heartbeat shows (her rule: lost wakes her, late does not)."""
    return bool(losses(store, persona, moment))


def losses(store, persona, moment):
    """What a 'nothing' beat would lose, by kind, so the roll's record says why it still reached her:
    {'waiting_groups': n} for groups where someone she waits for would drop off her list, {'asides_full': True}."""
    from . import lines, places, waiting as _waiting
    groups = [scene_id for scene_id, _, _ in places.groups(store.config)]
    pending = _waiting.pending(store, groups, moment, persona)
    out = {}
    if pending:
        out['waiting_groups'] = len({row['scene_id'] for row in pending})
    if lines.asides_full(store):
        out['asides_full'] = True
    return out


def review(store, persona, occurrence, moment=None):
    """dice_review_from_program: every roll since her last review (not this one), with what each beat did."""
    from .config import excerpt
    from .render import model_and_policy
    moment = moment or datetime.now(timezone.utc)
    floor = (moment - timedelta(days=REVIEW_DAYS)).isoformat()
    rolled = {'type': 'presence.rolled', 'occurred_at': {'$gte': floor}, 'payload.occurrence': {'$ne': occurrence}}
    last = store.db.audit_events.find_one({**rolled, 'payload.outcome': 'review_dice', 'payload.reaches': True},
                                          {'occurred_at': 1}, sort=[('occurred_at', -1)])
    if last:
        rolled['occurred_at'] = {'$gt': last['occurred_at']}
    rows = list(store.db.audit_events.find(rolled, {'occurred_at': 1, 'payload': 1})
                .sort('occurred_at', -1).limit(REVIEW_ROLLS))[::-1]
    out = []
    from .affect import AffectLedger, first_rule, project
    model, policy = model_and_policy(store, persona)
    ledger = AffectLedger(store, persona, model, policy)
    felt = (ledger.events(), ledger.amendments()) if ledger.enabled else None      # read once for every roll
    for row in rows:
        p = row['payload']
        item = {'at': row['occurred_at'], 'roll': NAMES.get(p.get('outcome'), p.get('outcome')),
                'period': PERIOD_WORDS.get(p.get('period'), p.get('period')),
                'reached': '叫了你' if p.get('reaches') else '没叫你'}
        if ledger.enabled:
            # ADR-086 D7: the band at that beat, so she can see her own mood-behaviour pairs when she retunes.
            band = first_rule(ledger.model.get('bands', []), project(ledger.model, felt[0], felt[1], row['occurred_at'])) or {}
            item['mood'] = band.get('label') or '平静'
        lost = p.get('lost') or {}
        if lost:                               # a 'nothing' beat that still reached her, and why
            item['why'] = '、'.join(([LOST_WORDS['waiting_groups'] % lost['waiting_groups']] if lost.get('waiting_groups') else [])
                                   + ([LOST_WORDS['asides_full']] if lost.get('asides_full') else []))
        if p.get('reaches'):
            source = ('self-development:dice:' if p.get('outcome') == 'self_development' else 'presence:') + p['occurrence']
            ep = store.db.episodes.find_one({'source_event_id': source}, {'silent_reason': 1})
            if not ep:
                item['reached'] = '叫了你，那拍还没跑或没留下记录'
            else:
                tools = collections.Counter(a['payload'].get('tool') for a in store.db.audit_events.find(
                    {'type': 'role_tool', 'stream_id': ep['_id']}, {'payload.tool': 1}))
                item['tools'] = dict(tools)
                from .records import messages as message_records
                item['said'] = message_records.turn_parts(store, ep['_id'], outbound=True).count()
                if ep.get('silent_reason'):
                    item['quiet'] = excerpt(' '.join(str(ep['silent_reason']).split()), QUIET_CHARS)
        out.append(item)
    return {'rolls': out, 'counts': dict(collections.Counter(item['roll'] for item in out)),
            'tables': {PERIOD_WORDS[period]: words(weights_for(model, policy, period)) for period in KEYS},
            **({'since_at': last['occurred_at']} if last else {}), 'note': REVIEW_NOTE}
