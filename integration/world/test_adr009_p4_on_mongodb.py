"""ADR-009 P4 on MongoDB, kept by ADR-104 decision 9 (a break would leak private data): owner-private derived data
stays out of linked public scenes, and a consult from a public task sees no owner-private material."""
import json
import shutil
import uuid

import pytest

from asuna.config import DATA
from asuna.context import ContextBuilder
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn

from turn_parts import event, owner

THINK = ('think', {'thought': '他说了一件小事，值得记下来。'})

pytestmark = pytest.mark.world                # `store` is the fixture world


def test_T4_11_owner_private_derived_data_stays_out_of_linked_public_scenes(store):
    owner(store)
    from asuna.visibility import without_link_downgrades
    store.config['context_links'] = {'g1': ['dm-a']}
    cleaned, rejected = without_link_downgrades(store.config)
    assert rejected and cleaned['context_links']['g1'] == []
    ep = Coordinator(store, FakeLane(store, [FakeTurn([('think', {'thought': 'OWNER_MONOLOGUE_CANARY'})], '好。')])).ingest(event('own-1'))
    assert store.raw.memory_units.find_one({'_id': ep['monologue_refs'][0]})['body_markdown'] == 'OWNER_MONOLOGUE_CANARY'
    store.config.update(cleaned)
    _, context, _ = ContextBuilder(store).prepare(event('pub-1', scene='g1'), 'P1')
    assert 'OWNER_MONOLOGUE_CANARY' not in json.dumps(context, ensure_ascii=False)


def test_T4_12_consult_from_a_public_task_sees_no_owner_private_material(store):
    owner(store)
    from asuna.documents import DocumentStore
    docs = DocumentStore(store, 'P1')
    docs.apply('persona', {'op': 'append_section', 'heading': '私密', 'visibility': 'owner_private', 'reason': 't'},
               'OWNER_PRIVATE_PERSONA_CANARY', base_revision_id=docs.read('persona')[0], author='operator', mutation_id='t412')
    work = DATA / 'work' / ('t412-' + uuid.uuid4().hex[:8]); work.mkdir(parents=True)
    try:
        store.config['channels'] = {'f': {'routes': {'g': {'scene_id': 'g1', 'target': {'type': 'group', 'id': 'x'},
                                    'members': {'s': {'person_id': 'A', 'workspace': str(work), 'read_only_paths': []}}}}}}
        delegate = ('delegate', {'title': '整理公开清单', 'brief': '把群里提到的公开清单整理一下。'})
        ep = Coordinator(store, FakeLane(store, [FakeTurn([THINK, delegate], '我交给行动脑了。')])).ingest(event('consult-g', scene='g1'))
        assert ep['manifest']['session_class'] == 'public' and ep['task_ids'], (ep['manifest'], ep.get('failure'))
        from asuna.tasks import TaskService
        task = TaskService(store).claim(ep['task_ids'][0])
        role = FakeLane(store, [FakeTurn([THINK, ('task', {'do': 'answer', 'answer': '建议先确认清单。'})])])
        answer = Coordinator(store, role).consult(task, 'c1', {'question': '怎么排？'})
        assert answer['answer'] == '建议先确认清单。' and role.calls
        assert 'OWNER_PRIVATE_PERSONA_CANARY' not in json.dumps([role.calls, role.tool_results], ensure_ascii=False)
    finally:
        shutil.rmtree(work, ignore_errors=True)
