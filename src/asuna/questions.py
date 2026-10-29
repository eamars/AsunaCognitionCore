"""Her questions (ADR-061): one question, or a problem report, to one or more of her home places or the action brain,
each place with a patience; what came back is kept with the question, never judged.

A question is asked with `ask` from a home turn (role_tools). Its places:
- this conversation: her reply in the asking turn is the question;
- another home place (the local chat, the owner's private chat, an agent or peer line; notes.targets): a trusted note
  carrying the question wakes it (schedule.note), and her line in the turn that note opened is the question there;
- the action brain: a `delegate` whose brief is the question; its report is the answer.

Answers join by the program (`refresh`): in a home place the first line there after her question line that is not
an internal event or a program notice, or a line that names the question (`raw.asuna_answer`, kept for home kinds
only: `tools/agent_line.py send --answers <id>`); for the action brain its task's report once the task is done.
A place whose patience ran out unanswered lapses; the turn the note opened ending with no line of hers is 没问.
The program closes a question once every place is settled: a home place or the action brain when it answered, a group
when its patience is over (more of the group may still answer until then), any place when it lapsed or was never
asked; a place without patience that never answers lets it close a week after it was asked. Its took says in words
how it ended (CLOSED_TOOK), each conversation it was asked in or shown at home is told that once, and she replaces
that took with her own by closing it herself (RETAKEN).

She reads it all in words (`block`: questions_from_program at home; `read`), times as `_at` fields. Each move is one
audit line without text (question.asked / answered / lapsed / closed). Words come from the versioned tables below.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from . import clock
from .config import excerpt
from .evidence import canonical, sha
from .state import Conflict, now
from . import visibility
from .records import scenes as scene_records
from .records import messages as message_records
from .records import episodes as episode_records
from .records import tasks as task_records
from .records.view import ANY, View, fenced, is_text, pinned
from .store.words import AddToSet, AnyOf, Each, HoldsNone, Not, Range

TABLES_VERSION = 1
# Patience words -> minutes (None: until it is answered, for a report).
PATIENCE = {'一会儿': 10, '一小时': 60, '半天': 720, '一天': 1440, '回了为止': None}
DEFAULT_PATIENCE = '一小时'          # her home places answered within an hour (ADR-061, Measured)
ACTION = '行动脑'
HERE = ('这里', 'here')
QUESTION_CHARS = 800
TOOK_CHARS = 500
PLACES_MAX = 3
EXCERPT = 40
ANSWER_CHARS = 2000
UNANSWERED = timedelta(days=7)      # a question without patience, never answered: closed by the program
SHOWN = 8
READ_DAYS, READ_SHOWN = 30, 10
SETTLED = ('not_asked', 'not_sent', 'not_done')     # nothing more can come of that place (a late answer still can)
ENDED = ('COMMITTED', 'WAITING_TASK', 'CANCELLED', 'FAILED', 'FAILED_PROTOCOL', 'INTERRUPTED', 'STALE')
ANSWER_KEY = 'asuna_answer'
ID = re.compile(r'q-[0-9a-f]{8}')
DEVELOPER_ROUTE = 'claude-code'     # the developer's line when no home route is marked `developer`

STATE_WORDS = {'pending': '还没问出来', 'waiting': '等着', 'answered': '答了', 'lapsed': '没答，不等了',
               'not_asked': '没问（那一回合你没说）', 'not_sent': '没问出去', 'working': '行动脑在做',
               'not_done': '行动脑没做完'}
QUESTION_WORDS = {'open': '等着', 'answered': '有回答', 'unanswered': '都没答', 'ended': '程序收了'}
NOTE_TEXT = ('你用 ask 要在这里问的问题（%s）：\n%s\n在这里问出来，或者决定不问；这里的回话程序会记到这个问题上。')
BLOCK_NOTE = ('你问出去的问题，还没结束的：每处问在哪、到几点不等、答了没有；回答本身用 ask 的 read 读。'
              '每处都答了或过了耐心，程序就收掉，在每个对话里说一次收成了什么；要写你自己的结论，照常 close 写 took。')
BRIEF = '这是一个问题：查清楚，在报告里回答。\n%s'
ASKED = '问出去了：答了没有、到几点不等，看 questions_from_program；回答用 ask 的 read 读，问完用 close 结束。'
# How the program closed it, by what came of its places (state_of before closing).
CLOSED_TOOK = {'answered': '程序收的：都有了结果，有回答', 'unanswered': '程序收的：没有回答',
               'open': '程序收的：问出去一周了还没回音'}
MIGRATED_TOOK = '从开发者留言箱搬过来的'
THANKS = '答你的有：%s。想谢谢他们、或告诉他们后来怎样，由你。'
NOBODY = '这个问题没人答。'
RETAKEN = '这个问题早就结束了；took 换成了你这次写的（原来是「%s」）。'
KEEP_HINT = ('要记下学到的：别人告诉你的，写的时候 from 写 别人说的；你自己的判断被回答证实了，用 replace_section '
             '改写它，from 写 查过的，依据写问过谁、几点、问题 id。')



# ── the owner of `questions` ──
# Read and written only through these: a question as stored (`fields` names what to return; `_id` always comes back).
# None follows the store's rule (ADR-104 section 4): an id, the persona or a conversation given None, or a value not of
# its kind, finds nothing without a read; a state given None finds the questions without one. Views are `View`s, in
# the replaced read's order. A source is one element of `sources`, matched whole (`Each`).
COLLECTION = 'questions'


def get(store, qid, fields=None, *, persona=ANY):
    """The question with this id (of this persona), or None."""
    if not is_text(qid):
        return None
    if persona is ANY:
        return store.collection(COLLECTION).get(qid, fields)
    return View(store, COLLECTION, fenced({'_id': qid}, {'persona': (persona, is_text)})).first(fields=fields)


def open_in(store, scene_id):
    """View: the open questions with a group source in this conversation."""
    where = {'state': 'open', 'sources': Each({'scene_id': scene_id, 'kind': 'group'})} if is_text(scene_id) else None
    return View(store, COLLECTION, where)


def closed_untold(store, told_in, *, persona=ANY, group=ANY):
    """View: the questions the program closed that were not told in `told_in` yet: a persona's (by when asked), or
    those with a group source in conversation `group`."""
    where = fenced({'state': 'closed', 'closed.by': 'program'}, {'persona': (persona, is_text)})
    if where is not None and group is not ANY:
        where = {**where, 'sources': Each({'scene_id': group, 'kind': 'group'})} if is_text(group) else None
    if where is not None:
        where = {**where, 'told_in': HoldsNone([told_in])} if is_text(told_in) else None
    return View(store, COLLECTION, where, (('asked_at', 1),) if group is ANY else ())


def of_persona(store, persona, *, state=ANY):
    """View: a persona's questions (in this state)."""
    return View(store, COLLECTION, pinned(fenced({}, {'persona': (persona, is_text)}), {'state': (state, is_text)}))


