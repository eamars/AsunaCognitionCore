"""Her messages to the developer agent (owner 2026-10-08): the agent that changes her program, not the owner.

From a home turn she leaves a message with `message_developer`: `wake` when she wants the developer soon (it checks
the inbox about hourly while its session is open), `note` for something that can wait for its next visit. The
developer reads `developer_inbox`, marks what it has seen and answered, and replies in her local chat. A message
from outside never reaches here directly: the tool exists only in home turns, so outside words come through her own
review there (ADR-017). Each kind has a daily limit; the audit records each message without its text. The program
also leaves the developer a note here when a task's result could not be handed back to her (handover.py); such a note
is marked `source.by: program`, counts against no limit of hers and is not shown to her as one of her messages.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import visibility
from .evidence import canonical, sha

WAKE, NOTE = 'wake', 'note'
LIMITS = {WAKE: 3, NOTE: 20}                 # per 24 hours
TEXT_CHARS = 800
SHOWN, KEEP_DAYS = 5, 7
STATE_WORDS = {'new': '还没看', 'seen': '看到了，还没回', 'answered': '回了（回话在本机聊天里）'}
BLOCK_NOTE = ('你写给开发代理（改你程序的那位，不是主人）的留言，新的在前。wake 是要他尽快来，note 等他下次来看；'
              '他在本机聊天里回你。')


def _now():
    return datetime.now(timezone.utc)


def leave(store, persona, level, text, *, key, source):
    """One message (idempotent by key). Raises ValueError (coded) over the daily limit."""
    message_id = 'dev-' + sha(canonical(key))[:32]
    row = store.db.developer_inbox.find_one({'_id': message_id})
    if row:
        return row
    since = (_now() - timedelta(hours=24)).isoformat()
    used = store.db.developer_inbox.count_documents({'persona': persona, 'level': level, 'created_at': {'$gte': since},
                                                    'source.by': {'$ne': 'program'}})
    if used >= LIMITS[level]:
        raise ValueError('DEVELOPER_MESSAGE_LIMIT: 24 小时内的 %s 已经 %d 条（上限 %d）；%s'
                         % (level, used, LIMITS[level], '不急的改用 level=note，真急就找主人' if level == WAKE
                            else '攒成一条写，或者等明天'))
    row = store.put('developer_inbox', {'_id': message_id, 'persona': persona, 'level': level, 'text': text,
                                        'state': 'new', 'source': source, 'created_at': _now().isoformat(),
                                        'scope_key': visibility.owner_private_scope(persona)}, stream=message_id)
    store.audit(message_id, 'developer.message', {'level': level, 'chars': len(text), **source},
                visibility.owner_private_scope(persona))
    return row


def block(store, persona, moment=None):
    """developer_inbox_from_program: what came of her recent messages, in words, or None."""
    from .config import ago
    moment = moment or _now()
    since = (moment - timedelta(days=KEEP_DAYS)).isoformat()
    # Hers only: the program's own notes to the developer (handover.py) are not something she wrote.
    rows = list(store.db.developer_inbox.find({'persona': persona, 'created_at': {'$gte': since}, 'source.by': {'$ne': 'program'}})
                .sort('created_at', -1).limit(SHOWN))
    if not rows:
        return None
    items = []
    for row in rows:
        hours = (moment - datetime.fromisoformat(row['created_at'])).total_seconds() / 3600
        items.append({'level': row['level'], 'when': ago(hours), 'text': row['text'][:120],
                      'state': STATE_WORDS.get(row.get('state'), row.get('state'))})
    return {'items': items, 'note': BLOCK_NOTE}


def unread(store, level=None):
    """For the developer: messages not yet seen, oldest first."""
    query = {'state': 'new', **({'level': level} if level else {})}
    return list(store.db.developer_inbox.find(query).sort('created_at', 1))


def mark(store, message_id, state):
    """The developer saw or answered a message."""
    if state not in ('seen', 'answered'):
        raise ValueError('DEVELOPER_STATE_INVALID: state 只能是 seen 或 answered')
    row = store.db.developer_inbox.find_one({'_id': message_id})
    if not row:
        raise ValueError('DEVELOPER_MESSAGE_UNKNOWN: 没有 %s' % message_id)
    return store.put('developer_inbox', {**row, 'state': state, state + '_at': _now().isoformat()},
                     expected=row['revision'], stream=message_id)
