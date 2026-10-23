"""Each version is written in one place and every other mention agrees with it.

DSH's version is the root package.json pin of `@deepseek-ai/dsh`; Asuna's is the core package's version. Manifests
must spell both out (npm needs literal pins), and the current references name them for the reader, so these tests
fail on the one mention an upgrade or a release forgot.
"""
import json
import re

from asuna.config import ROOT
from asuna import repo_files

DSH = json.loads((ROOT / 'package.json').read_text(encoding='utf-8'))['dependencies']['@deepseek-ai/dsh']
ASUNA = json.loads((ROOT / 'packages/cognition-core/package.json').read_text(encoding='utf-8'))['version']
RANGE = ASUNA.split('.')[0] + '.x'
# Tracked manifests only: a test's leftover copy of a package is not one of ours.
MANIFESTS = [ROOT / path for path in repo_files.files(
    ROOT, 'package.json', 'packages/**/package.json', 'tests/fixtures/personas/*/package.json')]
REFERENCES = [*sorted(ROOT.glob('*.md')), ROOT / 'docs/DEVELOPMENT.md', *sorted(ROOT.glob('packages/*/*/README.md')),
              *sorted(ROOT.glob('packages/*/README.md')), *sorted(ROOT.glob('tools/**/README.md'))]


def dependencies(manifest):
    for field in ('dependencies', 'devDependencies', 'peerDependencies', 'optionalDependencies'):
        yield from (manifest.get(field) or {}).items()


def test_every_dsh_pin_is_the_root_pin():
    wrong = ['%s: %s %s' % (path.relative_to(ROOT).as_posix(), name, pin)
             for path in MANIFESTS for name, pin in dependencies(json.loads(path.read_text(encoding='utf-8')))
             if name.startswith('@deepseek-ai/dsh') and pin != DSH]
    assert not wrong, 'pin DSH %s: %s' % (DSH, wrong)


def test_the_inline_build_follows_the_pinned_dsh():
    """The fork's branch for this DSH: `asuna/<version>`, or one built on it (`asuna/<version>-<what it adds>`)."""
    source = json.loads((ROOT / 'tools/dsh-inline/source.json').read_text(encoding='utf-8'))
    assert source['dsh'] == DSH
    assert source['branch'] == 'asuna/' + DSH or source['branch'].startswith('asuna/' + DSH + '-'), source['branch']


def test_the_core_and_its_channels_share_one_version_and_every_package_accepts_it():
    wrong = []
    for path in MANIFESTS:
        manifest = json.loads(path.read_text(encoding='utf-8'))
        name = path.relative_to(ROOT).as_posix()
        if name.startswith(('packages/channels/', 'packages/cognition-core/')) or name == 'package.json':
            if manifest['version'] != ASUNA:
                wrong.append('%s version %s' % (name, manifest['version']))
        accepted = dict(dependencies(manifest)).get('@asuna/cognition-core')
        if accepted is not None and accepted != RANGE:
            wrong.append('%s accepts the core %s' % (name, accepted))
    assert not wrong, 'Asuna %s (%s): %s' % (ASUNA, RANGE, wrong)


def test_the_worker_package_is_asunas_version():
    project = re.search(r'^version = "([^"]+)"', (ROOT / 'pyproject.toml').read_text(encoding='utf-8'), re.M).group(1)
    assert project == ASUNA, 'pyproject.toml version %s, Asuna %s' % (project, ASUNA)


def test_the_references_name_the_current_versions():
    wrong = []
    for path in REFERENCES:
        text = path.read_text(encoding='utf-8')
        name = path.relative_to(ROOT).as_posix()
        wrong += ['%s: DSH %s' % (name, found) for found in
                  re.findall(r'(?:DSH|DeepSeek Harness)\s+\**(\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?)', text) if found != DSH]
        wrong += ['%s: release badge v%s' % (name, found) for found in re.findall(r'Release-v([0-9.]+)', text)
                  if found != ASUNA]
        wrong += ['%s: core %s' % (name, found) for found in
                  re.findall(r'`@asuna/cognition-core`\s*(?:的\s*)?`?(\d+\.(?:\d+\.)?(?:x|\d+))', text) if found != RANGE]
    assert not wrong, 'DSH %s, Asuna %s: %s' % (DSH, ASUNA, wrong)
