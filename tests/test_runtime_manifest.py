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


def test_packing_removes_artifacts_nothing_names_any_more(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('pack_plugins', ROOT / 'tools/pack_plugins.py')
    pack = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pack)
    adr008 = tmp_path / 'adr008'
    monkeypatch.setattr(pack, 'DESTINATION', adr008 / 'packages')
    pack.DESTINATION.mkdir(parents=True)
    for name in ('core-1-aaaa.tgz', 'core-1-bbbb.tgz', 'core-1-cccc.tgz', 'core-1-dddd.tgz', 'core-1.tgz'):
        (pack.DESTINATION / name).write_bytes(b'x')
    installed = adr008 / 'profiles/demo/home/profiles/demo'
    installed.mkdir(parents=True)
    (installed / 'package.json').write_text(json.dumps({'dependencies': {
        '@asuna/core': 'file:C:/data/adr008/packages/core-1-bbbb.tgz'}}), encoding='utf-8')
    (adr008 / 'activation.json').write_text(json.dumps({'projects': {'core': {
        'artifact': r'C:\data\adr008\packages\core-1-cccc.tgz'}}}), encoding='utf-8')
    pack.prune([{'path': str(pack.DESTINATION / 'core-1-aaaa.tgz')}])
    # This pack, what a profile installed and what a selection names stay; older packs and npm's copy go.
    assert sorted(p.name for p in pack.DESTINATION.iterdir()) == ['core-1-aaaa.tgz', 'core-1-bbbb.tgz', 'core-1-cccc.tgz']
