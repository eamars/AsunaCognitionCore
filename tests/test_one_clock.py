"""The worker reads the time from one clock (asuna.clock), which never gives the same time twice in a process: what
decides by the latest or the oldest decides by the order of the writes, not by a tie."""
import re
import threading

from asuna import clock, repo_files, state
from asuna.config import ROOT

# The worker's code: the core, its record owners and store, and the channel kind modules it imports. A module that
# runs apart from the worker, in its own process, keeps its own clock; so does a database.
SOURCES = ('src/asuna', 'packages/channels')
WORKER = re.compile(r'^(src/asuna/(records/|store/)?[^/]+|packages/channels/[^/]+/python/.+)\.py$')
APART = {'src/asuna/clock.py',               # the clock itself
         'src/asuna/integration_image.py',   # a one-shot script inside the managed integration namespace
         'src/asuna/store/memory.py'}        # the in-memory database's own clock (its `Now`, as a server's)
READS = re.compile(rb'datetime\.(now|utcnow)\(|\btime\.time\(\)')


def test_the_worker_reads_the_time_only_from_its_one_clock():
    listed = [path for path in repo_files.files(ROOT, *SOURCES) if WORKER.match(path) and path not in APART]
    assert {'src/asuna/state.py', 'src/asuna/records/messages.py', 'src/asuna/store/words.py'} <= set(listed), \
        'the scan reached the core, its record owners and its store'
    found = ['%s:%d' % (path, n) for path in listed
             for n, line in enumerate((ROOT / path).read_bytes().splitlines(), 1) if READS.search(line)]
    assert not found, 'read the time with asuna.clock (clock.now(), clock.stamp()), not the system clock: %s' % found


def test_the_clock_never_gives_the_same_time_twice_even_from_many_threads():
    seen, lock = [], threading.Lock()

    def read():
        mine = [clock.now() for _ in range(2000)]
        with lock:
            seen.extend(mine)
    threads = [threading.Thread(target=read) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(set(seen)) == len(seen) == 8000 and all(moment.tzinfo for moment in seen)
    run = [clock.now() for _ in range(2000)]
    assert all(a < b for a, b in zip(run, run[1:]))


def test_a_stamp_keeps_its_microseconds_so_text_order_is_time_order():
    stamps = [state.now() for _ in range(2000)]
    assert all(len(s) == len('2026-10-28T02:48:12.139059+00:00') for s in stamps)
    assert stamps == sorted(stamps) and len(set(stamps)) == len(stamps)
