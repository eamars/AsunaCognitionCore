"""Cognitive-view authority and truthful missing/selected state regressions."""
from copy import deepcopy
from types import SimpleNamespace

import mongomock
import pytest

from asuna.native_api import NativeMemory
from asuna.native_worker import BusinessWorker
from asuna.state import Denied, Store


@pytest.fixture
def view():
    store = Store.__new__(Store)
    store.config = {'character_id': 'character', 'chat': {'persona': 'p'}}
    store.name, store.fail_audit = 'in-memory', False
    store.db = mongomock.MongoClient()[store.name]
    scene = {'_id': 'qq:bot:group:one', 'scope_key': 'scene:one', 'policy_epoch': 1,
             'members': ['qq:11', 'qq:22']}
    store.db.scenes.insert_one(scene)
    binding = {'_id': 'role', 'native_host': True, 'lane': 'character', 'role_session_id': 'role',
               'persona': 'p', 'person_id': 'qq:11', 'scene_id': scene['_id'],
               'scope_key': scene['scope_key'], 'policy_epoch': 1}
    store.db.sessions.insert_one(binding)
    from asuna.documents import DocumentStore
    DocumentStore(store, 'p').seed('persona', 'persona', '真实人格正文', path='persona.md')   # the persona is a document
    store.init_head('relationship:qq:11', 'scene:one', {'body': '这个人偏好简洁表达'}, [])
    worker = BusinessWorker()
    worker.app = SimpleNamespace(store=store)
    return store, worker, binding


def snapshot(store, binding, **changes):
    persona = store.head('doc:p:persona', 'global-safe')[0]
    relation = store.head('relationship:qq:11', 'scene:one')[0]
    episode = {'_id': 'ep', 'native_session_id': 'role', 'scene_id': binding['scene_id'],
               'person_id': binding['person_id'], 'scope_key': binding['scope_key'],
               'policy_epoch': 1, 'persona': 'p', 'monologue_refs': ['thought'],
               'context': {'person_id': binding['person_id'], 'policy_epoch': 1,
                           'self_state_from_program': {}},
               'manifest': {'persona_revision': persona['revision_id'], 'selected': ['selected'],
                            'relationship_entity_key': relation['_id'],
                            'relationship_revision': relation['revision_id']}, **changes}
    store.db.episodes.insert_one(deepcopy(episode))
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


def test_peer_projection_reuses_authenticated_sender_and_scene_checks(view):
    store, worker, binding = view
    row = {'_id': 'message', 'direction': 'inbound', 'scene_id': binding['scene_id'],
           'policy_epoch': 1, 'author': 'qq:11', 'scene_seq': 1, 'text': '原话',
           'event': {'channel': {'id': 'qq', 'sender_id': '11', 'target': {'type': 'group', 'id': 'one'}},
                     'raw': {'asuna_peer': {'person_id': 'qq:11', 'account_id': '11',
                         'group_id': 'one', 'scene': 'group:one', 'display': '同学',
                         'role': 'member', 'verified': True}}}}
    store.db.messages.insert_one(row)
    memory = NativeMemory(worker, 'role')
    detail = memory.detail('cognition:peer')
    assert detail['body'].startswith('当前说话人：[同学 #') and 'qq:11' not in detail['body']
    assert detail['sources'][0]['text'] == '原话'
    store.db.messages.update_one({'_id': 'message'}, {'$set': {'event.raw.asuna_peer.person_id': 'qq:22'}})
    with pytest.raises(Denied, match='MEMORY_NOT_VISIBLE'):      # a mismatched identity block is never shown
        NativeMemory(worker, 'role').detail('cognition:peer')


def test_private_heads_and_undelivered_messages_cannot_be_read(view):
    store, worker, binding = view
    memory = NativeMemory(worker, 'role')
    for identifier in ('head:relationship:qq:22|scene:one', 'cognition:invented'):
        with pytest.raises(Denied, match='MEMORY_NOT_VISIBLE'):
            memory.detail(identifier)
    store.db.messages.insert_one({'_id': 'unsent', 'scene_id': binding['scene_id'], 'policy_epoch': 1,
                                  'direction': 'outbound', 'delivery_state': 'SENDING', 'text': '未送达'})
    with pytest.raises(Denied, match='MEMORY_NOT_VISIBLE'):
        memory.detail('source:unsent')
    store.db.scenes.update_one({'_id': binding['scene_id']}, {'$set': {'policy_epoch': 2}})
    with pytest.raises(Denied, match='NATIVE_SESSION_EPOCH_CHANGED'):
        NativeMemory(worker, 'role')


def test_revision_sources_keep_interpretations_distinct_and_private_sources_hidden(view):
    store, worker, _ = view
    for identifier, scope in (('visible', 'scene:one'), ('private', 'scene:private')):
        store.db.memory_units.insert_one({'_id': identifier, 'character_id': 'character',
            'scope_key': scope, 'policy_epoch': 1, 'status': 'active',
            'epistemic_type': 'character_interpretation', 'body_markdown': identifier + '的理解'})
    revision = store.head('relationship:qq:11', 'scene:one')[1]
    store.db.state_revisions.update_one({'_id': revision['_id']},
        {'$set': {'source_ids': ['visible', 'private']}})
    detail = NativeMemory(worker, 'role').detail('head:relationship:qq:11|scene:one')
    assert [(s['_id'], s['category']) for s in detail['sources']] == [('visible', 'character_interpretation')]


def test_her_idea_notebook_is_shown_only_in_an_owner_private_view(view):
    store, worker, binding = view
    store.db.ideas.insert_one({'_id': 'idea-1', 'persona': 'p', 'idea': '回复可以更短', 'why': '有人嫌长', 'state': 'adopted',
                               'source': {'by': 'character', 'scene_id': binding['scene_id']}, 'created_at': '2026-10-05T00:00:00+00:00',
                               'decisions': [{'decision': 'adopt', 'why': '值得做', 'at': '2026-10-05T01:00:00+00:00'}]})
    assert NativeMemory(worker, 'role').page('ideas')['rows'] == [], 'a group conversation never shows her notebook'
    store.config['chat'].update(scene_id=binding['scene_id'], person_id=binding['person_id'])   # now the owner's own
    rows = NativeMemory(worker, 'role').page('ideas')['rows']
    assert [(row['id'], row['title']) for row in rows] == [('idea:idea-1', '回复可以更短')]
    detail = NativeMemory(worker, 'role').detail('idea:idea-1')
    assert detail['status'] == 'idea.adopted' and {'key': 'memory.idea.decision.adopt', 'params': {'why': '值得做'}} in detail['body']
