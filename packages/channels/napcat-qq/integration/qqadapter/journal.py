"""Disk-backed spool, journals and counters.

The spool directory *is* the inbound queue: an authorized event is on disk
before anything is attempted in memory, so a full queue, a crash or a SIGTERM
cannot drop it silently.  Anything that stops being retried is moved into a
journal file with a reason instead of vanishing.
"""
import json
import os
import threading
import time

try:                      # Linux and macOS
    import fcntl
except ImportError:       # Windows: the same non-blocking exclusive lock, on one byte past the file's content
    fcntl = None
    import msvcrt

# Windows locks bytes, and a locked byte cannot be read through another handle: the lock sits past the end of
# the file, so the informational pid line stays readable. (A byte range past the end may be locked.)
LOCK_OFFSET = 1 << 20


def _lock(fd):
    if fcntl:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    else:
        os.lseek(fd, LOCK_OFFSET, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)


def _unlock(fd):
    if fcntl:
        fcntl.flock(fd, fcntl.LOCK_UN)
    else:
        os.lseek(fd, LOCK_OFFSET, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


class Counters:
    def __init__(self):
        self._lock = threading.Lock()
        self._vals = {}

    def inc(self, name, delta=1):
        with self._lock:
            self._vals[name] = self._vals.get(name, 0) + delta

    def set(self, name, value):
        with self._lock:
            self._vals[name] = value

    def snapshot(self):
        with self._lock:
            return dict(self._vals)


class Journal:
    def __init__(self, root):
        self.root = root
        self.spool_in = os.path.join(root, "spool", "inbound")
        self.spool_re = os.path.join(root, "spool", "receipts")
        self.jdir = os.path.join(root, "journal")
        for directory in (self.spool_in, self.spool_re, self.jdir):
            os.makedirs(directory, exist_ok=True)
        self._lock = threading.Lock()
        self._seq = 0
        self.started = time.time()

    @staticmethod
    def write_json(path, obj):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(obj, handle, ensure_ascii=False, sort_keys=True, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)

    @staticmethod
    def read_json(path):
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def append(self, name, obj):
        """Append one line to journal/<name>.jsonl."""
        path = os.path.join(self.jdir, name)
        line = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
        with self._lock:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        return path

    def spool_add(self, bucket, obj, key=""):
        directory = self.spool_in if bucket == "inbound" else self.spool_re
        with self._lock:
            self._seq += 1
            seq = self._seq
        stamp = int(time.time() * 1000)
        safe_key = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(key))[:64]
        name = "%013d-%06d-%s.json" % (stamp, seq, safe_key or "x")
        path = os.path.join(directory, name)
        self.write_json(path, obj)
        _fsync_dir(directory)
        return path

    def spool_list(self, bucket):
        directory = self.spool_in if bucket == "inbound" else self.spool_re
        try:
            names = sorted(os.listdir(directory))
        except OSError:
            return []
        return [os.path.join(directory, n) for n in names if n.endswith(".json")]

    def spool_remove(self, path):
        try:
            os.unlink(path)
            return True
        except FileNotFoundError:
            return False

    def spool_move(self, path, journal_name, extra=None):
        """Remove a spool item after recording it (with reason) in a journal."""
        try:
            obj = self.read_json(path)
        except Exception as exc:  # unreadable spool file: keep the name, note it
            obj = {"unreadable": str(exc), "path": os.path.basename(path)}
        record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "item": obj}
        if extra:
            record.update(extra)
        self.append(journal_name, record)
        self.spool_remove(path)
        return record

    def write_health(self, obj):
        self.write_json(os.path.join(self.root, "health.json"), obj)

    def read_health(self):
        try:
            return self.read_json(os.path.join(self.root, "health.json"))
        except Exception:
            return None

    def acquire_lock(self):
        """Refuse to run twice against the same data dir.

        A non-blocking `flock` on the lock file is the whole mechanism.  The
        kernel drops it as soon as the holder exits, however it exits, so a
        file left behind by an earlier run never blocks a restart, and a peer
        that is really alive - in this PID namespace or another one - cannot be
        mistaken for a stale pid.  No pid guessing, no TTL, no heartbeat.
        """
        path = os.path.join(self.root, "adapter.lock")
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            _lock(fd)
        except OSError:
            os.close(fd)
            raise RuntimeError("another adapter process is holding %s" % path)
        self._lock_fd = fd
        self._lock_path = path
        try:                      # informational only; the flock is the lock
            os.ftruncate(fd, 0)
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, ("pid=%d" % os.getpid() + chr(10)).encode("ascii"))
            os.fsync(fd)
        except OSError:
            pass
        return path

    def release_lock(self):
        """Unlock and close.  Leaving the file behind is harmless: an unlocked
        file carries no claim, which is exactly why restarts work."""
        fd = getattr(self, "_lock_fd", None)
        self._lock_fd = None
        if fd is None:
            return
        try:
            _unlock(fd)
        except OSError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass


def _fsync_dir(path):
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass
