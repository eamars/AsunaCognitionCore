"""The files of a source tree as git lists them, with or without git.

A development checkout asks git. A plain copy of the tree (a publication's candidate, an unpacked release) is not a
checkout of its own, even when it sits inside one, so its files are walked and filtered by the tree's `.gitignore`. In
a copy that is a superset of what git would list (a file that is neither tracked nor ignored is included), which is
the safe side for every check that reads it.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def checkout(root):
    """Whether `root` is the top of a git work tree (inside one, as a candidate under `.runtime/` is, does not count)."""
    try:
        top = subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=root, capture_output=True, text=True,
                             timeout=30, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return False
    return top.returncode == 0 and Path(top.stdout.strip()).resolve() == Path(root).resolve()


def _ignore(root):
    import pathspec
    found = Path(root) / '.gitignore'
    return pathspec.GitIgnoreSpec.from_lines(found.read_text(encoding='utf-8').splitlines() if found.is_file() else [])


def _within(patterns):
    """A matcher for pathspecs given from the root (`src/asuna`, `packages/**/package.json`), read with gitignore
    rules: there `**/` also matches no folder at all, where git's own pathspec needs one."""
    import pathspec
    return pathspec.GitIgnoreSpec.from_lines(['/' + p.lstrip('/') for p in patterns])


def files(root, *patterns):
    """Tracked files (posix, relative to root), optionally only those under or matching the given pathspecs."""
    root = Path(root)
    if checkout(root):
        listed = subprocess.run(['git', 'ls-files', '-z', '--', *patterns], cwd=root, capture_output=True,
                                check=True, stdin=subprocess.DEVNULL).stdout
        return [name.decode('utf-8') for name in listed.split(b'\0') if name]
    ignore, within = _ignore(root), (_within(patterns) if patterns else None)
    found = []
    for folder, dirs, names in os.walk(root):
        here = Path(folder).relative_to(root).as_posix()
        here = '' if here == '.' else here + '/'
        dirs[:] = sorted(d for d in dirs if d != '.git' and not ignore.match_file(here + d + '/'))
        for name in sorted(names):
            relative = here + name
            if not ignore.match_file(relative) and (within is None or within.match_file(relative)):
                found.append(relative)
    return found


def ignored(root, relative):
    """Whether a path inside the tree is ignored (git's answer in a checkout, the tree's `.gitignore` otherwise)."""
    if checkout(root):
        return subprocess.run(['git', 'check-ignore', '-q', relative], cwd=root,
                              stdin=subprocess.DEVNULL).returncode == 0
    return _ignore(root).match_file(relative)
