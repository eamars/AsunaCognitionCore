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


def test_private_heads_and_undelivered_messages_cannot_be_read(view):
    store, worker, binding = view
    memory = NativeMemory(worker, 'role')
    for identifier in ('head:relationship:qq:22|scene:one', 'person:qq:22'):
        with pytest.raises(Denied, match='MEMORY_NOT_VISIBLE'):
            memory.detail(identifier)
    store.db.messages.insert_one({'_id': 'unsent', 'scene_id': binding['scene_id'], 'policy_epoch': 1,
                                  'direction': 'outbound', 'delivery_state': 'SENDING', 'text': '未送达'})
    with pytest.raises(Denied, match='MEMORY_NOT_VISIBLE'):
        memory.detail('source:unsent')
    store.db.scenes.update_one({'_id': binding['scene_id']}, {'$set': {'policy_epoch': 2}})
    with pytest.raises(Denied, match='NATIVE_SESSION_EPOCH_CHANGED'):
        NativeMemory(worker, 'role')


def test_people_she_knows_and_people_here(view):
    # Owner 2026-10-16: People was only the person this conversation is bound to. Now every person she has written
    # about is listed everywhere (searchable), and a conversation lists the last people who spoke in it.
    store, worker, binding = view
    store.init_head('relationship:qq:11', 'person', {'body': '哪儿都成立的那层'}, [])
    store.db.scene_people.insert_one({'_id': 'sp', 'person': 'qq:11', 'scene_id': binding['scene_id'], 'card': '同学',
                                      'seen_at': '2026-10-16T00:00:00+00:00'})
    people = NativeMemory(worker, 'role').page('people')
    assert [(row['id'], row['title'], row['scene_title']) for row in people['rows']] == [('person:qq:11', '同学', None)]
    assert NativeMemory(worker, 'role').page('people', search='没有的人')['rows'] == []
    detail = NativeMemory(worker, 'role').detail('person:qq:11')
    texts = [part for part in detail['body'] if isinstance(part, str) and part.strip()]
    assert texts == ['哪儿都成立的那层', '这个人偏好简洁表达'], 'what holds anywhere first, then each conversation'
    for n, author in enumerate(['qq:11', 'qq:22', 'qq:11']):
        store.db.messages.insert_one({'_id': f'm{n}', 'scene_id': binding['scene_id'], 'direction': 'inbound',
                                      'author': author, 'occurred_at': f'2026-10-16T00:0{n}:00+00:00'})
    here = {row['id']: row for row in NativeMemory(worker, 'role').page('here_people')['rows']}
    assert set(here) == {'person:qq:11', 'person:qq:22'}
    assert here['person:qq:11']['excerpt'] == '这个人偏好简洁表达'
    assert here['person:qq:22']['excerpt'] == {'key': 'memory.status.empty', 'params': {}}


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


def test_the_tab_shows_her_memory_as_her_turns_read_it(view):
    # Regression: after the tiered-memory redesign the tab still listed the old self heads (one stale, one empty),
    # only one of the two records about a person, each section's written label instead of its place, and timed
    # her thoughts through the audit log (2.7 s for "all").
    store, worker, binding = view
    from asuna.documents import DocumentStore
    docs = DocumentStore(store, 'p')
    docs.seed('self', 'self', '## 说话直接\n不绕。\n\n## 先读再说\n猜完先去拿读数。', path='self.md')
    sections = docs.read('self')[1]['sections']
    store.db.memory_tiers.insert_one({'_id': 'tier-1', 'row': 'item', 'persona': 'p', 'doc': 'self',
                                      'sid': sections[-1]['sid'], 'place': '收着', 'memorable_at': '2026-10-15T00:00:00+00:00'})
    store.init_head('current_self:p', 'global-safe', {'body': '旧的一整段'}, [])
    rows = NativeMemory(worker, 'role').page('self')['rows']
    ids = [row['id'] for row in rows]
    assert len([i for i in ids if i.startswith('item:self#')]) == len(sections)
    assert 'head:current_self:p|global-safe' not in ids, 'the old head is gone once she has written her self as items'
    assert 'head:character_core:p|global-safe' in ids, 'an empty core leaves its old head'
    put_away = next(row for row in rows if row['id'].endswith(sections[-1]['sid']))
    assert put_away['excerpt'][-1] == {'key': 'memory.inject.never', 'params': {}}
    detail = NativeMemory(worker, 'role').detail('doc:self')
    assert {'key': 'memory.inject.never', 'params': {}} in [part['params']['inject'] for part in detail['body']
                                                          if isinstance(part, dict) and part['key'] == 'memory.doc.meta']
    assert all(row['scene_title'] is None for row in NativeMemory(worker, 'role').page('self')['rows']
               if row['id'].startswith('item:'))
    for unit, formed in (('older', '2026-10-01T00:00:00+00:00'), ('newer', '2026-10-02T00:00:00+00:00')):
        store.db.memory_units.insert_one({'_id': unit, 'character_id': 'character', 'scope_key': 'scene:one',
            'policy_epoch': 1, 'status': 'active', 'kind': 'monologue', 'formed_at': formed,
            'epistemic_type': 'character_interpretation', 'body_markdown': unit})
    assert NativeMemory(worker, 'role').detail('unit:older')['generated_at'] == '2026-10-01T00:00:00+00:00'


def test_documents_are_named_and_counted_by_place(view):
    # Owner 2026-10-16: a reader tells her documents apart by name and sees how much of each she carries.
    store, worker, _ = view
    from asuna.documents import DocumentStore
    DocumentStore(store, 'p').seed('self', 'self', '## 一\n甲\n\n## 二\n乙', path='self.md')
    rows = {row['id']: row for row in NativeMemory(worker, 'role').page('documents')['rows']}
    assert rows['doc:persona']['title'] == {'key': 'memory.doc.persona', 'params': {}}
    assert rows['doc:self']['title'] == {'key': 'memory.doc.self', 'params': {}}
    places = [part['params']['label']['key'] for part in rows['doc:self']['excerpt'] if isinstance(part, dict)]
    assert places and all(key.startswith('memory.inject.') for key in places)
    with pytest.raises(ValueError, match='INVALID_MEMORY_CATEGORY'):
        NativeMemory(worker, 'role').page('all')


def test_a_groups_notes_are_this_groups_not_every_documents(view):
    # Owner 2026-10-16: Documents showed every group's notes in any conversation. A group's notes are listed in
    # that group's own conversation only.
    store, worker, binding = view
    from asuna.documents import DocumentStore
    from asuna.group_admin import notes_slug
    store.db.scenes.update_one({'_id': binding['scene_id']}, {'$set': {'kind': 'group'}})
    slug = notes_slug(binding['scene_id'])
    DocumentStore(store, 'p').seed(slug, 'working', '## 群规\n别刷屏', path='notes.md')
    assert 'doc:' + slug not in {row['id'] for row in NativeMemory(worker, 'role').page('documents')['rows']}
    notes = NativeMemory(worker, 'role').page('group_notes')['rows']
    assert [row['title'] for row in notes] == ['群规'] and notes[0]['scene_title'] is None
    assert NativeMemory(worker, 'role').detail(notes[0]['id'])['category'] == 'group_notes'
    assert NativeMemory(worker, 'role').page('documents')['scene_kind'] == 'group'
