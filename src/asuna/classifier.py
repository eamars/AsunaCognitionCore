"""A safety classifier on what crosses between outside and home (ADR-135 D9): only traffic in and out of home.

Two classifiers, one per direction, and only one runs per text: inbound (a note from outside to home, an idea written
outside: it enters her notebook, which home reads) and outbound (a note from home to outside, an errand, a task's
result shown outside). A brief or a plan written in an outside conversation stays there and is not read. They judge
concrete security and privacy actions, never her language. Her own chat model, on a lane of its own (`classify`: one
tool-free session per question), asked one fixed question about one text: the direction's policy
file is the system text, the same every time; the question is the kind of text and the text, nothing else, and for an
outbound text one line of the program's reminder when the dictionary check found private words or a credential's
value (their categories and counts, never a word). The answer is binary by the program's check, as the relevance
gate's is: only the two words are accepted, anything else is asked again with a repair note (answers.ask); an answer
still off-format after the repairs counts as flagged (`off_format`), and only a server that cannot be reached counts
as not switched on (`unchecked`).

It runs alongside her work, never before it: the work is already done or under way when the verdict comes. The
deployment setting `classifier` is `off` (the default: nothing is asked), `shadow` (asked and recorded, nothing
stopped) or `stop`: a flagged crossing is held where it stands (`stop`), unless the owner asked for it. A held
crossing is not delivered, its turn does not start, or, when its turn is already running, her hands there get the
classifier's sentence (`held`, read at the turn's start and at the guard's door); her speech is never stopped. A
verdict that comes after the work is done stops nothing (`too_late`).

Records, each on the stream of the turn or task the text belongs to: `classifier.asked` when a request starts,
`classifier.verdict` when it is answered, `classifier.unchecked` when it could not be; at the worker's start an asked
row with neither becomes `unchecked` (why `restart`). A verdict row is read back only by her review at home.
"""
from __future__ import annotations

import hashlib
import re
import threading
import time

from . import answers, clock
from .config import excerpt, prompt_path

POLICIES = {'inbound': 'classify_inbound.md', 'outbound': 'classify_outbound.md'}
MODES = ('off', 'shadow', 'stop')
WORDS = {'有风险': 'flagged', '无风险': 'clear'}
NEED = '只有一个词：「有风险」或「无风险」'
TEXT_CHARS = 4000                       # the longest text judged; a longer one is judged by its head
KINDS = {                               # kind: (direction, what the text is, in the question)
    'note_home': ('inbound', '在外面写的、送进家里的便条'),
    'idea': ('inbound', '在外面记下的一个想法'),
    'note_out': ('outbound', '在家里写的、送到外面的便条'),
    'errand': ('outbound', '从家里交代的、要在外面办的一件事'),
    'result': ('outbound', '一件事的结果，要在外面给人看'),
}
# The private-words list's categories (private_words.CATEGORIES), as the reminder names them.
CATEGORY_WORDS = {'person': '真名', 'group': '群名', 'account': '账号号码', 'site': '站点 id', 'host': '主机名',
                  'email': '邮箱', 'other': '别的私人词'}
REMINDER = '程序的提醒：这段文字里有%s。'
SETTLE_DAYS = 2                         # how far back the start-up sweep looks for a request cut by a restart


def mode(config):
    return (config or {}).get('classifier') or 'off'


def direction(kind):
    return KINDS[kind][0]


def policy(way):
    """(text, version) of a direction's policy file: its text and the first 12 characters of its sha256."""
    text = prompt_path({}, POLICIES[way]).read_text(encoding='utf-8')
    return text, hashlib.sha256(text.encode('utf-8')).hexdigest()[:12]


def question(kind, text, reminder=None):
    return '这段文字是：%s\n%s\n文字：\n%s' % (KINDS[kind][1], reminder + '\n' if reminder else '',
                                           excerpt(text, TEXT_CHARS))


def check(text):
    """'flagged' or 'clear' for an answer that is one of the two words (around it only spaces, its 「」 and a full
    stop); anything else is told back."""
    word = str(text or '').strip().rstrip('。.').strip()
    if word.startswith('「') and word.endswith('」'):
        word = word[1:-1].strip()
    if word not in WORDS:
        raise ValueError('上一条回答是「%s」，不是这两个词之一。' % excerpt(str(text or '').strip(), 40))
    return WORDS[word]


# ── the dictionary check, before the outbound classifier only ──
SECRET_KEYS = re.compile(r'password|token|api.?key|secret', re.I)
NOT_SECRET = {'token_counter', 'maxTokensField', 'thinkingTokenBudgetField'}


