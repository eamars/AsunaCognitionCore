"""The checks that guard main, run on a candidate before it is published (`PublicationFloor.publish`,
packages/cognition-core/src/floor.js), so a publication is refused where it can still be fixed:

- every file: no word of the deployment's private list (as tests/test_personal_words.py, `asuna.private_words`) and
  no private address (check_staged_secrets.py `private_address`, as tests/test_release_scan.py);
- a file the release ships (tools/release.py `RELEASED`: each package's `files`, and src/asuna): no personal data
  (tools/check_staged_secrets.py --personal: account numbers, private addresses, the denylist, time zones, a persona's
  name in the core) and no persona's name (tools/release.py `persona_names`), as tests/test_release_scan.py.

A file's name is checked as well. The same checks as on main, the same way: nothing main accepts is refused, and a hit
can only be in what the candidate brings.

    python tools/publication_scan.py <request.json>

request: {"root": the candidate's folder, "prefix": where that folder sits in the repository ('' for the core
repository, 'packages/channels/napcat-qq' for that package), "paths": changed paths relative to root, "reason": the
publication's reason}. Prints {"findings": [{"path", "line", "category", "entry"?}] (the first MAX_FINDINGS), "total",
"reason": [{"line", "category", "entry"?}], "list": "checked" or "missing" (no private list: unchecked, not clean),
"unread": changed paths it could not read (unchecked: the publication is refused), "scan": the first 12 hex digits
of the sha256 of this file and check_staged_secrets.py, the checks that ran}:
`line` 0 for the file's name, `path` null when the name itself carries a hit, `entry` the private list's line for a
listed word; never a word or a number.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tools'))

import release  # noqa: E402
from asuna import private_words  # noqa: E402

TEXT_LIMIT = 2 * 1024 * 1024             # tests/test_personal_words.py reads files up to this size


def _secrets():
    spec = importlib.util.spec_from_file_location('check_staged_secrets', ROOT / 'tools' / 'check_staged_secrets.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _files_of(package, root, prefix):
    """A released package's `files` entries: the candidate's own package.json when the candidate is that package."""
    manifest = (Path(root) / 'package.json') if prefix == package else ROOT / package / 'package.json'
    try:
        return json.loads(manifest.read_text(encoding='utf-8')).get('files') or []
    except (OSError, ValueError):
        return []


def shipped(key, root, prefix):
    """Whether the release packs this repository path (tests/test_release_scan.py `shipped`)."""
    if key.startswith('src/asuna/'):
        return True
    for package in release.RELEASED:
        if key.startswith(package + '/'):
            rest = key[len(package) + 1:]
            if '/integration/vendor/' in '/' + rest:
                return False
            return any(rest == entry.rstrip('/') or rest.startswith(entry.rstrip('/') + '/')
                       for entry in _files_of(package, root, prefix))
    return False


MAX_FINDINGS = 50                        # printed; `total` counts them all


def _checks():
    secrets = _secrets()
    allow = set(secrets.load_list('ASUNA_PERSONAL_ALLOWLIST', ROOT / 'tools' / 'personal_scan_allow.txt'))
    entries = private_words.load()
    return secrets, allow, secrets.denylist(), entries, release.persona_names()


def scan_version():
    """Which checks ran: this file and the release's personal-data checks it loads, as one short hash."""
    digest = hashlib.sha256()
    for name in ('publication_scan.py', 'check_staged_secrets.py'):
        digest.update((ROOT / 'tools' / name).read_bytes())
    return digest.hexdigest()[:12]


def scan(root, prefix, paths, checks=None, unread=None):
    """Findings for the changed files: the private list and private addresses in every file of text up to TEXT_LIMIT
    and in every name (as tests/test_personal_words.py and tests/test_release_scan.py), and, in what the release ships, the release's checks on its UTF-8 text of any size
    (as check_staged_secrets.py --personal) and the persona names (as tests/test_release_scan.py). A changed path that
    is not a file it can read is appended to `unread` (unchecked, never clean) and gets no findings."""
    secrets, allow, deny, entries, names = checks or _checks()
    findings = []
    for name in paths:
        key = (prefix.rstrip('/') + '/' + name) if prefix else name
        ships = shipped(key, root, prefix) and not secrets.SKIP.search(key)
        found = set()

        def listed(text, line):
            for entry, category in private_words.find(entries or [], text):
                found.add((line, 'listed:' + category, entry))
            if not ships and secrets.private_address(text, allow):     # what ships gets it with the release's checks
                found.add((line, 'private_address', None))

        def released(text, line):
            for _number, category in secrets.scan_lines(text, key, allow, deny):
                found.add((line, category, None))
            if any(word in text for word in names):
                found.add((line, 'persona_name', None))
        listed(key, 0)
        if ships:
            released(key, 0)
        path = Path(root) / name
        try:
            data = path.read_bytes()
        except OSError:
            if unread is not None:
                unread.append(name)
            data = b''                    # its name was checked above; its content was not
        if len(data) <= TEXT_LIMIT and b'\0' not in data[:4096]:
            for number, line in enumerate(data.decode('utf-8', 'replace').splitlines(), 1):
                listed(line, number)
        if ships and b'\0' not in data and key.rsplit('/', 1)[-1] not in secrets.LOCKFILES:
            try:
                text = data.decode('utf-8')
            except UnicodeDecodeError:
                text = ''                            # not text the release scan reads
            for number, line in enumerate(text.split('\n'), 1):
                released(line, number)
        named = any(line == 0 for line, _category, _entry in found)
        findings += [{'path': None if named else name, 'line': line, 'category': category,
                      **({'entry': entry} if entry else {})}
                     for line, category, entry in sorted(found, key=lambda item: (item[0], item[1]))]
    return findings


def scan_reason(reason, checks=None):
    """The publication's reason, which becomes a public commit message: the private list and the release's
    personal-data checks (not persona names: she may say who she is in her own commit)."""
    secrets, allow, deny, entries, _names = checks or _checks()
    found = set()
    for number, line in enumerate(str(reason or '').split('\n'), 1):
        for entry, category in private_words.find(entries or [], line):
            found.add((number, 'listed:' + category, entry))
        for _n, category in secrets.scan_lines(line, '', allow, deny):
            found.add((number, category, None))
    return [{'line': line, 'category': category, **({'entry': entry} if entry else {})}
            for line, category, entry in sorted(found, key=lambda item: (item[0], item[1]))]


def main(argv):
    request = json.loads(Path(argv[0]).read_text(encoding='utf-8'))
    checks = _checks()
    unread = []
    findings = scan(request['root'], request.get('prefix') or '', request['paths'], checks, unread)
    reason = scan_reason(request.get('reason'), checks)
    print(json.dumps({'findings': findings[:MAX_FINDINGS], 'total': len(findings), 'reason': reason[:MAX_FINDINGS],
                      'list': 'missing' if checks[3] is None else 'checked', 'unread': unread,
                      'scan': scan_version()}))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
