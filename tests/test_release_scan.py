"""What a release ships passes the release's own checks every day, not only on release night.

tools/release.py refuses a tarball with a personal-data hit or a persona's name in it; these tests run the same
checks over the tracked files that the released packages (the core and the NapCat channel) are packed from.
"""
import json
import re
import subprocess
import sys

from asuna.config import ROOT
from conftest import needs_git

sys.path.insert(0, str(ROOT / 'tools'))
import release  # noqa: E402

RELEASED = ['packages/cognition-core', 'packages/channels/napcat-qq']


def shipped():
    files = []
    for package in RELEASED:
        listed = json.loads((ROOT / package / 'package.json').read_text(encoding='utf-8'))['files']
        tracked = subprocess.run(['git', 'ls-files', '--', *(package + '/' + entry for entry in listed)], cwd=ROOT,
                                 capture_output=True, text=True, check=True).stdout.split()
        files += [path for path in tracked if '/integration/vendor/' not in path]
    # The core's python/ folder is packed from src/asuna; check the source it is copied from.
    files += subprocess.run(['git', 'ls-files', '--', 'src/asuna'], cwd=ROOT, capture_output=True, text=True,
                            check=True).stdout.split()
    return sorted(set(files))


@needs_git
def test_the_released_files_have_no_personal_data():
    scan = subprocess.run([sys.executable, str(ROOT / 'tools/check_staged_secrets.py'), '--personal', '--paths',
                           *shipped()], cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
    hits = [line for line in scan.stdout.splitlines() if not line.startswith('personal-scan:')]
    assert re.search(r'personal-scan: 0 hit', scan.stdout), 'path:line:category %s' % hits


@needs_git
def test_the_released_files_name_no_persona():
    names = release.persona_names()
    found = []
    for path in shipped():
        try:
            text = (ROOT / path).read_text(encoding='utf-8')
        except (UnicodeDecodeError, OSError):
            continue
        found += ['%s:%d' % (path, number) for number, line in enumerate(text.splitlines(), 1)
                  if any(name in line for name in names)]
    assert not found, found
