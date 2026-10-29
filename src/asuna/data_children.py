"""The action brain's history search and discussion digest, run in the data child (data_worker.py) while the Host
runs, so their work, however long, never holds the worker's interpreter lock and ends at its deadline.

- One child, supervised by `media_children.Child` (lane `data`): one job at a time, DEADLINE seconds a job, then the
  child is killed; a job waits at most LOCK_WAIT seconds behind another job or a start, a start takes at most
  START_SECONDS; one try. After a kill or a death the next job starts a fresh child within its own budget.
- What she reads when the job did not run to its end is a result carrying `error` (the tool's call closes FAILED with
  those words, tasks.failure_words): TIMEOUT past the deadline, BUSY behind another job or a start past its wait,
  UNAVAILABLE when the child will not start, has stopped with the Host, or died in the job.
- A refusal of a known class (`data_worker.refusal_class`) is raised here again with its class and words, as the
  tool raises it in the worker; any other error of the child's code is DataFault (and a lane fault), its traceback
  tail in the evidence (`host.data_program_error`).
- The job's evidence records come back with its answer and are recorded here.
- With no Host running (tools, offline checks, tests) the job runs in this process: DATA is None until `start`.
"""
from __future__ import annotations

import json

from . import data_worker
from .media_children import Busy, Child, Died, JobError, StartFailed, Timeout

DEADLINE = 30                # one job (history and digest measured at most 3.4 s)
LOCK_WAIT = 30               # behind another job or a start
START_SECONDS = 30
MODULE = 'asuna.data_worker'

TIMEOUT = 'QUERY_TIMEOUT: 这次查询超过 30 秒被停下了，没有结果；把范围收窄（时间窗、人、话题、limit）再试'
BUSY = 'QUERY_BUSY: 做查询的后台程序这会儿腾不出来，这次没有结果；过一会儿再试'
UNAVAILABLE = 'QUERY_UNAVAILABLE: 做这次查询的后台程序这会儿没起来，这次没有结果；过一会儿再试'

DATA = None                  # the data child while the Host runs; None: jobs run in this process


class DataFault(RuntimeError):
    """The data child's own code failed on a job (not the job's content)."""


def start(fault=None):
    """The Host's data child, started in the background (warm for the first job)."""
    global DATA
    DATA = Child('data', fault=fault, module=MODULE, tries=1, lock_wait=LOCK_WAIT,
                 start_seconds=START_SECONDS).start_in_background()
    return DATA


def stop():
    """The data child stops with the Host: a job asked for afterwards is UNAVAILABLE, never run in this process."""
    if DATA is not None:
        DATA.close()


def _raised(name, words):
    from .state import Conflict, Denied
    return {'Denied': Denied, 'Conflict': Conflict, 'PermissionError': PermissionError}.get(name, ValueError)(words)


def run(tool, task, args, config, database, evidence):
    """The tool's result for one call: in the data child while the Host runs, else in this process."""
    from . import channel_kinds
    job = json.dumps({'tool': tool, 'task': task, 'args': args, 'config': dict(config), 'database': database,
                      'channels': channel_kinds.loaded()}, ensure_ascii=False, default=str).encode('utf-8')
    child = DATA
    if child is None:
        services = data_worker.Services()
        try:
            _, payload = data_worker.answer(services, job)
        finally:
            services.close()
    else:
        try:
            _, payload = child.call({'job': tool}, job, DEADLINE, LOCK_WAIT + START_SECONDS + DEADLINE)
        except Busy:
            return {'error': BUSY}
        except Timeout:
            return {'error': TIMEOUT}
        except (StartFailed, Died):
            return {'error': UNAVAILABLE}
        except JobError as exc:
            evidence.record('host.data_program_error', {'tool': tool, 'error': str(exc)[:400], 'trace': exc.trace})
            raise DataFault(str(exc)) from None
    body = json.loads(payload.decode('utf-8'))
    for kind, record in body.get('evidence') or ():
        evidence.record(kind, record)
    if 'refused' in body:
        raise _raised(body['refused'], body['words'])
    return body['result']
