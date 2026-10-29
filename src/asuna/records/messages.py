"""The owner of `messages`: the lines of every conversation (what people wrote, her lines and where they are on their
way, the program's own lines), read and written only through these operations.

A read is a view: a named question with its natural order, answered through its verbs `rows` (`each` as they
come), `first`, `count` and `values` (`View`). A view's order is its `by` field (`by=None`: the database's order); `newest_first` turns it.
`get` and the other single reads return a record as stored (`fields` names what to return, `_id` always comes back).
None follows the store's rule (ADR-104 section 4): an id, a fence (a conversation or several, an epoch, a scope, the
lines or authors read) or a bound of a window (positions, times) given None, or a value not of its kind, finds nothing
without a read; a value condition (a direction, a channel, a delivery state, a topic, a wake reason, ...) given None
finds the lines whose field is null or missing. A parameter not given is `ANY` (records.view). `save` is the
revisioned write (`Store.put`); the other writes each change one mark of a line.

The words of a view: "people" are everyone but the program (`PROGRAM_AUTHOR`, the author of its own lines); an
author condition given to a view replaces "people only". "Said" is what people wrote and her delivered lines.
"""
from ..store.words import (And, AnyOf, Contains, Each, Exists, Holds, IsNull, NonEmpty, NoneOf, Not, Or, Range, Set,
                           StartsWith)

from .view import ANY as _ANY, redact

COLLECTION = 'messages'
# A line's author is who wrote it (ADR-089): the program for every row it makes.
PROGRAM_AUTHOR = 'asuna:internal'
INBOUND, OUTBOUND, ARCHIVED = 'inbound', 'outbound', 'archived'
DELIVERED, SPEAK = 'DELIVERED', 'SPEAK'


def _rows(store):
    return store.collection(COLLECTION)


def _text(value):
    return isinstance(value, str) and bool(value)


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _texts(values):
    return [value for value in values if _text(value)]


class View:
    """A named read: its condition and its order (`by`, ascending; None leaves it to the database). `where` None is
    a question nothing can answer (a fence that holds nothing): every verb answers it without a read."""

    def __init__(self, store, where, by='scene_seq', then=()):
        self.store, self.where = store, where
        self.order = (((by, 1),) if by else ()) + tuple(then)

    def _sort(self, newest_first):
        return tuple((path, -direction) for path, direction in self.order) if newest_first else self.order

    def rows(self, newest_first=False, limit=None, skip=0, fields=None):
        return list(self.each(newest_first, limit, skip, fields))

    def each(self, newest_first=False, limit=None, skip=0, fields=None):
        """The rows, read as they come (for a read too large to hold at once)."""
        if self.where is None:
            return iter(())
        return _rows(self.store).find(self.where, self._sort(newest_first), skip, limit, fields)

    def first(self, newest_first=False, fields=None):
        return next(iter(self.rows(newest_first, 1, 0, fields)), None)

    def count(self, limit=None):
        return 0 if self.where is None else _rows(self.store).count(self.where, limit)

    def values(self, field):
        """The distinct values of `field` among the view's lines (lines without it left out), ascending."""
        return [] if self.where is None else _rows(self.store).group(self.where, field, total=None)


def _window(path, holds, **bounds):
    """{path: Range} of the bounds given (gt, gte, lte, lt), {} when none is; None when a bound given does not hold
    (None included): a bound given None holds nothing."""
    given = {word: value for word, value in bounds.items() if value is not _ANY}
    if not all(holds(value) for value in given.values()):
        return None
    return {path: Range(**given)} if given else {}


def _positions(after=_ANY, from_seq=_ANY, upto=_ANY, before=_ANY):
    """The scene_seq window: after (>), from_seq (>=), upto (<=), before (<)."""
    return _window('scene_seq', _number, gt=after, gte=from_seq, lte=upto, lt=before)


def _with(where, *parts):
    """`where` with more entries (a dict each); None when it or one of them holds nothing."""
    if where is None or any(part is None for part in parts):
        return None
    for part in parts:
        where.update(part)
    return where


def _value(path, value, extra):
    """A value condition: {path: value}, or for None the field null or missing (appended to `extra`); {} not given."""
    if value is _ANY:
        return {}
    if value is None:
        extra.append(Or({path: IsNull()}, {path: Exists(False)}))
        return {}
    return {path: value}


def _fence(where, scene=_ANY, epoch=_ANY, scenes=_ANY, scope=_ANY):
    """`where` with the conversation and epoch fences; None when a fence given holds nothing."""
    if scene is not _ANY:
        if not _text(scene):
            return None
        where['scene_id'] = scene
    if scenes is not _ANY:
        if not isinstance(scenes, (list, tuple, set)):
            return None
        where['scene_id'] = AnyOf(_texts(scenes))
    if epoch is not _ANY:
        if not _number(epoch):
            return None
        where['policy_epoch'] = epoch
    if scope is not _ANY:
        if not _text(scope):
            return None
        where['scope_key'] = scope
    return where


def _authors(where, author=_ANY, authors=_ANY, not_author=None, people_only=False):
    """`where` with its author condition: an author condition given replaces "people only" (the program's lines
    left out). None when the author given is no author (nothing is by them)."""
    if author is not _ANY:
        if not _text(author):
            return None
        where['author'] = author
    elif authors is not _ANY:
        if not isinstance(authors, (list, tuple, set)):
            return None
        where['author'] = AnyOf(_texts(authors))
    elif not_author is not None:
        where['author'] = Not(not_author)
    elif people_only:
        where['author'] = Not(PROGRAM_AUTHOR)
    return where


# Single lines.

def get(store, line_id, fields=None, *, scene=_ANY, epoch=_ANY, scope=_ANY, direction=_ANY, channel=_ANY,
        from_channel=False):
    """The line with this id (within the fences given: a conversation, epoch, scope, direction, channel, or a line
    that came from a channel), or None."""
    if not _text(line_id):
        return None
    if scene is _ANY and epoch is _ANY and scope is _ANY and direction is _ANY and channel is _ANY \
            and not from_channel:
        return _rows(store).get(line_id, fields)
    extra = []
    where = _with(_fence({'_id': line_id}, scene, epoch, scope=scope), _value('direction', direction, extra),
                  _value('channel_id', channel, extra))
    if where is None:
        return None
    if from_channel:
        where['event.channel'] = Exists(True)
    return next(_rows(store).find(And(where, *extra) if extra else where, fields=fields, limit=1), None)


def many(store, line_ids, *, scene=_ANY, scenes=_ANY, epoch=_ANY, since=_ANY, by=None):
    """View: the lines with these ids (within a conversation or several and an epoch, or received since a time)."""
    where = _fence({'_id': AnyOf(sorted(set(_texts(line_ids))))}, scene, epoch)
    if where is not None and scenes is not _ANY:
        where = {**where, 'scene_id': _scenes(scenes)} if isinstance(scenes, (list, tuple, set)) else None
    return View(store, _with(where, _window('received_at', _text, gte=since)), by)


def at(store, scene, seq, *, author=_ANY, direction=_ANY, fields=None):
    """The line at this position of a conversation (by this author, in this direction), or None."""
    if not _text(scene) or not _number(seq):
        return None
    extra = []
    where = _with(_authors({'scene_id': scene, 'scene_seq': seq}, author), _value('direction', direction, extra))
    if where is None:
        return None
    return next(_rows(store).find(And(where, *extra) if extra else where, fields=fields, limit=1), None)


# What people saw.

def _said(inbound=None):
    return Or({'direction': INBOUND, **(inbound or {})}, {'direction': OUTBOUND, 'delivery_state': DELIVERED})


def said(store, scene=_ANY, epoch=_ANY, *, people_only=False, heard_before=_ANY, after=_ANY, from_seq=_ANY,
         upto=_ANY, topic=_ANY, unsummarised=False, by='scene_seq'):
    """View: a conversation as people saw it in an epoch: the lines people wrote and her delivered lines. People
    only: not the program's lines; `heard_before`: people's lines only before that position (hers all); `topic`:
    the lines of one topic thread; `unsummarised`: not yet in a summary."""
    extra = []
    positions = _positions(after, from_seq, upto)
    where = _with(_fence(positions, scene, epoch) if positions is not None else None,
                  _value('event.group_context.topic_id', topic, extra))
    inbound = _positions(before=heard_before)
    if where is None or inbound is None:
        return View(store, None)
    _authors(where, people_only=people_only)
    if unsummarised:
        where['summary_batch_id'] = Exists(False)
    parts = ([where] if where else []) + extra + [_said(inbound)]
    return View(store, And(*parts) if len(parts) > 1 else parts[0], by)


def said_across(store, heard_in, spoken_in, *, by='received_at'):
    """View: what people wrote in some conversations and her delivered lines in others."""
    return View(store, Or({'scene_id': AnyOf(_texts(heard_in)), 'direction': INBOUND},
                          {'scene_id': AnyOf(_texts(spoken_in)), 'direction': OUTBOUND,
                           'delivery_state': DELIVERED}), by)


def said_in_sources(store, sources, *, line=_ANY, lines=_ANY, search=None, by='occurred_at'):
    """View: the lines of these sources (conversations and the epochs read there, {scene_id, policy_epoch}) that
    people wrote or she delivered, people only (the Web memory page's source lines); one by id, several by ids, or
    those whose text contains `search` (case-blind). Newest first by `occurred_at`, then `_id`."""
    branches = []
    for source in sources:
        if _text(source.get('scene_id')) and _number(source.get('policy_epoch')):
            branches.append({'scene_id': source['scene_id'], 'policy_epoch': source['policy_epoch']})
    if not branches:
        return View(store, None)
    where = [Or(*branches), {'author': Not(PROGRAM_AUTHOR)}, _said()]
    if line is not _ANY:
        if not _text(line):
            return View(store, None)
        where.append({'_id': line})
    if lines is not _ANY:
        if not isinstance(lines, (list, tuple, set)):
            return View(store, None)
        where.append({'_id': AnyOf(_texts(lines))})
    if search:
        where.append({'text': Contains(search, case=False)})
    return View(store, And(*where), by, then=(('_id', 1),) if by else ())


POINTABLE = Or({'direction': INBOUND, 'event.raw.asuna_notice': Exists(False), 'author': Not(PROGRAM_AUTHOR)},
               {'direction': OUTBOUND, 'delivery_state': DELIVERED})


def pointable(store, scene, *, line=_ANY, seq=_ANY, by='scene_seq'):
    """View: the lines one may point at in a conversation: people's lines that are not notices, her delivered
    lines; one by id or by position."""
    if not _text(scene):
        return View(store, None)
    where = {'scene_id': scene}
    if line is not _ANY:
        if not _text(line):
            return View(store, None)
        where['_id'] = line
    if seq is not _ANY:
        if not _number(seq):
            return View(store, None)
        where['scene_seq'] = seq
    return View(store, And(where, POINTABLE), by)


def lines(store, scene=_ANY, epoch=_ANY, *, live=False, after=_ANY, from_seq=_ANY, upto=_ANY, before=_ANY,
          group_name=False, by='scene_seq'):
    """View: a conversation's lines (`live`: only those in and out, not the program's internal ones nor archived
    ones), after or between positions; `group_name`: those that carry the group's name."""
    positions = _positions(after, from_seq, upto, before)
    where = _fence(positions, scene, epoch) if positions is not None else None
    if where is not None and group_name:
        where['event.raw.group_name'] = Exists(True)
    if where is None or not live:
        return View(store, where, by)
    return View(store, And(where, Or({'direction': INBOUND}, {'direction': OUTBOUND})), by)


# What people wrote.

def inbound(store, scene=_ANY, epoch=_ANY, *, scenes=_ANY, besides=None, author=_ANY, authors=_ANY, not_author=None,
            people_only=False, after=_ANY, from_seq=_ANY, upto=_ANY, before=_ANY, since=_ANY, since_after=_ANY,
            until=_ANY, wake=_ANY, wakes=_ANY, media=False, no_notice=False, peer=False, group_name=False,
            peer_display=False, asides=None, forward=_ANY, peer_named=_ANY, answers_question=_ANY,
            no_answer_mark=False, not_outcome=None, answers_to=_ANY, by='scene_seq'):
    """View: lines people wrote, in one conversation or several (`scenes`; `besides` all but one); by author (one,
    several, all but one, people only), in a window of positions or of the times they came (`since` >=, `since_after` >,
    `until` <=), woken for a reason (`wake`, `wakes`), and with marks: a picture (`media`), not a platform notice
    (`no_notice`), a peer card (`peer`), the group's name (`group_name`), a peer's shown name (`peer_display`), an
    aside (`asides` True) or not one (False), a forward (`forward`, its ref), a peer's name in a card, nickname,
    shown name or alias (`peer_named`), an answer to a question (`answers_question`) or no answer mark at all
    (`no_answer_mark`), not left with an outcome (`not_outcome`), and answering her question (`answers_to`: her
    lines' ids and platform ids, a wait it woke, a reaction)."""
    extra = []
    where = _fence({'direction': INBOUND}, scene, epoch, scenes)
    if where is not None and besides is not None:
        where['scene_id'] = Not(besides)
    where = _with(where, _positions(after, from_seq, upto, before),
                  _window('received_at', _text, gte=since, gt=since_after, lte=until),
                  _value('event.group_context.wake_reason', wake, extra),
                  _value('event.raw.asuna_answer.question', answers_question, extra))
    if where is None or _authors(where, author, authors, not_author, people_only) is None:
        return View(store, None)
    if wakes is not _ANY:
        if not isinstance(wakes, (list, tuple, set)):
            return View(store, None)
        where['event.group_context.wake_reason'] = AnyOf(list(wakes))
    if media:
        where['event.raw.asuna_media'] = Exists(True)
    if no_notice:
        where['event.raw.asuna_notice'] = Exists(False)
    if peer:
        where['event.raw.asuna_peer'] = Exists(True)
    if group_name:
        where['event.raw.group_name'] = Exists(True)
    if peer_display:
        where['event.raw.asuna_peer.display'] = Exists(True)
    if asides is True:
        where['event.raw.asuna_aside'] = True
    elif asides is False:
        where['event.raw.asuna_aside'] = Not(True)
    if forward is not _ANY:
        if not _text(forward):
            return View(store, None)
        where['event.raw.asuna_forward'] = Each({'ref': forward})
    if no_answer_mark:
        where['event.raw.asuna_answer'] = Exists(False)
    if not_outcome is not None:
        where['processing_outcome'] = Not(not_outcome)
    if peer_named is not _ANY:
        if not _text(peer_named):
            return View(store, None)
        extra.append(Or(*[{'event.raw.asuna_peer.' + key: peer_named} for key in ('card', 'nickname', 'display')],
                        {'event.raw.asuna_peer.aliases': Holds(peer_named)}))
    if answers_to is not _ANY:
        if not isinstance(answers_to, (list, tuple)) or len(answers_to) != 2:
            return View(store, None)
        ids, platform = answers_to
        extra.append(Or({'event.group_context.reply_message_id': AnyOf(_texts(ids))},
                        {'event.group_context.wake_reason': 'question_wait'},
                        {'event.raw.asuna_notice.kind': 'reaction',
                         'event.raw.asuna_notice.line.message_id': AnyOf(_texts(platform))}))
    return View(store, And(where, *extra) if extra else where, by)


def woken(store, scene, reason, *, after):
    """The first line of a conversation after a position that woke her for this reason (its id only), or None."""
    if not _text(scene) or not _number(after):
        return None
    return next(_rows(store).find({'scene_id': scene, 'scene_seq': Range(gt=after),
                                   'event.group_context.wake_reason': reason}, fields=['_id'], limit=1), None)


def mentions(store, scene, since):
    """View: a conversation's lines that @-mention accounts, received since a time."""
    if not _text(scene) or not _text(since):
        return View(store, None)
    return View(store, {'scene_id': scene, 'received_at': Range(gte=since),
                        'event.group_context.mentioned_account_ids': NonEmpty()}, None)


