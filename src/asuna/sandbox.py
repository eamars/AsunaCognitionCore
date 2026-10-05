"""Bounded task-only Linux namespace: bubblewrap under the worker's sandbox backend (sandbox_backend.py)."""
from pathlib import Path
import json
import subprocess
from .config import DATA
from . import sandbox_backend


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

    def run(self, argv: list[str], timeout: int = 30) -> dict:
        if not argv or len(argv) > 40 or sum(map(len, argv)) > 16000:
            raise ValueError('INVALID_COMMAND')
        sandbox=sandbox_backend.require(self.config)
        mount=sandbox_backend.path(sandbox,self.task_dir)
        protected=[]
        for path in self.protected_paths:
            relative=path.relative_to(self.task_dir).as_posix()
            protected+=['--ro-bind',mount+'/'+relative,'/task/'+relative]
        # --exec bypasses WSL's default shell reconstruction. Without it a
        # single argv containing shell punctuation can be reinterpreted outside
        # bubblewrap before the sandbox starts.
        wrapper='''import subprocess,selectors,time,os,signal,json,sys
p=subprocess.Popen(json.loads(sys.argv[1]),stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
s=selectors.DefaultSelector();s.register(p.stdout,selectors.EVENT_READ,0);s.register(p.stderr,selectors.EVENT_READ,1)
buffers=[bytearray(),bytearray()];start=time.monotonic();limit=False;expired=False
try:
 while s.get_map():
  if time.monotonic()-start>float(sys.argv[2]):expired=True;break
  for key,_ in s.select(.1):
   data=os.read(key.fileobj.fileno(),8192)
   if not data:s.unregister(key.fileobj);continue
   if sum(map(len,buffers))+len(data)>262144:limit=True;break
   buffers[key.data].extend(data)
  if limit:break
finally:
 if p.poll() is None or limit or expired:
  try:os.killpg(p.pid,signal.SIGKILL)
  except ProcessLookupError:pass
 p.wait()
print(json.dumps({'exit_code':p.returncode,'stdout':buffers[0].decode('utf-8','replace'),'stderr':buffers[1].decode('utf-8','replace'),'output_limit':limit,'timed_out':expired}))
'''
        command=[*sandbox_backend.prefix(sandbox),'bwrap','--unshare-all','--die-with-parent','--new-session',
                 '--ro-bind','/usr','/usr','--symlink','usr/bin','/bin','--symlink','usr/lib','/lib',
                 '--symlink','usr/lib64','/lib64','--proc','/proc','--dev','/dev','--tmpfs','/tmp',
                 '--bind',mount,'/task',*protected,'--chdir','/task','--clearenv','--setenv','PATH','/usr/bin:/bin',
                 '/usr/bin/prlimit','--cpu=20','--as=1073741824','--fsize=8388608','--nofile=128','--',
                 'python3','-c',wrapper,json.dumps(argv),str(timeout)]
        # stdin is the worker's request pipe from the Host: wsl relays its stdin into Linux, so an inherited stdin
        # swallows Host requests while the command runs (a cut request ends the worker's read loop).
        result=subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout+5,
                              encoding='utf-8', errors='replace')
        if result.returncode:raise RuntimeError(f'SANDBOX_LAUNCH_FAILED (exit {result.returncode})\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}')
        value=json.loads(result.stdout)
        if value['output_limit']:raise RuntimeError('TOOL_OUTPUT_LIMIT')
        if value['timed_out']:raise TimeoutError('TOOL_TIMEOUT')
        return {'argv':argv,**value,
                'sandbox':'wsl-bubblewrap-unshare-all','network':'isolated','mount':'task-only'}
