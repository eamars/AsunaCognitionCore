"""Build the core plugin and the persona and channel packages passed with --persona / --channel; no local state or secrets."""
import argparse
import json
import hashlib
import shutil
from pathlib import Path
import subprocess
import tarfile
import os
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
# This tree's own source comes first: an environment shared with another checkout (an editable install) would
# otherwise read that checkout's modules.
sys.path.insert(0, str(ROOT / 'src'))
from asuna import repo_files  # noqa: E402

DESTINATION = ROOT / '.runtime/adr008/packages'
# Every tracked file under src/asuna ships with the worker except the debug CLI and its Web shim.
NOT_IN_WORKER = {'src/asuna/cli.py', 'src/asuna/native_ui.py'}


def worker_sources(root=ROOT):
    """The tracked files of src/asuna that ship with the worker (posix paths relative to root), in git's order."""
    return [name for name in repo_files.files(root, 'src/asuna') if name not in NOT_IN_WORKER and (root / name).is_file()]


def stage_worker(destination: Path, root=ROOT) -> list:
    """Copy the worker's files (worker_sources, and RUNTIME_API.md into its resources) into `destination` (the
    package's python/asuna), replacing what was there. Returns the source -> packaged path mapping recorded in
    runtime-manifest.json."""
    destination = Path(destination)
    if destination.exists():
        shutil.rmtree(destination)
    mappings = []
    for name in worker_sources(root):
        relative = name.removeprefix('src/asuna/')
        (destination / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, destination / relative)
        mappings.append([name, 'python/asuna/' + relative])
    (destination / 'resources').mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / 'RUNTIME_API.md', destination / 'resources/RUNTIME_API.md')
    mappings.append(['RUNTIME_API.md', 'python/asuna/resources/RUNTIME_API.md'])
    return mappings


# Run by the interpreter under check (`python -c IMPORT_CHECK <tree>`, from the worker's data folder, as the worker
# starts): imports the worker's entry and every module of every package in <tree>/asuna, then prints where each asuna
# module came from. Exit 1 when one fails to import or resolves outside <tree> (an editable install, site-packages,
# the working folder).
IMPORT_CHECK = r'''
import importlib, os, sys, traceback
tree = os.path.realpath(sys.argv[1])
names = ['asuna.native_worker']
for folder, dirs, files in os.walk(os.path.join(tree, 'asuna')):
    dirs.sort()
    if '__init__.py' not in files:
        dirs[:] = []
        continue
    package = os.path.relpath(folder, tree).replace(os.sep, '.')
    names += [package] + [package + '.' + f[:-3] for f in sorted(files) if f.endswith('.py') and f != '__init__.py']
failed = []
for name in names:
    try:
        importlib.import_module(name)
    except BaseException:
        failed.append(name + ': does not import')
        traceback.print_exc()
loaded = sorted((name, getattr(module, '__file__', None)) for name, module in list(sys.modules.items())
                if name == 'asuna' or name.startswith('asuna.'))
for name, file in loaded:
    real = os.path.realpath(file) if file else ''
    try:
        inside = bool(real) and os.path.commonpath([tree, real]) == tree
    except ValueError:
        inside = False                            # another drive
    print(name, os.path.relpath(real, tree).replace(os.sep, '/') if inside else 'OUTSIDE ' + str(file))
    if not inside:
        failed.append(name + ': resolved outside the tree, from ' + str(file))
print('%d asuna modules imported with %s from %s; %d problem(s)' % (len(loaded), sys.executable, tree, len(failed)))
for line in failed:
    print('FAILED ' + line)
sys.exit(1 if failed else 0)
'''


