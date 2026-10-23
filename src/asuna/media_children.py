"""Voice and video decoding in child processes (ADR-095 §5.3.1): one long-lived child per kind, each on its own, so a
hang or a crash in native decoding holds only its own kind of work and never the Host.

- `Child` is the supervisor both kinds share. It starts `python -m asuna.media_worker <kind> <host pid> ...` on the
  base interpreter (on Windows the venv's python.exe is a redirector whose kill misses the real interpreter), waits
  for its ready frame, and runs one job at a time. Each call has a budget counted from when it was asked: the wait
  behind the kind's other jobs, a start, and each try come out of it, and a try ends at its deadline or the budget,
  whichever is first. Past it, or when the child exits or answers garbage, the child is killed and reaped, a fresh one
  is started, and the job is tried once more if the budget allows. A child that will not start is tried again at
  most once every RESTART_WAIT seconds.
- No child outlives the Host: on Windows each sits in a job object that kills it when the Host's handle closes; on
  every system the worker exits when its stdin closes or its Host's pid is gone (media_worker.py).
- Frames on the child's stdin and stdout: a 4-byte length and a JSON header, then an 8-byte length and the payload.
- A setting that is off, or a missing package or model found when the Host starts, is the machine's state, not a
  job's failure: the caller says so in its own words and starts no child (`voice.py`, `video_snapshot`).
- Each kill, death, failed start or program error in a child is one lane fault (`lane_faults.record`, lanes
  `transcriber` and `video`); a program error's traceback tail comes back in its answer for the evidence.
- `video_snapshot` is the video side: the contact sheet of `animated.video_snapshot`, cut in the video child.
"""
from __future__ import annotations

import ctypes
import importlib.util
import json
import os
import queue
import struct
import subprocess
import sys
import threading
import time

START_SECONDS = 120          # a child loads its decoder (the voice model: about 1 s) within this
RESTART_WAIT = 60            # a child that would not start is tried again at most once a minute
VOICE_DEADLINE = 90          # one try of one voice, decoded and transcribed (a minute of speech takes a few seconds)
VOICE_BUDGET = 180           # one voice in all: waiting behind other voices, a start, two tries
VIDEO_DEADLINE = 120         # one try of one video's contact sheet (36 seeks, at most 32 MB)
VIDEO_BUDGET = 240
FAULT_LANES = {'voice': 'transcriber', 'video': 'video'}
VIDEO_PACKAGES = ('av', 'PIL')

VIDEO_OFF = 'VIDEO_NOT_SPLIT: 视频解码关着，这段视频看不了'
VIDEO_NOT_SET_UP = 'VIDEO_NOT_SPLIT: 这台机器上拆视频要用的程序没装好（缺 %s），这段视频看不了；重试也一样'
VIDEO_NOT_STARTED = 'VIDEO_NOT_SPLIT: 这台机器上拆视频的程序没能启动，这段视频看不了'
VIDEO_TIMEOUT = 'VIDEO_NOT_SPLIT: 拆这段视频超时了，没有截图可看'
VIDEO_CRASHED = 'VIDEO_NOT_SPLIT: 拆视频的程序出错了，没有截图可看'


class StartFailed(Exception):
    """The child exited, or did not say it was ready, while starting."""


class Closed(StartFailed):
    """The kind is closing (the Host stops): a job it ended is not the job's failure."""


class Timeout(Exception):
    """The job's try ran past its deadline, or the call's budget ran out."""


class Died(Exception):
    """The child exited, or answered something that is not a frame, during the job."""


class JobError(Exception):
    """The job could not be done; `program` when the child's own code failed (not the job's content)."""

    def __init__(self, words, program=False, trace=''):
        super().__init__(words)
        self.program, self.trace = program, trace


def write_frame(stream, header, payload=b''):
    body = json.dumps(header, ensure_ascii=False).encode('utf-8')
    stream.write(struct.pack('>I', len(body)) + body + struct.pack('>Q', len(payload)) + payload)
    stream.flush()


def _exactly(stream, size):
    data = b''
    while len(data) < size:
        piece = stream.read(size - len(data))
        if not piece:
            raise EOFError
        data += piece
    return data


