"""Process-wide and cross-process endpoint serialization, without cloud routes."""
import hashlib
import msvcrt
import time
import threading
from urllib.parse import urlsplit
from .config import ROOT


class EndpointLock:
    def __init__(self,url,timeout=900):
        host=urlsplit(url).netloc
        self.path=ROOT/'.runtime/locks'/(hashlib.sha256(host.encode()).hexdigest()+'.lock')
        self.timeout=timeout
    def __enter__(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.file=self.path.open('a+b')
        if self.file.tell()==0:self.file.write(b'0');self.file.flush()
        start=time.monotonic()
        while True:
            self.file.seek(0)
            try:msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1);break
            except OSError:
                if time.monotonic()-start>self.timeout:self.file.close();raise TimeoutError('LOCAL_ENDPOINT_QUEUE_TIMEOUT')
                time.sleep(.05)
        self.wait_seconds=time.monotonic()-start
        return self
    def __exit__(self,*args):
        self.file.seek(0);msvcrt.locking(self.file.fileno(),msvcrt.LK_UNLCK,1);self.file.close()


class RuntimeLease(EndpointLock):
    def __init__(self,path,timeout=2):
        self.path=path.resolve();self.timeout=timeout
        if not self.path.is_relative_to((ROOT/'.runtime').resolve()):raise PermissionError('RUNTIME_LEASE_PATH_DENIED')


class _DatabaseEffectsLock:
    """Serialize accepted cancellation with local tool/publication effects.

    A reentrant thread lock and a Windows byte lock share one local database
    domain. The OS releases the byte lock on process exit. Model inference is
    deliberately outside this lock, so a running model cannot block cancel.
    """
    def __init__(self,name):
        self.thread=threading.RLock();self.depth=0
        self.path=ROOT/'.runtime/locks'/('effects-'+hashlib.sha256(name.encode()).hexdigest()+'.lock')
    def __enter__(self):
        self.thread.acquire()
        try:
            if not self.depth:
                self.lease=RuntimeLease(self.path,timeout=120);self.lease.__enter__()
            self.depth+=1
            return self
        except BaseException:self.thread.release();raise
    def __exit__(self,*args):
        try:
            self.depth-=1
            if not self.depth:self.lease.__exit__(*args)
        finally:self.thread.release()


_database_locks={}
_registry_lock=threading.Lock()


def database_effects_lock(name):
    with _registry_lock:
        return _database_locks.setdefault(name,_DatabaseEffectsLock(name))
