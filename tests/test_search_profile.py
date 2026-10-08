"""Her web_search goes through the cognition core's ordered provider (ADR-026): the installer pins it on DSH's web
seam, and restates the base row's fetch provider because a profile patch replaces the whole row config."""
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
    assert rows['web'] == {'id': 'web', 'config': {'searchProvider': 'asuna-search', 'fetchProvider': 'http'}}
