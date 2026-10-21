"""A name used but never defined fails only when its line runs, so it reaches her as a program fault (live 10-21:
`feel` with `who` on a feeling not about a person). The project's own Python is checked for it here; the vendored
websocket client and the persona packages, which are the character's own files, are not."""
from pathlib import Path

from pyflakes import api, messages, reporter

ROOT = Path(__file__).resolve().parents[1]
CHECKED = ('src/asuna', 'tools', 'packages/channels', 'tests')
UNDEFINED = (messages.UndefinedName, messages.UndefinedLocal, messages.UndefinedExport)


class Collect(reporter.Reporter):
    def __init__(self):
        super().__init__(None, None)
        self.found = []

    def flake(self, message):
        if isinstance(message, UNDEFINED):
            where = Path(message.filename).resolve().relative_to(ROOT).as_posix()
            self.found.append('%s:%d: %s' % (where, message.lineno, message.message % message.message_args))

    def syntaxError(self, filename, msg, lineno, offset, text):
        self.found.append('%s:%s: syntax error: %s' % (filename, lineno, msg))

    def unexpectedError(self, filename, msg):
        self.found.append('%s: %s' % (filename, msg))


def test_no_python_file_uses_a_name_it_never_defines():
    seen = Collect()
    for top in CHECKED:
        for path in sorted((ROOT / top).rglob('*.py')):
            if not {'vendor', 'node_modules', '__pycache__'} & set(path.relative_to(ROOT).parts):
                api.checkPath(str(path), seen)
    assert not seen.found, '\n'.join(seen.found)