def read_frame(stream):
    """(header, payload); EOFError at the end of the stream, ValueError for something that is not a frame."""
    size = struct.unpack('>I', _exactly(stream, 4))[0]
    if size > 16 * 1024 * 1024:
        raise ValueError('header too large')
    header = json.loads(_exactly(stream, size).decode('utf-8'))
    if not isinstance(header, dict):
        raise ValueError('header is not an object')
    length = struct.unpack('>Q', _exactly(stream, 8))[0]
    if length > 512 * 1024 * 1024:
        raise ValueError('payload too large')
    return header, _exactly(stream, length)


def _python():
    return getattr(sys, '_base_executable', None) or sys.executable


def _installed():
    """The folders this interpreter imports installed packages from (a venv's site-packages among them)."""
    import site
    found = list(site.getsitepackages()) + [site.getusersitepackages()]
    found += [path for path in sys.path if os.path.basename(path.rstrip('/\\')) in ('site-packages', 'dist-packages')]
    return [path for path in dict.fromkeys(found) if os.path.isdir(path)]


def _job_object(proc):
    """Windows: a job object that kills `proc` when its handle closes (the Host exits or kills it)."""
    from ctypes import wintypes

    class Basic(ctypes.Structure):
        _fields_ = [('PerProcessUserTimeLimit', ctypes.c_int64), ('PerJobUserTimeLimit', ctypes.c_int64),
                    ('LimitFlags', wintypes.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                    ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wintypes.DWORD),
                    ('Affinity', ctypes.c_size_t), ('PriorityClass', wintypes.DWORD),
                    ('SchedulingClass', wintypes.DWORD)]

    class Counters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in ('ReadOperationCount', 'WriteOperationCount',
                                                          'OtherOperationCount', 'ReadTransferCount',
                                                          'WriteTransferCount', 'OtherTransferCount')]

    class Extended(ctypes.Structure):
        _fields_ = [('BasicLimitInformation', Basic), ('IoInfo', Counters), ('ProcessMemoryLimit', ctypes.c_size_t),
                    ('JobMemoryLimit', ctypes.c_size_t), ('PeakProcessMemoryUsed', ctypes.c_size_t),
                    ('PeakJobMemoryUsed', ctypes.c_size_t)]

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        return None
    info = Extended()
    info.BasicLimitInformation.LimitFlags = 0x2000          # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    kernel.SetInformationJobObject(wintypes.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info))
    if not kernel.AssignProcessToJobObject(wintypes.HANDLE(job), wintypes.HANDLE(int(proc._handle))):
        kernel.CloseHandle(wintypes.HANDLE(job))
        return None
    return job


def _close_job(job):
    if job:
        from ctypes import wintypes
        ctypes.WinDLL('kernel32').CloseHandle(wintypes.HANDLE(job))