def asked(store, persona, since, *, scene_id=ANY, action=False):
    """View: a persona's questions asked since `since` (ISO text), to a source in this conversation, or (`action`)
    to the action brain; by when asked."""
    where = fenced({}, {'persona': (persona, is_text)}) if is_text(since) else None
    if where is not None:
        where['asked_at'] = Range(gte=since)
        if action:
            where['sources'] = Each({'kind': 'action'})
        elif scene_id is not ANY:
            where = {**where, 'sources': Each({'scene_id': scene_id})} if is_text(scene_id) else None
    return View(store, COLLECTION, where, (('asked_at', 1),))


def migrated(store, ids):
    """The developer-inbox rows of these ids already moved into questions (their ids)."""
    ids = [row_id for row_id in ids if is_text(row_id)]
    if not ids:
        return set()
    return {row['migrated_from'] for row in View(store, COLLECTION, {'migrated_from': AnyOf(ids)}).each(
        fields=['migrated_from'])}


def count_open(store, persona):
    """How many of a persona's questions are not closed."""
    return View(store, COLLECTION, fenced({'state': Not('closed')}, {'persona': (persona, is_text)})).count()


def mark_told(store, ids, scene_id):
    """These questions were told in this conversation (`told_in`, outside a revision)."""
    ids = [qid for qid in ids if is_text(qid)]
    if ids:
        store.collection(COLLECTION).update({'_id': AnyOf(ids)}, AddToSet('told_in', scene_id), many=True)


