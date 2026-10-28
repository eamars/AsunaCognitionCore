"""The owner of `tasks` and `task_messages`: the work she hands to the action brain (its request, lease, state,
result and hand-back) and the messages between her and the action session about it, read and written only through
these operations.

`get` and `thread_message` return a record as stored (`fields` names what to return, `_id` always comes back),
within the fences given. None follows section 4's rule: an id or a fence (conversation, scope, epoch, requester, the
turn or task whose records are read) given None finds nothing without a read; a value condition (a state, a pause
reason, the side a message came from, whether it was delivered) given None finds the records whose field is null or
missing. The other reads are views (`View`: `rows`, `each`, `first`, `count`), in the replaced read's order (none
where it had none). `save` and `save_message` are the revisioned writes (`Store.put`). `recent_with_inputs` answers what the conversation-context aggregate did, by reads.
"""
from ..store.words import And, AnyOf, Exists, NoneOf, Not, Range, StartsWith
from .view import ANY, View, fenced, is_number, is_text, pinned, texts

COLLECTION, MESSAGES = 'tasks', 'task_messages'
ACTIVE = ('READY', 'RUNNING')
# What the conversation's task list shows of each task (context's task_state_from_program), as the aggregate projected.
SHOWN = ('_id', 'state', 'goal', 'title', 'feedback_state', 'finished_at', 'cancel_reason', 'pause_reason',
         'paused_at', 'tier')
RECENT = 16
INPUTS_A_READ = 1000


def _view(store, where, by=None):
    return View(store, COLLECTION, where, ((by, 1),) if by else ())


def _fences(scene=ANY, scope=ANY, epoch=ANY, requester=ANY):
    return {'scene_id': (scene, is_text), 'scope_key': (scope, is_text), 'policy_epoch': (epoch, is_number),
            'requester_id': (requester, is_text)}


# Single records.

def get(store, task_id, fields=None, *, state=ANY, scene=ANY, scope=ANY, epoch=ANY, requester=ANY):
    """The task with this id (in this state; of this conversation, scope, epoch, requester), or None."""
    if not is_text(task_id):
        return None
    if all(value is ANY for value in (state, scene, scope, epoch, requester)):
        return store.collection(COLLECTION).get(task_id, fields)
    where = pinned(fenced({'_id': task_id}, _fences(scene, scope, epoch, requester)), {'state': (state, is_text)})
    return _view(store, where).first(fields=fields)


def thread_message(store, message_id, *, sender=ANY):
    """The task message with this id (from this side: `character` or `action`), or None."""
    if not is_text(message_id):
        return None
    if sender is ANY:
        return store.collection(MESSAGES).get(message_id)
    where = pinned({'_id': message_id}, {'from': (sender, is_text)})
    return View(store, MESSAGES, where).first()


# Views.

def many(store, task_ids, *, states=None):
    """View: the tasks with these ids (in these states)."""
    where = {'_id': AnyOf(texts(task_ids))}
    if states is not None:
        where['state'] = AnyOf(list(states))
    return _view(store, where)


def in_states(store, states, *, besides=None):
    """View: the tasks in these states (but one); a single state (None: none) as an equality."""
    where = {'_id': Not(besides)} if besides is not None else {}
    if states is None or isinstance(states, str):
        return _view(store, pinned(where, {'state': (states, is_text)}))
    where['state'] = AnyOf(list(states))
    return _view(store, where)


def by_prefix(store, prefix, *, scene, requester, epoch):
    """View: a requester's tasks in a conversation and epoch whose id starts with `prefix`."""
    if not is_text(prefix):
        return _view(store, None)
    return _view(store, fenced({'_id': StartsWith(prefix)}, _fences(scene=scene, epoch=epoch, requester=requester)))


def continuations(store, task_ids):
    """View: the tasks that continue these, in the order they were created."""
    return _view(store, {'continues_task_id': AnyOf(texts(task_ids))}, by='created_at')


def awaiting_feedback(store, finished, taken):
    """The tasks in these finished states whose feedback has a state, and not one of `taken` (the states of a result
    that reached her). Read as the feedback present and not taken; one whose feedback is null is left out after the
    read (the words have no "not null")."""
    where = And({'state': AnyOf(list(finished)), 'feedback_state': Exists(True)},
                {'feedback_state': NoneOf(list(taken))})
    return [row for row in _view(store, where).each() if row.get('feedback_state') is not None]