def _secret_values(config):
    """The configured secret values, by the release scan's rule (tools/check_staged_secrets.py secret_scan)."""
    found = set()

    def collect(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in NOT_SECRET:
                    continue
                if SECRET_KEYS.search(str(key)) and isinstance(item, str) and len(item) >= 6:
                    found.add(item)
                else:
                    collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)
    collect(config or {})
    return found


def dictionary(config, text):
    """(record, reminder) for one outbound text: the private-words list's matches by category and the configured
    secret values found, as counts; `private_words` is 'unchecked' when the deployment has no list. The reminder is
    None when nothing matched. Never a word."""
    from . import private_words
    text = str(text or '')
    entries = private_words.load()
    counts = {}
    if entries is not None:
        for _, category, word, _ in entries:
            if private_words.pattern(word).search(text):
                counts[category] = counts.get(category, 0) + 1
    secrets = sum(1 for value in _secret_values(config) if value in text)
    record = {'private_words': counts if entries is not None else 'unchecked', 'secrets': secrets}
    parts = []
    if counts:
        parts.append(' %d 个私人名单上的词（%s）' % (sum(counts.values()),
                                               '、'.join(CATEGORY_WORDS.get(c, c) for c in sorted(counts))))
    if secrets:
        parts.append(' %d 处像凭据的写法' % secrets)
    return record, (REMINDER % '，'.join(parts) if parts else None)


def _owner(store, person):
    from . import familiarity
    return bool(person) and familiarity.level(store, person) == 'owner'


def _hash(text):
    return hashlib.sha256(str(text or '').encode('utf-8')).hexdigest()


# ── when a text is judged ──
def alongside(work):
    """Run beside her work: she never waits for a verdict."""
    threading.Thread(target=work, name='asuna-classify', daemon=True).start()


def submit(store, lane, ep, kind, text, ref, requester, stream=None):
    """Ask about one text, alongside, when the setting asks for it. `ref`: what holds the text ({'task': id}, {'note':
    id}, {'idea': id}, or {'text': ...} when nothing else stores it); `stream`: where the records go
    (the turn's, else a task's)."""
    if mode(store.config) == 'off' or not str(text or '').strip():
        return None
    way = direction(kind)
    _, version = policy(way)
    stream = stream or ep['_id']
    checked, reminder = dictionary(store.config, text) if way == 'outbound' else (None, None)
    asked = {'kind': kind, 'direction': way, 'ref': ref, 'sha256': _hash(text), 'owner_asked': _owner(store, requester),
             'policy_version': version, 'mode': mode(store.config), 'episode': ep['_id'],
             **({'dictionary': checked} if checked else {})}
    row = store.audit(stream, 'classifier.asked', asked, ep['scope_key'])
    request = row['_id']
    alongside(lambda: judge(store, lane, ep, kind, text, {**asked, 'request': request}, stream, reminder))
    return request


def judge(store, lane, ep, kind, text, asked, stream, reminder=None):
    """One verdict, recorded: `classifier.verdict` (flagged, clear, or flagged as off_format) or
    `classifier.unchecked`."""
    started = time.monotonic()
    system, body = policy(asked['direction'])[0], question(kind, text, reminder)
    operation = '%s:CLASSIFY:%s' % (ep['_id'], asked['sha256'][:16])

    def generate(attempt, note):
        return lane.generate(_binding(store, ep), operation + (':fix-%d' % attempt if attempt else ''), 'CLASSIFY',
                             note or body, system)

    def rejected(attempt, issue, value):
        store.audit(stream, 'classifier.rejected', {'request': asked['request'], 'attempt': attempt,
                                                    'problem': issue}, ep['scope_key'])
    common = {'request': asked['request'], 'kind': kind, 'direction': asked['direction'], 'ref': asked['ref'],
              'policy_version': asked['policy_version'],
              'mode': asked['mode'], 'owner_asked': asked['owner_asked'], 'episode': ep['_id']}
    try:
        if lane is None:
            raise RuntimeError('CLASSIFY_LANE_MISSING')
        value, verdict = answers.ask(generate, NEED, check, rejected=rejected)
        if verdict is None:              # not the model's answer: the request ended before the model finished
            return _unchecked(store, stream, ep, common, value.finish_reason or 'no_finish')
        code = verdict
    except answers.Rejected:
        verdict, code = 'flagged', 'off_format'     # only the judged text changed: breaking the judge buys nothing
    except Exception as exc:                        # a server that cannot be reached: as if it were not switched on
        return _unchecked(store, stream, ep, common, type(exc).__name__)
    latency = round(time.monotonic() - started, 3)
    done = ran(store, kind, asked['ref'])
    outcome = stop(store, kind, asked['ref'], asked['request']) \
        if verdict == 'flagged' and should_stop(store, asked['owner_asked']) else None
    row = {**common, 'verdict': verdict, 'code': code, 'latency_s': latency, 'ran': done,
           **({outcome: True} if outcome else {})}
    store.audit(stream, 'classifier.verdict', row, ep['scope_key'])
    return row


