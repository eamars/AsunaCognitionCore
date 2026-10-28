"""The batch check's timing gate (tools/adr104_equivalence.py): a read case whose new p50 is more than twice its old
and more than 5 ms above it fails the run, unless the lead accepted it; a watched or accepted case is reported, not
passed silently. Synthetic timings only: nothing here reaches a database."""
import importlib.util
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


def test_the_run_is_not_clean_while_the_whole_search_differs(check):
    """B7's own proof: a search whose final six or 24 vector candidates differ, old against new, fails the run."""
    totals, validators = {'create': 0, 'make': 0, 'conflicts': 0}, {'same': 1}
    report = {'fields_differ': [], 'reads': {}, 'slowdowns': {'failing': [], 'accepted': []},
              'search': {'queries': 40, 'differing': 1}}
    assert not check.clean(report, totals, validators)
    report['search']['differing'] = 0
    assert check.clean(report, totals, validators)
