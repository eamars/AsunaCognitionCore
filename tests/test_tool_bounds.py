"""Tool bodies and the worker's locks: a persona job runs without the effects lock and is checked again after it, and
two static guards keep it so (nothing but the data child's job runs history or the digest; persona_job_run is never
under the effects lock in ToolBroker.call)."""
import ast
from pathlib import Path

import pytest

from asuna import tasks
from asuna.records import tasks as task_records
from asuna.state import Denied
from test_data_child import Recorded, seeded

SRC = Path(tasks.__file__).resolve().parent


def test_a_persona_job_runs_without_the_effects_lock_and_is_checked_after_it(world, tmp_path):
    task = seeded(world)
    task = task_records.save(
        world, {**task, 'development_grant': True, 'allowed_capabilities': ['persona_job_run']},
        expected=task['revision'], stream=task['_id'])
    broker = tasks.ToolBroker(tasks.TaskService(world), Recorded())
    broker.bindings['session'] = (task, type('Sandbox', (), {'task_dir': tmp_path, 'protected_paths': []})())
    held = []

    def job(task_row, args):
        held.append(broker.service.lock.holder)
        if args.get('cancel'):
            current = task_records.get(world, task_row['_id'])
            task_records.save(
                world, {**current, 'state': 'CANCELLED'}, expected=current['revision'], stream=task_row['_id'])
        return {'status': 'done'}
    broker.persona_jobs = job
    assert broker.call('session', 'call-1', 'persona_job_run', {'job': 'x'})['status'] == 'done'
    with pytest.raises(Denied, match='STALE_TASK_FENCE'):
        broker.call('session', 'call-2', 'persona_job_run', {'job': 'x', 'cancel': True})
    assert held == [None, None], 'no thread held the effects lock while the job ran'


def test_only_the_data_childs_job_runs_history_or_the_digest():
    called = []
    for path in sorted(SRC.rglob('*.py')):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ('query_for_task', 'digest_for_task')):
                called.append((path.relative_to(SRC).as_posix(), node.func.attr))
    assert sorted(called) == [('data_worker.py', 'digest_for_task'), ('data_worker.py', 'query_for_task')], called


def test_persona_job_run_is_never_under_the_effects_lock_in_the_broker():
    source = (SRC / 'tasks.py').read_text(encoding='utf-8')
    call = next(node for node in ast.walk(ast.parse(source))
                if isinstance(node, ast.FunctionDef) and node.name == 'call'
                and 'self.service.lock' in ast.get_source_segment(source, node))
    chosen = [item.context_expr for node in ast.walk(call) if isinstance(node, ast.With) for item in node.items
              if isinstance(item.context_expr, ast.IfExp)
              and ast.get_source_segment(source, item.context_expr.orelse) == 'self.service.lock']
    assert len(chosen) == 1, 'the one place a body chooses whether it holds the effects lock'
    unlocked = eval(compile(ast.Expression(chosen[0].test), 'tasks.py', 'eval'),
                    {**vars(tasks), 'tool': 'persona_job_run'})
    assert unlocked, 'persona_job_run runs its body under the effects lock'