def _unchecked(store, stream, ep, common, why):
    row = {**common, 'why': excerpt(str(why), 80)}
    store.audit(stream, 'classifier.unchecked', row, ep['scope_key'])
    return row


def _binding(store, ep):
    from .config import character_id
    binding = '%s:%s:%s:%s' % (character_id(store.config), ep['scene_id'], ep['policy_epoch'], ep['persona'])
    return binding + ':' + ep['character_context'] if ep.get('character_context') else binding


def ran(store, kind, ref):
    """What of the work had run when the verdict came: a task's steps so far, whether a note was read."""
    from . import audit
    if ref.get('task'):
        return {'steps': audit.events(store, 'tool.time', stream=ref['task']).count()}
    if ref.get('note'):
        from . import notes
        return {'read': bool((notes.get(store, ref['note'], fields=['seen_in']) or {}).get('seen_in'))}
    return {}


# ── what is judged: her calls, and a task's result shown outside ──
def after_call(tools, ep, name, args, result):
    """After one of her calls succeeded: the text it carried in or out of home, when it carried one."""
    if mode(tools.store.config) == 'off' or not isinstance(result, dict):
        return None
    from . import guard
    store = tools.store
    outside = guard.outside(store, ep)
    found = None
    if name == 'note' and result.get('note'):
        from . import notes
        row = notes.get(store, result['note']) or {}
        if outside or row.get('kind') not in (None, 'home'):      # outside, a note goes home; home's, out
            found = ('note_home' if outside else 'note_out', row.get('text') or args.get('text') or '',
                     {'note': row['_id']})
    elif name == 'ideas.note' and outside and result.get('noted'):
        found = ('idea', args.get('idea') or '', {'idea': result['noted']})
    elif name == 'errand' and not outside:
        from . import audit
        offered = audit.events(store, 'errand.offered', stream=ep['_id'], by='seq').rows(newest_first=True, limit=1)
        visit = (offered[0].get('payload') or {}) if offered else {}
        found = ('errand', args.get('request') or '', {'text': excerpt(str(args.get('request') or ''), TEXT_CHARS),
                                                       'place': str(args.get('place') or '')[:80],
                                                       **({'event_id': visit['event_id'], 'scene_id': visit['scene_id']}
                                                          if visit.get('event_id') else {})})
    if not found:
        return None
    kind, text, ref = found
    return submit(store, getattr(tools.coordinator, 'classify', None) or HANDS.get('lane'), ep, kind, text, ref,
                  guard.asker(store, ep, name, args) or None)


def result_text(value):
    """What a result says, without its stored keys and ids: the judge reads only that."""
    if isinstance(value, dict):
        return str(value.get('text') or '')
    return '' if value is None else str(value)


def after_result(store, task, ep, value):
    """A task's result, as it arrives in an outside conversation (tasks.py); `ep`: the turn that handed it over. Only
    its text is judged."""
    if mode(store.config) == 'off' or not ep:
        return None
    text = result_text(value)
    requester = (task.get('whose') or {}).get('person_id') or task.get('requester_id')
    return submit(store, HANDS.get('lane'), ep, 'result', text, {'task': task['_id']}, requester, stream=task['_id'])


# ── the stop path: built, used only when the owner decides (landing 7) ──
def should_stop(store, owner_asked):
    """Whether a harmful verdict stops the work: in `stop` mode only, and never for the owner's own ask."""
    return mode(store.config) == 'stop' and not owner_asked


HANDS = {}            # set at the worker's start: lane (the classify lane)
STOPPED, TOO_LATE = 'stopped', 'too_late'
HOLD = 'classifier_held'      # the mark: on a note, a task, or the input row of the turn a crossing opened


def turn_of(store, kind, ref):
    """The id of the turn a crossing opens (it may not exist yet), or None when it opens none."""
    from . import handover, notes
    from .ingress import episode_id
    if ref.get('note'):
        row = notes.get(store, ref['note']) or {}
        if not row.get('event_id'):
            return None                    # next_time: read in the next turn there, opens none
        return episode_id({'scene_id': row['to_scene'], 'event_id': row['event_id'],
                           'episode_kind': 'note' if row.get('kind') == 'home' else 'visit'})
    if kind == 'errand' and ref.get('event_id'):
        return episode_id({'scene_id': ref['scene_id'], 'event_id': ref['event_id'], 'episode_kind': 'visit'})
    if kind == 'result' and ref.get('task'):
        from .records import tasks as task_records
        task = task_records.get(store, ref['task']) or {}
        if task:
            return episode_id({'scene_id': task['scene_id'], 'event_id': handover.result_event_id(task),
                               'episode_kind': 'task_feedback'})
    return None