def lease_expired(store, moment):
    """View: the running tasks whose lease expired before `moment` (seconds since the epoch)."""
    return _view(store, {'state': 'RUNNING', 'lease_expires_at': Range(lt=moment)})


def paused(store, reason, *, states=None, since=None):
    """View: the paused tasks paused for `reason` (that were in these states; paused since a time)."""
    where = {'state': 'PAUSED'}
    if states is not None:
        where['paused_state'] = AnyOf(list(states))
    if since is not None:
        where['paused_at'] = Range(gte=since)
    return _view(store, pinned(where, {'pause_reason': (reason, is_text)}))


def of_conversations(store, scene_ids, by=None):
    """View: the tasks of these conversations (ordered by `by`)."""
    return _view(store, {'scene_id': AnyOf(texts(scene_ids))}, by)


def created(store, since, *, until=None, scenes=None, besides=None, by=None):
    """View: the tasks created since a time (before `until`; of these conversations, an empty list being those of
    none; not of `besides`)."""
    window = Range(gte=since, lt=until) if until is not None else Range(gte=since)
    parts = [{'created_at': window}]
    if besides is not None:
        parts.append({'scene_id': NoneOf(texts(besides))})
    if scenes is not None:
        ids = texts(scenes)
        parts.append({'scene_id': AnyOf(ids)} if ids else pinned({}, {'scene_id': (None, is_text)}))
    return _view(store, parts[0] if len(parts) == 1 else And(*parts), by)


def of_episode(store, episode_id):
    """View: the tasks a turn made."""
    return _view(store, fenced({}, {'episode_id': (episode_id, is_text)}))


def finished_since(store, since, fields=None):
    """A task that finished after a time, or None."""
    return _view(store, {'finished_at': Range(gt=since)}).first(fields=fields)


def of_scope(store, scope_key, fields=None):
    """The tasks of a scope."""
    return _view(store, fenced({}, {'scope_key': (scope_key, is_text)})).rows(fields=fields)


def thread(store, task_id, *, sender=ANY, delivered=ANY):
    """View: a task's messages (from one side; delivered or not), in the order they were written."""
    where = pinned(fenced({}, {'task_id': (task_id, is_text)}),
                   {'from': (sender, is_text), 'delivered': (delivered, lambda value: isinstance(value, bool))})
    return View(store, MESSAGES, where, (('created_at', 1),))


def recent_with_inputs(store, scene_id, scope_key, epoch):
    """A conversation's RECENT most relevant tasks in an epoch: the running and queued first, then by the newest time
    one of their input lines was received (those without one last), then by id; each with the SHOWN fields it has,
    `_active` (1 running or queued, else 0) and `_report_chars` (the length of its result's text). Read as the
    conversation's tasks, then their input lines by id."""
    from . import messages
    where = fenced({}, _fences(scene=scene_id, scope=scope_key, epoch=epoch))
    tasks = _view(store, where).rows(fields=[*SHOWN, 'raw_input_refs', 'result.text'])
    refs = sorted({ref for task in tasks for ref in _refs(task)})
    received = {}
    for start in range(0, len(refs), INPUTS_A_READ):
        for line in messages.many(store, refs[start:start + INPUTS_A_READ]).each(fields=['received_at']):
            received[line['_id']] = line.get('received_at')
    rows = []
    for task in tasks:
        times = [received[ref] for ref in _refs(task) if received.get(ref) is not None]
        text = (task.get('result') or {}).get('text') if isinstance(task.get('result'), dict) else None
        shown = {key: value for key, value in task.items() if key in SHOWN}
        shown['_active'] = 1 if task.get('state') in ACTIVE else 0
        shown['_report_chars'] = len(text) if isinstance(text, str) else 0
        rows.append((shown, max(times) if times else None))
    rows.sort(key=lambda row: row[0]['_id'])
    rows.sort(key=lambda row: (row[0]['_active'], row[1] is not None, row[1] or ''), reverse=True)
    return [shown for shown, _ in rows[:RECENT]]


def _refs(task):
    refs = task.get('raw_input_refs')
    return [ref for ref in (refs if isinstance(refs, list) else [refs]) if is_text(ref)]


# Writes.

def save(store, task, **kwargs):
    """The revisioned write of a whole task (`Store.put`: `expected`, `stream`, `reset_counters`)."""
    return store.put(COLLECTION, task, **kwargs)


def save_message(store, message, **kwargs):
    """The revisioned write of a task message (`Store.put`)."""
    return store.put(MESSAGES, message, **kwargs)
