"""The committed runtime manifest lists what the packer bundles: her core publications copy files by it."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_committed_runtime_manifest_matches_the_sources():
    spec = importlib.util.spec_from_file_location('pack_plugins', ROOT / 'tools/pack_plugins.py')
    pack = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pack)
    from asuna.development import DEVELOPMENT_TOOLS
    resources = ROOT / 'src/asuna/resources'
    files = [[f'src/asuna/{name}.py', f'python/asuna/{name}.py'] for name in pack.runtime_modules()]
    for path in sorted(p for p in resources.rglob('*') if p.is_file() and '__pycache__' not in p.parts):
        relative = path.relative_to(resources).as_posix()
        files.append([f'src/asuna/resources/{relative}', f'python/asuna/resources/{relative}'])
    files.append(['RUNTIME_API.md', 'python/asuna/resources/RUNTIME_API.md'])
    manifest = json.loads((ROOT / 'packages/cognition-core/runtime-manifest.json').read_text(encoding='utf-8'))
    # A stale list (a deleted module still named, a new one missing) breaks her next core publication.
    assert manifest == {'files': files, 'developmentTools': DEVELOPMENT_TOOLS}, \
        'run tools/pack_plugins.py and commit packages/cognition-core/runtime-manifest.json'
