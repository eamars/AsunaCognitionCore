"""The memory page on MongoDB, kept by ADR-104 decision 9 (a break would leak private data): private heads and
undelivered messages cannot be read, her idea notebook shows only in an owner-private view, and usage never borrows
another context."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from asuna.records import heads as head_records
from asuna.native_api import NativeMemory
from asuna.native_worker import BusinessWorker
from asuna.state import Denied

from turn_parts import raw_insert

pytestmark = pytest.mark.world                # `store` is the fixture world


@pytest.fixture
def view(store):
    store.config['character_id'], store.config['chat'] = 'character', {'persona': 'p'}
    scene = {'_id': 'qq:bot:group:one', 'scope_key': 'scene:one', 'policy_epoch': 1,
             'members': ['qq:11', 'qq:22']}
    raw_insert(store, 'scenes', scene)
    binding = {'_id': 'role', 'native_host': True, 'lane': 'character', 'role_session_id': 'role',
               'persona': 'p', 'person_id': 'qq:11', 'scene_id': scene['_id'],
               'scope_key': scene['scope_key'], 'policy_epoch': 1}
    raw_insert(store, 'sessions', binding)
    from asuna.documents import DocumentStore
    DocumentStore(store, 'p').seed('persona', 'persona', '真实人格正文', path='persona.md')   # the persona is a document
    head_records.init(store, 'relationship:qq:11', 'scene:one', {'body': '这个人偏好简洁表达'}, [])
    worker = BusinessWorker()
    worker.app = SimpleNamespace(store=store)
    return store, worker, binding


def snapshot(store, binding, **changes):
    persona = head_records.current(store, 'doc:p:persona', 'global-safe')[0]
    relation = head_records.current(store, 'relationship:qq:11', 'scene:one')[0]
    episode = {'_id': 'ep', 'native_session_id': 'role', 'scene_id': binding['scene_id'],
               'person_id': binding['person_id'], 'scope_key': binding['scope_key'],
               'policy_epoch': 1, 'persona': 'p', 'monologue_refs': ['thought'],
               'context': {'person_id': binding['person_id'], 'policy_epoch': 1,
                           'self_state_from_program': {}},
               'manifest': {'persona_revision': persona['revision_id'], 'selected': ['selected'],
                            'relationship_entity_key': relation['_id'],
                            'relationship_revision': relation['revision_id']}, **changes}
    raw_insert(store, 'episodes', deepcopy(episode))
    store.audit('ep', 'context.prepared', {'context': episode['context']}, binding['scope_key'])
    return episode


@pytest.mark.parametrize('changes', [
    {'native_session_id': 'other'}, {'policy_epoch': 2}, {'person_id': 'qq:22'},
    {'scene_id': 'other'}, {'persona': 'other'},
])
def test_usage_never_borrows_another_context(view, changes):
    store, worker, binding = view
    snapshot(store, binding, **changes)
    memory = NativeMemory(worker, 'role')
    assert memory.cognition.snapshot is None
    assert memory.detail('doc:persona')['usage'] == 'none'


def test_private_heads_and_undelivered_messages_cannot_be_read(view):
    store, worker, binding = view
    memory = NativeMemory(worker, 'role')
    for identifier in ('head:relationship:qq:22|scene:one', 'person:qq:22'):
        with pytest.raises(Denied, match='MEMORY_NOT_VISIBLE'):
            memory.detail(identifier)
    raw_insert(store, 'messages', {'_id': 'unsent', 'scene_id': binding['scene_id'], 'policy_epoch': 1,
                                  'direction': 'outbound', 'delivery_state': 'SENDING', 'text': '未送达'})
    with pytest.raises(Denied, match='MEMORY_NOT_VISIBLE'):
        memory.detail('source:unsent')
    store.raw.scenes.update_one({'_id': binding['scene_id']}, {'$set': {'policy_epoch': 2}})
    with pytest.raises(Denied, match='NATIVE_SESSION_EPOCH_CHANGED'):
        NativeMemory(worker, 'role')


def test_her_idea_notebook_is_shown_only_in_an_owner_private_view(view):
    store, worker, binding = view
    raw_insert(store, 'ideas', {'_id': 'idea-1', 'persona': 'p', 'idea': '回复可以更短', 'why': '有人嫌长', 'state': 'adopted',
                               'source': {'by': 'character', 'scene_id': binding['scene_id']}, 'created_at': '2026-10-05T00:00:00+00:00',
                               'decisions': [{'decision': 'adopt', 'why': '值得做', 'at': '2026-10-05T01:00:00+00:00'}]})
    assert NativeMemory(worker, 'role').page('ideas')['rows'] == [], 'a group conversation never shows her notebook'
    store.config['chat'].update(scene_id=binding['scene_id'], person_id=binding['person_id'])   # now the owner's own
    rows = NativeMemory(worker, 'role').page('ideas')['rows']
    assert [(row['id'], row['title']) for row in rows] == [('idea:idea-1', '回复可以更短')]
    detail = NativeMemory(worker, 'role').detail('idea:idea-1')
    assert detail['status'] == 'idea.adopted' and {'key': 'memory.idea.decision.adopt', 'params': {'why': '值得做'}} in detail['body']


