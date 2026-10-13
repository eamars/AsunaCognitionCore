"""Loaded by every Python a confined command starts (the sandbox puts this folder on PYTHONPATH).

On Windows CPython turns mkdir mode 0o700 (tempfile.mkdtemp, TemporaryDirectory, pytest's tmp_path) into a protected
ACL that drops the inherited ones, and inside DSH's sandbox the command's write grant is inherited: such a folder is
one the command itself can neither list nor write. Those folders are made with their parent's permissions instead.
"""
import os
import sys

if sys.platform == 'win32' and not getattr(os.mkdir, 'inherits', False):
    _plain = os.mkdir

    def _mkdir(path, mode=0o777, *, dir_fd=None):
        return _plain(path, 0o777 if mode == 0o700 else mode, dir_fd=dir_fd)
    _mkdir.inherits = True
    os.mkdir = _mkdir