class Child:
    """One kind's child process: started warm, one job at a time, killed and replaced past a deadline."""

    def __init__(self, kind, args=(), *, fault=None, start_seconds=START_SECONDS, restart_wait=RESTART_WAIT,
                 command=None):
        self.kind, self.args = kind, list(args)
        self._fault = fault
        self.start_seconds, self.restart_wait = start_seconds, restart_wait
        self.command = command                   # tests: another program speaking the same frames
        self.lock = threading.Lock()
        self.proc = self.job = self.replies = None
        self.failed_start_at = None
        self.closed = False

    def fault(self, stage, error):
        """One lane fault; counting never reaches the job."""
        if self._fault is not None:
            try:
                self._fault(stage, error)
            except Exception:                        # noqa: BLE001
                pass

    # -- the process ------------------------------------------------------------------------------------------------
    def _spawn(self):
        # -P: no current or script folder on its path. Its path is this package's root and the installed packages
        # only, never the Host's whole sys.path: a folder such as the package itself would put asuna/queue.py in front
        # of the standard library's queue.
        command = self.command or [_python(), '-X', 'utf8', '-P', '-m', 'asuna.media_worker', self.kind,
                                   str(os.getpid()), *self.args]
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env = {**os.environ, 'PYTHONPATH': os.pathsep.join(dict.fromkeys([here, *_installed()]))}
        windows = os.name == 'nt'
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                env=env, cwd=here, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.job = _job_object(proc) if windows else None
        self.proc, self.replies = proc, queue.Queue()
        threading.Thread(target=self._read, args=(proc, self.replies), name='asuna-media-' + self.kind,
                         daemon=True).start()

    @staticmethod
    def _read(proc, replies):
        """Every frame the child writes, in order; a closed or garbled stream ends with the reason."""
        try:
            while True:
                replies.put(read_frame(proc.stdout))
        except EOFError:
            replies.put(Died('exited'))
        except (ValueError, OSError, struct.error, UnicodeDecodeError):
            replies.put(Died('protocol'))

    def _kill(self):
        """Kill and reap the child; nothing of it is left."""
        proc, job, self.proc, self.job, self.replies = self.proc, self.job, None, None, None
        if proc is None:
            return
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.wait(3)                                 # a killed process ends at once; never hold the job long
        except subprocess.TimeoutExpired:
            pass
        for stream in (proc.stdin, proc.stdout):
            try:
                stream.close()
            except OSError:
                pass
        _close_job(job)

    def _ensure(self, within):
        """A running child, started now if needed (waiting at most `within` seconds); StartFailed when it will not
        start or the kind is closing. Returns the seconds a start took (0 when the child was running)."""
        if self.closed:
            raise Closed()
        if self.proc is not None and self.proc.poll() is None:
            return 0.0
        self._kill()
        if self.failed_start_at is not None and time.monotonic() - self.failed_start_at < self.restart_wait:
            raise StartFailed('waiting before the next try')
        began = time.monotonic()
        try:
            self._spawn()
            reply = self.replies.get(timeout=max(0.1, min(self.start_seconds, within)))
        except queue.Empty:
            reply = StartFailed('not ready in time')
        except OSError as exc:
            reply = StartFailed(type(exc).__name__)
        if self.closed:                                  # closed while it started: it never runs
            self._kill()
            raise Closed()
        if isinstance(reply, tuple) and reply[0].get('ready'):
            self.failed_start_at = None
            return round(time.monotonic() - began, 3)
        self._kill()
        self.failed_start_at = time.monotonic()
        self.fault('start', 'start_failed')
        raise StartFailed(reply[0].get('error', 'not ready') if isinstance(reply, tuple) else str(reply))

    def start(self):
        """Start the child now (warm for the first job); a failure is kept for the next job to see."""
        with self.lock:
            try:
                self._ensure(self.start_seconds)
            except StartFailed:
                pass
        return self

    def start_in_background(self):
        threading.Thread(target=self.start, name='asuna-media-start-' + self.kind, daemon=True).start()
        return self

    def close(self):
        """Stop the kind now: a job that is running ends (its process is killed), no child starts again."""
        self.closed = True
        proc = self.proc
        if proc is not None:
            try:
                proc.kill()
            except OSError:
                pass
        if self.lock.acquire(blocking=False):            # no job running: reap here; else the job's thread reaps
            try:
                self._kill()
            finally:
                self.lock.release()

    # -- jobs -------------------------------------------------------------------------------------------------------
    def _once(self, header, payload, deadline, ends, times):
        times['started_s'] += self._ensure(ends - time.monotonic())
        limit = min(deadline, ends - time.monotonic())
        if limit <= 0:
            raise Timeout()
        proc, replies, fired = self.proc, self.replies, threading.Event()

        def expire():
            fired.set()
            try:
                proc.kill()
            except OSError:
                pass
        timer = threading.Timer(limit, expire)            # the deadline covers writing the job too
        timer.daemon = True
        timer.start()
        try:
            try:
                write_frame(proc.stdin, header, payload)
                reply = replies.get(timeout=limit + 1)
            except queue.Empty:
                reply = None
            except OSError:
                reply = Died('exited')
        finally:
            timer.cancel()
        if isinstance(reply, tuple):                     # an answer that came is kept, however late the timer
            pass
        elif self.closed:
            self._kill()
            raise Closed()
        elif fired.is_set() or reply is None:
            self._kill()
            self.fault('decode', 'deadline')
            raise Timeout()
        else:
            self._kill()
            self.fault('decode', str(reply))
            raise reply
        answer, data = reply
        if not answer.get('ok'):
            if answer.get('program'):
                self.fault('decode', 'program')
            raise JobError(str(answer.get('error') or ''), bool(answer.get('program')), str(answer.get('trace') or ''))
        return answer, data

    def call(self, header, payload=b'', deadline=60, budget=None):
        """One job: (answer header, payload). `budget` (seconds from now; default two deadlines) bounds the wait behind
        other jobs, a start and the tries. A timeout or a death is tried once more in a fresh child while the budget
        lasts; then Timeout or Died. StartFailed when the child will not start, Closed when the kind closed (the Host
        stops), JobError when the job could not be done. The answer carries `times`: waited_s, started_s, tries."""
        asked = time.monotonic()
        ends = asked + (budget if budget is not None else 2 * deadline)
        if not self.lock.acquire(timeout=max(0.0, ends - asked)):
            raise Timeout()                              # behind other jobs of this kind for the whole budget
        try:
            times = {'waited_s': round(time.monotonic() - asked, 3), 'started_s': 0.0, 'tries': 1}
            try:
                answer, data = self._once(header, payload, deadline, ends, times)
                return {**answer, 'times': times}, data
            except (Timeout, Died):
                if self.closed:
                    raise Closed()
                if ends - time.monotonic() <= 0:
                    raise
            times['tries'] = 2
            try:
                answer, data = self._once(header, payload, deadline, ends, times)
                return {**answer, 'times': times}, data
            finally:
                if self.proc is None and not self.closed:
                    self.start_in_background()           # warm for the next job
        finally:
            self.lock.release()