def authors(store, scene=_ANY, epoch=_ANY, *, scenes=_ANY, direction=_ANY, live_only=False, among=_ANY, named=None):
    """Values: who wrote in one conversation or several (in a direction; archived lines not deleted; among these
    authors or under this historical name)."""
    extra = []
    where = _with(_fence({}, scene, epoch, scenes), _value('direction', direction, extra))
    if where is None:
        return []
    if extra:
        where = And(where, *extra)
    if live_only:
        where = And(where, {'deletion_id': Exists(False)}) if isinstance(where, And) else {**where,
                                                                                         'deletion_id': Exists(False)}
    if among is not _ANY and not isinstance(among, (list, tuple, set)):
        return []
    branches = ([{'author': AnyOf(_texts(among))}] if among is not _ANY else []) + (
        [{'historical_display_name': named}] if _text(named) else [])
    if branches:
        where = And(where, Or(*branches))
    return View(store, where, None).values('author')


# Her lines.

def spoken(store, scene=_ANY, epoch=_ANY, *, author=_ANY, delivered=True, speech=False, receipt_since=_ANY,
           with_receipt=False, not_in=None, by='scene_seq'):
    """View: her lines (delivered, or every one of her speech when `delivered` is False and `speech`), in one
    conversation or all of them but `not_in`, by this author, with a receipt (since a time)."""
    where = _fence({'direction': OUTBOUND}, scene, epoch)
    if where is None:
        return View(store, None)
    if delivered:
        where['delivery_state'] = DELIVERED
    if speech:
        where['phase'] = SPEAK
    if _authors(where, author) is None:
        return View(store, None)
    if receipt_since is not _ANY:
        if not _text(receipt_since):
            return View(store, None)
        where['receipt_at'] = Range(gte=receipt_since)
    elif with_receipt:
        where['receipt_at'] = Exists(True)
    if not_in is not None:
        where['scene_id'] = NoneOf(_texts(not_in))
    return View(store, where, by)


def outgoing(store, scene, states, *, by='scene_seq'):
    """View: her lines in a conversation in these delivery states."""
    if not _text(scene):
        return View(store, None)
    return View(store, {'scene_id': scene, 'direction': OUTBOUND, 'delivery_state': AnyOf(list(states))}, by)


def turn_parts(store, episode, *, scene=_ANY, speech=True, outbound=False, delivered=False, state=_ANY, states=_ANY,
               not_states=None, reply_parts=False, after_segment=_ANY, before_segment=_ANY, by='scene_seq'):
    """View: the lines one turn produced: its speech (`speech`), outbound only, delivered or in a delivery state
    (`state`, one of `states`, none of `not_states`), its reply parts, the parts after or before a segment."""
    if not _text(episode):
        return View(store, None)
    extra = []
    where = _with(_fence({'episode_id': episode}, scene),
                  _window('segment_index', _number, gt=after_segment, lt=before_segment))
    if where is None:
        return View(store, None)
    if speech:
        where['phase'] = SPEAK
    if outbound:
        where['direction'] = OUTBOUND
    if delivered:
        where['delivery_state'] = DELIVERED
    elif state is not _ANY:
        where.update(_value('delivery_state', state, extra))
    elif states is not _ANY:
        if not isinstance(states, (list, tuple, set)):
            return View(store, None)
        where['delivery_state'] = AnyOf(list(states))
    elif not_states is not None:
        where['delivery_state'] = NoneOf(list(not_states))
    if reply_parts:
        where['reply_part'] = True
    return View(store, And(where, *extra) if extra else where, by)


def unsettled(store):
    """Count: her lines still queued for a channel or being sent."""
    return _rows(store).count({'direction': OUTBOUND, 'delivery_state': AnyOf(['QUEUED_EXTERNAL', 'SENDING'])})


# Lines by the platform's ids.

def of_event(store, scene, epoch, event_id, fields=None):
    """The line of a conversation and epoch whose event has this id, or None."""
    where = _fence({'event.event_id': event_id}, scene, epoch)
    return None if where is None or not _text(event_id) else next(_rows(store).find(where, fields=fields, limit=1),
                                                                    None)


