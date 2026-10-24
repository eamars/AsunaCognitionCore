"""The publication scan (tools/publication_scan.py) runs the checks that guard main on a candidate: the private list and
private addresses in every file, the release's personal-data and persona-name checks in what the release ships, a
file's name too; it
accepts what main accepts (the allow list, the marker, the fixtures' placeholders, lock files, unshipped paths) and
never prints a word or a number."""
import json
import subprocess
import sys

import pytest

from asuna.config import ROOT

sys.path.insert(0, str(ROOT / 'tools'))
import publication_scan  # noqa: E402
import release  # noqa: E402


@pytest.fixture
def lists(tmp_path, monkeypatch):
    words = tmp_path / 'personal-words.txt'
    words.write_text('# test list\ngroup|示例交流群|a placeholder group\n', encoding='utf-8')
    monkeypatch.setenv('ASUNA_PRIVATE_WORDS', str(words))
    monkeypatch.setenv('ASUNA_PERSONAL_DENYLIST', str(tmp_path / 'personal-denylist.txt'))
    return tmp_path


def candidate(tmp_path, files):
    root = tmp_path / 'candidate'
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding='utf-8')
    return root


def categories(findings):
    return sorted((item['path'], item['line'], item['category']) for item in findings)


def test_a_channel_candidate_is_checked_as_the_release_checks_it(lists):
    persona = sorted(release.persona_names())[0]
    allowed = next(line.strip() for line in (ROOT / 'tools/personal_scan_allow.txt').read_text(encoding='utf-8').splitlines()
                   if line.strip() and not line.startswith('#'))
    root = candidate(lists, {
        'package.json': json.dumps({'files': ['integration']}),
        'integration/a.py': '\n'.join([
            'ok = 1',                                   # 1
            'seen in 示例交流群',                         # 2 listed
            'qq = 1234567890',                          # 3 an account-shaped number
            'speaker = %r' % persona,                   # 4 a persona's name in a shipped file
            'limit = %s' % allowed,                     # 5 an allow-listed constant
            'group = 900000001',                        # 6 a fixtures' placeholder
            'qq = 1234567890  # personal-scan: ok',     # 7 the marker
        ]) + '\n',
        # not shipped: the private list and private addresses only (the address is put together here, so this file
        # holds none)
        'test/b.py': 'speaker = %r\nin 示例交流群\nhost = "%s"\n' % (persona, '192.168.' + '0.20'),
        'uv.lock': 'hash = 12345678901234567890\n',            # a lock file: lines not scanned
    })
    found = publication_scan.scan(str(root), 'packages/channels/napcat-qq',
                                  ['integration/a.py', 'test/b.py', 'uv.lock'])
    assert categories(found) == [('integration/a.py', 2, 'listed:group'), ('integration/a.py', 3, 'account_id'),
                                 ('integration/a.py', 4, 'persona_name'), ('test/b.py', 2, 'listed:group'),
                                 ('test/b.py', 3, 'private_address')], found
    assert [item.get('entry') for item in found if item['category'].startswith('listed')] == [2, 2]


def test_a_persona_package_may_name_its_persona_and_a_name_with_a_hit_is_not_printed(lists):
    persona = sorted(release.persona_names())[0]
    root = candidate(lists, {'skills/x/SKILL.md': '%s writes this\n' % persona, 'notes-示例交流群.md': 'plain\n'})
    found = publication_scan.scan(str(root), 'packages/personas/demo', ['skills/x/SKILL.md', 'notes-示例交流群.md'])
    assert categories(found) == [(None, 0, 'listed:group')], found


