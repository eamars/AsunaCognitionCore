"""Media children (ADR-095 §5.3.1): one job at a time with a deadline; a hung or dead child is killed, reaped and
replaced, the job tried once more; a child that will not start waits before the next try; no child outlives the Host.
Real child processes speak the frames; a scripted one stands in for the decoders."""
import os
import subprocess
import sys
import textwrap
import time

import pytest

import threading

from asuna import media_children
from asuna.media_children import Child, Died, JobError, StartFailed, Timeout

SRC = os.path.dirname(os.path.dirname(os.path.abspath(media_children.__file__)))
PYTHON = getattr(sys, '_base_executable', None) or sys.executable

SCRIPT = textwrap.dedent('''
    import os, sys, threading, time
    from asuna.media_children import read_frame, write_frame
    from asuna.media_worker import _watch          # the real worker's watch of its Host's pid
    threading.Thread(target=_watch, args=(os.getppid(),), daemon=True).start()
    out, inp = sys.stdout.buffer, sys.stdin.buffer
    mode, flag = sys.argv[1], sys.argv[2]
    if mode == 'fail-start':
        write_frame(out, {'ready': False, 'error': 'ImportError'}); sys.exit(1)
    if mode == 'silent-start':
        time.sleep(60)
    if mode == 'deaf-start':
        write_frame(out, {'ready': True, 'pid': os.getpid()}); time.sleep(60)
    write_frame(out, {'ready': True, 'pid': os.getpid()})
    while True:
        try:
            header, data = read_frame(inp)
        except EOFError:
            sys.exit(0)
        do = header.get('do')
        if do == 'hang-once' and not os.path.exists(flag):
            open(flag, 'w').close(); do = 'hang'
        if do == 'hang':
            time.sleep(60)
        elif do == 'exit':
            os._exit(3)
        elif do == 'garbage':
            out.write(b'not a frame at all'); out.flush(); time.sleep(60)
        elif do == 'error':
            write_frame(out, {'ok': False, 'error': 'the bytes are not audio'}); continue
        elif do == 'program-error':
            write_frame(out, {'ok': False, 'program': True, 'error': 'bad', 'trace': 'Traceback'}); continue
        elif do == 'deaf':
            time.sleep(60)
        write_frame(out, {'ok': True, 'pid': os.getpid()}, data)
''')


def alive(pid):
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.WinDLL('kernel32')
        handle = kernel.OpenProcess(0x1000, False, pid)             # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        kernel.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel.CloseHandle(handle)
        return code.value == 259                                  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def gone(pid, seconds=10):
    deadline = time.monotonic() + seconds
    while alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    return not alive(pid)


@pytest.fixture
def child(tmp_path):
    script = tmp_path / 'fake_child.py'
    script.write_text(SCRIPT, encoding='utf-8')
    made = []

    def make(mode='serve', **kwargs):
        faults = []
        c = Child('test', fault=lambda stage, error: faults.append((stage, error)),
                  command=[PYTHON, str(script), mode, str(tmp_path / 'flag')], **kwargs)
        c.faults = faults
        made.append(c)
        return c
    yield make
    for c in made:
        c.close()


def test_a_job_goes_out_and_comes_back_with_its_payload(child):
    c = child().start()
    answer, data = c.call({'do': 'echo'}, b'\x00\x01bytes', 5)
    assert data == b'\x00\x01bytes' and answer['ok'] and answer['times']['tries'] == 1
    assert answer['times']['waited_s'] >= 0 and answer['times']['started_s'] == 0
    assert c.call({'do': 'echo'}, b'', 5)[0]['pid'] == answer['pid'], 'the same warm child takes the next job'
    assert c.faults == []


def test_a_job_past_its_deadline_is_killed_and_tried_once_more_in_a_fresh_child(child):
    c = child().start()
    first = c.call({'do': 'echo'}, b'', 5)[0]['pid']
    answer, _ = c.call({'do': 'hang-once'}, b'', 1)
    assert answer['times']['tries'] == 2 and answer['times']['started_s'] > 0
    assert answer['pid'] != first and gone(first)
    assert c.faults == [('decode', 'deadline')]


def test_two_timeouts_raise_and_leave_no_process(child):
    c = child().start()
    pid = c.call({'do': 'echo'}, b'', 5)[0]['pid']
    with pytest.raises(Timeout):
        c.call({'do': 'hang'}, b'', 1)
    assert c.faults == [('decode', 'deadline')] * 2 and gone(pid)
    assert c.call({'do': 'echo'}, b'', 10)[0]['ok'], 'warm again for the next job'


def test_a_child_that_dies_or_answers_garbage_is_replaced_and_counted(child):
    c = child().start()
    with pytest.raises(Died):
        c.call({'do': 'exit'}, b'', 5)
    assert c.faults == [('decode', 'exited')] * 2
    c.faults.clear()
    with pytest.raises(Died):
        c.call({'do': 'garbage'}, b'', 5)
    assert c.faults == [('decode', 'protocol')] * 2


def test_a_jobs_own_content_error_keeps_the_child(child):
    c = child().start()
    pid = c.call({'do': 'echo'}, b'', 5)[0]['pid']
    with pytest.raises(JobError) as refused:
        c.call({'do': 'error'}, b'', 5)
    assert str(refused.value) == 'the bytes are not audio'
    assert c.call({'do': 'echo'}, b'', 5)[0]['pid'] == pid and c.faults == []


def test_a_child_that_will_not_start_waits_before_the_next_try(child):
    c = child('fail-start').start()
    assert c.faults == [('start', 'start_failed')] and c.proc is None
    with pytest.raises(StartFailed):
        c.call({'do': 'echo'}, b'', 5)
    assert c.faults == [('start', 'start_failed')], 'within the wait: not started again, not counted again'
    quick = child('silent-start', start_seconds=1, restart_wait=0).start()
    assert quick.faults == [('start', 'start_failed')] and quick.proc is None


