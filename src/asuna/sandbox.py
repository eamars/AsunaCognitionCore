"""A task's commands, run under DSH's sandbox (sandbox_backend.py): writes stay in the task folder.

Commands are native to the machine the Host runs on. `python3`/`python` is the worker's own Python, and an argument
naming `/task` (how her tools and briefs name the task folder) is the task folder itself.
"""
from pathlib import Path
import subprocess
import sys
import threading
from .config import DATA
from . import sandbox_backend

OUTPUT_LIMIT = 262144
PYTHONS = ('python3', 'python', 'python3.exe', 'python.exe')


class Sandbox:
    def __init__(self, task_dir: Path, protected_paths=(), *, allowed_root=None, config=None):
        self.config = config if config is not None else {}
        self.task_dir = task_dir.resolve()
        root = Path(allowed_root).resolve() if allowed_root else DATA/'work'
        if not any(root.is_relative_to(DATA/name) for name in ('work','channels','integration')):
            raise PermissionError('SANDBOX_ROOT_OUTSIDE_RUNTIME')
        if not self.task_dir.is_relative_to(root):
            raise PermissionError('TASK_WORKSPACE_OUTSIDE_ALLOWLIST')
        self.task_dir.mkdir(parents=True, exist_ok=True)
        self.protected_paths=[]
        for path in protected_paths:
            path=Path(path).resolve()
            if not path.is_relative_to(self.task_dir) or not path.exists():raise PermissionError('PROTECTED_INPUT_PATH_DENIED')
            self.protected_paths.append(path)

    def native(self, argv):
        """Her argv as this machine runs it: python3 is the worker's Python, /task is the task folder."""
        root = self.task_dir.as_posix()
        out = [sys.executable if argv[0] in PYTHONS else argv[0]]
        for arg in argv[1:]:
            out.append(root + arg[len('/task'):] if arg == '/task' or arg.startswith('/task/') else arg)
        return out

    def run(self, argv: list[str], timeout: int = 30, env=None) -> dict:
        """``env``: extra variables for this one command (her credentials, credentials.environment)."""
        if not argv or len(argv) > 40 or sum(map(len, argv)) > 16000 or any(not isinstance(a, str) or '\0' in a for a in argv):
            raise ValueError('INVALID_COMMAND')
        command = sandbox_backend.confine(self.config, self.native(argv), self.task_dir)
        value = run_bounded(command, self.task_dir, timeout, env=env)
        if value['launch_failed']:
            raise RuntimeError('SANDBOX_LAUNCH_FAILED (exit %s)\nstderr:\n%s' % (value['exit_code'], value['stderr']))
        if value['output_limit']:raise RuntimeError('TOOL_OUTPUT_LIMIT')
        if value['timed_out']:raise TimeoutError('TOOL_TIMEOUT')
        return {'argv': argv, 'exit_code': value['exit_code'], 'stdout': value['stdout'], 'stderr': value['stderr'],
                'output_limit': False, 'timed_out': False, 'sandbox': 'dsh', 'writes': 'task folder only'}


def run_bounded(command, cwd, timeout, *, stdin=None, env=None, limit=OUTPUT_LIMIT):
    """Run a wrapped command: its output capped, its time bounded, stdin never the worker's own (the Host's request
    pipe). Killing the wrapper ends the confined command (DSH's runner holds it in a kill-on-close job)."""
    process = subprocess.Popen(command, cwd=str(cwd), env=sandbox_backend.environment(env),
                               stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    buffers, state = [bytearray(), bytearray()], {'limit': False}
    lock = threading.Lock()

    def read(stream, index):
        while chunk := stream.read1(8192) if hasattr(stream, 'read1') else stream.read(8192):
            with lock:
                if len(buffers[0]) + len(buffers[1]) + len(chunk) > limit:
                    state['limit'] = True
                    process.kill()
                    return
                buffers[index].extend(chunk)
    readers = [threading.Thread(target=read, args=(process.stdout, 0), daemon=True),
               threading.Thread(target=read, args=(process.stderr, 1), daemon=True)]
    for reader in readers:
        reader.start()
    if stdin is not None:
        try:
            process.stdin.write(stdin if isinstance(stdin, bytes) else stdin.encode('utf-8'))
            process.stdin.close()
        except OSError:
            pass
    timed_out = False
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        process.wait()
    for reader in readers:
        reader.join(timeout=5)
    stderr = buffers[1].decode('utf-8', 'replace')
    # DSH's runners report their own failure on stderr with exit 127 (windows-acl-run: …), not the command's.
    launch_failed = process.returncode == 127 and ('windows-acl-run:' in stderr or 'bwrap:' in stderr)
    return {'exit_code': process.returncode, 'stdout': buffers[0].decode('utf-8', 'replace'), 'stderr': stderr,
            'output_limit': state['limit'], 'timed_out': timed_out, 'launch_failed': launch_failed}
