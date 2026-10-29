"""The owner of `state_heads` and `state_revisions`: her revisioned state (documents, relationships and the person
layer, scene affect, policy, self descriptions), a head per entity and scope naming its current revision, read and
written only through these operations.

A head's id is `<entity>|<scope>`; a revision belongs to one head's key (`entity_key`) and names its parent. `head`
and `revision` return a record as stored (`fields` names what to return; `_id` always comes back), within the fences
given. None follows section 4's rule: an id or a fence (a scope, an entity's key) given None, or a value not of its
kind, finds nothing without a read. The other reads are views (`View`: `rows`, `each`, `first`, `count`), in the
replaced read's order (none where it had none). `current` is a head with its revision; `init` creates a head with its
first revision; `mutate` writes her relationship or scene-affect revision from sources she may read. `save_head` and
`save_revision` are the revisioned writes (`Store.put`); `point_to`, `drop_head` and `tombstone_revision` an erasure's.
"""
from ..store.words import AnyOf, NoneOf, Range, Set, StartsWith
from .view import ANY, View, fenced, is_text, texts

HEADS, REVISIONS = 'state_heads', 'state_revisions'


def _heads(store, where, by=()):
    by = (by,) if isinstance(by, str) else tuple(by)
    return View(store, HEADS, where, tuple((path, 1) for path in by))


def _revisions(store, where, by=()):
    by = (by,) if isinstance(by, str) else tuple(by)
    return View(store, REVISIONS, where, tuple((path, 1) for path in by))


# Single records.

def head(store, key, fields=None):
    """The head with this id (`<entity>|<scope>`), or None."""
    return store.collection(HEADS).get(key, fields) if is_text(key) else None


def current(store, entity, scope):
    """(head, its revision) of an entity in a scope, or None when it has no head."""
    found = head(store, '%s|%s' % (entity, scope))
    if not found:
        return None
    return found, revision(store, found['revision_id'])


def revision(store, revision_id, fields=None, *, entity=ANY):
    """The revision with this id (of this entity's key), or None."""
    if not is_text(revision_id):
        return None
    if entity is ANY:
        return store.collection(REVISIONS).get(revision_id, fields)
    return _revisions(store, fenced({'_id': revision_id}, {'entity_key': (entity, is_text)})).first(fields=fields)


def by_mutation(store, mutation_id, fields=None):
    """The revision a mutation id wrote, or None."""
    if not is_text(mutation_id):
        return None
    return _revisions(store, {'mutation_id': mutation_id}).first(fields=fields)


# Views.

def with_prefix(store, *prefixes):
    """View: the heads whose id starts with any of these prefixes."""
    prefixes = texts(prefixes)
    return _heads(store, {'_id': StartsWith(*prefixes)} if prefixes else None)


def heads(store, ids=ANY, *, scope=ANY, scopes=ANY, by=()):
    """View: the heads with these ids, or of this scope or one of these, ordered by `by`."""
    listed = (list, tuple, set)
    if not (ids is ANY or isinstance(ids, listed)) or not (scopes is ANY or isinstance(scopes, listed)):
        return _heads(store, None, by)
    where = {} if ids is ANY else {'_id': AnyOf(texts(ids))}
    if scopes is not ANY:
        where['scope_key'] = AnyOf(texts(scopes))
    return _heads(store, fenced(where, {'scope_key': (scope, is_text)}), by)


def revisions(store, revision_ids):
    """View: the revisions with these ids."""
    return _revisions(store, {'_id': AnyOf(texts(revision_ids))})


def history(store, entity_key, *, since=ANY, before=ANY, by='created_at'):
    """View: an entity's revisions (written at or after `since`, or before `before`, ISO times), by `by`."""
    where = fenced({}, {'entity_key': (entity_key, is_text)})
    if where is not None and (since is not ANY or before is not ANY):
        bounds = {**({'gte': since} if since is not ANY else {}), **({'lt': before} if before is not ANY else {})}
        if not all(is_text(value) for value in bounds.values()):
            return _revisions(store, None)
        where['created_at'] = Range(**bounds)
    return _revisions(store, where, by)


