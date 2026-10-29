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
from .records.view import ANY, View, fenced, is_text, pinned
from .store.words import Increase, Not

WAKE, NOTE = 'wake', 'note'
TEXT_CHARS = 800


# ── the owner of `developer_inbox` ──
# Read and written only through these: a row as stored (`fields` names what to return; `_id` always comes back). None
# follows the store's rule (ADR-104 section 4): an id or the persona given None, or a value not of its kind, finds
# nothing without a read; a level given None finds the rows without one. Views are `View`s, in the replaced read's
# order.
COLLECTION = 'developer_inbox'


def get(store, message_id, fields=None):
    """The row with this id, or None."""
    return store.collection(COLLECTION).get(message_id, fields) if is_text(message_id) else None


def of_persona(store, persona):
    """View: a persona's rows that the program did not leave (`source.by` other than `program`, or none)."""
    return View(store, COLLECTION, fenced({'source.by': Not('program')}, {'persona': (persona, is_text)}))


def bump(store, message_id):
    """One more of the failures a program note stands for (its `count`, outside a revision)."""
    if is_text(message_id):
        store.collection(COLLECTION).update({'_id': message_id}, Increase('count'))


def save(store, row, **kwargs):
    """The revisioned write of a row (`Store.put`: `expected`, `stream`)."""
    return store.put(COLLECTION, row, **kwargs)



def leave(store, persona, level, text, *, key, source):
    """One note from the program (idempotent by key)."""
    message_id = 'dev-' + sha(canonical(key))[:32]
    row = get(store, message_id)
    if row:
        return row
    row = save(store, {'_id': message_id, 'persona': persona, 'level': level, 'text': text,
                                        'state': 'new', 'source': source, 'created_at': clock.now().isoformat(),
                                        'scope_key': visibility.owner_private_scope(persona)}, stream=message_id)
    store.audit(message_id, 'developer.message', {'level': level, 'chars': len(text), **source},
                visibility.owner_private_scope(persona))
    return row


def unread(store, level=ANY):
    """For the developer: messages not yet seen (of this level), oldest first."""
    return View(store, COLLECTION, pinned({'state': 'new'}, {'level': (level, is_text)}), (('created_at', 1),)).rows()


def mark(store, message_id, state):
    """The developer saw or answered a message."""
    if state not in ('seen', 'answered'):
        raise ValueError('DEVELOPER_STATE_INVALID: state 只能是 seen 或 answered')
    row = get(store, message_id)
    if not row:
        raise ValueError('DEVELOPER_MESSAGE_UNKNOWN: 没有 %s' % message_id)
    return save(store, {**row, 'state': state, state + '_at': clock.now().isoformat()},
                expected=row['revision'], stream=message_id)
