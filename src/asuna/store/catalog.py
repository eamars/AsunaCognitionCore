"""The catalog: every collection the core keeps, declared once, and the vector spaces searched in them.

A collection declares its fields (path, kind, nullable, required), its indexes, the index names `ensure` drops
(`retired`), its owner module and its flags. Only declared fields can be named in a condition, sort, group or index;
other fields are stored and returned unchanged. A dotted path is a field inside a declared `object`, or inside the
objects of a declared `list` of `object` (queried only through `Each`). A nested required field is required wherever
its parent is present. `CATALOG` holds the core's collections; each is declared when its owner moves onto the store.
"""
from __future__ import annotations
from dataclasses import dataclass, field as _field
from datetime import datetime
from .errors import QueryInvalid

KINDS = ('text', 'number', 'bool', 'time', 'list', 'object', 'vector')
ELEMENTS = ('text', 'number', 'bool', 'time', 'object')
# Words of the JSON form of a condition (words.from_json): no field may be named one of them.
RESERVED = ('or', 'and')


def is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def kind_of(value) -> str:
    """The kind a value is: null, bool, number, text, time, list, object, bytes or other."""
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'bool'
    if is_number(value):
        return 'number'
    if isinstance(value, str):
        return 'text'
    if isinstance(value, datetime):
        return 'time'
    if isinstance(value, list):
        return 'list'
    if isinstance(value, dict):
        return 'object'
    if isinstance(value, bytes):
        return 'bytes'
    return 'other'


def _invalid(why):
    return ValueError('CATALOG_INVALID: ' + why)


@dataclass(frozen=True)
class Field:
    """A declared field: `of` is a list's element kind, `dimensions` a vector's length."""
    path: str
    kind: str
    of: str | None = None
    dimensions: int | None = None
    nullable: bool = False
    required: bool = False

    def holds(self, value) -> bool:
        """Whether a value other than null is of this field's kind."""
        if self.kind == 'vector':
            return (isinstance(value, list) and len(value) == self.dimensions
                    and all(is_number(x) for x in value))
        if self.kind == 'list':
            return isinstance(value, list) and all(self.holds_element(x) for x in value)
        return kind_of(value) == self.kind

    def holds_element(self, value) -> bool:
        return kind_of(value) == self.of


ID = Field('_id', 'text', required=True)


@dataclass(frozen=True)
class Index:
    """An index: `keys` are (path, 1 | -1); a unique index's fields are required, except in a partial one: a
    record missing a field listed in `only_where_present` (or holding null) is outside the index, and inside it the
    other fields may be missing (indexed as null). `expire_after`:
    a server removes a record that many seconds after the time in its one key (a TTL index; the in-memory adapter
    removes nothing)."""
    name: str
    keys: tuple
    unique: bool = False
    only_where_present: tuple = ()
    expire_after: int | None = None


@dataclass(frozen=True)
class Space:
    """Vectors searched by cosine similarity: each record of `collection` holds its vector in `path`, and a search
    may filter on `fields`. A change of dimensions or fields is a new space."""
    name: str
    collection: str
    path: str
    dimensions: int
    fields: tuple


