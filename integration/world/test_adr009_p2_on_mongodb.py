"""ADR-009 P2 on MongoDB, kept by ADR-104 decision 9 (a break would leak private data): recall reads a document's
sections by their visibility, and the action brain gets public values only."""
import json

import pytest

from asuna.coordinator import Coordinator
from asuna.documents import DocumentStore
from asuna.lanes import FakeLane, FakeTurn
from asuna.render import action_values

from turn_parts import event

pytestmark = pytest.mark.world                # `store` is the fixture world


def owner(store, scene='dm-a', person='A'):
    """Make (scene, person) the owner's local scene: its turns are owner_private."""
    store.config['chat'] = {**store.config.get('chat', {}), 'scene_id': scene, 'person_id': person,
                            'persona': 'P1', 'display_name': '示例角色'}
    return store


THINK = ('think', {'thought': '他说了一件小事，值得记下来。'})


def test_T2_7_recall_reads_sections_by_visibility(store):
    owner(store)
    docs = DocumentStore(store, 'P1')
    docs.seed('notes', 'working', '<!-- asuna-seed {"visibility": "owner_private"} -->\n## 私密\nPRIVATE_NOTE_BODY\n')
    read = ('recall', {'query': '笔记', 'sections': [{'doc': 'notes', 'sid': '私密'}]})
    lane = FakeLane(store, [FakeTurn([THINK, read], '看到了。')])
    Coordinator(store, lane).ingest(event('read-private'))
    result = lane.tool_results[1]
    assert result[5] and 'PRIVATE_NOTE_BODY' in result[4]['documents'][0]['body']
    group = FakeLane(store, [FakeTurn([THINK, read], '没看到。')])
    ep = Coordinator(store, group).ingest(event('read-group', scene='g1'))
    result = group.tool_results[1]
    assert ep['state'] == 'COMMITTED' and result[5] and 'documents' not in result[4]
    assert result[4]['not_read'] == ['notes#私密：这里读不到']
    assert 'PRIVATE_NOTE_BODY' not in json.dumps([group.calls, group.tool_results], ensure_ascii=False)


def test_T2_10_action_brain_gets_public_values_only(store):
    from asuna.persona_model import neutral
    owner(store)
    model = neutral('P1', 'P1')
    store.config['persona_model'] = {**model, 'render': {**model.get('render', {}), 'action_persona': 'values'}}
    docs = DocumentStore(store, 'P1')
    for i, (vis, tags) in enumerate([('public', ['values']), ('owner_private', ['values']), ('public', [])]):
        docs.apply('persona', {'op': 'append_section', 'heading': f'节{i}', 'visibility': vis, 'tags': tags,
                               'reason': '测试'}, f'SECTION_BODY_{i}', base_revision_id=docs.read('persona')[0],
                   author='operator', mutation_id=f't210-{i}')
    text = action_values(store, 'P1')
    assert 'SECTION_BODY_0' in text and 'SECTION_BODY_1' not in text and 'SECTION_BODY_2' not in text