def by_platform_id(store, scene, epoch=_ANY, *, platform_id, author=_ANY, delivered_only=True, by=None):
    """View: a conversation's lines (in an epoch) that the platform knows by this id: people's by its event id, hers
    (delivered, by this author) by its message id."""
    where = _fence({}, scene, epoch)
    if where is None or not _text(platform_id):
        return View(store, None)
    mine = {'direction': OUTBOUND, 'platform_message_id': platform_id}
    if delivered_only:
        mine['delivery_state'] = DELIVERED
    if author is not _ANY:
        if not _text(author):
            return View(store, None)
        mine['author'] = author
    return View(store, And(where, Or({'direction': INBOUND, 'event.channel.platform_event_id': platform_id}, mine)),
                by)


def quoted(store, scene, platform_id, *, mine, since):
    """The line a platform notice is about, newest first: hers by its message id however old (`mine`), else
    anyone's within a time (people's by received time, hers by receipt time); None when there is none."""
    if not _text(scene) or not _text(platform_id) or not _text(since):
        return None
    fields = ['_id', 'text', 'author', 'direction', 'scene_seq']
    found = None
    if mine:
        found = View(store, {'scene_id': scene, 'direction': OUTBOUND, 'platform_message_id': platform_id}).first(
            newest_first=True, fields=fields)
    return found or View(store, And({'scene_id': scene}, Or(
        {'direction': INBOUND, 'event.channel.platform_event_id': platform_id, 'received_at': Range(gte=since)},
        {'direction': OUTBOUND, 'platform_message_id': platform_id, 'receipt_at': Range(gte=since)}))).first(
        newest_first=True, fields=fields)


def referenced(store, scene, epoch, reference, fields=None):
    """The line of a conversation and epoch a reference names: by its own id, its platform event id or its platform
    message id; None when none does."""
    where = _fence({}, scene, epoch)
    if where is None or not _text(reference):
        return None
    return next(_rows(store).find(And(where, Or({'_id': reference}, {'event.channel.platform_event_id': reference},
                                                {'platform_message_id': reference})), fields=fields, limit=1), None)


def of_platform_event(store, platform_event_id, fields=None):
    """The lines stored for this platform event id."""
    if not _text(platform_event_id):
        return []
    return View(store, {'platform_event_id': platform_event_id}, None).rows(fields=fields)


# A channel's outbox.

def queued(store, channel, *, files=None, target=_ANY):
    """View: a channel's lines queued for it (`files` True: only files, False: no files), for one route's target."""
    if not _text(channel):
        return View(store, None)
    where = {'channel_id': channel, 'delivery_state': 'QUEUED_EXTERNAL'}
    if files is not None:
        where['file'] = Exists(files)
    if target is not _ANY:
        if not isinstance(target, dict) or not (_text(target.get('type')) and _text(target.get('id'))):
            return View(store, None)
        where.update({'target.type': target['type'], 'target.id': target['id']})
    return View(store, where, None)


def in_flight_scenes(store, channel, claimed_since):
    """Values: the conversations with a chat line (not a file) out on this channel, claimed since a time."""
    if not _text(channel) or not _text(claimed_since):
        return []
    return View(store, {'channel_id': channel, 'delivery_state': 'SENDING', 'file': Exists(False),
                        'claimed_at': Range(gte=claimed_since)}, None).values('scene_id')


def sending(store):
    """View: the lines left being sent on a channel (what the Host's start settles)."""
    return View(store, {'channel_id': Exists(True), 'delivery_state': 'SENDING'}, None)


def claim_unshown(store, scene, author, at):
    """The oldest line of this author in a conversation not yet shown on its line, marked shown at `at`; or None."""
    return _rows(store).claim({'scene_id': scene, 'direction': INBOUND, 'author': author,
                               'shown_on_line': Exists(False)}, Set({'shown_on_line': at}), sort=[('scene_seq', 1)])


# The Host's inputs.

def ingress(store, states):
    """View: the inputs the Host manages in these ingress states, by when they came."""
    return View(store, {'host_managed': True, 'ingress_state': AnyOf(list(states))}, 'received_at')


def channel_inbound(store, since):
    """View: the inputs the Host manages that came from a channel since a time, by when they came."""
    if not _text(since):
        return View(store, None)
    return View(store, {'host_managed': True, 'received_at': Range(gte=since), 'event.channel': Exists(True)},
                'received_at')


