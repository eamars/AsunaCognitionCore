"""Run the launcher's start preparation (rung 0) for one commit in a scratch folder and check what it installed.

A git worktree of the commit gets a .venv and node_modules linked in (this checkout's, else the main checkout's, found
through git; the script reruns itself with that .venv's Python), a synthetic config (a database
name no server is asked for, an unresolvable server, no model endpoint) and a fresh profile's launch record. Then
`asuna-launch.mjs --prepare 0` packs and installs it as a start would. The check passes (exit 0) only when the
preparation succeeds and installed the checkout, every file the core package ships from src/asuna is installed and
byte-identical to the commit's blob (none missing, none extra), every file of the packed core matches the installed one
(pyproject.toml and requirements.lock included), and the installed worker imports every package and module from its
own copy with the environment its requirements.lock builds and with the interpreter the profile's worker is set to.
The scratch folder and the worktree are removed at the end (--keep leaves them for reading).

    .venv/Scripts/python.exe tools/check_prepared_start.py --commit HEAD
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile

import pack_plugins

ROOT = Path(__file__).resolve().parents[1]
PROFILE = 'prepare-check'
PREPARE_SECONDS = 1200


def git(*args, cwd=ROOT):
    return subprocess.run(['git', *args], cwd=cwd, capture_output=True, check=True, stdin=subprocess.DEVNULL).stdout


def blob_id(data):
    """The id git gives these bytes as a blob (`git hash-object --no-filters`)."""
    return hashlib.sha1(b'blob %d\0' % len(data) + data).hexdigest()


def link(target, at):
    if os.name == 'nt':
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(at), str(target)], check=True, capture_output=True)
    else:
        os.symlink(target, at, target_is_directory=True)


def unlink(at):
    """Remove a link made by link() without touching what it points at."""
    if os.path.islink(at):
        os.unlink(at)
    elif getattr(os.path, 'isjunction', lambda _: False)(at):
        os.rmdir(at)
    if os.path.lexists(at):
        raise RuntimeError('link not removed: %s' % at)


def remove(path):
    def writable(function, name, _error):
        os.chmod(name, stat.S_IWRITE)
        function(name)
    if Path(path).exists():
        shutil.rmtree(path, onexc=writable)


def prepare(tree, scratch, persona, channels):
    """Rung 0 as the launcher runs it, for a fresh profile of the tree. Returns (profile base, ok, output)."""
    runtime = tree / '.runtime'
    config = scratch / 'prepare.local.json'
    config.write_text(json.dumps({
        'database': 'asuna_v2_test_prepare', 'allowed_databases': ['asuna_v2_test_prepare'],
        'mongo_uri': 'mongodb://prepare-check.invalid:27017/?directConnection=true',
        'dsh_home': (runtime / 'prepare/asuna-dsh').as_posix(),
        'embedding': {'base_url': 'http://127.0.0.1:9/v1', 'model': '<embedding-model>', 'query_prefix': '',
                      'document_prefix': '', 'api_key': ''},
        'self_development': {'enabled': False},
        'chat': {'scene_id': 'prepare-local-dm', 'person_id': 'prepare-owner', 'persona': 'demo',
                 'workspace': (runtime / 'work/prepare').as_posix(), 'read_only_paths': []}}, indent=2), encoding='utf-8')
    base = runtime / 'adr008/profiles' / PROFILE
    base.mkdir(parents=True)
    # A profile never installed: the launcher installs every package (changedPackages with nothing recorded).
    (base / 'launch.json').write_text(json.dumps({'config': str(config), 'profile': PROFILE,
        'setup': {'persona_package': persona, 'channel_packages': channels}, 'installed': {}}, indent=2), encoding='utf-8')
    env = {key: value for key, value in os.environ.items()
           if key.upper() not in ('PYTHONPATH', 'ASUNA_DATA_ROOT', 'DSH_HOME', 'ASUNA_PROFILE', 'ASUNA_CONFIG')}
    # The tree's own asuna for its tools, whatever the shared .venv's editable install points at: a commit whose tools
    # do not put their own source first would otherwise install into the other checkout.
    env.update(PYTHONPATH=str(tree / 'src'), PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    result = subprocess.run(['node', 'tools/asuna-launch.mjs', 'ui', '--profile', PROFILE, '--config', str(config),
                             '--prepare', '0'], cwd=tree, env=env, capture_output=True, text=True, encoding='utf-8',
                            errors='replace', timeout=PREPARE_SECONDS, stdin=subprocess.DEVNULL)
    output = result.stdout + result.stderr
    (scratch / 'prepare.log').write_text(output, encoding='utf-8')
    installed = 'Asuna: installing the checkout' in output
    notes = any(line.startswith('ASUNA_PREPARE_NOTES ') for line in result.stdout.splitlines())
    return base, result.returncode == 0 and installed and notes, output


def byte_check(sha, tree, base):
    """Problems of the installed core against the commit and the packed artifact, and the counts checked."""
    installed = base / 'home/profiles' / PROFILE / 'node_modules/@asuna/cognition-core'
    listing = git('ls-tree', '-r', '-z', sha, '--', 'src/asuna', 'RUNTIME_API.md',
                  'packages/cognition-core/runtime-manifest.json')
    blobs = {}
    for row in filter(None, listing.split(b'\0')):
        meta, name = row.split(b'\t', 1)
        blobs[name.decode('utf-8')] = meta.split()[2].decode()
    expected = {'python/asuna/' + name.removeprefix('src/asuna/'): blobs[name]
                for name in blobs if name.startswith('src/asuna/') and name not in pack_plugins.NOT_IN_WORKER}
    expected['python/asuna/resources/RUNTIME_API.md'] = blobs['RUNTIME_API.md']
    expected['runtime-manifest.json'] = blobs['packages/cognition-core/runtime-manifest.json']
    problems = []
    for name, blob in sorted(expected.items()):
        path = installed / name
        if not path.is_file():
            problems.append('missing: ' + name)
        elif blob_id(path.read_bytes()) != blob:
            problems.append('differs from the commit: ' + name)
    extra = sorted(path.relative_to(installed).as_posix() for path in (installed / 'python/asuna').rglob('*')
                   if path.is_file() and 'python/' + path.relative_to(installed / 'python').as_posix() not in expected)
    problems += ['not in the commit: ' + name for name in extra]
    packed = next(item for item in json.loads((tree / '.runtime/adr008/packages/manifest.json').read_text(encoding='utf-8'))
                  if item['name'] == '@asuna/cognition-core')
    entries = 0
    in_package = set()
    with tarfile.open(packed['path'], 'r:gz') as archive:
        for entry in archive.getmembers():
            if not entry.isfile():
                continue
            entries += 1
            name = entry.name.removeprefix('package/')
            in_package.add(name)
            path = installed / name
            if not path.is_file() or path.read_bytes() != archive.extractfile(entry).read():
                problems.append('differs from the packed core: ' + name)
    for path in installed.rglob('*'):
        relative = path.relative_to(installed).as_posix()
        if path.is_file() and not relative.startswith('node_modules/') and relative not in in_package:
            problems.append('installed but not packed: ' + relative)
    for name in ('python/pyproject.toml', 'python/requirements.lock'):
        if name not in in_package:
            problems.append('not packed: ' + name)
    return installed, problems, len(expected), entries


def lock_environment(installed, scratch):
    """The worker's environment as the plugin builds it on first start (python-env.js): uv when on PATH, else venv
    and pip. Returns its python."""
    env = scratch / 'python-env'
    python = env / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    lock = installed / 'python/requirements.lock'
    if shutil.which('uv'):
        steps = [['uv', 'venv', '--quiet', '--python', '3.12', str(env)],
                 ['uv', 'pip', 'install', '--quiet', '--python', str(python), '-r', str(lock)]]
    else:
        base = getattr(sys, '_base_executable', sys.executable)
        steps = [[base, '-m', 'venv', str(env)], [str(python), '-m', 'pip', 'install', '--no-input', '-q', '-r', str(lock)]]
    for step in steps:
        result = subprocess.run(step, cwd=scratch, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                                env={**os.environ, 'PYTHONUTF8': '1', 'PIP_DISABLE_PIP_VERSION_CHECK': '1'})
        if result.returncode != 0:
            raise RuntimeError('building the lock environment failed: %s: %s' % (' '.join(step[:3]),
                                                                                (result.stdout + result.stderr)[-600:]))
    return python


def configured_python(base):
    """The interpreter the profile's worker is set to (the core's `python` setting), or None."""
    import yaml
    patch = yaml.safe_load((base / 'home/profiles' / PROFILE / 'cordis.patch.yml').read_text(encoding='utf-8')) or []
    row = next((row for row in patch if row.get('id') == 'asuna-cognition-core'), {})
    return row.get('config', {}).get('python')


def lender():
    """The checkout whose .venv and node_modules the prepared tree uses: this one when it has both, else the main
    checkout of the repository (a fresh worktree has neither). None when neither has them."""
    common = Path(git('rev-parse', '--git-common-dir').decode().strip())
    for root in (ROOT, (ROOT / common).resolve().parent):
        if (root / '.venv').exists() and (root / 'node_modules').exists():
            return root
    return None


def venv_python(root):
    return root / ('.venv/Scripts/python.exe' if os.name == 'nt' else '.venv/bin/python')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--commit', default='HEAD', help='the commit to prepare (default HEAD)')
    parser.add_argument('--persona', default='tests/fixtures/personas/demo', help='persona package of the profile')
    parser.add_argument('--channel', action='append', default=[], help='channel package of the profile (repeatable)')
    parser.add_argument('--scratch', type=Path, help='an empty folder to work in (default: a new temporary one)')
    parser.add_argument('--keep', action='store_true', help='leave the scratch folder and its worktree for reading')
    args = parser.parse_args()
    sha = git('rev-parse', '--verify', args.commit + '^{commit}').decode().strip()
    lent = lender()
    if lent is None:
        print('FAIL: neither this checkout nor the main checkout has both .venv (uv sync) and node_modules (npm install)')
        return 1
    if Path(sys.prefix).resolve() != (lent / '.venv').resolve():
        # The checks need the checkout's dependencies (PyYAML, packaging): run again with its environment.
        return subprocess.run([str(venv_python(lent)), str(Path(__file__).resolve()), *sys.argv[1:]],
                              env={**os.environ, 'PYTHONUTF8': '1'}).returncode
    print('lending the prepared tree .venv and node_modules of %s' % lent)
    if args.scratch:
        args.scratch.mkdir(parents=True, exist_ok=True)
        if any(args.scratch.iterdir()):
            print('FAIL: the scratch folder is not empty: %s' % args.scratch)
            return 1
    scratch = (args.scratch or Path(tempfile.mkdtemp(prefix='asuna-prepare-'))).resolve()
    tree = scratch / 'tree'
    links = [tree / '.venv', tree / 'node_modules']
    try:
        git('worktree', 'add', '--detach', '--quiet', str(tree), sha)
        for at in links:
            link((lent / at.name).resolve(), at)
        print('prepared tree: %s at %s' % (tree, sha[:12]))
        base, prepared, output = prepare(tree, scratch, args.persona, args.channel)
        if not prepared:
            print(output[-4000:])
            print('FAIL: the rung-0 preparation did not install the checkout (whole output: %s)' % (scratch / 'prepare.log'))
            return 1
        print('preparation: installed the checkout')
        installed, problems, files, entries = byte_check(sha, tree, base)
        print('byte check: %d files the core ships from the commit, %d entries of the packed core; %d problem(s)'
              % (files, entries, len(problems)))
        for line in problems:
            print('  ' + line)
        failed = bool(problems)
        interpreters = [('lock environment', lock_environment(installed, scratch)),
                        ("profile's worker interpreter", configured_python(base))]
        for label, python in interpreters:
            if not python:
                print('FAIL: no %s' % label)
                failed = True
                continue
            code, listing = pack_plugins.check_worker_imports(python, installed / 'python', base)
            print('import check, %s:' % label)
            print(listing.rstrip())
            failed |= code != 0
        ok = not failed
        print(('PASS' if ok else 'FAIL') + ': %s prepared in a scratch folder' % sha[:12])
        return 0 if ok else 1
    finally:
        if args.keep:
            print('kept: %s (remove with: git worktree remove --force %s, after removing its links %s)'
                  % (scratch, tree, ', '.join(str(at) for at in links)))
        else:
            try:
                for at in links:
                    if os.path.lexists(at):
                        unlink(at)
                remove(tree)
                git('worktree', 'prune')
                remove(scratch)
            except Exception as error:      # the verdict stands; what is left is said
                print('FAIL: the scratch folder was not removed (%s): %s' % (error, scratch))
                sys.exit(1)


if __name__ == '__main__':
    sys.exit(main())
