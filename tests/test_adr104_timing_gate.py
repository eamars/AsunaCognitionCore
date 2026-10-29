"""The batch check's timing gate (tools/adr104_equivalence.py): a read case whose new p50 is more than twice its old
and more than 5 ms above it fails the run, unless the lead accepted it; a watched or accepted case is reported, not
passed silently; a stopped query is TIMED OUT or UNREACHABLE by what stopped it. Synthetic timings only: nothing
here reaches a database server (the words' case reads the stand-in)."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def check():
    spec = importlib.util.spec_from_file_location('adr104_equivalence', ROOT / 'tools' / 'adr104_equivalence.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def timed(old, new):
    return {'ms_old_p50': old, 'ms_new_p50': new, 'plan_new': ['LIMIT', 'COLLSCAN'], 'differing': 0,
            'plans_differ': 0}


def test_a_case_twice_as_slow_and_more_than_five_ms_slower_fails(check):
    cases = {'who wrote here': timed(9, 293), 'ratio only': timed(2, 6.5), 'ms only': timed(40, 60),
             'just under twice': timed(12, 19), 'twice and six ms': timed(6, 12.1), 'no times': timed(None, None)}
    failing, accepted = check.slowdowns('b4', cases)
    assert [name for name, *_ in failing] == ['who wrote here', 'twice and six ms'] and accepted == []
    assert failing[0] == ('who wrote here', 9, 293, ['LIMIT', 'COLLSCAN']), 'named with both times and the new plan'


def test_a_case_timed_again_is_decided_by_its_second_timing(check):
    """Jitter on a read of a few ms passes when timed again; a read slower on every run still fails."""
    jitter = {**timed(7, 25), 'confirm': {'runs': 10, 'ms_old_p50': 1.1, 'ms_new_p50': 1.2}}
    slow = {**timed(9, 293), 'confirm': {'runs': 10, 'ms_old_p50': 9, 'ms_new_p50': 280}}
    unconfirmed = {**timed(9, 293), 'confirm': {'runs': 0, 'why': 'over the query budget: not timed again'}}
    failing, _ = check.slowdowns('b5', {'jitter': jitter, 'slow': slow, 'unconfirmed': unconfirmed})
    assert [(name, old, new) for name, old, new, _ in failing] == [('slow', 9, 280), ('unconfirmed', 9, 293)]


def test_an_accepted_slowdown_is_reported_apart_and_does_not_fail_the_run(check, monkeypatch):
    monkeypatch.setattr(check, 'ACCEPTED_SLOWDOWNS', {'b5': {'slow': {
        'old_ms': 3, 'new_ms': 30, 'reason': 'synthetic', 'recheck': 'never: a test'}}})
    cases = {'slow': timed(3, 30)}
    assert check.slowdowns('b5', cases) == ([], [('slow', 3, 30, ['LIMIT', 'COLLSCAN'])])
    assert [name for name, *_ in check.slowdowns('b4', cases)[0]] == ['slow'], 'accepted for its batch only'


def test_the_run_is_not_clean_while_a_case_is_slower_past_the_gate(check):
    totals, validators = {'create': 0, 'make': 0, 'conflicts': 0}, {'same': 1}
    reads = {'fast': timed(5, 6), 'slow': timed(5, 40)}
    report = {'fields_differ': [], 'reads': reads}
    report['slowdowns'] = dict(zip(('failing', 'accepted'), check.slowdowns('b5', reads)))
    assert not check.clean(report, totals, validators)
    del reads['slow']
    report['slowdowns'] = dict(zip(('failing', 'accepted'), check.slowdowns('b5', reads)))
    assert check.clean(report, totals, validators)


def test_every_accepted_or_watched_entry_says_why_and_when_it_is_looked_at_again(check):
    for batch in check.ACCEPTED_PLAN_DIFFERENCES.values():
        assert all(entry['reason'] and entry['recheck'] for entry in batch.values())
    for batch in check.ACCEPTED_SLOWDOWNS.values():
        assert all({'old_ms', 'new_ms', 'reason', 'recheck'} <= set(entry) for entry in batch.values())
    assert check.WATCHED['b4']['who wrote in these']['family'] == 'who wrote here'


def test_a_read_over_its_limit_is_timed_out_with_the_limit_and_a_server_out_of_reach_is_unreachable(
        check, monkeypatch, tmp_path, capsys):
    """The check's words for a stopped query: a query its time limit stopped (the server's MaxTimeMSExpired, the
    client's socket timeout) is TIMED OUT, named with where it was and the limit; UNREACHABLE is only a server that
    cannot be reached. On the stand-in, which holds no time limit of its own, so the limit's errors are raised by the
    read itself, as pymongo raises them."""
    from pymongo import MongoClient
    from pymongo.errors import ExecutionTimeout, NetworkTimeout, OperationFailure, ServerSelectionTimeoutError
    client = MongoClient('mongodb://unit-run.invalid:27017/')
    assert getattr(client, 'unit_run', False), 'the stand-in, never a server'
    database = 'asuna_v2_test_timeout_words'
    client[database]['scenes'].insert_one({'_id': 'scene-a', 'kind': 'dm'})

    def over(param):
        raise ExecutionTimeout('operation exceeded time limit', 50)
    cases = [('stopped at its limit', lambda param: ('find_one', 'scenes', {'_id': param}, None, None), over,
              ['scene-a'], 'value')]
    monkeypatch.setattr(check, '_cases_b5', lambda store, config: (cases, 1))
    try:
        found, _ = check.reads(client, database, 50, 'b5', {})
    finally:
        client.drop_database(database)
    assert found['stopped at its limit']['timed_out'] == {'limit_ms': 50, 'error': 'ExecutionTimeout'}
    totals, validators = {'create': 0, 'make': 0, 'conflicts': 0}, {'same': 1}
    assert not check.clean({'fields_differ': [], 'reads': found}, totals, validators)

    def stopped(error):
        def dry_run(adapter):
            raise error
        monkeypatch.setattr(check, 'dry_run', dry_run)
        settings = {'mongo_uri': 'mongodb://unit-run.invalid:27017/'}
        assert check.check('b3', settings, database, tmp_path, 75) == 2
        report = json.loads((tmp_path / 'b3.json').read_text(encoding='utf-8'))
        assert report['max_ms'] == 75, 'the report holds the limit the run used'
        return capsys.readouterr().out.splitlines()[0], report['stopped']

    said, stop = stopped(NetworkTimeout('unit-run.invalid:27017: timed out (configured timeouts: socketTimeoutMS)'))
    assert said == 'TIMED OUT: ensure, dry run: a query stopped at its limit of 75 ms (NetworkTimeout)'
    assert stop == {'during': 'ensure, dry run', 'error': 'NetworkTimeout', 'timed_out': True}
    said, stop = stopped(ExecutionTimeout('operation exceeded time limit', 50))
    assert said.startswith('TIMED OUT: ensure, dry run: ') and '75 ms' in said
    said, stop = stopped(ServerSelectionTimeoutError('unit-run.invalid:27017: getaddrinfo failed'))
    assert said == 'ADR104_CHECK_UNREACHABLE: ServerSelectionTimeoutError (during ensure, dry run)'
    assert stop['timed_out'] is False
    said, _ = stopped(OperationFailure('not authorized', 13))
    assert said == 'ADR104_CHECK_FAILED: OperationFailure (during ensure, dry run)', 'neither a time limit nor reach'


def test_the_run_is_not_clean_while_the_whole_search_differs(check):
    """B7's own proof: a search whose final six or 24 vector candidates differ, old against new, fails the run."""
    totals, validators = {'create': 0, 'make': 0, 'conflicts': 0}, {'same': 1}
    report = {'fields_differ': [], 'reads': {}, 'slowdowns': {'failing': [], 'accepted': []},
              'search': {'queries': 40, 'differing': 1}}
    assert not check.clean(report, totals, validators)
    report['search']['differing'] = 0
    assert check.clean(report, totals, validators)
