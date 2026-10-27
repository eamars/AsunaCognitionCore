"""What a release ships passes the release's own checks every day, not only on release night.

tools/release.py refuses a tarball with a personal-data hit or a persona's name in it; these tests run the same
checks over the tracked files that the released packages (the core and the NapCat channel) are packed from. A private
address is checked in every committed file, shipped or not.
"""
import json
import re
import subprocess
import sys

from asuna.config import ROOT

sys.path.insert(0, str(ROOT / 'tools'))
import check_staged_secrets  # noqa: E402
import release  # noqa: E402
from asuna import repo_files

RELEASED = release.RELEASED


def shipped():
    files = []
    for package in RELEASED:
        listed = json.loads((ROOT / package / 'package.json').read_text(encoding='utf-8'))['files']
        tracked = repo_files.files(ROOT, *(package + '/' + entry for entry in listed))
        files += [path for path in tracked if '/integration/vendor/' not in path]
    # The core's python/ folder is packed from src/asuna; check the source it is copied from.
    files += repo_files.files(ROOT, 'src/asuna')
    return sorted(set(files))


def test_the_released_files_have_no_personal_data():
    scan = subprocess.run([sys.executable, str(ROOT / 'tools/check_staged_secrets.py'), '--personal', '--paths',
                           *shipped()], cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
    hits = [line for line in scan.stdout.splitlines() if not line.startswith('personal-scan:')]
    assert re.search(r'personal-scan: 0 hit', scan.stdout), 'path:line:category %s' % hits


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


def committed_lines(path):
    """The lines of a committed file as the release scan reads them: none for a lock file or a binary one."""
    if path.rsplit('/', 1)[-1] in check_staged_secrets.LOCKFILES:
        return []
    try:
        data = (ROOT / path).read_bytes()
    except OSError:
        return []
    return [] if b'\0' in data else data.decode('utf-8', 'replace').split('\n')


def test_no_committed_file_holds_a_private_address():
    allow = set(check_staged_secrets.load_list('ASUNA_PERSONAL_ALLOWLIST', ROOT / 'tools' / 'personal_scan_allow.txt'))
    found = []
    for path in repo_files.files(ROOT):
        if check_staged_secrets.SKIP.search(path):
            continue
        if check_staged_secrets.private_address(path, allow):
            found.append(path + ':0')
        found += ['%s:%d' % (path, number) for number, line in enumerate(committed_lines(path), 1)
                  if check_staged_secrets.private_address(line, allow)]
    assert not found, 'path:line (0 is the name) %s' % found


def test_a_git_id_is_not_an_account_but_a_bare_number_on_any_platform_still_is():
    """A git commit or blob id cited in a doc (7-40 hex characters with a letter a-f) is not an account id, however many
    digits it holds; a bare number of 7 digits or more still is, whatever platform it would belong to: the rule assumes
    no platform's id shape. Positive controls: a number beside a git id on the same line, and an all-digit token."""
    found = lambda line: check_staged_secrets.account_id(line, set())
    assert not found('signed against commit `b1f6f2ce` (README blob `5e9365951b39`)')
    assert not found('git diff 626121d66364d5672f1a9d5571442ca24ca33958..HEAD')
    assert found('member 123456789 joined')                              # 9 digits, QQ-length
    assert found('author 112233445566778899 posted')                     # 18 digits, snowflake-length
    assert found('blob 5e9365951b39 from 112233445566778899')             # beside a git id, still reported
    assert found('token 1234567890123')                                 # all digits: no letter, not a git id
    assert found('user id9365951b39 here')                               # glued to a letter on the left: not a git id
    assert found('user 9365951b39z here')                                # glued to a letter on the right: not a git id
