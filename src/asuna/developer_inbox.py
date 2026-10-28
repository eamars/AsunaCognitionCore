"""Notes for the developer agent (the agent that changes her program, not the owner) that the program leaves itself:
when a task's result could not be handed back to her (handover.py), one row in `developer_inbox`, marked
`source.by: program`. The developer reads unseen rows (`unread`) and marks them `seen` or `answered` (`mark`); the
audit records each without its text. Her own questions and reports to the developer are `ask` (questions.py); rows she
left before that are moved into closed questions (questions.migrate).
"""
from __future__ import annotations


from . import clock
from . import visibility
from .evidence import canonical, sha

WAKE, NOTE = 'wake', 'note'
TEXT_CHARS = 800



def leave(store, persona, level, text, *, key, source):
    """One note from the program (idempotent by key)."""
    message_id = 'dev-' + sha(canonical(key))[:32]
    row = store.db.developer_inbox.find_one({'_id': message_id})
    if row:
        return row
    row = store.put('developer_inbox', {'_id': message_id, 'persona': persona, 'level': level, 'text': text,
                                        'state': 'new', 'source': source, 'created_at': clock.now().isoformat(),
                                        'scope_key': visibility.owner_private_scope(persona)}, stream=message_id)
    store.audit(message_id, 'developer.message', {'level': level, 'chars': len(text), **source},
                visibility.owner_private_scope(persona))
    return row


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
    return store.put('developer_inbox', {**row, 'state': state, state + '_at': clock.now().isoformat()},
                     expected=row['revision'], stream=message_id)
