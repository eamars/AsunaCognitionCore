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
    # Who a person is on this machine (records/people.py): the fields its owner names; the rest is stored as written.
    # The fields of its plain unique index are required (3.5).
    Collection('identities', 'records.people', (
        Field('_last_op', 'text'), Field('schema_version', 'number'),
        *(Field(path, 'text', required=True) for path in ('platform', 'account_id')), *_text('person_id')),
        (index(('platform', 1), ('account_id', 1), unique=True),),
        versioned=True),
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
    # A task and its messages (records/tasks.py): the fields their owner names; the rest is stored as written. The
    # field of the tasks' unique index is required (3.5). Their times are ISO text, but a lease's expiry: seconds.
    Collection('tasks', 'records.tasks', (
        Field('_last_op', 'text'), Field('schema_version', 'number'), Field('request_key', 'text', required=True),
        *_text('state', 'scene_id', 'scope_key', 'requester_id', 'episode_id', 'continues_task_id', 'feedback_state',
               'pause_reason', 'paused_state', 'paused_at', 'created_at', 'finished_at'),
        Field('policy_epoch', 'number', nullable=True), Field('lease_expires_at', 'number', nullable=True)),
        (index(('request_key', 1), unique=True),),
        versioned=True),
    # A plan (records/plans.py): the fields its owner names; the rest is stored as written. Its times are ISO text.
    Collection('plans', 'records.plans', (
        Field('_last_op', 'text'), Field('schema_version', 'number'),
        *_text('scene_id', 'scope_key', 'person_id', 'status', 'kind', 'next_fire_at', 'created_at', 'last_outcome'),
        Field('policy_epoch', 'number', nullable=True)),
        (index(('scene_id', 1), ('person_id', 1), ('status', 1)),),
        versioned=True),
    # A memory (records/memories.py): the fields its owner names; the rest is stored and returned as written. Its
    # times are ISO text, as the core writes them; its embedding is the vector space's.
    Collection('memory_units', 'records.memories', (
        Field('_last_op', 'text'), Field('schema_version', 'number'),
        *_text('scope_key', 'character_id', 'status', 'kind', 'source', 'episode_id', 'epistemic_type', 'body_markdown',
               'embedding_status', 'embedding_revision', 'origin', 'source_identity', 'generated_at', 'occurred_at',
               'formed_at'),
        Field('policy_epoch', 'number', nullable=True),
        *(Field(path, 'list', of='text', nullable=True) for path in ('source_event_ids', 'depends_on')),
        Field('embedding', 'vector', dimensions=768, nullable=True)),
        (index(('scope_key', 1), ('status', 1), ('policy_epoch', 1)),
         index(('scope_key', 1), ('origin', 1), ('source_identity', 1), unique=True,
               only_where_present=('source_identity',))),
        versioned=True, counters=('salience',), derived=('embedding',)),
    # Her revisioned state (records/heads.py): a head per entity and scope, and its revisions; the fields their owner
    # names, the rest stored as written. A revision's mutation id is its plain unique index's field, required (3.5);
    # its times are ISO text.
    Collection('state_heads', 'records.heads', (
        Field('_last_op', 'text'), Field('schema_version', 'number'), *_text('revision_id', 'scope_key')),
        versioned=True),
    Collection('state_revisions', 'records.heads', (
        Field('_last_op', 'text'), Field('schema_version', 'number'), Field('mutation_id', 'text', required=True),
        *_text('entity_key', 'scope_key', 'created_at')),
        (index(('mutation_id', 1), unique=True),),
        versioned=True),
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
    # A kept file or record apart from the conversation (records/artifacts.py): the fields its owner names; the rest
    # is stored and returned as written. Its times are ISO text, as the core writes them.
    Collection('artifacts', 'records.artifacts', (
        Field('_last_op', 'text'), Field('schema_version', 'number'),
        *_text('kind', 'state', 'storage', 'scope_key', 'scene_id', 'channel_id', 'task_id', 'tool', 'sha256', 'ref',
               'answer', 'claimed_at', 'kept_at', 'created_at', 'received_at'),
        *(Field(path, 'number', nullable=True) for path in ('intent_revision', 'number')),
        *(Field(path, 'list', of='text', nullable=True) for path in ('source_ids', 'copies'))),
        versioned=True),
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
    # How a conversation labels each person (records/people.py): the fields of its plain unique index are required
    # (3.5); its times are ISO text.
    Collection('scene_people', 'records.people', (
        Field('_last_op', 'text'), Field('schema_version', 'number'), Field('scene_id', 'text', required=True),
        Field('handle', 'number', required=True), *_text('person', 'seen_at')),
        (index(('scene_id', 1), ('handle', 1), unique=True),),
        versioned=True),
    Collection('task_messages', 'records.tasks', (
        Field('_last_op', 'text'), Field('schema_version', 'number'),
        *_text('task_id', 'thread', 'from', 'created_at'), Field('delivered', 'bool', nullable=True)),
        (index(('task_id', 1), ('created_at', 1)), index(('thread', 1), ('created_at', 1))),
        versioned=True),
    # Her improvement ideas (records/ideas.py): the fields its owner names; the rest is stored as written.
    Collection('ideas', 'records.ideas', (
        Field('_last_op', 'text'), Field('schema_version', 'number'),
        *_text('persona', 'state', 'idea', 'why', 'created_at')),
        (index(('persona', 1), ('state', 1), ('created_at', 1)),),
        versioned=True),
    # Her sticker shelf, the candidates people posted in her groups, and the stickers she knows (stickers.py): the
    # fields their owner names; the rest is stored as written. The fields of their plain unique indexes are required
    # (3.5); their times are ISO text.
    Collection('stickers', 'stickers', (
        Field('_last_op', 'text'), Field('schema_version', 'number'), Field('revision', 'number', nullable=True),
        *(Field(path, 'text', required=True) for path in ('persona', 'name', 'identity')),
        *_text('when', 'kept_at', 'kept_in', 'last_sent_at', 'last_sent_in', 'origin', 'kind', 'artifact_id', 'sha256',
               'media_type', 'md5', 'picture'),
        *(Field(path, 'number', nullable=True) for path in ('sent', 'size')), Field('market', 'object', nullable=True)),
        (index(('persona', 1), ('name', 1), unique=True), index(('persona', 1), ('identity', 1), unique=True)),
        versioned=True),
    Collection('sticker_pool', 'stickers', (
        Field('_last_op', 'text'), Field('schema_version', 'number'), Field('revision', 'number', nullable=True),
        *_text('identity', 'kind', 'artifact_id', 'sha256', 'md5', 'picture', 'media_type', 'first_seen', 'last_seen',
               'source_message_id'),
        *(Field(path, 'number', nullable=True) for path in ('seen', 'size')),
        Field('scenes', 'list', of='text', nullable=True), Field('market', 'object', nullable=True)),
        (index(('last_seen', 1)), index(('artifact_id', 1))),
        versioned=True),
    Collection('sticker_memory', 'stickers', (
        Field('_last_op', 'text'), Field('schema_version', 'number'),
        *(Field(path, 'text', required=True) for path in ('persona', 'key')),
        *_text('name', 'note', 'how', 'identity', 'picture', 'at'), Field('aliases', 'list', of='text', nullable=True)),
        (index(('persona', 1), ('key', 1), unique=True),),
        versioned=True),
    # Her watchlist (watches.py): the fields its owner names; the rest is stored as written. Its times are ISO text;
    # a sighting moves `last_seen_at` and `appeared` outside a revision.
    Collection('watches', 'watches', (
        Field('_last_op', 'text'), Field('schema_version', 'number'),
        *_text('persona', 'person', 'name', 'set_in', 'set_class', 'why', 'mode', 'state', 'created_at', 'until',
               'last_seen_at', 'ended_at'),
        Field('appeared', 'number', nullable=True)),
        (index(('persona', 1), ('person', 1), ('state', 1)),),
        versioned=True, counters=('last_seen_at', 'appeared')),
    # Notes between her conversations (notes.py): the fields its owner names; the rest is stored as written. Its times
    # are ISO text; each turn that shows a note adds itself to `seen_in` outside a revision.
    Collection('notes', 'notes', (
        Field('_last_op', 'text'), Field('schema_version', 'number'),
        *_text('persona', 'from_scene', 'from_class', 'from_episode', 'to_scene', 'kind', 'place', 'text', 'trust',
               'mode', 'reply_to', 'created_at', 'owner_line', 'question', 'event_id'),
        *(Field(path, 'number', nullable=True) for path in ('hop', 'tables_version')),
        Field('seen_in', 'list', of='text', nullable=True)),
        (index(('to_scene', 1), ('created_at', -1)), index(('from_scene', 1), ('created_at', -1)),
         index(('persona', 1), ('created_at', -1)), index(('reply_to', 1))),
        versioned=True, counters=('seen_in',)),
    # The program's notes to the developer agent (developer_inbox.py): the fields its owner names; the rest is stored
    # as written. Its times are ISO text; a note's `count` rises outside a revision.
    Collection('developer_inbox', 'developer_inbox', (
        Field('_last_op', 'text'), Field('schema_version', 'number'),
        *_text('persona', 'level', 'text', 'state', 'scope_key', 'created_at', 'seen_at', 'answered_at'),
        Field('source', 'object', nullable=True), *_text('source.by'), Field('count', 'number', nullable=True)),
        (index(('persona', 1), ('created_at', -1)), index(('state', 1), ('created_at', 1))),
        versioned=True),
    # Who is in each group, as the channel adapter last fetched it (group_members.py), one row per conversation.
    Collection('group_members', 'group_members', (
        Field('_last_op', 'text'), Field('schema_version', 'number'),
        *_text('scene_id', 'group_id', 'channel_id', 'fetched_at', 'received_at', 'scope_key'),
        Field('members', 'list', of='object', nullable=True), Field('count', 'number', nullable=True)),
        versioned=True),
    # A Host taken away from outside, found at the next start (host_stops.py); its times are ISO text.
    Collection('host_stops', 'host_stops', (
        Field('_last_op', 'text'), Field('schema_version', 'number'),
        *_text('how', 'alive_until', 'back_at', 'scope_key', 'shown_at', 'by', 'cause'),
        *(Field(path, 'number', nullable=True) for path in ('exit_code', 'tries', 'inside'))),
        (index(('how', 1), ('back_at', -1)),),
        versioned=True),
    # A look the relevance gate could not decide (host_stops.py), by its turn's id; its time is ISO text.
    Collection('missed_looks', 'host_stops', _text('scene_id', 'at', 'cause')),
    # Her switches (switches.py): the fields its owner names; the rest is stored as written. Its times are ISO text.
    Collection('switches', 'switches', (
        Field('_last_op', 'text'), Field('schema_version', 'number'),
        *_text('persona', 'kind', 'label', 'scene_id', 'person_id', 'until', 'state', 'set_at', 'set_in', 'why',
               'cleared_at'),
        Field('tools', 'list', of='text', nullable=True)),
        (index(('state', 1), ('kind', 1), ('until', 1)), index(('persona', 1), ('state', 1))),
        versioned=True),
    # Her own mute in each group, as the platform last said it (own_mute.py); its times are ISO text.
    Collection('own_mutes', 'own_mute', (
        Field('_last_op', 'text'), Field('schema_version', 'number'),
        *_text('scene_id', 'scope_key', 'updated_at', 'source', 'since', 'until', 'by', 'cleared_at', 'cleared_by'),
        *(Field(path, 'bool', nullable=True) for path in ('muted', 'whole_group'))),
        (index(('muted', 1)),),
        versioned=True),
    # Her running records, one row per entry and each change beside it (documents.py): the fields of their plain
    # unique indexes are required (3.5); their times are ISO text.
    Collection('journal_entries', 'documents', (
        Field('_last_op', 'text'), Field('schema_version', 'number'),
        *(Field(path, 'text', required=True) for path in ('persona', 'slug', 'sid')),
        Field('seq', 'number', required=True), *_text('last_mutation')),
        (index(('persona', 1), ('slug', 1), ('seq', 1), unique=True),
         index(('persona', 1), ('slug', 1), ('sid', 1), unique=True), index(('last_mutation', 1))),
        versioned=True),
    Collection('journal_revisions', 'documents', (
        Field('_last_op', 'text'), Field('schema_version', 'number'), Field('mutation_id', 'text', required=True),
        *_text('persona', 'slug', 'sid', 'body_sha256', 'entry_id', 'created_at')),
        (index(('mutation_id', 1), unique=True), index(('persona', 1), ('slug', 1), ('created_at', -1)),
         index(('entry_id', 1), ('created_at', 1))),
        versioned=True),
    # Her questions, each to one or more places, with what came back (questions.py): the fields its owner names; the
    # rest is stored as written. Its times are ISO text; a source is one element of `sources`.
    Collection('questions', 'questions', (
        Field('_last_op', 'text'), Field('schema_version', 'number'),
        *_text('persona', 'scope_key', 'text', 'scene_id', 'episode_id', 'asked_at', 'patience', 'state',
               'migrated_from'),
        Field('tables_version', 'number', nullable=True), Field('told_in', 'list', of='text', nullable=True),
        Field('sources', 'list', of='object', nullable=True), *_text('sources.scene_id', 'sources.kind'),
        Field('closed', 'object', nullable=True), *_text('closed.by')),
        versioned=True),
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
