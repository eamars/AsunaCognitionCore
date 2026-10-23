"""The child process of one media kind (media_children.py): `python -P -m asuna.media_worker voice <host pid> <model
directory>` or `... video <host pid>`. It loads its decoder, says it is ready, then answers one job at a time on stdout
in media_children's frames. stdout carries frames only; anything else the libraries print goes to stderr.

- voice: a voice's bytes and their container -> the detector's pieces, decoded on their own (voice.SenseVoice), with
  the time each stage took. A voice that cannot be decoded answers its reason in words.
- video: a video's bytes -> its contact sheet (animated.video_snapshot) and its words.
- An error of the child's own code (not of the job's content) is answered with `program` and the traceback's tail.
- It exits when its stdin closes or its Host's pid is gone, even in the middle of a job (on Windows the Host's job
  object kills it as well).
"""
from __future__ import annotations

import os
import sys
import threading
import time
import traceback

from .media_children import read_frame, write_frame

TRACE_CHARS = 800


def _voice(directory):
    from . import voice
    engine = voice.SenseVoice(directory)
    engine._load()

    def job(header, data):
        started = time.monotonic()
        try:
            samples = voice.pcm16(data, header.get('container'))
        except voice.VoiceError as exc:
            return {'ok': False, 'error': str(exc)}, b''
        if not len(samples):
            return {'ok': False, 'error': '音频是空的'}, b''
        decoded = time.monotonic()
        result = engine.transcribe(samples.astype('float32') / 32768.0)
        done = time.monotonic()
        return {'ok': True, 'samples': int(len(samples)), 'result': result,
                'stages': {'decode_s': round(decoded - started, 3), 'transcribe_s': round(done - decoded, 3)}}, b''
    return job


def _video():
    import av  # noqa: F401  the decoder, loaded before the first job
    from . import animated

    def job(header, data):
        sheet, words = animated.video_snapshot(data)
        return {'ok': True, 'words': words}, sheet or b''
    return job


def _alive(pid):
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.WinDLL('kernel32')
        handle = kernel.OpenProcess(0x1000, False, pid)            # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        kernel.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel.CloseHandle(handle)
        return code.value == 259                                 # STILL_ACTIVE
    return os.getppid() == pid


def _watch(pid):
    """Exit at once when the Host is gone, whatever the job is doing."""
    while _alive(pid):
        time.sleep(1)
    os._exit(0)


def main(argv):
    out, inp = sys.stdout.buffer, sys.stdin.buffer
    sys.stdout = sys.stderr                       # a stray print never lands between frames
    kind = argv[0] if argv else ''
    try:
        host = int(argv[1])
        threading.Thread(target=_watch, args=(host,), name='host-watch', daemon=True).start()
        job = _voice(argv[2]) if kind == 'voice' else _video() if kind == 'video' else None
        if job is None:
            raise ValueError('unknown kind')
    except Exception as exc:                      # noqa: BLE001 the Host is told it did not start, with the class
        write_frame(out, {'ready': False, 'error': type(exc).__name__})
        return 1
    write_frame(out, {'ready': True, 'pid': os.getpid()})
    while True:
        try:
            header, data = read_frame(inp)
        except EOFError:
            return 0
        try:
            answer, payload = job(header, data)
        except Exception as exc:                  # noqa: BLE001 a fault of this program, with its class and trace
            answer, payload = {'ok': False, 'program': True, 'error': '识别程序出错（%s）' % type(exc).__name__,
                               'trace': traceback.format_exc()[-TRACE_CHARS:]}, b''
        write_frame(out, answer, payload)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