def visits(store, intent, *, since=_ANY):
    """View: her visit lines of this intent (received since a time), by when they came."""
    where = {'event.visit.intent': intent} if _text(intent) else None
    return View(store, _with(where, _window('received_at', _text, gte=since)), 'received_at')


def errand_results(store, scene):
    """View: a conversation's completed errand visits not yet told there, by when they came."""
    if not _text(scene):
        return View(store, None)
    return View(store, {'adapter_id': 'visit', 'scene_id': scene, 'platform_event_id': StartsWith('visit:errand:'),
                        'ingress_state': 'COMPLETE', 'errand_told': Exists(False)}, 'received_at')


# Files and pictures lines name.

def artifact_refs(store, kind, *, states=_ANY):
    """Values: the artifact ids lines name as their picture (`attachment`) or file (`file`), in these delivery
    states."""
    path = kind + '.artifact_id'
    where = {path: Exists(True)}
    if states is not _ANY:
        if not isinstance(states, (list, tuple, set)):
            return []
        where['delivery_state'] = AnyOf(list(states))
    return View(store, where, None).values(path)


# History search (history_query, discussion_digest).

PERSON_KEYS = ('author', 'event.raw.asuna_peer.person_id', 'event.raw.asuna_peer.card',
               'event.raw.asuna_peer.nickname', 'event.raw.asuna_peer.display', 'event.raw.asuna_peer.aliases')


def _scenes(scene_ids):
    ids = list(dict.fromkeys(_texts(scene_ids)))
    return ids[0] if len(ids) == 1 else AnyOf(ids)


def _person(values):
    """Lines by a person: the author is one of these values, or the peer card names one of them (its aliases hold
    one)."""
    return Or(*[{key: Holds(value) if key.endswith('.aliases') else value} for key in PERSON_KEYS
                for value in values])


def search(store, scene_ids, epoch, stream, *, text=None, case=True, author=None, authors=None, person=None,
           window=None, after=None, after_too=None, receipts=None, limit=None):
    """History search: one stream's lines of these conversations in an epoch, newest first by the stream's time,
    then position and conversation. Streams: `inbound` (people's lines by `occurred_at`; text in the line or in a
    forward it carried), `outbound` (her delivered speech by `receipt_at`), `receipt` (her delivered speech without
    `receipt_at` that names one of `receipts`, by position) and `archived` (archived lines not deleted, by
    `occurred_at`; their `legacy` copy left out). `authors` (resolved ids) or `person` (values a person may be known
    by) narrow it; `window` is (from, to) of the stream's time; `after` the cursor (time, position[, conversation]):
    the lines after it in the stream's order, a part of it that is None standing for a line without that field.
    `after_too`: a second cursor the lines also come after (the archived stream's known defect, kept in B4: see
    history_query.search_messages)."""
    ids = list(dict.fromkeys(_texts(scene_ids)))
    if not ids or not _number(epoch):
        return []
    clock = {'inbound': 'occurred_at', 'outbound': 'receipt_at', 'archived': 'occurred_at'}.get(stream)
    if stream == 'archived':
        where = {'scene_id': AnyOf(['archive:' + sid for sid in ids])}
    else:
        where = {'scene_id': _scenes(ids)}
    where['policy_epoch'] = epoch
    if author:
        where['author'] = author
    found = Contains(text, case=case) if text else None
    if stream in ('inbound', 'archived'):
        where['direction'] = INBOUND if stream == 'inbound' else ARCHIVED
        if stream == 'archived':
            where['deletion_id'] = Exists(False)
    else:
        where.update({'direction': OUTBOUND, 'phase': SPEAK, 'delivery_state': DELIVERED})
    if stream == 'receipt':
        where['receipt'] = AnyOf(sorted(_texts(receipts or ())))
        where['receipt_at'] = Exists(False)
    elif window:
        bounds = {name: value for name, value in zip(('gte', 'lte'), window) if value}
        if bounds:
            where[clock] = Range(**bounds)
    extra = []
    if found is not None:
        if stream == 'outbound' or stream == 'receipt':
            where['text'] = found
        else:
            extra.append(Or({'text': found}, {'event.raw.asuna_forward': Each({'nodes': Each({'text': found})})}))
    if authors is not None:
        extra.append({'author': AnyOf(_texts(authors))})
    elif person:
        extra.append(_person(person))
    if after_too and clock:
        extra.append(_after(clock, after_too))
    if after and clock:
        extra.append(_after(clock, after))
    order = (('scene_seq', -1), ('scene_id', -1)) if stream == 'receipt' else (
        (clock, -1), ('scene_seq', -1), ('scene_id', -1))
    rows = _rows(store).find(And(where, *extra) if extra else where, order, 0, limit)
    if stream == 'archived':
        return [{key: value for key, value in row.items() if key != 'legacy'} for row in rows]
    return list(rows)


