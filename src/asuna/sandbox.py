"""Bounded task-only Linux namespace via existing WSL bubblewrap."""
from pathlib import Path
import subprocess
from .config import ROOT


class Sandbox:
    def __init__(self, task_dir: Path):
        self.task_dir = task_dir.resolve()
        if not self.task_dir.is_relative_to((ROOT/'.runtime/work').resolve()):
            raise PermissionError('TASK_WORKSPACE_OUTSIDE_ALLOWLIST')
        self.task_dir.mkdir(parents=True, exist_ok=True)

    def run(self, argv: list[str], timeout: int = 30) -> dict:
        if not argv or len(argv) > 40 or sum(map(len, argv)) > 16000:
            raise ValueError('INVALID_COMMAND')
        p=self.task_dir
        mount='/mnt/'+p.drive[0].lower()+p.as_posix()[2:]
        command=['wsl','-d','Ubuntu','--','bwrap','--unshare-all','--die-with-parent','--new-session',
                 '--ro-bind','/usr','/usr','--symlink','usr/bin','/bin','--symlink','usr/lib','/lib',
                 '--symlink','usr/lib64','/lib64','--proc','/proc','--dev','/dev','--tmpfs','/tmp',
                 '--bind',mount,'/task','--chdir','/task','--clearenv','--setenv','PATH','/usr/bin:/bin',
                 '/usr/bin/prlimit','--cpu=20','--as=1073741824','--fsize=8388608','--nofile=128','--',*argv]
        result=subprocess.run(command, capture_output=True, timeout=timeout, encoding='utf-8', errors='replace')
        if len(result.stdout)+len(result.stderr)>262144:
            raise RuntimeError('TOOL_OUTPUT_LIMIT')
        return {'argv':argv,'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr,
                'sandbox':'wsl-bubblewrap-unshare-all','network':'isolated','mount':'task-only'}