def save(store, row, **kwargs):
    """The revisioned write of a question (`Store.put`: `expected`, `stream`)."""
    return store.put(COLLECTION, row, **kwargs)


def _at(value):
    if not value:
        return None
    moment = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def question_id(key):
    return 'q-' + sha(canonical(key))[:8]


def until(asked_at, patience):
    minutes = PATIENCE.get(patience)
    return None if minutes is None else (_at(asked_at) + timedelta(minutes=minutes)).isoformat()


def developer_place(config):
    """The home line of the agent that changes her program: a home route marked `developer`, else the route named
    `claude-code` (the route for Claude Code). (scene_id, None) or (None, why)."""
    found = []
    for channel in (config.get('channels') or {}).values():
        for name, route in ((channel or {}).get('routes') or {}).items():
            scene_id = (route or {}).get('scene_id')
            if scene_id and scene_id in visibility.owner_private_scenes(config):
                found.append((bool(route.get('developer')), name == DEVELOPER_ROUTE, scene_id))
    for marked, named, scene_id in sorted(found, reverse=True):
        if marked or named:
            return scene_id, None
    return None, '没有开发代理的线（家里的线里没有标着 developer 的）'


# ── asking ─────────────────────────────────────────────────────────
def record(store, ep, qid, text, patience, sources):
    """The question as asked (idempotent by its id). `sources`: [{to, scene_id, kind, name, episode|note|task}]."""
    row = get(store, qid)
    if row:
        return row
    asked = now()
    row = save(store, {
        '_id': qid, 'persona': ep['persona'], 'scope_key': visibility.owner_private_scope(ep['persona']),
        'text': text, 'scene_id': ep['scene_id'], 'episode_id': ep['_id'], 'asked_at': asked,
        'patience': patience, 'state': 'open', 'tables_version': TABLES_VERSION, 'told_in': [],
        'sources': [{**source, 'until': None if source['kind'] == 'action' else until(asked, patience),
                     'state': 'working' if source['kind'] == 'action' else 'pending', 'answers': []}
                    for source in sources]}, stream=qid)
    store.audit(qid, 'question.asked', {'question': qid, 'places': len(sources), 'chars': len(text),
                                        'patience': patience}, row['scope_key'])
    return row


# ── a question in a group (ADR-061 step 2): a reply with wait=question ──
GROUP_PATIENCE = ('一会儿', '半天', '一天')
LOOK_MINUTES = 10                   # people who speak unaddressed while it waits get her a look, this long at most
GROUP_MORE = '更早的还有 %d 个没结'
TOLD_MANY = '程序一次收了你问的 %d 个问题：%s'
GROUP_ORIGINAL = '%s 里的原话（群里的人说的，不是你的话；只在这一回合读到，家里不存）'
GONE = '这条原话在群的记录里已经取不到了'
GROUP_NOTE = ('你在这里问的问题：等到几点、谁回了（按标签和时间）；过了耐心程序就收掉，说一次收成了什么。'
              '回答怎么带回家由你，用 note 写 question。')


