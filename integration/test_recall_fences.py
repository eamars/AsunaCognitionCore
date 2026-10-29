"""On MongoDB: recall's fences (ADR-009 T4.2). An owner-private memory comes back in her owner-private recall and
never in a public conversation's, not even as a lexical candidate, and a public search may not link an owner-private
scope. On a throwaway database holding the fixture world (conftest.py)."""
import json

import pytest

from asuna.evidence import Evidence
from asuna.persona_data import PersonaDataAPI
from asuna.retrieval import Retrieval


@pytest.fixture
def retrieval(world, tmp_path):
    value = Retrieval(world, Evidence(tmp_path / 'evidence'))
    yield value
    value.close()


def owner(store, scene='dm-a', person='A'):
    """Make (scene, person) the owner's local scene: its turns are owner_private."""
    store.config['chat'] = {**store.config.get('chat', {}), 'scene_id': scene, 'person_id': person,
                            'persona': 'P1', 'display_name': '示例角色'}
    return store


def api(store, retrieval):
    owner(store)
    return PersonaDataAPI(store, 'P1', run_id='run-test', job_id='migrate', grants=('persona_data.write', 'probe'),
                          sources={'demo-home': 'cohabiting'}, retrieval=retrieval)


def unit(identity, body, vis='owner_private'):
    return {'source_identity': identity, 'entry_type': 'diary', 'body_markdown': body, 'visibility': vis,
            'source_window': {'origin': 'demo-home', 'path': 'diary/2026-01.md', 'file_sha256': 'f' * 64,
                              'line_from': 1, 'line_to': 2, 'heading': identity}}


def test_T4_2_owner_private_units_never_reach_public_retrieval(world, retrieval):
    data = api(world, retrieval)
    data.dispatch('memory.upsert', {'origin': 'demo-home', 'units': [unit('secret', 'PRIVATE_TOKEN_CANARY 深夜的心事')]})
    private, _ = retrieval.search('scene:dm-a', 1, 'PRIVATE_TOKEN_CANARY 深夜的心事', private_scope='owner-private:P1')
    public, manifest = retrieval.search('scene:g1', 1, 'PRIVATE_TOKEN_CANARY 深夜的心事')
    assert any(m['source_identity'] == 'secret' for m in private if m.get('source_identity'))
    assert not any(m.get('source_identity') == 'secret' for m in public)
    assert 'imp-' not in json.dumps(manifest.get('lexical_ids'))                 # not even a lexical candidate
    with pytest.raises(ValueError):
        retrieval.search('scene:g1', 1, 'x', linked_scopes=['owner-private:P1'], private_scope='scene:g1')
    if manifest['path'] != 'server_vector_rrf':
        pytest.skip('vector filter not exercised: embedding service unavailable (lexical candidates verified above)')
