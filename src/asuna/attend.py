"""The relevance gate (owner direction 2026-10-04): may she let a group message pass?

A group turn first asks her one short question in a fresh small session: 接话 or 不理. Only 接话 starts the
full turn with its recall, monologue and decision. Asked: the proactive rules fired, a reply inside a thread
she was in, her name without an @, the ambiguous looks (a possible answer to what she waits for or asked, a watched
person), and (ADR-086 E1) an @ or a reply to her, where 不理 is "not now": the line stays in the group's catch-up
and her next turn there sees it. Not asked, so the full turn runs at once: an @ or a reply to her from the person
she is waiting on, or inside her open question's wait (`answers_her`, set at intake from the same checks). Each
question has everything it needs, so the gate keeps no history of earlier questions. A gate
that cannot decide (the model failed, or never answered 接话 or 不理) is the program's failure, recorded as
`failed`, never as her 不理; on an addressed line it falls back to the full turn.

Her conversation there already holds every line the gate looks at (it is written in as it arrives), so a line she lets
pass reads like any other in her next turn. Each 不理 is kept (`hold_passed`, an `artifacts` row of kind
`passed_line`) until her next turn there lists it once (`take_passed`): who, when, and her one-line reason, newest
PASSED_MAX, the rest counted. A Host restart keeps what was not shown yet.

The gate reads words only: why she is being asked, who is talking and how well she knows them, what was
said here since she last spoke (bounded), and her mood as one public paragraph (ADR-086 D6; `affect.gate:
none` leaves it out). Nothing is recalled, and the group's own conversation is not touched, so its cached
prefix stays as it was.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .caught_up import said_at
from .config import ago, character_id, excerpt, prompt_path

# Why she is being asked, in words; any other wake reason runs the full turn as before.
GATED = {
    'proactive_unprompted': '群里在聊，没人叫你；按群里的节奏，这会儿可以插一句',
    'reply_in_active_topic': '有人在一串刚叫过你的对话里接话（那串里不一定有你说的话），不是回你',
    'name_called': '有人提到了你的名字，但没有 @ 你',
    'chain': '群里在跟队形：好几个人接连发了同一句或同一张，没人叫你',
    'awaited_answer': '你刚在这里问了人、说了在等回话；这句没 @ 你也没引用你，可能是在回你，也可能不是',
    'question_wait': '你在这里问了大家一个问题，还在等回答；这句没 @ 你也没引用你，可能是在答你，也可能不是',
    'watched': '这个人在你的 watch 名单上，他在这里说话了；这句没 @ 你，不一定是对你说的',
    'mentioned_account': '有人 @ 了你',
    'reply_to_character': '有人回了你的话',
    'catchup_mention': '这句是断线时漏收、恢复后补读进来的旧话，当时 @ 了你或回了你；那会儿你没看到，现在接不接由你定',
    'poked': '有人戳了戳你（平台的戳一戳），没说话',
    'reacted': '有人给你说过的一句话点了表情，没说话',
}
# An @ or a reply to her (ADR-086 E1): asked like the rest, unless it answers what she waits for or asked
# (`answers_her`, channels.group_context): that must wake her, so it runs the full turn without a question.
ADDRESSED = ('mentioned_account', 'reply_to_character')
CHOICES = {'接话': 'join', '不理': 'quiet'}
# Catch-up: the lines since she last spoke here, reaching back at least 10 and at most 60 minutes.
WINDOW_MIN_MINUTES, WINDOW_MAX_MINUTES = 10, 60
MAX_LINES, MAX_CHARS = 40, 4000
REASON_LIMIT = 60
PASSED_KIND = 'passed_line'
PASSED_MAX, PASSED_KEPT = 10, 50             # listed in one turn; kept per conversation before the oldest go
PASSED_NOTE = '上回合以后，你在这个群看过、当时没接的话：谁、什么时候，括号里是你当时的理由；只给这一次。'


def hold_passed(store, scene_id, message_id, received_at):
    """A line she let pass, kept until her next turn there lists it (ADR-086 §16, her condition)."""
    import uuid
    store.db.artifacts.insert_one({'_id': 'passed-' + uuid.uuid4().hex, 'kind': PASSED_KIND, 'scene_id': scene_id,
                                   'message_id': message_id, 'received_at': received_at, 'schema_version': 1})
    extra = list(store.db.artifacts.find({'kind': PASSED_KIND, 'scene_id': scene_id}, {'_id': 1})
                 .sort('received_at', -1).skip(PASSED_KEPT))
    if extra:
        store.db.artifacts.delete_many({'_id': {'$in': [doc['_id'] for doc in extra]}})


def take_passed(store, scene, persona=None):
    """The lines she let pass here since her last turn, once: {'items': [...], 'more': ...} or None."""
    held = list(store.db.artifacts.find({'kind': PASSED_KIND, 'scene_id': scene['_id']}).sort('received_at', 1))
    if not held:
        return None
    store.db.artifacts.delete_many({'_id': {'$in': [doc['_id'] for doc in held]}})
    from .people import People
    from .schedule_rules import line_stamp, scene_timezone
    rows = {row['_id']: row for row in store.db.messages.find(
        {'_id': {'$in': [doc['message_id'] for doc in held]}},
        {'author': 1, 'attend': 1, 'occurred_at': 1, 'received_at': 1, 'event': 1})}
    people, zone, items = People(store, persona), scene_timezone(store.config, scene), []
    for doc in held:
        row = rows.get(doc['message_id'])
        if not row or (row.get('attend') or {}).get('choice') != 'quiet':
            continue
        reason = ' '.join(str(row['attend'].get('reason') or '').split())
        items.append('%s %s：看过，没接%s' % (people.speaker(scene, row['author'], row), line_stamp(zone, said_at(row)) or '',
                                         '（%s）' % reason if reason else ''))
    if not items:
        return None
    out = {'items': items[-PASSED_MAX:]}
    if len(items) > PASSED_MAX:
        out['more'] = '还有 %d 条更早的没列出' % (len(items) - PASSED_MAX)
    return out


def gated(scene, event):
    group = event.get('group_context') or {}
    if group.get('wake_reason') in ADDRESSED and group.get('answers_her'):
        return False
    return scene.get('kind') == 'group' and group.get('wake_reason') in GATED


def addressed(event):
    """An @ or a reply to her: a failed gate on it falls back to the full turn (ADR-086 E1, her condition)."""
    return (event.get('group_context') or {}).get('wake_reason') in ADDRESSED


def _seconds(stamp):
    try:
        return datetime.fromisoformat(str(stamp).replace('Z', '+00:00')).timestamp()
    except ValueError:
        return None


def _amount(count):
    return '没有新的话' if not count else '几句' if count <= 3 else '十来句' if count <= 15 else '几十句'


def recent(store, scene, until_seq, now_ts=None):
    """(lines as she reads them, words for how long since she spoke here and how much came since)."""
    from .people import People
    now_ts = now_ts or datetime.now(timezone.utc).timestamp()
    me = character_id(store.config)
    mine = store.db.messages.find_one({'scene_id': scene['_id'], 'direction': 'outbound', 'author': me,
                                       'delivery_state': 'DELIVERED'}, {'scene_seq': 1, 'receipt_at': 1},
                                      sort=[('scene_seq', -1)])
    rows = list(store.db.messages.find(
        {'scene_id': scene['_id'], 'policy_epoch': scene['policy_epoch'], 'scene_seq': {'$lte': until_seq},
         '$or': [{'direction': 'inbound'}, {'direction': 'outbound', 'delivery_state': 'DELIVERED'}]},
        {'_id': 1, 'author': 1, 'text': 1, 'direction': 1, 'scene_seq': 1, 'received_at': 1, 'receipt_at': 1,
         'occurred_at': 1, 'scene_id': 1, 'event': 1, 'errand': 1}).sort('scene_seq', -1).limit(MAX_LINES))
    floor = now_ts - WINDOW_MAX_MINUTES * 60
    always = now_ts - WINDOW_MIN_MINUTES * 60
    since = (mine or {}).get('scene_seq') or 0
    people, kept, used = People(store), [], 0
    for row in rows:                                         # newest first, then put back in order
        at = _seconds(said_at(row))
        if at is None or at < floor or (row['scene_seq'] <= since and at < always):
            break
        if row['direction'] == 'outbound':
            text = ('你（差事）：' if row.get('errand') else '你：') + ' '.join(str(row.get('text') or '').split())
        else:
            text = people.transcript(scene, row, once=False)
        used += len(text)
        if kept and used > MAX_CHARS:
            break
        kept.append(text)
    kept.reverse()
    newer = store.db.messages.count_documents({'scene_id': scene['_id'], 'direction': 'inbound',
                                               'scene_seq': {'$gt': since, '$lte': until_seq}}, limit=50)
    spoke = _seconds((mine or {}).get('receipt_at'))
    if spoke is None:
        timing = '你还没在这里说过话'
    else:
        timing = '你上次在这里说话是' + ago(max(0.0, now_ts - spoke) / 3600)
    return kept, timing + '；之后来了' + _amount(newer)


def material(store, scene, event, row, persona):
    """Everything the gate reads, in words."""
    from . import familiarity
    from .people import People
    people = People(store, persona)
    lines, since = recent(store, scene, row['scene_seq'])
    doc = people.entry(scene, event['person_id'], row)
    out = {'scene': people.scene_title(scene),
           'why_asked': GATED[event['group_context']['wake_reason']],
           'speaker': people.head(scene['_id'], doc, str(row.get('received_at') or '')),
           **{'speaker_' + key: value for key, value in familiarity.words(store, event['person_id'], persona).items()},
           'since_you_spoke': since,
           'lines': lines or [people.transcript(scene, row, once=False)]}
    from . import notices
    held = notices.take(store, scene, persona, keep=True)      # after the stored lines; hers once, here or in the turn
    if held:
        out['notices'] = held
    notes = group_notes(store, persona, scene)
    if notes:
        out['your_notes_here'] = notes
    about = speaker_understanding(store, scene, event['person_id'])
    if about:
        out['speaker_understanding'] = about
    from .affect import AffectLedger, interpret
    from .render import model_and_policy
    from . import visibility
    model, policy = model_and_policy(store, persona)
    ledger = AffectLedger(store, persona, model, policy)
    if ledger.enabled and ledger.model.get('gate', 'paragraph') != 'none':
        # ADR-086 D6: the public paragraph (state, causes recorded here, pull); nothing at a quiet band.
        mood = interpret(ledger.model, ledger.projection(), visibility.PUBLIC, scope=scene.get('scope_key'))
        if mood:
            out['mood'] = mood.get('心情') or {key: mood[key] for key in ('label', 'face', 'policy') if mood.get(key)}
    return out


def system(store, persona):
    """Shared rules, then who she is: her core sentences (public), not her persona's rules for talking; small, so a cold
    read is cheap (owner 2026-10-14: the gate only answers whether to join, she judges in her turn)."""
    from .documents import DocumentStore, render_markdown
    from .render import common_text, readable_sections
    from . import visibility
    name = (store.config.get('chat') or {}).get('display_name') or persona
    _, content = DocumentStore(store, persona).read('core')
    sections = readable_sections(content, visibility.PUBLIC)
    return common_text(store.config) + '\n你是' + name + '。' + ('\n' + render_markdown(sections) if sections else '')


# What of this group's own context the gate reads, cut at the same place every time: the same line in the same group
# is judged on the same text (her condition, 2026-10-14).
NOTES_CHARS = 800
UNDERSTANDING_CHARS = 400


def _cut(text, limit):
    text = str(text or '').strip()
    return text if len(text) <= limit else text[:limit] + '…'


def group_notes(store, persona, scene):
    """Her notes about this group: the always-shown sections in their order, headings and bodies, the first
    NOTES_CHARS characters."""
    from .context_budget import shown
    from .documents import DocumentStore
    from .group_admin import notes_slug
    _, content = DocumentStore(store, persona).read(notes_slug(scene['_id']))
    sections = shown((content or {}).get('sections') or [])
    text = '\n'.join('%s：%s' % (s.get('heading') or s['sid'], ' '.join(str(s.get('body') or '').split())) for s in sections)
    return _cut(text, NOTES_CHARS) if text else None


def speaker_understanding(store, scene, person_id):
    """Her lines about the speaker (ADR-082): the person layer's short, then this group's, each the body while it has
    no short; cut at UNDERSTANDING_CHARS. Nothing from her other conversations."""
    from . import understanding
    person, here = understanding.layers(store, scene, person_id)
    parts = [str(understanding.line(pair) or '').strip() for pair in (person, here)]
    text = '\n'.join(part for part in parts if part)
    return _cut(text, UNDERSTANDING_CHARS) if text else None


def instruction(config):
    return prompt_path(config, 'stage_attend.md').read_text(encoding='utf-8')


NEED = '只有一行：以「接话」或「不理」开头，后面用一句短话说为什么'


def check(text):
    """The verdict of an answer whose first line starts with 接话 or 不理; anything else is a mistake the
    gate tells back to her (answers.py)."""
    first = next((line.strip() for line in str(text or '').splitlines() if line.strip()), '')
    if not any(first.startswith(word) for word in CHOICES):
        raise ValueError('上一条第一行是「%s」，没有以「接话」或「不理」开头。' % excerpt(first, REASON_LIMIT))
    return parse(text)


def parse(text):
    """{'choice': 'join'|'quiet', 'reason': words}; anything she did not answer as 接话 counts as 不理."""
    first = next((line.strip() for line in str(text or '').splitlines() if line.strip()), '')
    for word, choice in CHOICES.items():
        if first.startswith(word):
            return {'choice': choice, 'reason': excerpt(first[len(word):].lstrip('：:，,。 ').strip(), REASON_LIMIT)}
    return {'choice': 'quiet', 'reason': '没有按 接话／不理 回答', 'unparsed': excerpt(first, REASON_LIMIT)}
