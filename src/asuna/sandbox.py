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
ARGV_ITEMS = 40
ARGV_CHARS = 16000
# A runner that could not find argv[0]: Windows error 2/3 (file/path not found), bwrap's execvp ENOENT.
NOT_FOUND = ('(Win32 2)', '(Win32 3)', 'No such file or directory')


def command_problem(argv, script='/task/run.py'):
    """What is wrong with this argv, in her words, or None. ``script``: how the example names a script."""
    if not argv:
        return 'argv 是空的；写成列表，例如 ["python3", "%s"]' % script
    if len(argv) > ARGV_ITEMS:
        return ('argv 有 %d 项，上限 %d 项；把参数写进脚本或数据文件，argv 只留 ["python3", "%s"]'
                % (len(argv), ARGV_ITEMS, script))
    for index, arg in enumerate(argv):
        if not isinstance(arg, str):
            return 'argv 第 %d 项是 %s，每一项都要是字符串' % (index + 1, type(arg).__name__)
        if '\0' in arg:
            return 'argv 第 %d 项含 NUL 字符；去掉它' % (index + 1)
    total = sum(map(len, argv))
    if total > ARGV_CHARS:
        return ('argv 一共 %d 字，上限 %d 字；长内容先写成脚本或数据文件，argv 只写 ["python3", "%s"] 去读它'
                % (total, ARGV_CHARS, script))
    return None


def launch_problem(argv, exit_code, stderr):
    """Why the sandbox could not start her command, and what to do."""
    if any(mark in stderr for mark in NOT_FOUND):
        return ('没有叫 %r 的程序：argv[0] 要是本机上的程序，argv 不经过 shell 运行（没有 sh，也没有 pwd、ls、cd、'
                'echo 这类 shell 命令和管道）；把要做的写成 python3，例如 ["python3", "-c", "import os; print(os.listdir())"]'
                '（exit %s）' % (str(argv[0])[:80], exit_code))
    return ('沙箱没能启动这个命令（exit %s）：%s；这不是命令自己的输出，重试也一样：检查 argv[0] 是不是本机程序，'
            '或改用 python3 脚本' % (exit_code, ' '.join(stderr.split())[:400]))


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
        problem = command_problem(argv)
        if problem:
            raise ValueError('INVALID_COMMAND: ' + problem)
        command = sandbox_backend.confine(self.config, self.native(argv), self.task_dir)
        value = run_bounded(command, self.task_dir, timeout, env=env)
        if value['launch_failed']:
            raise RuntimeError('SANDBOX_LAUNCH_FAILED: ' + launch_problem(argv, value['exit_code'], value['stderr']))
        if value['output_limit']:
            raise RuntimeError('TOOL_OUTPUT_LIMIT: 输出超过 %d 字节（256 KiB），命令被停下，输出没有保留；同样的命令重试也一样：'
                               '让脚本把结果写进 /task 里的文件（每个 32 KiB 以内，read_file 一次读一个），'
                               '或只打印过滤后需要的部分' % OUTPUT_LIMIT)
        if value['timed_out']:
            raise TimeoutError('TOOL_TIMEOUT: 命令跑满 %d 秒还没结束，被停下，输出没有保留；同样的命令重试也一样：'
                               '把活拆小（每次只处理一部分，进度写进 /task 的文件，下一次接着做），'
                               '或让脚本在时限内自己收尾' % timeout)
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
