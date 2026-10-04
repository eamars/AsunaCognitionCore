"""Build the core plugin and any persona packages passed with --persona; no local state or secrets."""
import argparse
import json
import hashlib
import shutil
from pathlib import Path
import subprocess
import tarfile
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / '.runtime/adr008/packages'
# Everything in the business package ships except the debug CLI and its Web shim.
NOT_IN_WORKER = {'cli', 'native_ui'}


def runtime_modules():
    return sorted(p.stem for p in (ROOT / 'src/asuna').glob('*.py') if p.stem not in NOT_IN_WORKER)


def prepare_resources(destination: Path) -> list:
    """Copy behavior resources next to the worker modules; no npm, no network.

    Returns the source → packaged path mapping recorded in runtime-manifest.json.
    """
    source = ROOT / 'src/asuna/resources'
    target = destination / 'resources'
    if target.exists():
        shutil.rmtree(target)
    mappings = []
    for path in sorted(p for p in source.rglob('*') if p.is_file() and '__pycache__' not in p.parts):
        relative = path.relative_to(source).as_posix()
        (target / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target / relative)
        mappings.append([f'src/asuna/resources/{relative}', f'python/asuna/resources/{relative}'])
    shutil.copyfile(ROOT / 'RUNTIME_API.md', target / 'RUNTIME_API.md')
    mappings.append(['RUNTIME_API.md', 'python/asuna/resources/RUNTIME_API.md'])
    return mappings


def bundle_python():
    """An explicit runtime allowlist; no debug CLI, local state or secrets."""
    destination = ROOT / 'packages/cognition-core/python/asuna'
    destination.mkdir(parents=True, exist_ok=True)
    for cache in destination.rglob('__pycache__'):
        if not cache.resolve().is_relative_to(destination.resolve()):
            raise ValueError('Unexpected cache outside the package')
        shutil.rmtree(cache)
    modules = runtime_modules()
    expected = {name + '.py' for name in modules}
    for existing in destination.glob('*.py'):
        if existing.name not in expected:
            existing.unlink()
    for filename in sorted(expected):
        shutil.copyfile(ROOT / 'src/asuna' / filename, destination / filename)
    from asuna.development import DEVELOPMENT_TOOLS
    mappings = [[f'src/asuna/{name}.py', f'python/asuna/{name}.py'] for name in modules]
    mappings += prepare_resources(destination)
    (ROOT / 'packages/cognition-core/runtime-manifest.json').write_text(
        json.dumps({'files': mappings, 'developmentTools': DEVELOPMENT_TOOLS}, indent=2), encoding='utf-8', newline='\n')
    (destination.parent / 'pyproject.toml').write_text('''[build-system]
requires = ["hatchling==1.30.1"]
build-backend = "hatchling.build"
[project]
name = "asuna-cognition-worker"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["httpx==0.28.1", "pymongo==4.16.0", "jsonschema==4.26.0", "pydantic==2.12.5", "PyYAML==6.0.3"]
[tool.hatch.build.targets.wheel]
packages = ["asuna"]
''', encoding='utf-8')
    subprocess.run([sys.executable, '-c',
        "import sys; import asuna.native_worker; assert 'asuna.cli' not in sys.modules"],
        cwd=destination.parent, env={**os.environ, 'ASUNA_DATA_ROOT': str(ROOT),
            'PYTHONPATH': str(destination.parent), 'PYTHONDONTWRITEBYTECODE': '1'}, check=True, capture_output=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--persona', action='append', default=[], type=Path,
                        help='persona package directory to pack alongside the core (repeatable)')
    args = parser.parse_args()
    DESTINATION.mkdir(parents=True, exist_ok=True)
    # The native inline extension (tools/dsh-inline) is built separately; pack only a current build.
    native = json.loads((DESTINATION / 'native-inline-manifest.json').read_text(encoding='utf-8'))
    patch_digest = hashlib.sha256((ROOT / 'tools/dsh-inline/rc2-inline.patch').read_bytes()).hexdigest()
    for artifact in native:
        if artifact['patchSha256'] != patch_digest or hashlib.sha256(Path(artifact['path']).read_bytes()).hexdigest() != artifact['sha256']:
            raise ValueError('Rebuild the current native inline extension before packing plugins')
    bundle_python()
    artifacts = list(native)
    for directory in [ROOT / 'packages/cognition-core', *[p.resolve() for p in args.persona]]:
        result = subprocess.run(['npm.cmd', 'pack', '--json', '--pack-destination', str(DESTINATION)],
                                cwd=directory, capture_output=True, text=True, check=True)
        package = json.loads(result.stdout)[0]
        path = DESTINATION / package['filename']
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        addressed = path.with_name(path.stem + '-' + digest[:12] + '.tgz')
        if addressed.exists():
            if addressed.read_bytes() != path.read_bytes():
                raise ValueError('Artifact digest collision')
        else:
            shutil.copyfile(path, addressed)
        path = addressed
        with tarfile.open(path, 'r:gz') as archive:
            allowed = ('package/src/', 'package/persona/', 'package/seeds/', 'package/jobs/', 'package/skills/', 'package/python/', 'package/integrations/')
            exact = {'package/package.json', 'package/cordis.patch.yml', 'package/README.md', 'package/runtime-manifest.json', 'package/resources-provenance.json', 'package/persona-model.json'}
            for entry in archive.getmembers():
                if '/__pycache__/' in entry.name or entry.name.endswith('.pyc'):
                    raise ValueError('Generated bytecode in package: ' + entry.name)
                if not entry.isfile() or not (entry.name in exact or entry.name.startswith(allowed)):
                    raise ValueError('Unexpected packaged entry: ' + entry.name)
        artifacts.append({'name': package['name'], 'path': str(path), 'integrity': package['integrity'],
                          'sha256': digest,
                          'files': [row['path'] for row in package['files']]})
    (DESTINATION / 'manifest.json').write_text(json.dumps(artifacts, indent=2), encoding='utf-8')
    print(json.dumps([{k:v for k,v in item.items() if k != 'files'} for item in artifacts], indent=2))


if __name__ == '__main__':
    main()