def ask_in_group(store, ep, scene, text, patience):
    """Her reply's question in this group, opened like any other (idempotent per turn)."""
    from .people import People
    patience = patience or GROUP_PATIENCE[0]
    qid = question_id([ep['_id'], 'reply'])
    title = People(store, ep['persona']).scene_title(scene)
    return record(store, ep, qid, text, patience, [{'to': '这里', 'scene_id': scene['_id'], 'kind': 'group',
                                                     'name': title, 'episode': ep['_id']}])


def _open_here(store, scene_id):
    """Her open questions with a group source in this conversation."""
    return open_in(store, scene_id).rows()


def wants_look(store, scene, person_id, moment=None):
    """Whether this person's unaddressed line gets her a look: a question of hers here waits, within LOOK_MINUTES of
    being asked, and this person has not had a look for it yet."""
    moment = moment or clock.now()
    for row in _open_here(store, scene['_id']):
        asked = _at(row['asked_at'])
        if not asked or moment > asked + timedelta(minutes=LOOK_MINUTES):
            continue
        source = next(s for s in row['sources'] if s.get('kind') == 'group')
        line = _question_line(store, source)
        if not line:
            continue
        if not message_records.inbound(store, scene['_id'], author=person_id, after=line.get('scene_seq') or 0,
                                       wake='question_wait', by=None).first(fields=['_id']):
            return True
    return False


def _group_answers(store, source, line):
    """Answers in a group: a reply to one of her question's lines, a line that got her a look while it waited, or
    a reaction to her question line. Each kept by reference, never its text."""
    mine = message_records.turn_parts(store, source.get('episode'), scene=source['scene_id'], outbound=True,
                                      by=None).rows(fields=['_id', 'platform_message_id'])
    ids = [row['_id'] for row in mine]
    platform = [row['platform_message_id'] for row in mine if row.get('platform_message_id')]
    # the program's lines answer nothing
    return message_records.inbound(store, source['scene_id'], people_only=True, after=line.get('scene_seq') or 0,
                                   until=source.get('until') or None, answers_to=(ids, platform)).rows()


def told_many(told):
    """Many questions the program closed at once, in one line: how many, and how each lot ended."""
    tally = {}
    for row in told:
        tally[row['closed']['took']] = tally.get(row['closed']['took'], 0) + 1
    return TOLD_MANY % (len(told), '；'.join('%s %d 个' % (took, n) for took, n in tally.items()))


