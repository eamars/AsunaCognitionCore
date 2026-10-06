"""The relevance gate (owner direction 2026-10-04): may she let a group message pass?

A group turn nobody addressed to her (the proactive rules fired, a reply inside a thread she was in, or her
name without an @) first asks her one short question in her own small per-group session: 接话 or 不理. Only
接话 starts the full turn with its recall, monologue and decision. An @ or a reply to her skips the gate.

The gate reads words only: why she is being asked, who is talking and how well she knows them, what was
said here since she last spoke (bounded), and her mood. Nothing is recalled, and the group's own
conversation is not touched, so its cached prefix stays as it was.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .config import ago, character_id, excerpt, prompt_path

# Why she is being asked, in words; any other wake reason runs the full turn as before.
GATED = {
    'proactive_unprompted': '群里在聊，没人叫你；按群里的节奏，这会儿可以插一句',
    'reply_in_active_topic': '有人在你说过话的那条线里接话，不是回你',
    'name_called': '有人提到了你的名字，但没有 @ 你',
    'chain': '群里在跟队形：好几个人接连发了同一句或同一张，没人叫你',
    'awaited_answer': '你刚在这里问了人、说了在等回话；这句没 @ 你也没引用你，可能是在回你，也可能不是',
}
CHOICES = {'接话': 'join', '不理': 'quiet'}
# Catch-up: the lines since she last spoke here, reaching back at least 10 and at most 60 minutes.
WINDOW_MIN_MINUTES, WINDOW_MAX_MINUTES = 10, 60
MAX_LINES, MAX_CHARS = 40, 4000
REASON_LIMIT = 60


def gated(scene, event):
    return scene.get('kind') == 'group' and (event.get('group_context') or {}).get('wake_reason') in GATED


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
         'scene_id': 1, 'event': 1}).sort('scene_seq', -1).limit(MAX_LINES))
    floor = now_ts - WINDOW_MAX_MINUTES * 60
    always = now_ts - WINDOW_MIN_MINUTES * 60
    since = (mine or {}).get('scene_seq') or 0
    people, kept, used = People(store), [], 0
    for row in rows:                                         # newest first, then put back in order
        at = _seconds(row.get('received_at') or row.get('receipt_at'))
        if at is None or at < floor or (row['scene_seq'] <= since and at < always):
            break
        if row['direction'] == 'outbound':
            text = '你：' + ' '.join(str(row.get('text') or '').split())
        else:
            text = people.transcript(scene, row)
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
           'lines': lines or [people.transcript(scene, row)]}
    from .affect import AffectLedger, interpret
    from .render import model_and_policy
    from . import visibility
    model, policy = model_and_policy(store, persona)
    ledger = AffectLedger(store, persona, model, policy)
    if ledger.enabled:
        mood = interpret(ledger.model, ledger.projection(), visibility.PUBLIC)
        out['mood'] = {key: mood[key] for key in ('label', 'face', 'policy') if mood.get(key)}
    return out


def system(store, persona):
    """Shared rules, then who she is (public every-turn persona sections); small, so a cold read is cheap."""
    from .documents import DocumentStore, render_markdown
    from .render import common_text, readable_sections
    from . import visibility
    name = (store.config.get('chat') or {}).get('display_name') or persona
    _, content = DocumentStore(store, persona).read('persona')
    sections = readable_sections(content, visibility.PUBLIC)
    return common_text(store.config) + '\n你是' + name + '。' + ('\n' + render_markdown(sections) if sections else '')


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