def stale_revisions(store, scope, besides):
    """View: a scope's revisions but these (the ones no head points at, when `besides` are its heads' revisions)."""
    where = fenced({'_id': NoneOf(texts(besides))}, {'scope_key': (scope, is_text)})
    return _revisions(store, where)


# Writes.

def save_head(store, row, **kwargs):
    """The revisioned write of a head (`Store.put`: `expected`, `stream`)."""
    return store.put(HEADS, row, **kwargs)


def save_revision(store, row, **kwargs):
    """The write of a revision (`Store.put`)."""
    return store.put(REVISIONS, row, **kwargs)


def point_to(store, head_id, revision_id, revision_number):
    """An erasure moves a head to an older revision (its own revision number given)."""
    return store.collection(HEADS).update({'_id': head_id}, Set({'revision_id': revision_id,
                                                                'revision': revision_number}))


def drop_head(store, head_id, *, revision_id=ANY):
    """Delete a head (only while it still names `revision_id`); how many went."""
    where = {'_id': head_id, **({'revision_id': revision_id} if revision_id is not ANY else {})}
    return store.collection(HEADS).delete(where)


def tombstone_revision(store, revision_id, deletion):
    """An erasure empties a revision: no content, no sources, a tombstone of this erasure."""
    return store.collection(REVISIONS).update({'_id': revision_id}, Set({
        'content': {}, 'source_ids': [], 'status': 'tombstone', 'deletion_id': deletion}))


def init(store, entity, scope, content, sources):
    """The head of an entity in a scope, created with its first revision when it has none; the head."""
    import uuid
    key = entity + '|' + scope
    found = head(store, key)
    if found:
        return found
    revision_id = str(uuid.uuid4())
    save_revision(store, {'_id': revision_id, 'entity_key': key, 'mutation_id': 'seed:' + key, 'scope_key': scope,
                          'content': content, 'source_ids': sources, 'parent_revision_id': None}, stream='seed')
    return save_head(store, {'_id': key, 'scope_key': scope, 'revision_id': revision_id}, stream='seed')