def group_block(store, persona, scene, moment=None):
    """questions_from_program in a group: her questions here, by id, when asked, how long she waits, who answered;
    and once each one the program closed here, with how it ended."""
    from .schedule_rules import line_stamp, scene_timezone
    moment = moment or clock.now()
    rows = [refresh(store, row, moment) for row in _open_here(store, scene['_id'])]
    rows = sorted((row for row in rows if row.get('state') == 'open'), key=lambda row: row['asked_at'], reverse=True)
    more = len(rows) - SHOWN                  # the newest only: a long list buries that something is still open (her ask)
    rows = rows[:SHOWN]
    told = closed_untold(store, scene['_id'], group=scene['_id']).rows()
    if not rows and not told:
        return None
    zone = scene_timezone(store.config, scene)
    if len(told) > SHOWN:                     # many closed at once: one line with the counts, not a list (her ask)
        items = [told_many(told)]
    else:
        items = ['%s 你 %s 问的：%s' % (row['_id'], line_stamp(zone, row['asked_at']), row['closed']['took']) for row in told]
    if told:
        mark_told(store, [row['_id'] for row in told], scene['_id'])
    for row in rows:
        source = next(s for s in row['sources'] if s.get('kind') == 'group')
        words = '%s 你 %s 问的：%s' % (row['_id'], line_stamp(zone, row['asked_at']), STATE_WORDS[source['state']])
        if source['state'] in ('pending', 'waiting') and source.get('until'):
            left = int((_at(source['until']) - moment).total_seconds() // 60)
            words += '，%s（还剩 %d 分钟）' % (row['patience'], max(left, 0))
        answers = [a for a in source.get('answers') or [] if a.get('by')]
        if answers:
            words += '；回了：' + '、'.join('%s %s' % (a['by'], line_stamp(zone, a.get('at'))) for a in answers)
        items.append(words)
    return {'items': items, **({'more': GROUP_MORE % more} if more > 0 else {}), 'note': GROUP_NOTE}


def answer_tail(store, persona, qid, zone):
    """The program's last line on a note that brings a group's answer home: who answered and when, and where the
    original lines are (never their text)."""
    from .schedule_rules import line_stamp
    row = get(store, qid, persona=persona)
    if not row:
        return None
    row = refresh(store, row)
    answers = [a for source in row['sources'] for a in source.get('answers') or [] if a.get('by')]
    who = '、'.join('%s %s' % (a['by'], line_stamp(zone, a.get('at'))) for a in answers)
    head = ('回答的是 %s；' % who) if who else '这个问题的记录里还没有人回；'
    return head + '原话家里不存，随时用 ask do=read id=%s 读' % qid


# ── what came back ─────────────────────────────────────────────────
def _question_line(store, source):
    """Her first line in the turn that asks there, or None."""
    return message_records.turn_parts(store, source.get('episode'), scene=source['scene_id'], outbound=True).first()


def _answer(row, people, scene):
    return {'line': row['_id'], 'event_id': row.get('platform_event_id'), 'at': row.get('received_at'),
            'by': people.speaker(scene, row.get('author'), row)}


def _lines_after(store, qid, source, line):
    """The answers in a home place: lines naming this question, else the first line after hers there."""
    named = message_records.inbound(store, source['scene_id'], people_only=True, asides=False,
                                    answers_question=qid).rows()
    if named:
        return named
    from . import channel_kinds
    marks = channel_kinds.marks_answers(source['scene_id'])
    # who can mark an answer answers only by marking it; others by their line
    first = message_records.inbound(store, source['scene_id'], people_only=True, asides=False,
                                    after=line.get('scene_seq') or 0, no_answer_mark=True,
                                    not_author=marks or None).first()
    return [first] if first else []


def _source_now(store, qid, source, persona, moment):
    """The source as it stands now: (state, answers)."""
    from .people import People
    if source.get('settled'):                    # never asked there, or the action brain's work ended without a report
        return source['state'], source.get('answers') or []
    if source['kind'] == 'action':
        from .tasks import TERMINAL
        task = task_records.get(store, source.get('task'), fields=['state', 'finished_at', 'result.text'])
        if not task:
            return 'not_done', []
        if task['state'] not in TERMINAL:
            return 'working', []
        # Its report is the answer, however the work ended (RETURNED is the usual end); none came back: not done.
        if (task.get('result') or {}).get('text'):
            return 'answered', [{'task': task['_id'], 'at': task.get('finished_at'), 'by': ACTION}]
        return 'not_done', []
    line = _question_line(store, source)
    if not line:
        episode = episode_records.get(store, source.get('episode'), fields=['state']) if source.get('episode') else None
        return ('not_asked' if episode and episode.get('state') in ENDED else 'pending'), []
    if line.get('delivery_state') == 'FAILED':
        return 'not_sent', []
    scene = scene_records.get(store, source['scene_id']) or {'_id': source['scene_id']}
    people = People(store, persona)
    lines = _group_answers(store, source, line) if source.get('kind') == 'group' else _lines_after(store, qid, source, line)
    found = [_answer(row, people, scene) for row in lines]
    if source.get('kind') == 'group':
        # An answer once recorded stays recorded: a line gone from the group's record is said so on read (GONE).
        seen = {answer['line'] for answer in found}
        found = [*[a for a in source.get('answers') or [] if a.get('line') not in seen], *found]
        found.sort(key=lambda answer: str(answer.get('at') or ''))
    if found:
        return 'answered', found
    if source.get('until') and moment >= _at(source['until']):
        return 'lapsed', []
    return 'waiting', []


def refresh(store, row, moment=None):
    """Bring one question up to date with what came back; closes it when it has run past its end. Returns the row."""
    moment = moment or clock.now()
    if row.get('state') != 'open':
        return row
    sources, changed, events = [], False, []
    for source in row['sources']:
        state, answers = _source_now(store, row['_id'], source, row['persona'], moment)
        if state != source.get('state') or answers != (source.get('answers') or []):
            changed = True
            if state == 'answered' and source.get('state') != 'answered':
                events.append(('question.answered', {'place': source.get('to'), 'answers': len(answers)}))
            if state == 'lapsed':
                events.append(('question.lapsed', {'place': source.get('to')}))
            source = {**source, 'state': state, 'answers': answers,
                      **({'settled': True} if state in SETTLED else {})}
        sources.append(source)
    update = {'sources': sources}
    ends = _ends(row, sources)
    if ends and moment >= ends:
        changed = True
        took = CLOSED_TOOK[state_of({**row, 'sources': sources})]
        update.update(state='closed', closed={'at': moment.isoformat(), 'by': 'program', 'took': took})
        events.append(('question.closed', {'by': 'program'}))
    if not changed:
        return row
    try:
        row = save(store, {**row, **update}, expected=row['revision'], stream=row['_id'])
    except Conflict:
        return get(store, row['_id']) or row
    for kind, payload in events:
        store.audit(row['_id'], kind, {'question': row['_id'], **payload}, row['scope_key'])
    return row


def _ends(row, sources):
    """When the program closes it: once every place is settled — a home place or the action brain when it answered,
    a group when its patience is over (more may still answer there until then), any place lapsed or never asked; a
    week after it was asked while a place without patience still waits."""
    marks = []
    for source in sources:
        if source['state'] in ('pending', 'working') or source['state'] == 'waiting' and not source.get('until'):
            return _at(row['asked_at']) + UNANSWERED
        if source['state'] == 'waiting':
            marks.append(_at(source['until']))
        elif source['state'] == 'answered':
            marks += [_at(answer.get('at')) for answer in source['answers'] if answer.get('at')]
            if source.get('kind') == 'group' and source.get('until'):
                marks.append(_at(source['until']))
        elif source.get('until') and source['state'] == 'lapsed':
            marks.append(_at(source['until']))
    marks = [mark for mark in marks if mark]
    return max(marks) if marks else _at(row['asked_at'])


def state_of(row):
    if row.get('state') == 'closed':
        return 'ended' if (row.get('closed') or {}).get('by') == 'program' else 'closed'
    states = [source['state'] for source in row['sources']]
    if 'answered' in states:
        return 'answered'
    if all(state in ('lapsed', 'not_asked', 'not_sent', 'not_done') for state in states):
        return 'unanswered'
    return 'open'


def place_words(source):
    """One place of a question as she reads it."""
    out = {'to': source.get('name') or source.get('to'), 'state': STATE_WORDS[source['state']]}
    if source['state'] in ('pending', 'waiting') and source.get('until'):
        out['until'] = source['until']
    if source['state'] == 'answered':
        out['answered_at'] = max(str(answer.get('at') or '') for answer in source['answers']) or None
        out['by'] = '、'.join(dict.fromkeys(answer['by'] for answer in source['answers'] if answer.get('by')))
    return out


# ── what she reads ─────────────────────────────────────────────────
def migrate(store, persona):
    """Her developer-inbox messages become closed questions to the developer's line, once each (by the row's id); the
    program's own notes there stay where they are."""
    from . import developer_inbox
    rows = developer_inbox.of_persona(store, persona).rows()
    done = migrated(store, [row['_id'] for row in rows]) if rows else set()
    rows = [row for row in rows if row['_id'] not in done]
    if not rows:
        return 0
    scene_id, _ = developer_place(store.config)
    moved = 0
    for inbox in rows:
        qid = question_id(['developer_inbox', inbox['_id']])
        answered = inbox.get('state') == 'answered'
        save(store, {
            '_id': qid, 'persona': persona, 'scope_key': visibility.owner_private_scope(persona),
            'text': inbox.get('text') or '', 'scene_id': (inbox.get('source') or {}).get('scene_id'),
            'asked_at': inbox.get('created_at'), 'patience': '一小时' if inbox.get('level') == 'wake' else '回了为止',
            'state': 'closed', 'tables_version': TABLES_VERSION, 'told_in': [], 'migrated_from': inbox['_id'],
            'sources': [{'to': 'developer', 'scene_id': scene_id, 'kind': 'home', 'name': '开发代理的线',
                         'until': None, 'settled': True, 'state': 'answered' if answered else 'lapsed',
                         'answers': [{'at': inbox.get('answered_at'), 'by': '开发代理'}] if answered else []}],
            'closed': {'at': now(), 'by': 'migrated', 'took': MIGRATED_TOOK}}, stream=qid)
        moved += 1
    return moved


def block(store, persona, scene_id, moment=None, opening=None):
    """questions_from_program at home: her open questions, and once in this conversation each one the program closed;
    None when there are none. `opening`: the question whose note opened this turn (its text is in that note)."""
    moment = moment or clock.now()
    from .config import excerpt
    # Every open one is brought up to date, shown or not: one past its end closes now, not when it reaches the top.
    rows = [refresh(store, row, moment) for row in of_persona(store, persona, state='open').each()]
    rows = sorted((row for row in rows if row.get('state') == 'open'), key=lambda row: row['asked_at'], reverse=True)[:SHOWN]
    told = closed_untold(store, scene_id, persona=persona).rows(newest_first=True)
    many = len(told) > SHOWN                  # many closed at once: one line with the counts, not a list (her ask)
    if not many:
        rows += told
    if not rows and not told:
        return None
    items = [told_many(told)] if many else []
    for row in rows:
        item = {'id': row['_id']}
        if row['_id'] != opening:
            item['question'] = excerpt(' '.join(row['text'].split()), EXCERPT)
        item.update(asked_at=row['asked_at'], state=QUESTION_WORDS[state_of(row)],
                    to=[place_words(source) for source in row['sources']])
        if row.get('state') == 'closed':
            item['took'] = row['closed']['took']
        items.append(item)
    if told:
        mark_told(store, [row['_id'] for row in told], scene_id)
    return {'items': items, 'note': BLOCK_NOTE}


def read(store, persona, qid, moment=None, outside=False):
    """One question with its answers' text (a task's report: its first page; `outside` home, without the machine's
    paths and tracebacks: machine_words)."""
    from .tasks import report_pages
    from . import machine_words
    row = get(store, qid, persona=persona)
    if not row:
        return None
    row = refresh(store, row, moment)
    places = []
    for source in row['sources']:
        place = place_words(source)
        answers = []
        for answer in source.get('answers') or []:
            if answer.get('task'):
                task = task_records.get(store, answer['task'], fields=['result.text'])
                pages = report_pages(((task or {}).get('result') or {}).get('text') or '')
                first = pages[0] if pages else ''
                answers.append({'by': ACTION, 'at': answer.get('at'), 'task': answer['task'],
                                'text': machine_words.text(first) if outside else first,
                                **({'more': '共 %d 页：task 的 page 接着读' % len(pages)} if len(pages) > 1 else {})})
            elif answer.get('line'):
                line = message_records.get(store, answer['line'], fields=['text'])
                text = str((line or {}).get('text') or '')
                said = {'by': answer.get('by'), 'at': answer.get('at'), 'line': answer['line'],
                        'event_id': answer.get('event_id'),
                        'text': excerpt(text, ANSWER_CHARS)}
                if source.get('kind') == 'group':
                    # A group's own words, read from its record for this turn only; home keeps none (her answer a).
                    said['where'] = GROUP_ORIGINAL % (source.get('name') or '那个群')
                    if line is None:
                        said['text'] = GONE
                answers.append(said)
            else:
                answers.append({'by': answer.get('by'), 'at': answer.get('at')})
        if answers:
            place['answers'] = answers
        places.append(place)
    out = {'id': row['_id'], 'question': row['text'], 'asked_at': row['asked_at'],
           'state': QUESTION_WORDS.get(state_of(row), '结束了'), 'to': places}
    if row.get('closed'):
        out['closed_at'], out['took'] = row['closed'].get('at'), row['closed'].get('took')
    return out


def history(store, persona, scene_id, name, moment=None):
    """Her last asks to one place (or the action brain) in READ_DAYS: when, answered or not, how long, her took."""
    moment = moment or clock.now()
    since = (moment - timedelta(days=READ_DAYS)).isoformat()
    def here(source):
        return source['kind'] == 'action' if scene_id is None else source.get('scene_id') == scene_id
    view = asked(store, persona, since, action=True) if scene_id is None else asked(store, persona, since,
                                                                                     scene_id=scene_id)
    rows = view.rows(newest_first=True, limit=READ_SHOWN)
    if not rows:
        return {'items': [], 'searched': '这 %d 天问过「%s」的问题里找了：没有' % (READ_DAYS, name)}
    items = []
    for row in rows:
        row = refresh(store, row, moment)
        source = next(source for source in row['sources'] if here(source))
        item = {'id': row['_id'], 'question': ' '.join(row['text'].split())[:EXCERPT], 'asked_at': row['asked_at'],
                'state': STATE_WORDS[source['state']]}
        if source['state'] == 'answered':
            first = min((_at(answer['at']) for answer in source['answers'] if answer.get('at')), default=None)
            if first:
                item['took_minutes'] = max(0, round((first - _at(row['asked_at'])).total_seconds() / 60))
        if row.get('closed', {}).get('took'):
            item['took'] = row['closed']['took']
        items.append(item)
    return {'items': items, 'searched': '这 %d 天问过「%s」的，新的在前，最多 %d 个' % (READ_DAYS, name, READ_SHOWN)}


def close(store, persona, qid, took, moment=None):
    """She closes a question with what she took from it. Returns (row, words)."""
    from . import memory_tiers
    row = get(store, qid, persona=persona)
    if not row:
        return None, None
    row = refresh(store, row, moment)
    if row.get('state') == 'closed':
        # What she took can change after it closed (an answer that came late, a first take that was wrong): the new
        # take replaces it, the close keeps its time.
        before = (row.get('closed') or {}).get('took', '')
        if not took or took == before:
            return row, '这个问题已经结束了（%s）。' % before
        row = save(store, {**row, 'closed': {**row['closed'], 'took': took, 'retaken_at': (moment or clock.now()).isoformat()}},
                   expected=row['revision'], stream=row['_id'])
        store.audit(row['_id'], 'question.retaken', {'question': row['_id'], 'chars': len(took)}, row['scope_key'])
        return row, RETAKEN % before
    row = save(store, {**row, 'state': 'closed',
                       'closed': {'at': (moment or clock.now()).isoformat(), 'by': 'her', 'took': took}},
               expected=row['revision'], stream=row['_id'])
    store.audit(row['_id'], 'question.closed', {'question': row['_id'], 'by': 'her', 'chars': len(took)}, row['scope_key'])
    who = [answer.get('by') for source in row['sources'] for answer in source.get('answers') or [] if answer.get('by')]
    words = THANKS % '、'.join(dict.fromkeys(who)) if who else NOBODY
    if memory_tiers.ENABLED and who:
        words += KEEP_HINT
    return row, words
