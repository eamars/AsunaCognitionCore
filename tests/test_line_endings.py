"""Every text file in the repository uses LF line endings (owner 2026-10-07).

.gitattributes makes git store and check out text as LF. This catches the other way CRLF comes back: a file
rewritten on Windows in the working tree (an editor, a shell tool) before it is committed.
"""
import subprocess

from asuna.config import ROOT


def test_gitattributes_keeps_text_as_lf():
    rules = [line.strip() for line in (ROOT / '.gitattributes').read_text(encoding='utf-8').splitlines()
             if line.strip() and not line.startswith('#')]
    assert rules == ['* text=auto eol=lf']


def test_no_tracked_text_file_has_crlf():
    listed = subprocess.run(['git', 'ls-files', '--eol'], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    crlf = []
    for row in listed.splitlines():
        flags, path = row.split('\t', 1)
        if flags.split()[0] == 'i/-text':            # binary (images): bytes are left alone
            continue
        file = ROOT / path
        if file.is_file() and b'\r\n' in file.read_bytes():
            crlf.append(path)
    assert not crlf, 'convert to LF: %s' % crlf
