"""Every text file in the repository uses LF line endings (owner 2026-10-07).

.gitattributes makes git store and check out text as LF. This catches the other way CRLF comes back: a file
rewritten on Windows in the working tree (an editor, a shell tool) before it is committed.
"""

from asuna.config import ROOT
from asuna import repo_files


def test_gitattributes_keeps_text_as_lf():
    rules = [line.strip() for line in (ROOT / '.gitattributes').read_text(encoding='utf-8').splitlines()
             if line.strip() and not line.startswith('#')]
    assert rules == ['* text=auto eol=lf']


def test_no_tracked_text_file_has_crlf():
    crlf = []
    for path in repo_files.files(ROOT):
        file = ROOT / path
        data = file.read_bytes() if file.is_file() else b''
        if b'\0' in data[:8000]:                     # binary (images): bytes are left alone
            continue
        if b'\r\n' in data:
            crlf.append(path)
    assert not crlf, 'convert to LF: %s' % crlf