@dataclass(frozen=True)
class Collection:
    """A declared collection. Flags: `versioned` (every record carries `schema_version`), `insert_only` (a ledger),
    `counters` (fields a revisioned write keeps at their stored values), `derived` (fields computed from the record's
    own content, left out of its audit), `pending` (its owner still reads it directly: only the fields the store
    itself names are declared, and its indexes may name fields not declared yet; a unique index's `only_where_present`
    fields are declared, their kind giving the index's filter)."""
    name: str
    owner: str
    fields: tuple = ()
    indexes: tuple = ()
    retired: tuple = ()
    versioned: bool = False
    insert_only: bool = False
    counters: tuple = ()
    derived: tuple = ()
    pending: bool = False
    _paths: dict = _field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self):
        paths = {'_id': ID}
        for declared in self.fields:
            path = declared.path
            if path in paths:
                raise _invalid('%s declares %s twice' % (self.name, path))
            parts = path.split('.')
            if not all(parts) or any(p.startswith('$') or p in RESERVED for p in parts):
                raise _invalid('%s: %r is not a field name' % (self.name, path))
            if declared.kind not in KINDS:
                raise _invalid('%s.%s: kind %r' % (self.name, path, declared.kind))
            if (declared.kind == 'list') != (declared.of in ELEMENTS):
                raise _invalid('%s.%s: a list names its element kind, and only a list' % (self.name, path))
            if (declared.kind == 'vector') != isinstance(declared.dimensions, int):
                raise _invalid('%s.%s: a vector names its dimensions, and only a vector' % (self.name, path))
            if declared.required and declared.nullable:
                raise _invalid('%s.%s: a required field is never null' % (self.name, path))
            if len(parts) > 1:
                parent = paths.get('.'.join(parts[:-1]))
                if parent is None or not (parent.kind == 'object' or parent.of == 'object'):
                    raise _invalid('%s.%s: declare its parent first, as an object or a list of objects'
                                   % (self.name, path))
            paths[path] = declared
        names = set()
        for index in self.indexes:
            if index.name in names or index.name in self.retired:
                raise _invalid('%s: index %s declared twice or also retired' % (self.name, index.name))
            names.add(index.name)
            for path, direction in index.keys:
                if direction not in (1, -1) or (path not in paths and not self.pending):
                    raise _invalid('%s: index %s names %r' % (self.name, index.name, path))
                if index.unique and path in index.only_where_present and path not in paths:
                    raise _invalid('%s: unique index %s: declare %s, whose kind gives its filter'
                                   % (self.name, index.name, path))
                if index.unique and path in paths:
                    if paths[path].kind in ('list', 'object', 'vector'):
                        raise _invalid('%s: unique index %s on %s' % (self.name, index.name, path))
                    # Inside a partial index (only_where_present) its other fields may be missing: indexed as null.
                    if not (paths[path].required or index.only_where_present or self.pending):
                        raise _invalid('%s: unique index %s: %s is neither required nor in a partial index'
                                       % (self.name, index.name, path))
            if not set(index.only_where_present) <= {path for path, _ in index.keys}:
                raise _invalid('%s: index %s: only_where_present names a field it does not index'
                               % (self.name, index.name))
        object.__setattr__(self, '_paths', paths)

    def field(self, path) -> Field | None:
        return self._paths.get(path)

    def paths(self) -> list[str]:
        return list(self._paths)

    def unique(self) -> list[Index]:
        return [index for index in self.indexes if index.unique]


class Catalog:
    """The declared collections and vector spaces, by name."""

    def __init__(self, collections=(), spaces=()):
        self._collections, self._spaces = {}, {}
        for declared in collections:
            if declared.name in self._collections:
                raise _invalid('collection %s declared twice' % declared.name)
            self._collections[declared.name] = declared
        for space in spaces:
            self.check_space(space)
            if space.name in self._spaces:
                raise _invalid('space %s declared twice' % space.name)
            self._spaces[space.name] = space

    def collection(self, name) -> Collection:
        declared = self._collections.get(name)
        if declared is None:
            raise QueryInvalid('QUERY_COLLECTION_NOT_DECLARED: 没有声明叫 "%s" 的集合；声明了的：%s'
                               % (name, '、'.join(self._collections) or '（没有）'))
        return declared

    def collections(self) -> list[Collection]:
        return list(self._collections.values())

    def names(self) -> list[str]:
        return list(self._collections)

    def spaces(self) -> list[Space]:
        return list(self._spaces.values())

    def check_space(self, space):
        """Refuse a space whose collection, vector path or filter fields are not declared."""
        declared = self._collections.get(space.collection)
        vector = declared and declared.field(space.path)
        if not vector or vector.kind != 'vector' or vector.dimensions != space.dimensions:
            raise _invalid('space %s: %s.%s is not a declared vector of %s dimensions'
                           % (space.name, space.collection, space.path, space.dimensions))
        for path in space.fields:
            if declared.field(path) is None or declared.field(path).kind in ('list', 'object', 'vector'):
                raise _invalid('space %s filters on %s, not a declared value field' % (space.name, path))