def mutate(store, entity, scope, base_revision_id, content, sources, request_scope, mutation_id, actor='character', *,
           reason=None, change_class=None, linked_scopes=(), origin=None):
    """Her relationship or scene-affect revision, from sources she may read in this scope (or the linked ones), on the
    head at `base_revision_id`; the revision. A retry with the same mutation id returns what it wrote."""
    from ..evidence import canonical, sha
    from ..state import Conflict, Denied
    from . import artifacts as artifact_records
    from . import episodes as episode_records
    from . import memories as memory_records
    from . import messages as message_records
    # A relationship is her understanding in prose; no level fields (nothing ever wrote them).
    allowed = {'body', 'short'}           # her prose, and her one line for herself (ADR-082)
    # 跨场景只读联动（A2）里唯一被放宽的是「关系/偏好状态落在哪一份」：配置认定同一个人时，
    # 别名场景这一轮写的是 canonical 那一份。linked_scopes 就是本轮授权的那个场景 scope——
    # 来源证据仍只许落在 global-safe、目标 scope 或它里面；不传就等于原来的行为。
    linked = {item for item in (linked_scopes or ()) if isinstance(item, str) and item}
    readable_scopes = {'global-safe', scope} | linked
    # The persona is a document (ADR-009 §5); state heads hold only relationships and scene affect.
    if actor != 'character' or not entity.startswith(('relationship:', 'scene_affect:')) or \
            not set(content).issubset(allowed):
        raise Denied('POLICY_PATH_OR_ACTOR_DENIED')
    if scope != request_scope and not (request_scope in linked
                                       and entity.startswith(('relationship:',
                                                              'scene_affect:'))):
        raise Denied('SCOPE_PROMOTION_DENIED')
    if not sources:
        raise Denied('MUTATION_REQUIRES_SOURCES')
    if reason is not None and (not isinstance(reason, str) or not 1 <= len(reason) <= 2000):
        raise Denied('INVALID_MUTATION_REASON')
    if change_class not in (None, 'persona', 'relationship', 'interpretation', 'scene_affect'):
        raise Denied('INVALID_CHANGE_CLASS')
    for source in sources:
        row = memory_records.get(store, source, erased=False)
        if not row or row['scope_key'] not in readable_scopes:
            raise Denied('MUTATION_SOURCE_DENIED')
    head_row, base = current(store, entity, scope) or (None, None)
    existing = by_mutation(store, mutation_id)
    if existing:
        if existing.get('content') != content or existing.get('source_ids') != sources or \
                existing.get('parent_revision_id') != base_revision_id or \
                existing.get('entity_key') != entity + '|' + scope or existing.get('reason') != reason or \
                existing.get('change_class') != change_class:
            raise Conflict('MUTATION_ID_CONTENT_CHANGED')
        ancestor = base
        for _ in range(512):
            if not ancestor:
                break
            if ancestor['_id'] == existing['_id']:
                return existing
            parent = ancestor.get('parent_revision_id')
            ancestor = revision(store, parent) if parent else None
        raise Conflict('MUTATION_ALREADY_ATTEMPTED')
    # A relationship has no record until she first writes one: that write starts from no base.
    first = head_row is None and base_revision_id is None and entity.startswith('relationship:')
    if not first and (not head_row or head_row['revision_id'] != base_revision_id):
        store.audit('mutation:' + mutation_id, 'state.conflict', {'entity': entity,
                    'base_revision_id': base_revision_id, 'reason': 'BASE_REVISION_STALE'}, scope)
        raise Conflict('BASE_REVISION_STALE')
    evidence_ids = set()
    visited = set()

    def roots(key, path):
        if key in path:
            raise Denied('SOURCE_CYCLE')
        if len(visited) > 512:
            raise Denied('SOURCE_GRAPH_LIMIT')
        if key in visited:
            return
        visited.add(key)
        row = memory_records.get(store, key)
        if row:
            if row.get('status') == 'tombstone' or row['scope_key'] not in readable_scopes:
                raise Denied('DERIVED_SOURCE_SCOPE_DENIED')
            descendants = row.get('source_event_ids', [])
            if descendants:
                for child in descendants:
                    roots(child, path | {key})
            else:
                evidence_ids.add(key)
        else:
            # Derived memory may cite a message/artifact rather than
            # another memory. Known internal sources retain their scope.
            line = message_records.get(store, key, fields=['scope_key', 'deletion_id'])
            known = [line] if line else []
            source = artifact_records.get(store, key, ['scope_key', 'deletion_id'])
            if source:
                known.append(source)
            turn = episode_records.get(store, key, fields=['scope_key', 'deletion_id'])
            if turn:
                known.append(turn)
            known += message_records.of_platform_event(store, key, fields=['scope_key', 'deletion_id'])
            if any(item.get('deletion_id') or item.get('scope_key') not in readable_scopes for item in known):
                raise Denied('DERIVED_SOURCE_SCOPE_DENIED')
            evidence_ids.add(key)
    for source in sources:
        roots(source, set())
    processed = set((base or {}).get('processed_source_ids', []))
    if evidence_ids and evidence_ids.issubset(processed):
        raise Conflict('NO_NEW_SOURCE_EVENTS')
    new_id = sha(canonical({'mutation_id': mutation_id, 'entity': entity, 'scope': scope}))
    # origin: where and when a revision was written, for a record read in other conversations (understanding.py).
    metadata = {k: v for k, v in {'reason': reason, 'change_class': change_class, 'origin': origin}.items()
                if v is not None}
    written = save_revision(store, {'_id': new_id, 'mutation_id': mutation_id, 'entity_key': entity + '|' + scope,
                                    'scope_key': scope, 'content': content, 'source_ids': sources,
                                    'processed_source_ids': sorted(processed | evidence_ids),
                                    'parent_revision_id': base_revision_id, **metadata},
                            stream='mutation:' + mutation_id)
    if first:
        save_head(store, {'_id': entity + '|' + scope, 'scope_key': scope, 'revision_id': new_id},
                  stream='mutation:' + mutation_id)
    else:
        save_head(store, {**head_row, 'revision_id': new_id}, expected=head_row['revision'],
                  stream='mutation:' + mutation_id)
    return written
