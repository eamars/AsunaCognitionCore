"""Her web_search goes through the cognition core's ordered provider (ADR-026): the installer pins it on DSH's web
seam, with its fetch provider (fetch.js) for web_fetch."""
import importlib.util
from pathlib import Path

from asuna.config import load

ROOT = Path(__file__).resolve().parents[1]


def test_the_profile_pins_the_ordered_search_and_keeps_fetch():
    spec = importlib.util.spec_from_file_location('setup_native_profile', ROOT / 'tools/setup_native_profile.py')
    setup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup)
    config = load(ROOT / 'config/local.example.json')
    persona = {'preset': 'p', 'project': 'persona', 'root': ROOT}
    rows = {row['id']: row for row in setup.profile_patch(config, ROOT / 'config/local.example.json', persona, profile='probe')}
    assert rows['web'] == {'id': 'web', 'config': {'searchProvider': 'asuna-search', 'fetchProvider': 'asuna-fetch'}}


def test_the_worker_leaves_the_search_section_and_its_unset_credential_alone():
    from asuna import native_settings
    deployment = {'database': 'd', 'mongo_uri': 'mongodb://127.0.0.1', 'chat': {}, 'embedding': {'base_url': 'http://127.0.0.1:9/v1', 'model': 'm'},
                  'search': {'exa': {'api_key': {'$secret': 'EXA_API_KEY'}}}}
    resolved = native_settings.runtime_settings(deployment, {}, {'character': {'model': 'x'}, 'action': {'model': 'x'}},
                                                persona='p')
    assert 'search' not in resolved