# ---- video --------------------------------------------------------------------------------------------------------
VIDEO = None                 # {'enabled', 'missing', 'child'} while the Host runs; None: decoded in this process


def video_missing():
    """The packages a contact sheet needs that are not installed."""
    return [name for name in VIDEO_PACKAGES if importlib.util.find_spec(name) is None]


def start_video(enabled=True, fault=None):
    """The Host's video side: off, not set up (one Host log line), or a child started in the background."""
    global VIDEO
    missing = video_missing() if enabled else []
    if missing:
        print('ASUNA_VIDEO_DECODER_UNAVAILABLE: %s not installed; videos read %s'
              % (', '.join(missing), VIDEO_NOT_SET_UP % '、'.join(missing)), file=sys.stderr, flush=True)
    child = Child('video', fault=fault).start_in_background() if enabled and not missing else None
    VIDEO = {'enabled': bool(enabled), 'missing': missing, 'child': child}
    return VIDEO


def stop_video():
    """The video side stops: a video asked for afterwards says the decoder is not running."""
    global VIDEO
    side = VIDEO
    VIDEO = {'enabled': True, 'missing': [], 'child': None}
    if side and side['child']:
        side['child'].close()


def video_snapshot(data):
    """(png bytes, words) for a video, or (None, {'error': words}): as `animated.video_snapshot`, cut in the video
    child while the Host runs (in this process only where no Host ever started one: tests and tools)."""
    from . import animated
    side = VIDEO
    if side is None:
        return animated.video_snapshot(data)
    if not side['enabled']:
        return None, {'error': VIDEO_OFF}
    if side['missing']:
        return None, {'error': VIDEO_NOT_SET_UP % '、'.join(side['missing'])}
    if side['child'] is None:
        return None, {'error': VIDEO_NOT_STARTED}
    try:
        answer, sheet = side['child'].call({'job': 'video'}, data, VIDEO_DEADLINE, VIDEO_BUDGET)
    except StartFailed:
        return None, {'error': VIDEO_NOT_STARTED}
    except Timeout:
        return None, {'error': VIDEO_TIMEOUT}
    except (Died, JobError):
        return None, {'error': VIDEO_CRASHED}
    return (sheet or None), answer.get('words') or {}