def test_no_child_outlives_its_host(tmp_path):
    """A Host killed hard (no cleanup at all), its child in the middle of a hung job, takes the child with it: the
    worker's watch of its Host's pid on every system, and the job object on Windows as well."""
    script = tmp_path / 'fake_child.py'
    script.write_text(SCRIPT, encoding='utf-8')
    host = tmp_path / 'host.py'
    host.write_text(textwrap.dedent('''
        import sys, time
        from asuna.media_children import Child
        c = Child('test', command=[%r, %r, 'serve', %r]).start()
        print(c.call({'do': 'echo'}, b'', 10)[0]['pid'], flush=True)
        c.call({'do': 'hang'}, b'', 60)     # killed in the middle of a job: stdin closing alone would not end it
    ''' % (PYTHON, str(script), str(tmp_path / 'flag'))), encoding='utf-8')
    proc = subprocess.Popen([PYTHON, str(host)], stdout=subprocess.PIPE, text=True,
                            env={**os.environ, 'PYTHONPATH': SRC})
    try:
        pid = int(proc.stdout.readline())
        assert alive(pid)
        time.sleep(0.5)                      # the hanging job is in the child
        proc.kill()
        proc.wait(10)
        assert gone(pid), 'the child outlived its host'
    finally:
        proc.kill()


def test_video_side_says_off_and_not_set_up_in_its_own_words():
    try:
        media_children.VIDEO = {'enabled': False, 'missing': [], 'child': None}
        assert media_children.video_snapshot(b'x') == (None, {'error': media_children.VIDEO_OFF})
        media_children.VIDEO = {'enabled': True, 'missing': ['av'], 'child': None}
        assert media_children.video_snapshot(b'x') == (None, {'error': media_children.VIDEO_NOT_SET_UP % 'av'})
        media_children.stop_video()
        assert media_children.video_snapshot(b'x') == (None, {'error': media_children.VIDEO_NOT_STARTED}), \
            'after the Host stops it, never decoded in this process'
    finally:
        media_children.VIDEO = None


def test_a_real_video_child_cuts_the_contact_sheet():
    from test_media_life import a_video
    data = a_video()
    side = media_children.start_video(enabled=True)
    try:
        if side['missing']:
            pytest.skip('av or PIL not installed')
        sheet, words = media_children.video_snapshot(data)
        assert sheet and sheet[:8] == b'\x89PNG\r\n\x1a\n' and words.get('kind') == '视频快照'
        sheet, words = media_children.video_snapshot(b'\x00\x00\x00\x18ftypmp42 not really a video')
        assert sheet is None and words['error'].startswith('VIDEO_NOT_SPLIT')
    finally:
        media_children.stop_video()


def test_a_call_waits_behind_its_kind_only_within_its_budget(child):
    c = child().start()
    busy = threading.Thread(target=lambda: pytest.raises(Timeout, c.call, {'do': 'hang'}, b'', 3, 3))
    busy.start()
    time.sleep(0.5)
    began = time.monotonic()
    with pytest.raises(Timeout):
        c.call({'do': 'echo'}, b'', 5, budget=1)
    assert time.monotonic() - began < 2.5, 'gave up at its budget, not after the job ahead of it'
    busy.join(15)
    assert c.faults == [('decode', 'deadline')], 'waiting in line is not a fault of the child'


def test_one_kind_hung_does_not_hold_the_other(child):
    """Proof test 9: a hung voice child while a video is cut, and the other way round."""
    for hung, other in ((child(), child()), (child(), child())):
        hung.start(), other.start()
        stuck = threading.Thread(target=lambda: pytest.raises(Timeout, hung.call, {'do': 'hang'}, b'', 3, 3))
        stuck.start()
        time.sleep(0.3)
        began = time.monotonic()
        assert other.call({'do': 'echo'}, b'ok', 5)[1] == b'ok'
        assert time.monotonic() - began < 2
        stuck.join(15)


def test_close_ends_a_hung_job_at_once_and_starts_nothing_again(child):
    c = child().start()
    pid = c.call({'do': 'echo'}, b'', 5)[0]['pid']
    errors = []
    worker = threading.Thread(target=lambda: errors.append(pytest.raises(media_children.Closed, c.call, {'do': 'hang'},
                                                                           b'', 60)))
    worker.start()
    time.sleep(0.5)
    began = time.monotonic()
    c.close()
    worker.join(15)
    assert time.monotonic() - began < 5 and gone(pid) and c.proc is None and c.faults == []
    with pytest.raises(StartFailed):
        c.call({'do': 'echo'}, b'', 5)


def test_a_child_started_from_a_thread_that_ends_stays_warm(child):
    c = child()
    starter = threading.Thread(target=c.start)
    starter.start()
    starter.join(15)
    pid = c.proc.pid
    time.sleep(1.5)
    assert alive(pid) and c.call({'do': 'echo'}, b'', 5)[0]['ok'] and c.faults == []


def test_a_program_error_in_the_child_is_counted_and_told_apart(child):
    c = child().start()
    with pytest.raises(JobError) as failed:
        c.call({'do': 'program-error'}, b'', 5)
    assert failed.value.program and failed.value.trace == 'Traceback' and c.faults == [('decode', 'program')]


def test_a_child_that_stops_reading_is_killed_at_its_deadline(child):
    c = child('deaf-start').start()
    began = time.monotonic()
    with pytest.raises(Timeout):
        c.call({'do': 'echo'}, b'x' * (8 * 1024 * 1024), 1)        # more than a pipe holds: the write itself blocks
    assert time.monotonic() - began < 8 and c.faults == [('decode', 'deadline')] * 2