def index(*keys, unique=False, only_where_present=(), expire_after=None):
    """An index named as MongoDB names one by default (`scene_id_1_scene_seq_1`)."""
    return Index('_'.join('%s_%s' % key for key in keys), tuple(keys), unique, tuple(only_where_present), expire_after)


def _core(name, owner, *indexes, fields=(), **flags):
    """A collection of the core's: versioned, pending until its owner moves, and carrying the commit mark `_last_op`
    that recovery reads."""
    return Collection(name, owner, (Field('_last_op', 'text'), *fields), tuple(indexes), versioned=True, pending=True,
                      **flags)


def _text(*paths):
    return tuple(Field(path, 'text', nullable=True) for path in paths)


CATALOG = Catalog([
    _core('identities', 'records.people', index(('platform', 1), ('account_id', 1), unique=True)),
    # A conversation (records/scenes.py): the fields its owner names; the rest is stored and returned as written.
    Collection('scenes', 'records.scenes', (
        Field('_last_op', 'text'), Field('schema_version', 'number'), Field('kind', 'text'), Field('scope_key', 'text'),
        Field('policy_epoch', 'number'), Field('sequence', 'number'), Field('members', 'list', of='text'),
        Field('channel_id', 'text', nullable=True), Field('condense_wanted', 'object', nullable=True),
        Field('condensed_at', 'text', nullable=True), Field('fault', 'object', nullable=True),
        Field('fault.at', 'text', nullable=True), Field('unsent', 'object', nullable=True),
        Field('unsent.episode_id', 'text', nullable=True), Field('asides_shown_seq', 'number')),
        versioned=True, counters=('sequence',)),
    # A line of a conversation (records/messages.py): the fields its owner names; the rest is stored and returned as
    # written. Its times are ISO text, as the core writes them.
    Collection('messages', 'records.messages', (
        Field('_last_op', 'text'), Field('schema_version', 'number'),
        *_text('scene_id', 'scope_key', 'direction', 'author', 'delivery_state', 'phase', 'episode_id', 'text',
               'received_at', 'receipt_at', 'occurred_at', 'claimed_at', 'shown_on_line', 'recalled_at',
               'errand_told', 'channel_id', 'ingress_state', 'adapter_id', 'platform_event_id', 'platform_message_id',
               'publication_key', 'processing_outcome', 'deletion_id', 'historical_display_name', 'summary_batch_id',
               'receipt', 'reply_to', 'failure_detail'),
        *(Field(path, 'number', nullable=True) for path in ('policy_epoch', 'scene_seq', 'segment_index')),
        *(Field(path, 'bool', nullable=True) for path in ('reply_part', 'host_managed', 'source_present')),
        Field('file', 'object', nullable=True), *_text('file.artifact_id'),
        Field('attachment', 'object', nullable=True), *_text('attachment.artifact_id'),
        Field('target', 'object', nullable=True), *_text('target.type', 'target.id'),
        Field('event', 'object', nullable=True), *_text('event.event_id'),
        Field('event.channel', 'object', nullable=True), *_text('event.channel.platform_event_id'),
        Field('event.group_context', 'object', nullable=True),
        *_text('event.group_context.wake_reason', 'event.group_context.topic_id',
               'event.group_context.reply_message_id'),
        Field('event.group_context.mentioned_account_ids', 'list', of='text', nullable=True),
        Field('event.visit', 'object', nullable=True), *_text('event.visit.intent'),
        Field('event.raw', 'object', nullable=True), *_text('event.raw.group_name'),
        Field('event.raw.asuna_aside', 'bool', nullable=True),
        Field('event.raw.asuna_media', 'object', nullable=True),
        Field('event.raw.asuna_notice', 'object', nullable=True), *_text('event.raw.asuna_notice.kind'),
        Field('event.raw.asuna_notice.line', 'object', nullable=True),
        *_text('event.raw.asuna_notice.line.message_id'),
        Field('event.raw.asuna_answer', 'object', nullable=True), *_text('event.raw.asuna_answer.question'),
        Field('event.raw.asuna_peer', 'object', nullable=True),
        *_text(*('event.raw.asuna_peer.' + key for key in ('person_id', 'card', 'nickname', 'display'))),
        Field('event.raw.asuna_peer.aliases', 'list', of='text', nullable=True),
        Field('event.raw.asuna_forward', 'list', of='object', nullable=True), *_text('event.raw.asuna_forward.ref'),
        Field('event.raw.asuna_forward.nodes', 'list', of='object', nullable=True),
        *_text('event.raw.asuna_forward.nodes.text')),
        (index(('adapter_id', 1), ('scene_id', 1), ('platform_event_id', 1), unique=True,
               only_where_present=('platform_event_id',)),
         index(('publication_key', 1), unique=True, only_where_present=('publication_key',)),
         index(('scene_id', 1), ('scene_seq', 1)),
         index(('host_managed', 1), ('ingress_state', 1), ('received_at', 1)),
         index(('channel_id', 1), ('delivery_state', 1), ('scene_seq', 1)),
         index(('author', 1), ('direction', 1)),
         index(('episode_id', 1)),
         index(('event.visit.intent', 1), ('received_at', 1), only_where_present=('event.visit.intent',))),
        versioned=True),
    # A turn (records/episodes.py): the fields its owner names; the rest is stored and returned as written. The fields
    # of its unique index are required (3.5).
    Collection('episodes', 'records.episodes', (
        Field('_last_op', 'text'), Field('schema_version', 'number'),
        *(Field(path, 'text', required=True) for path in ('scene_id', 'source_event_id', 'episode_kind')),
        *_text('state', 'persona', 'person_id', 'scope_key', 'native_session_id', 'speech'),
        Field('policy_epoch', 'number', nullable=True),
        Field('system_ref', 'object', nullable=True), Field('system_ref.carried', 'object', nullable=True)),
        (index(('scene_id', 1), ('source_event_id', 1), ('episode_kind', 1), unique=True),
         index(('person_id', 1), ('state', 1))),
        versioned=True),
    _core('tasks', 'records.tasks', index(('request_key', 1), unique=True)),
    _core('plans', 'records.plans', index(('scene_id', 1), ('person_id', 1), ('status', 1))),
    _core('memory_units', 'records.memories',
          index(('scope_key', 1), ('status', 1), ('policy_epoch', 1)),
          index(('scope_key', 1), ('origin', 1), ('source_identity', 1), unique=True,
                only_where_present=('source_identity',)),
          fields=(Field('embedding', 'vector', dimensions=768, nullable=True),
                  Field('policy_epoch', 'number', nullable=True),
                  *_text('source_identity', 'scope_key', 'character_id', 'status', 'embedding_revision', 'kind')),
          counters=('salience',), derived=('embedding',)),
    _core('state_heads', 'records.heads'),
    _core('state_revisions', 'records.heads', index(('mutation_id', 1), unique=True)),
    # A native session's binding (records/sessions.py): the fields its owner names; the rest is stored as written.
    Collection('sessions', 'records.sessions', (
        Field('_last_op', 'text'), Field('schema_version', 'number'), Field('binding_key', 'text', required=True),
        *(Field(path, 'bool', nullable=True) for path in ('native_host', 'main_conversation')),
        *_text('scene_id', 'scope_key', 'person_id', 'persona', 'lane', 'character_context', 'native_title',
               'successor_id', 'parent_session_id', 'broker_session', 'task_id', 'binding_updated_at', 'state',
               'deletion_id'),
        Field('policy_epoch', 'number', nullable=True)),
        (index(('binding_key', 1), unique=True),),
        versioned=True),
    _core('audit_events', 'audit',
          index(('stream_id', 1), ('seq', 1), unique=True), index(('type', 1), ('occurred_at', 1)),
          index(('occurred_at', 1)),
          fields=(Field('stream_id', 'text', required=True), Field('seq', 'number', required=True),
                  Field('type', 'text'), Field('payload', 'object'), Field('payload.operation', 'text', nullable=True)),
          insert_only=True),
    _core('artifacts', 'records.artifacts'),
    # What a sink received, and what a model lane answered (records/receipts.py): the fields their owner names; the
    # rest is stored as written. Their times are ISO text, as the core and the Host write them.
    Collection('sink_receipts', 'records.receipts', (
        Field('_last_op', 'text'), Field('schema_version', 'number'),
        *_text('kind', 'state', 'project', 'published_at', 'received_at')),
        versioned=True),
    Collection('lane_receipts', 'records.receipts', (
        Field('_last_op', 'text'), Field('schema_version', 'number'), *_text('session_id')),
        versioned=True),
    _core('affect_events', 'affect',
          index(('persona', 1), ('ts', 1)),
          index(('persona', 1), ('origin', 1), ('source_identity', 1), unique=True,
                only_where_present=('source_identity',)),
          fields=_text('source_identity'), insert_only=True),
    _core('affect_amendments', 'affect',
          index(('target', 1)),
          index(('persona', 1), ('origin', 1), ('source_identity', 1), unique=True,
                only_where_present=('source_identity',)),
          fields=_text('source_identity'), insert_only=True),
    _core('affect_proposals', 'affect', index(('persona', 1), ('kind_row', 1), ('created_at', 1)), insert_only=True),
    _core('scene_people', 'records.people', index(('scene_id', 1), ('handle', 1), unique=True)),
    _core('task_messages', 'records.tasks', index(('task_id', 1), ('created_at', 1)),
          index(('thread', 1), ('created_at', 1))),
    _core('ideas', 'records.ideas', index(('persona', 1), ('state', 1), ('created_at', 1))),
    _core('stickers', 'stickers', index(('persona', 1), ('name', 1), unique=True),
          index(('persona', 1), ('identity', 1), unique=True)),
    _core('sticker_pool', 'stickers', index(('last_seen', 1)), index(('artifact_id', 1))),
    _core('sticker_memory', 'stickers', index(('persona', 1), ('key', 1), unique=True)),
    _core('watches', 'watches', index(('persona', 1), ('person', 1), ('state', 1)),
          counters=('last_seen_at', 'appeared')),
    _core('notes', 'notes', index(('to_scene', 1), ('created_at', -1)), index(('from_scene', 1), ('created_at', -1)),
          index(('persona', 1), ('created_at', -1)), index(('reply_to', 1)), counters=('seen_in',)),
    _core('developer_inbox', 'developer_inbox', index(('persona', 1), ('created_at', -1)),
          index(('state', 1), ('created_at', 1))),
    _core('group_members', 'group_members'),
    _core('host_stops', 'host_stops', index(('how', 1), ('back_at', -1))),
    _core('switches', 'switches', index(('state', 1), ('kind', 1), ('until', 1)), index(('persona', 1), ('state', 1))),
    _core('own_mutes', 'own_mute', index(('muted', 1))),
    _core('journal_entries', 'documents',
          index(('persona', 1), ('slug', 1), ('seq', 1), unique=True),
          index(('persona', 1), ('slug', 1), ('sid', 1), unique=True), index(('last_mutation', 1))),
    _core('journal_revisions', 'documents', index(('mutation_id', 1), unique=True),
          index(('persona', 1), ('slug', 1), ('created_at', -1)), index(('entry_id', 1), ('created_at', 1))),
    _core('questions', 'questions'),
    # Its fault counts leave KEEP_DAYS after their hour through lane_faults.forget_old, which replaces the TTL index.
    Collection('lane_faults', 'lane_faults', (
        Field('_last_op', 'text'), Field('schema_version', 'number', required=True),
        *(Field(path, 'text', required=True) for path in ('channel_id', 'lane', 'stage', 'error', 'hour')),
        Field('hour_at', 'time', required=True), Field('count', 'number', required=True),
        Field('first_posted_at', 'time'), Field('last_posted_at', 'time')),
        (index(('channel_id', 1), ('hour', 1)), index(('lane', 1), ('stage', 1), ('error', 1), ('hour', 1))),
        retired=('hour_at_1',), versioned=True),
    # One record, `host`: the Host holding the database (host_lease.py).
    Collection('host_leases', 'host_lease', (
        Field('instance', 'text', required=True), Field('host', 'text', nullable=True),
        Field('persona', 'text', nullable=True), Field('pid', 'number', nullable=True),
        Field('since', 'time'), Field('expires_at', 'time', required=True), Field('planned_stop', 'object'),
        Field('planned_stop.at', 'time'), Field('planned_stop.by', 'text', nullable=True))),
])