def _all(*parts):
    """Every part holds: one condition when the parts are plain entries, else their And."""
    if all(isinstance(part, dict) for part in parts):
        return {key: test for part in parts for key, test in part.items()}
    return And(*parts)


def _same(path, value):
    """Equal to the value, or (None) without one: missing or null."""
    return {path: value} if value is not None else Or({path: Exists(False)}, {path: IsNull()})


def _after(clock, cursor):
    """After the cursor (time, position[, conversation]) going newest first: an earlier time; the same time and an
    earlier position; the same of both and an earlier conversation. Nothing is earlier than a missing value."""
    at, seq = cursor[0], cursor[1]
    branches = []
    if at is not None:
        branches.append({clock: Range(lt=at)})
    if seq is not None:
        branches.append(_all(_same(clock, at), {'scene_seq': Range(lt=seq)}))
    if len(cursor) > 2 and cursor[2] is not None:
        branches.append(_all(_same(clock, at), _same('scene_seq', seq), {'scene_id': Range(lt=cursor[2])}))
    # a cursor with nothing earlier than it: the (impossible) missing _id
    return Or(*branches) if branches else {'_id': Exists(False)}


def thread(store, scene_ids, epoch, *, replying_to=(), ids=(), fields=None):
    """The lines of these conversations in an epoch that reply to these lines (people's by their quoted line, hers
    by the line she answered), and the lines with these ids (a digest's thread)."""
    if not _number(epoch):
        return []
    targets = sorted(set(_texts(replying_to)))
    branches = [{key: AnyOf(targets)} for key in ('event.group_context.reply_message_id', 'reply_to')]
    if ids:
        branches.append({'_id': AnyOf(sorted(set(_texts(ids))))})
    where = {'scene_id': _scenes(scene_ids), 'policy_epoch': epoch}
    return list(_rows(store).find(And(where, Or(*branches)), fields=fields))


def excluded(store, scene_ids, epoch):
    """Counts of her lines a digest leaves out in these conversations and epoch: speech not delivered
    (`undelivered_outbound`) and lines that are not speech (`non_speak_outbound`)."""
    if not _number(epoch):
        return {'undelivered_outbound': 0, 'non_speak_outbound': 0}
    base = {'scene_id': _scenes(scene_ids), 'policy_epoch': epoch, 'direction': OUTBOUND}
    return {'undelivered_outbound': _rows(store).count({**base, 'phase': SPEAK, 'delivery_state': Not(DELIVERED)}),
            'non_speak_outbound': _rows(store).count({**base, 'phase': Not(SPEAK)})}


# Writes.

def save(store, line, **kwargs):
    """The revisioned write of a whole line (`Store.put`: `expected`, `stream`)."""
    return store.put(COLLECTION, line, **kwargs)


def redact_scope(store, scope, deletion, epoch):
    """An erasure of a scope's lines (`view.redact`)."""
    redact(store, COLLECTION, scope, deletion, epoch)


def mark_recalled(store, line_id, at):
    """Her line was taken back on the platform at `at`."""
    _rows(store).update({'_id': line_id}, Set({'recalled_at': at}))


def note_failure(store, line_id, present, words):
    """A file line whose bytes were gone: whether its original is still there, and the words that say so."""
    _rows(store).update({'_id': line_id}, Set({'source_present': present, 'failure_detail': words}))


def mark_errands_told(store, line_ids, at):
    """These errand visits were told in their conversation at `at`."""
    _rows(store).update({'_id': AnyOf(_texts(line_ids))}, Set({'errand_told': at}), many=True)
