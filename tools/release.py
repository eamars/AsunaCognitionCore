"""Build and check a GitHub Release of the distributable plugins (ADR-010 D10).

The release carries the core and channel packages only: never a persona package (each owner brings their own) and
never the locally patched DSH UI packages (INSTALL.md explains the optional local build). Every tarball is checked
before anything leaves this machine:
- it is one of the release packages, at the version being tagged, with `"license": "GPL-3.0-only"` and LICENSE;
- the personal-data scan (tools/check_staged_secrets.py --personal) finds nothing in its files;
- no persona package's id or display name appears in it (the core is persona-agnostic).

Output: `.runtime/release/<tag>/` with the tarballs, SHA256SUMS and NOTES.md. Publishing is a separate, explicit
step done by the owner (or with their go-ahead): create the GitHub Release <tag> on this repository and attach the
files from that folder.

    python tools/release.py --channel packages/channels/napcat-qq [--tag v0.2.0]
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ROOT / '.runtime/adr008/packages'


def persona_names():
    names = set()
    for model in ROOT.glob('packages/personas/*/persona-model.json'):
        persona = json.loads(model.read_text(encoding='utf-8')).get('persona') or {}
        names |= {str(value) for key, value in persona.items() if key in ('id', 'display_name', 'name') and value}
    return {name for name in names if len(name) >= 2}


def check(path, version, names):
    problems = []
    with tempfile.TemporaryDirectory() as temporary:
        with tarfile.open(path) as archive:
            archive.extractall(temporary, filter='data')
        package = Path(temporary) / 'package'
        manifest = json.loads((package / 'package.json').read_text(encoding='utf-8'))
        if manifest.get('version') != version:
            problems.append('version %s is not %s' % (manifest.get('version'), version))
        if manifest.get('license') != 'GPL-3.0-only':
            problems.append('license is not GPL-3.0-only')
        if not (package / 'LICENSE').is_file():
            problems.append('LICENSE missing')
        files = [str(f) for f in package.rglob('*') if f.is_file()]
        # Vendored third-party code is outside the scan, as it is in the repository (check_staged_secrets.py).
        scanned = [f for f in files if not Path(f).relative_to(package).as_posix().startswith('integration/vendor/')]
        scan = subprocess.run([sys.executable, str(ROOT / 'tools/check_staged_secrets.py'), '--personal', '--paths', *scanned],
                              capture_output=True, text=True, encoding='utf-8', errors='replace')
        hits = re.search(r'personal-scan: (\d+) hit', scan.stdout)
        if not hits or int(hits.group(1)):
            problems.append('personal-data scan: ' + (hits.group(0) if hits else 'did not run'))
        for file in files:
            try:
                text = Path(file).read_text(encoding='utf-8')
            except (UnicodeDecodeError, OSError):
                continue
            for name in names:
                if name in text:
                    problems.append('persona name in ' + Path(file).relative_to(package).as_posix())
    return manifest['name'], problems


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--channel', action='append', default=[], type=Path, help='channel package to release (repeatable)')
    parser.add_argument('--tag', help='release tag; default v<core version>')
    args = parser.parse_args()
    version = json.loads((ROOT / 'packages/cognition-core/package.json').read_text(encoding='utf-8'))['version']
    tag = args.tag or 'v' + version
    if tag != 'v' + version:
        raise SystemExit('The tag must name the core version (v%s)' % version)
    packed = subprocess.run([sys.executable, str(ROOT / 'tools/pack_plugins.py'), *sum((['--channel', str(c)] for c in args.channel), [])],
                            capture_output=True, text=True, encoding='utf-8', errors='replace')
    if packed.returncode:
        raise SystemExit('Packing failed:\n' + packed.stderr[-2000:])
    manifest = json.loads((PACKAGES / 'manifest.json').read_text(encoding='utf-8'))
    wanted = {'@asuna/cognition-core', *(json.loads((c / 'package.json').read_text(encoding='utf-8'))['name'] for c in args.channel)}
    artifacts = [a for a in manifest if a['name'] in wanted]
    if {a['name'] for a in artifacts} != wanted:
        raise SystemExit('Missing packed artifacts: ' + ', '.join(sorted(wanted - {a['name'] for a in artifacts})))
    names, failed = persona_names(), False
    out = ROOT / '.runtime/release' / tag
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    sums = []
    for artifact in artifacts:
        name, problems = check(artifact['path'], version, names)
        for problem in problems:
            print('REFUSED %s: %s' % (name, problem))
        failed |= bool(problems)
        target = out / (name.removeprefix('@').replace('/', '-') + '-' + version + '.tgz')
        shutil.copyfile(artifact['path'], target)
        sums.append('%s  %s' % (hashlib.sha256(target.read_bytes()).hexdigest(), target.name))
    if failed:
        shutil.rmtree(out)
        raise SystemExit(1)
    (out / 'SHA256SUMS').write_text('\n'.join(sums) + '\n', encoding='utf-8')
    assets = '\n'.join('- `%s`' % line.split('  ')[1] for line in sums)
    (out / 'NOTES.md').write_text(f'''Asuna {tag} for DeepSeek Harness 0.2.0-rc.2.

Install with DSH's own installer, using the links of the files below; then configure Asuna on its settings card.
INSTALL.md in the repository is written for the agent or person doing the install.

{assets}

Not included: a persona package (bring your own) and the patched DSH UI packages for the inline view of the
action brain's work (optional; INSTALL.md shows the local build). Licence: GPL-3.0-only.
''', encoding='utf-8')
    print(json.dumps({'tag': tag, 'folder': str(out), 'assets': [line.split('  ')[1] for line in sums]}, indent=2))


if __name__ == '__main__':
    main()
