"""Temporary folders a test can use inside DSH's Windows sandbox.

CPython on Windows turns mkdir mode 0o700 (pytest's tmp_path folders, tempfile.mkdtemp and TemporaryDirectory) into a
protected ACL that drops the inherited ones. Inside DSH's sandbox the write grant is inherited, so such a folder is
one the confined run can neither list nor write. `inherit()` makes a test process create those folders with their
parent's permissions instead; conftest and the offline-check cases call it before they make any.
"""
import os
import sys


def inherit():
    if sys.platform != 'win32' or getattr(os.mkdir, 'inherits', False):
        return
    plain = os.mkdir

    def mkdir(path, mode=0o777, *, dir_fd=None):
        return plain(path, 0o777 if mode == 0o700 else mode, dir_fd=dir_fd)
    mkdir.inherits = True
    os.mkdir = mkdir
