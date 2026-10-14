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
A question still open a day after its patience (or its last answer), or a week after it was asked with no patience,
is closed by the program, and each home conversation is told that once. She closes a question herself with `took`.

She reads it all in words (`block`: questions_from_program at home; `read`), times as `_at` fields. Each move is one
audit line without text (question.asked / answered / lapsed / closed). Words come from the versioned tables below.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from .evidence import canonical, sha
from .state import Conflict, now
from . import visibility

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
ENDING = timedelta(hours=24)        # open this long after its patience or its last answer: closed by the program
UNANSWERED = timedelta(days=7)      # a question without patience, never answered: closed by the program
SHOWN = 8
READ_DAYS, READ_SHOWN = 30, 10
SETTLED = ('not_asked', 'not_sent', 'not_done')     # nothing more can come of that place (a late answer still can)
ENDED = ('COMMITTED', 'WAITING_TASK', 'CANCELLED', 'FAILED', 'FAILED_PROTOCOL', 'INTERRUPTED', 'STALE')
ANSWER_KEY = 'asuna_answer'
ID = re.compile(r'q-[0-9a-f]{8}')
DEVELOPER_ROUTE = 'claude-code'     # the developer's line when no home route is marked `developer`

STATE_WORDS = {'pending': '还没问出来', 'waiting': '等着', 'answered': '答了', 'lapsed': '没答，不等了',
               'not_asked': '没问（那一轮你没说）', 'not_sent': '没问出去', 'working': '行动脑在做',
               'not_done': '行动脑没做完'}
QUESTION_WORDS = {'open': '等着', 'answered': '有回答', 'unanswered': '都没答', 'ended': '程序关了'}
NOTE_TEXT = ('你用 ask 要在这里问的问题（%s）：\n%s\n在这里问出来，或者决定不问；这里的回话程序会记到这个问题上。')
BLOCK_NOTE = ('你问出去的问题，还没结束的：每处问在哪、到几点不等、答了没有；回答本身用 ask 的 read 读，'
              '结束用 ask 的 close。程序关掉的，在每个对话里说一次。')
BRIEF = '这是一个问题：查清楚，在报告里回答。\n%s'
ASKED = '问出去了：答了没有、到几点不等，看 questions_from_program；回答用 ask 的 read 读，问完用 close 结束。'
ENDED_TOOK = '程序关的：过了耐心一天还没结束'
MIGRATED_TOOK = '从开发者留言箱搬过来的'
THANKS = '答你的有：%s。想谢谢他们、或告诉他们后来怎样，由你。'
NOBODY = '这个问题没人答。'
KEEP_HINT = ('要记下学到的：别人告诉你的，写的时候 from 写 别人说的；你自己的判断被回答证实了，用 replace_section '
             '改写它，from 写 查过的，依据写问过谁、几点、问题 id。')


