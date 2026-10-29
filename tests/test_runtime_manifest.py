"""What the packer ships of src/asuna: every tracked file of the tree, which imports from the packed copy, and the
committed runtime manifest that her core publications copy files by."""
import importlib.util
import json
import sys
from pathlib import Path

from asuna import repo_files

ROOT = Path(__file__).resolve().parents[1]


def packer():
    spec = importlib.util.spec_from_file_location('pack_plugins', ROOT / 'tools/pack_plugins.py')
    pack = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pack)
    return pack


def test_every_tracked_worker_file_ships_and_the_packed_copy_imports_from_itself(tmp_path):
    """Regression: a new package (src/asuna/records/) was not shipped, the packed worker did not import, and a start
    fell back to the version before (2026-10-28). No list names the packages: each one the tree has ships."""
    pack = packer()
    staged = tmp_path / 'python'
    mappings = pack.stage_worker(staged / 'asuna')
    tracked = [name for name in repo_files.files(ROOT, 'src/asuna') if name not in pack.NOT_IN_WORKER]
    expected = {'asuna/' + name.removeprefix('src/asuna/'): ROOT / name for name in tracked}
    expected['asuna/resources/RUNTIME_API.md'] = ROOT / 'RUNTIME_API.md'
    shipped = {path.relative_to(staged).as_posix(): path for path in staged.rglob('*') if path.is_file()}
    assert sorted(shipped) == sorted(expected), 'the packed copy is not the tracked tree'
    differing = [name for name, source in expected.items() if shipped[name].read_bytes() != source.read_bytes()]
    assert not differing, differing
    # The check her starts rely on: each package and module imports from the packed copy, none from elsewhere.
    code, output = pack.check_worker_imports(sys.executable, staged, tmp_path / 'data')
    assert code == 0, output
    imported = {line.split(' ', 1)[0] for line in output.splitlines()}
    packages = {path.parent.relative_to(ROOT / 'src').as_posix().replace('/', '.')
                for path in (ROOT / 'src/asuna').rglob('__init__.py')}
    assert packages <= imported and {'asuna', 'asuna.store', 'asuna.records'} <= packages, sorted(packages - imported)
    # A stale list (a deleted file still named, a new one missing) breaks her next core publication.
    from asuna.development import DEVELOPMENT_TOOLS
    manifest = json.loads((ROOT / 'packages/cognition-core/runtime-manifest.json').read_text(encoding='utf-8'))
    assert manifest == {'files': mappings, 'developmentTools': DEVELOPMENT_TOOLS},         'run tools/pack_plugins.py and commit packages/cognition-core/runtime-manifest.json'


def test_packing_removes_artifacts_nothing_names_any_more(tmp_path, monkeypatch):
    pack = packer()
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


def test_every_folder_a_package_ships_is_one_the_packer_admits():
    """Regression: the core's new meta/ folder was refused at pack time and the Host did not start (2026-10-09)."""
    import json
    source = (ROOT / 'tools/pack_plugins.py').read_text(encoding='utf-8')
    allowed = source.split('allowed = (', 1)[1].split(')', 1)[0]
    for manifest in [ROOT / 'packages/cognition-core/package.json', *ROOT.glob('packages/personas/*/package.json'),
                     *ROOT.glob('packages/channels/*/package.json')]:
        for entry in json.loads(manifest.read_text(encoding='utf-8')).get('files', []):
            if (manifest.parent / entry).is_dir():
                assert "'package/%s/'" % entry in allowed, '%s ships %s/, which the packer refuses' % (manifest.parent.name, entry)