def test_the_command_prints_findings_and_never_the_word_or_the_number(lists):
    root = candidate(lists, {'src/asuna/x.py': 'qq = 1234567890  # 示例交流群\n'})
    request = lists / 'request.json'
    request.write_text(json.dumps({'root': str(root), 'prefix': '', 'paths': ['src/asuna/x.py']}), encoding='utf-8')
    done = subprocess.run([sys.executable, str(ROOT / 'tools/publication_scan.py'), str(request)], capture_output=True,
                          text=True, encoding='utf-8', timeout=120)
    assert done.returncode == 0, done.stderr
    assert categories(json.loads(done.stdout)['findings']) == [('src/asuna/x.py', 1, 'account_id'),
                                                              ('src/asuna/x.py', 1, 'listed:group')]
    assert '1234567890' not in done.stdout and '示例交流群' not in done.stdout


def test_the_reason_is_checked_too_and_the_answer_is_capped_and_says_when_the_list_is_missing(lists, monkeypatch):
    root = candidate(lists, {'src/asuna/x.py': '\n'.join('qq = %d' % (1234567000 + n) for n in range(80)) + '\n'})
    request = lists / 'request.json'
    request.write_text(json.dumps({'root': str(root), 'prefix': '', 'paths': ['src/asuna/x.py'],
                                   'reason': '只改 x\n在示例交流群 1234567890'}), encoding='utf-8')

    def answer():
        done = subprocess.run([sys.executable, str(ROOT / 'tools/publication_scan.py'), str(request)],
                              capture_output=True, text=True, encoding='utf-8', timeout=120)
        assert done.returncode == 0, done.stderr
        assert '1234567890' not in done.stdout and '示例交流群' not in done.stdout
        return json.loads(done.stdout)
    told = answer()
    assert told['total'] == 80 and len(told['findings']) == publication_scan.MAX_FINDINGS and told['list'] == 'checked'
    assert sorted((item['line'], item['category']) for item in told['reason']) == [(2, 'account_id'), (2, 'listed:group')]
    monkeypatch.setenv('ASUNA_PRIVATE_WORDS', str(lists / 'no-such-list.txt'))
    told = answer()
    assert told['list'] == 'missing' and told['total'] == 80, 'the release checks still ran; the list check did not'


def test_a_changed_file_it_cannot_read_is_unread_never_clean_and_the_answer_names_the_scan(lists):
    root = candidate(lists, {'src/asuna/x.py': 'x = 1\n'})
    request = lists / 'request.json'
    request.write_text(json.dumps({'root': str(root), 'prefix': '', 'paths': ['src/asuna/x.py', 'src/asuna/gone.py']}),
                       encoding='utf-8')
    done = subprocess.run([sys.executable, str(ROOT / 'tools/publication_scan.py'), str(request)], capture_output=True,
                          text=True, encoding='utf-8', timeout=120)
    told = json.loads(done.stdout)
    assert told['unread'] == ['src/asuna/gone.py'] and told['findings'] == [], told
    assert told['scan'] == publication_scan.scan_version() and len(told['scan']) == 12


def test_what_main_holds_passes_its_own_scan():
    """Nothing main accepts is refused: the shipped files of the checkout, scanned as one candidate, have no hit
    beyond what tests/test_release_scan.py and test_personal_words.py would already fail on."""
    from test_release_scan import shipped
    paths = [path for path in shipped() if path.startswith('packages/channels/napcat-qq/')]
    found = publication_scan.scan(str(ROOT / 'packages/channels/napcat-qq'), 'packages/channels/napcat-qq',
                                  [path[len('packages/channels/napcat-qq/'):] for path in paths])
    persona_or_data = [item for item in found if not item['category'].startswith('listed')]
    import test_release_scan                                  # same verdict as the release test on these files
    assert bool(persona_or_data) == bool(_release_hits(test_release_scan, paths)), persona_or_data[:5]


def _release_hits(module, paths):
    done = subprocess.run([sys.executable, str(ROOT / 'tools/check_staged_secrets.py'), '--personal', '--paths', *paths],
                          cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=300)
    names = release.persona_names()
    lines = [line for line in done.stdout.splitlines() if ':' in line and not line.startswith(('personal-scan', 'report-only'))]
    named = [path for path in paths if any(name in (ROOT / path).read_text(encoding='utf-8', errors='replace')
                                           for name in names)]
    return lines + named