def _now():
    return datetime.now(timezone.utc)


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
    row = store.db.questions.find_one({'_id': qid})
    if row:
        return row
    asked = now()
    row = store.put('questions', {
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
GROUP_ORIGINAL = '%s 里的原话（群里的人说的，不是你的话；只在这一回合读到，家里不存）'
GONE = '这条原话在群的记录里已经取不到了'
GROUP_NOTE = '你在这里问的问题：等到几点、谁回了（按标签和时间）；回答怎么带回家由你，用 leave_note 写 question。'


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
    return list(store.db.questions.find({'state': 'open', 'sources': {'$elemMatch': {'scene_id': scene_id,
                                                                                     'kind': 'group'}}}))


def wants_look(store, scene, person_id, moment=None):
    """Whether this person's unaddressed line gets her a look: a question of hers here waits, within LOOK_MINUTES of
    being asked, and this person has not had a look for it yet."""
    moment = moment or _now()
    for row in _open_here(store, scene['_id']):
        asked = _at(row['asked_at'])
        if not asked or moment > asked + timedelta(minutes=LOOK_MINUTES):
            continue
        source = next(s for s in row['sources'] if s.get('kind') == 'group')
        line = _question_line(store, source)
        if not line:
            continue
        if not store.db.messages.find_one({'scene_id': scene['_id'], 'direction': 'inbound', 'author': person_id,
                                           'scene_seq': {'$gt': line.get('scene_seq') or 0},
                                           'event.group_context.wake_reason': 'question_wait'}, {'_id': 1}):
            return True
    return False


def _group_answers(store, source, line):
    """Answers in a group: a reply to one of her question's lines, a line that got her a look while it waited, or
    a reaction to her question line. Each kept by reference, never its text."""
    mine = list(store.db.messages.find({'scene_id': source['scene_id'], 'episode_id': source.get('episode'),
                                        'direction': 'outbound', 'phase': 'SPEAK'}, {'_id': 1, 'platform_message_id': 1}))
    ids = [row['_id'] for row in mine]
    platform = [row['platform_message_id'] for row in mine if row.get('platform_message_id')]
    query = {'scene_id': source['scene_id'], 'direction': 'inbound', 'scene_seq': {'$gt': line.get('scene_seq') or 0},
             '$or': [{'event.group_context.reply_message_id': {'$in': ids}},
                     {'event.group_context.wake_reason': 'question_wait'},
                     {'event.raw.asuna_notice.kind': 'reaction', 'event.raw.asuna_notice.line.message_id': {'$in': platform}}]}
    if source.get('until'):
        query['received_at'] = {'$lte': source['until']}
    return list(store.db.messages.find(query).sort('scene_seq', 1))


def group_block(store, persona, scene, moment=None):
    """questions_from_program in a group: her questions here, by id, when asked, how long she waits, who answered."""
    from .schedule_rules import line_stamp, scene_timezone
    moment = moment or _now()
    rows = [refresh(store, row, moment) for row in _open_here(store, scene['_id'])]
    rows = [row for row in rows if row.get('state') == 'open']
    if not rows:
        return None
    zone = scene_timezone(store.config, scene)
    items = []
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
    return {'items': items, 'note': GROUP_NOTE}


def answer_tail(store, persona, qid, zone):
    """The program's last line on a note that brings a group's answer home: who answered and when, and where the
    original lines are (never their text)."""
    from .schedule_rules import line_stamp
    row = store.db.questions.find_one({'_id': qid, 'persona': persona})
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
    return store.db.messages.find_one({'scene_id': source['scene_id'], 'episode_id': source.get('episode'),
                                       'direction': 'outbound', 'phase': 'SPEAK'}, sort=[('scene_seq', 1)])


def _answer(row, people, scene):
    return {'line': row['_id'], 'event_id': row.get('platform_event_id'), 'at': row.get('received_at'),
            'by': people.speaker(scene, row.get('author'), row)}


def _lines_after(store, qid, source, line):
    """The answers in a home place: lines naming this question, else the first line after hers there."""
    from .ingress import NOT_CORE_NOTICE
    base = {'scene_id': source['scene_id'], 'direction': 'inbound', **NOT_CORE_NOTICE,
            'event.raw.asuna_aside': {'$ne': True}}
    named = list(store.db.messages.find({**base, 'event.raw.%s.question' % ANSWER_KEY: qid}).sort('scene_seq', 1))
    if named:
        return named
    after = {**base, 'scene_seq': {'$gt': line.get('scene_seq') or 0}, 'event.raw.%s' % ANSWER_KEY: {'$exists': False}}
    from . import channel_kinds
    marks = channel_kinds.marks_answers(source['scene_id'])
    if marks:
        after['author'] = {'$ne': marks}        # who can mark an answer answers only by marking it; others by their line
    first = store.db.messages.find_one(after, sort=[('scene_seq', 1)])
    return [first] if first else []


def _source_now(store, qid, source, persona, moment):
    """The source as it stands now: (state, answers)."""
    from .people import People
    if source.get('settled'):                    # never asked there, or the action brain's work ended without a report
        return source['state'], source.get('answers') or []
    if source['kind'] == 'action':
        from .tasks import TERMINAL
        task = store.db.tasks.find_one({'_id': source.get('task')}, {'state': 1, 'finished_at': 1, 'result.text': 1})
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
        episode = store.db.episodes.find_one({'_id': source.get('episode')}, {'state': 1}) if source.get('episode') else None
        return ('not_asked' if episode and episode.get('state') in ENDED else 'pending'), []
    if line.get('delivery_state') == 'FAILED':
        return 'not_sent', []
    scene = store.db.scenes.find_one({'_id': source['scene_id']}) or {'_id': source['scene_id']}
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
    moment = moment or _now()
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
        update.update(state='closed', closed={'at': moment.isoformat(), 'by': 'program', 'took': ENDED_TOOK})
        events.append(('question.closed', {'by': 'program'}))
    if not changed:
        return row
    try:
        row = store.put('questions', {**row, **update}, expected=row['revision'], stream=row['_id'])
    except Conflict:
        return store.db.questions.find_one({'_id': row['_id']}) or row
    for kind, payload in events:
        store.audit(row['_id'], kind, {'question': row['_id'], **payload}, row['scope_key'])
    return row


def _ends(row, sources):
    """When the program closes it: a day after its last patience or answer once every place is settled or past
    patience; a week after it was asked otherwise."""
    marks = []
    for source in sources:
        if source['state'] in ('pending', 'working') or source['state'] == 'waiting' and not source.get('until'):
            return _at(row['asked_at']) + UNANSWERED
        if source['state'] == 'answered':
            marks += [_at(answer.get('at')) for answer in source['answers'] if answer.get('at')]
        elif source.get('until'):
            marks.append(_at(source['until']))
    marks = [mark for mark in marks if mark]
    return (max(marks) if marks else _at(row['asked_at'])) + ENDING


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
    rows = list(store.db.developer_inbox.find({'persona': persona, 'source.by': {'$ne': 'program'}}))
    done = {row['migrated_from'] for row in store.db.questions.find(
        {'migrated_from': {'$in': [row['_id'] for row in rows]}}, {'migrated_from': 1})} if rows else set()
    rows = [row for row in rows if row['_id'] not in done]
    if not rows:
        return 0
    scene_id, _ = developer_place(store.config)
    moved = 0
    for inbox in rows:
        qid = question_id(['developer_inbox', inbox['_id']])
        answered = inbox.get('state') == 'answered'
        store.put('questions', {
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
    moment = moment or _now()
    from .config import excerpt
    rows = [refresh(store, row, moment) for row in
            store.db.questions.find({'persona': persona, 'state': 'open'}).sort('asked_at', -1).limit(SHOWN)]
    told = list(store.db.questions.find({'persona': persona, 'state': 'closed', 'closed.by': 'program',
                                         'told_in': {'$ne': scene_id}}).sort('asked_at', -1).limit(SHOWN))
    rows += told
    if not rows:
        return None
    items = []
    for row in rows:
        item = {'id': row['_id']}
        if row['_id'] != opening:
            item['question'] = excerpt(' '.join(row['text'].split()), EXCERPT)
        item.update(asked_at=row['asked_at'], state=QUESTION_WORDS[state_of(row)],
                    to=[place_words(source) for source in row['sources']])
        items.append(item)
    if told:
        store.db.questions.update_many({'_id': {'$in': [row['_id'] for row in told]}},
                                       {'$addToSet': {'told_in': scene_id}})
    return {'items': items, 'note': BLOCK_NOTE}


def read(store, persona, qid, moment=None):
    """One question with its answers' text (a task's report: its first page)."""
    from .tasks import report_pages
    row = store.db.questions.find_one({'_id': qid, 'persona': persona})
    if not row:
        return None
    row = refresh(store, row, moment)
    places = []
    for source in row['sources']:
        place = place_words(source)
        answers = []
        for answer in source.get('answers') or []:
            if answer.get('task'):
                task = store.db.tasks.find_one({'_id': answer['task']}, {'result.text': 1})
                pages = report_pages(((task or {}).get('result') or {}).get('text') or '')
                answers.append({'by': ACTION, 'at': answer.get('at'), 'task': answer['task'],
                                'text': pages[0] if pages else '',
                                **({'more': '共 %d 页：task 的 page 接着读' % len(pages)} if len(pages) > 1 else {})})
            elif answer.get('line'):
                line = store.db.messages.find_one({'_id': answer['line']}, {'text': 1})
                text = str((line or {}).get('text') or '')
                said = {'by': answer.get('by'), 'at': answer.get('at'), 'line': answer['line'],
                        'event_id': answer.get('event_id'),
                        'text': text if len(text) <= ANSWER_CHARS else text[:ANSWER_CHARS] + '…'}
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
    moment = moment or _now()
    since = (moment - timedelta(days=READ_DAYS)).isoformat()
    def here(source):
        return source['kind'] == 'action' if scene_id is None else source.get('scene_id') == scene_id
    where = {'sources.kind': 'action'} if scene_id is None else {'sources.scene_id': scene_id}
    rows = list(store.db.questions.find({'persona': persona, 'asked_at': {'$gte': since}, **where})
                .sort('asked_at', -1).limit(READ_SHOWN))
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
    row = store.db.questions.find_one({'_id': qid, 'persona': persona})
    if not row:
        return None, None
    row = refresh(store, row, moment)
    if row.get('state') == 'closed':
        return row, '这个问题已经结束了（%s）。' % (row.get('closed') or {}).get('took', '')
    row = store.put('questions', {**row, 'state': 'closed',
                                  'closed': {'at': (moment or _now()).isoformat(), 'by': 'her', 'took': took}},
                    expected=row['revision'], stream=row['_id'])
    store.audit(row['_id'], 'question.closed', {'question': row['_id'], 'by': 'her', 'chars': len(took)}, row['scope_key'])
    who = [answer.get('by') for source in row['sources'] for answer in source.get('answers') or [] if answer.get('by')]
    words = THANKS % '、'.join(dict.fromkeys(who)) if who else NOBODY
    if memory_tiers.ENABLED and who:
        words += KEEP_HINT
    return row, words