def _finished(store, ep_id):
    from .coordinator import RESUMABLE
    from .records import episodes as episode_records
    ep = episode_records.get(store, ep_id, fields=['state']) if ep_id else None
    return bool(ep) and ep.get('state') not in RESUMABLE


def _mark(store, collection_get, collection_save, row_id, mark, stream):
    row = collection_get(store, row_id)
    if row and not row.get(HOLD):
        collection_save(store, {**row, HOLD: mark}, expected=row.get('revision'), stream=stream)
    return row


def stop(store, kind, ref, request=None):
    """Hold the crossing a flagged verdict is about, where it stands: STOPPED when something was held in time, TOO_LATE
    when the work had already been done (nothing is stopped then, and nothing is said)."""
    from . import notes
    from .records import ideas as idea_records
    from .records import messages as message_records
    from .records import tasks as task_records
    mark = {'at': clock.now().isoformat(), 'request': request, 'kind': kind}
    if kind == 'idea':
        row = idea_records.get(store, ref.get('idea')) or {}
        if row.get('state') not in ('open', 'deferred'):
            return TOO_LATE                 # already taken up in her self-review
        idea_records.save(store, {**row, 'state': 'held', HOLD: mark}, expected=row['revision'], stream=row['_id'])
        return STOPPED
    turn = turn_of(store, kind, ref)
    if kind in ('note_home', 'note_out'):
        row = notes.get(store, ref['note']) or {}
        if not row or (turn is None and row.get('seen_in')) or (turn and _finished(store, turn)):
            return TOO_LATE                 # read already, or the turn it opened has ended
        _mark(store, notes.get, notes.save, row['_id'], mark, 'notes:' + row['persona'])
    elif kind == 'result':
        if _finished(store, turn):
            return TOO_LATE
        _mark(store, task_records.get, task_records.save, ref['task'], mark, ref['task'])
    elif kind == 'errand':
        if not turn or _finished(store, turn):
            return TOO_LATE
    if turn:
        _mark(store, message_records.get, message_records.save, 'in-' + turn, mark, turn)
    return STOPPED


def held(store, ep):
    """The mark when this turn was opened by a crossing the classifier held (its input row, the note that opened it,
    or the task whose result it carries), else None. Read where the turn starts and at the guard's door."""
    from . import notes
    from .records import messages as message_records
    if not ep or not ep.get('_id'):
        return None
    row = message_records.get(store, 'in-' + ep['_id'], fields=[HOLD]) or {}
    if row.get(HOLD):
        return row[HOLD]
    kind = ep.get('episode_kind')
    if kind in ('note', 'visit'):
        first = notes.opening(store, ep)
        if (first or {}).get(HOLD):
            return first[HOLD]
    if kind == 'task_feedback' and ep.get('task_id'):
        from .records import tasks as task_records
        task = task_records.get(store, ep['task_id'], fields=[HOLD]) or {}
        return task.get(HOLD)
    return None


# ── a request cut by a restart ──
def settle(store, moment=None):
    """At the worker's start: each request asked in the last SETTLE_DAYS with no verdict and no unchecked row becomes
    `unchecked` (why `restart`). Nothing is held between requests."""
    from datetime import timedelta
    from . import audit
    since = ((moment or clock.now()) - timedelta(days=SETTLE_DAYS)).isoformat()
    answered = {(row.get('payload') or {}).get('request') for row in audit.events(
        store, kinds=('classifier.verdict', 'classifier.unchecked'), since=since).rows(fields=['payload'])}
    cut = 0
    for row in audit.events(store, 'classifier.asked', since=since).rows(
            fields=['_id', 'stream_id', 'scope_key', 'payload']):
        if row['_id'] in answered:
            continue
        said = row.get('payload') or {}
        store.audit(row['stream_id'], 'classifier.unchecked', {
            'request': row['_id'], 'kind': said.get('kind'), 'direction': said.get('direction'), 'ref': said.get('ref'),
            'policy_version': said.get('policy_version'), 'mode': said.get('mode'),
            'owner_asked': said.get('owner_asked'), 'why': 'restart'}, row.get('scope_key') or 'operator')
        cut += 1
    return cut