def check_worker_imports(python, tree, data_root):
    """Run IMPORT_CHECK with `python` on the prepared tree (the folder holding asuna/) as the worker starts:
    from its data folder, with the tree as PYTHONPATH. Returns (exit code, output)."""
    Path(data_root).mkdir(parents=True, exist_ok=True)
    result = subprocess.run([str(python), '-c', IMPORT_CHECK, str(tree)], cwd=data_root, capture_output=True,
                            text=True, encoding='utf-8', errors='replace',
                            env={**os.environ, 'PYTHONPATH': str(tree), 'ASUNA_DATA_ROOT': str(data_root),
                                 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8', 'PYTHONDONTWRITEBYTECODE': '1'})
    return result.returncode, result.stdout + result.stderr


WORKER_DEPENDENCIES = ['httpx', 'pymongo', 'jsonschema', 'pydantic', 'PyYAML', 'tzdata', 'websockets', 'pillow', 'paramiko', 'av', 'zstandard',
                       'sherpa-onnx', 'sherpa-onnx-core', 'numpy', 'jieba']


def pinned_requirements(roots):
    """The worker's dependency closure at the exact versions this tested environment has (ADR-010 D2): the plugin
    builds its first-start environment from it. Platform markers are kept, so a dependency only some platforms need
    is installed only there; the file works with `uv pip install` and with pip."""
    from importlib import metadata
    from packaging.requirements import Requirement
    lines, seen, queue = {}, set(), [(name, None) for name in roots]
    while queue:
        name, marker = queue.pop(0)
        key = name.lower().replace('_', '-')
        if key in seen:
            continue
        seen.add(key)
        dist = metadata.distribution(name)
        lines[key] = dist.metadata['Name'] + '==' + dist.version + (' ; ' + marker if marker else '')
        for raw in dist.requires or ():
            requirement = Requirement(raw)
            if requirement.marker and 'extra' in str(requirement.marker):
                continue                          # an optional feature this worker does not ask for
            try:
                metadata.distribution(requirement.name)
            except metadata.PackageNotFoundError:
                continue                          # not needed on this platform; the installer resolves it there
            queue.append((requirement.name, str(requirement.marker) if requirement.marker else None))
    header = '# Generated by tools/pack_plugins.py from the tested worker environment. Do not edit.'
    return '\n'.join([header, *(lines[key] for key in sorted(lines))]) + '\n'


def bundle_python():
    """The worker's copy in the core package (stage_worker; no debug CLI, local state or secrets), its manifest,
    project file and lock, checked by importing it with this interpreter."""
    destination = ROOT / 'packages/cognition-core/python/asuna'
    from asuna.development import DEVELOPMENT_TOOLS
    mappings = stage_worker(destination)
    (ROOT / 'packages/cognition-core/runtime-manifest.json').write_text(
        json.dumps({'files': mappings, 'developmentTools': DEVELOPMENT_TOOLS}, indent=2), encoding='utf-8', newline='\n')
    (destination.parent / 'pyproject.toml').write_text('''[build-system]
requires = ["hatchling==1.30.1"]
build-backend = "hatchling.build"
[project]
name = "asuna-cognition-worker"
version = "%s"
requires-python = ">=3.12"
dependencies = ["httpx==0.28.1", "pymongo==4.16.0", "jsonschema==4.26.0", "pydantic==2.12.5", "PyYAML==6.0.3", "tzdata==2026.4"]
[tool.hatch.build.targets.wheel]
packages = ["asuna"]
''' % json.loads((ROOT / 'packages/cognition-core/package.json').read_text(encoding='utf-8'))['version'],
        encoding='utf-8')
    (destination.parent / 'requirements.lock').write_text(pinned_requirements(WORKER_DEPENDENCIES), encoding='utf-8', newline='\n')
    code, output = check_worker_imports(sys.executable, destination.parent, ROOT / '.runtime')
    if code != 0:
        sys.stderr.write(output)
        raise SystemExit('The packed worker does not import from its own copy (above); a module it needs is not '
                         'tracked under src/asuna (git add it) or fails to import')


def prune(artifacts):
    """Remove packed files that neither this manifest nor any profile's installed packages or activation still name."""
    named = {Path(item['path']).name for item in artifacts}
    adr008 = DESTINATION.parent
    for base in [adr008, *(adr008 / 'profiles').glob('*')]:
        profiles = base / 'home/profiles'
        for record in [base / 'activation.json', *profiles.glob('*/package.json'), *profiles.glob('*/pnpm-lock.yaml')]:
            if record.is_file():
                named.update(re.findall(r'[\w.+-]+\.tgz', record.read_text(encoding='utf-8')))
    for path in DESTINATION.glob('*.tgz'):
        if path.name not in named:
            path.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--persona', action='append', default=[], type=Path,
                        help='persona package directory to pack alongside the core (repeatable)')
    parser.add_argument('--channel', action='append', default=[], type=Path,
                        help='channel package directory (e.g. packages/channels/napcat-qq) to pack alongside the core (repeatable)')
    args = parser.parse_args()
    DESTINATION.mkdir(parents=True, exist_ok=True)
    # The DSH patches (tools/dsh-inline) are optional and built separately; pack only a current build.
    built = DESTINATION / 'native-inline-manifest.json'
    native = json.loads(built.read_text(encoding='utf-8')) if built.exists() else []
    pinned = json.loads((ROOT / 'tools/dsh-inline/source.json').read_text(encoding='utf-8'))['commit']
    for artifact in native:
        if artifact.get('sourceCommit') != pinned or hashlib.sha256(Path(artifact['path']).read_bytes()).hexdigest() != artifact['sha256']:
            raise ValueError('Rebuild the current native inline extension before packing plugins')
    bundle_python()
    artifacts = list(native)
    for directory in [ROOT / 'packages/cognition-core', *[p.resolve() for p in [*args.persona, *args.channel]]]:
        for cache in [c for c in directory.rglob('__pycache__') if 'node_modules' not in c.parts]:
            shutil.rmtree(cache)          # bytecode a local run left behind is never packed
        result = subprocess.run(['npm.cmd' if os.name == 'nt' else 'npm', 'pack', '--json', '--pack-destination', str(DESTINATION)],
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
            allowed = ('package/src/', 'package/persona/', 'package/seeds/', 'package/jobs/', 'package/skills/', 'package/python/', 'package/integration/', 'package/locale/', 'package/meta/')
            exact = {'package/package.json', 'package/LICENSE', 'package/cordis.patch.yml', 'package/README.md', 'package/runtime-manifest.json', 'package/resources-provenance.json', 'package/persona-model.json', 'package/icon.svg', 'package/icon.png'}
            for entry in archive.getmembers():
                if '/__pycache__/' in entry.name or entry.name.endswith('.pyc'):
                    raise ValueError('Generated bytecode in package: ' + entry.name)
                if not entry.isfile() or not (entry.name in exact or entry.name.startswith(allowed)):
                    raise ValueError('Unexpected packaged entry: ' + entry.name)
        artifacts.append({'name': package['name'], 'path': str(path), 'integrity': package['integrity'],
                          'sha256': digest,
                          'files': [row['path'] for row in package['files']]})
    (DESTINATION / 'manifest.json').write_text(json.dumps(artifacts, indent=2), encoding='utf-8')
    prune(artifacts)
    print(json.dumps([{k:v for k,v in item.items() if k != 'files'} for item in artifacts], indent=2))


if __name__ == '__main__':
    main()
