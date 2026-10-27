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
    assert found('member 123456789 joined')                  # personal-scan: ok (made up; 9 digits)
    assert found('author 112233445566778899 posted')         # personal-scan: ok (made up; 18 digits)
    assert found('blob 5e9365951b39 from 112233445566778899') # personal-scan: ok (beside a git id, still reported)
    assert found('token 1234567890123')                      # personal-scan: ok (all digits: not a git id)
    assert found('user id9365951b39 here')                   # personal-scan: ok (glued on the left: not a git id)
    assert found('user 9365951b39z here')                    # personal-scan: ok (glued on the right: not a git id)


def test_only_the_exact_marker_exempts_a_line_and_a_number_without_it_is_reported():
    """The marker silences a line, so it is a way out for a real number too: only the exact marker exempts, and a line
    without it is reported (Xiaoman's review of the made-up numbers' markers). The number is built here, so this file
    holds none."""
    number = '1' + '2' * 8
    scan = lambda line: [category for _, category in check_staged_secrets.scan_lines(line, 'tests/x.py', set(), [])]
    assert scan('member %s joined' % number) == ['account_id']
    assert scan('member %s joined  # personal-scan: ok (made up)' % number) == []
    for wrong in ('personal-scan:ok', 'personal_scan: ok', 'personal-scan: okay', 'personal-scan: OK'):
        assert scan('member %s joined  # %s' % (number, wrong)) == ['account_id'], wrong


def test_strict_exits_1_on_a_counted_hit_and_the_default_stays_report_only(tmp_path):
    """`--strict` is the form a push gate uses: exit 1 when anything counted was found, 0 when nothing was; without it
    the scan only reports (exit 0). A file outside the repository is checked by its name."""
    flagged = tmp_path / ('n' + '1' + '2' * 8 + '.txt')
    clean = tmp_path / 'clean.txt'
    flagged.write_text('x\n', encoding='utf-8')
    clean.write_text('x\n', encoding='utf-8')
    run = lambda *args: subprocess.run([sys.executable, str(ROOT / 'tools/check_staged_secrets.py'), '--personal', *args],
                                       cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=60)
    assert run('--strict', '--paths', str(flagged)).returncode == 1
    assert run('--paths', str(flagged)).returncode == 0
    assert run('--strict', '--paths', str(clean)).returncode == 0


def test_strict_counts_only_counted_hits_never_report_only_ones(monkeypatch, capsys):
    """`--strict` exits 1 on a counted hit only: a hit printed as report-only (docs/development_plans/) leaves it at 0,
    so the gate does not stop a push for what the scan itself does not count (Xiaoman's review of --strict)."""
    number = ('1' + '2' * 8).encode()
    def sources(key):
        return lambda args: iter([(key, key, b'member ' + number + b' joined\n')])
    monkeypatch.setattr(check_staged_secrets, 'personal_sources', sources('docs/development_plans/ADR-900-x/README.md'))
    assert check_staged_secrets.personal_scan(['--personal', '--strict', '--all']) == 0
    assert 'report-only:docs/development_plans/ADR-900-x/README.md:1:account_id' in capsys.readouterr().out
    monkeypatch.setattr(check_staged_secrets, 'personal_sources', sources('src/asuna/x.py'))
    assert check_staged_secrets.personal_scan(['--personal', '--strict', '--all']) == 1
