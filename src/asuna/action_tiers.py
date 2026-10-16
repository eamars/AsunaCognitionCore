"""ADR-075: her action brain in two tiers, 低 and 高, told by what each can do, never by model, provider, price or how
it is run. 高 exists only when the owner configured a route for it (`routes.actionHigh`); then `delegate` takes a tier
(低 when left out) and, for 高, a `why`. A 高 job runs on that route; a hard failure there (an error end the plugin
sees, index.js) falls to 低 for the rest of the job and never rises again; a failure of the line itself makes 高
rest, so later 高 jobs go 低 at once. She is told what happened in capability words only.

The task keeps `tier`: {chosen, why, ran, fell: {reason, mid_run, at}}. REST is the plugin's word on 高 resting, held
here so a dispatch can say it: {reason, until (ISO) or None}."""
from datetime import datetime, timezone

LOW, HIGH = '低', '高'
WHY_CHARS = 80
LINES = {LOW: '低：派之前说得出路线、走错重跑一趟就行——查自己的记录、拉网页、画一张图、把手上的材料整理成一段、'
              '路线清楚的改文件和跑命令',
         HIGH: '高：路线可能中途变、要中途改判断，或走错就得从头来；选高要写 why'}
TIER_FIELD = {'type': 'string', 'enum': [LOW, HIGH],
              'description': '交给哪一档，不写就是低。' + LINES[LOW] + '。' + LINES[HIGH] + '。'}
# Why a 高 job ran at 低, in capability words (her condition: each asks a different next step of her).
REASONS = {'refused': '这件高档没接', 'down': '高档这会儿用不了', 'busy': '高档忙', 'owner': '高档这会儿用不了'}
MID_RUN = '做到一半落到低档接着做，会慢一些；结果是两档接力做的'
NO_CLOCK = '要等主人处理，没有钟点'

CONFIGURED = False          # set at the worker's start from the routes (native_worker.initialize)
REST = None                 # {'reason': 'down' | 'busy' | 'owner', 'until': ISO or None}, from the plugin


def offered():
    return CONFIGURED


def resting(moment=None):
    """The current rest, or None (a rest past its clock is over)."""
    if not REST:
        return None
    until = REST.get('until')
    if until and datetime.fromisoformat(until) <= (moment or datetime.now(timezone.utc)):
        return None
    return REST


def clock_words(rest, zone):
    """When 高 is tried again: a retry clock, never a promise; no clock when it waits on the owner."""
    if not rest.get('until'):
        return NO_CLOCK
    from .local_time import face
    return '最早 %s 再试' % face(datetime.fromisoformat(rest['until']), zone['tz'])


def chosen(args):
    """(tier, why) from her delegate call; raises ValueError with the words to send back."""
    tier = (args or {}).get('tier') or LOW
    if tier not in (LOW, HIGH):
        raise ValueError('tier 写 低 或 高（不写就是低）。%s。%s。' % (LINES[LOW], LINES[HIGH]))
    why = str((args or {}).get('why') or '').strip()
    if tier == HIGH and not why:
        raise ValueError('选高要写 why：为什么这件要高档（%d 字以内）。%s。%s。' % (WHY_CHARS, LINES[LOW], LINES[HIGH]))
    if len(why) > WHY_CHARS:
        raise ValueError('why 最多 %d 字，这次 %d 字；说清为什么要高档就够了。' % (WHY_CHARS, len(why)))
    return tier, (why if tier == HIGH else None)


def at_dispatch(tier, why, zone, moment=None):
    """The task's tier record and the words her dispatch returns (None when there is nothing to say)."""
    record = {'chosen': tier, 'ran': tier, **({'why': why} if why else {})}
    rest = resting(moment) if tier == HIGH else None
    if not rest:
        return record, (None if tier == LOW else '交给高档')
    record.update(ran=LOW, fell={'reason': rest['reason'], 'mid_run': False, 'at': _now(moment)})
    return record, '%s，%s；这件按低档做' % (REASONS[rest['reason']], clock_words(rest, zone))


def carried(previous, fresh, zone, moment=None):
    """A continuation's tier: the same context keeps the tier it ran at (a job that fell does not rise again); a fresh
    context is a new start at the tier she chose."""
    if not previous:
        return None, None
    if not fresh:
        return {k: previous[k] for k in ('chosen', 'why', 'ran', 'fell') if k in previous}, None
    return at_dispatch(previous['chosen'], previous.get('why'), zone, moment)


def words(tier):
    """The tier line of a task in task_state_from_program: what she chose, what ran it, and why they differ."""
    if not tier:
        return None
    if tier['ran'] == tier['chosen']:
        return tier['chosen']
    fell = tier.get('fell') or {}
    reason = REASONS.get(fell.get('reason'), REASONS['refused'])
    return '选了高，跑的是低：%s%s' % (reason, '；' + MID_RUN if fell.get('mid_run') else '')


def weekly(tasks):
    """The week's tiers for her tooling review: counts only, and each 高 reason beside what happened (her condition:
    a reason cannot grade itself)."""
    tiered = [task for task in tasks if task.get('tier')]
    if not tiered:
        return None
    count = lambda key: {t: sum(1 for task in tiered if task['tier'].get(key) == t) for t in (LOW, HIGH)}
    fell = [task['tier']['fell'] for task in tiered if task['tier'].get('fell')]
    out = {'chosen': count('chosen'), 'ran': count('ran'),
           'fell': {REASONS[r] if r != 'owner' else REASONS[r] + '（等主人）': sum(1 for f in fell if f.get('reason') == r)
                    for r in REASONS if any(f.get('reason') == r for f in fell)},
           'fell_mid_run': sum(1 for f in fell if f.get('mid_run'))}
    out['why_beside'] = [{'why': task['tier']['why'], 'ran': task['tier']['ran'], 'steps': task.get('tool_steps', 0),
                          'state': task.get('state')}
                         for task in tiered if task['tier'].get('chosen') == HIGH and task['tier'].get('why')][:6]
    return out


def _now(moment=None):
    return (moment or datetime.now(timezone.utc)).isoformat()
