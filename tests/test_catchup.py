"""Catch-up after a gap (Xiaoman's handoff, 2026-10-08): the adapter fetches what she missed from the platform's
history and feeds it oldest first through the usual inbound path, marked as caught up; the host shows each line
at the time it was said, and an old @ or reply to her asks her through the relevance gate instead of waking her."""
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from asuna import attend
from asuna.caught_up import CATCHUP_KEY, said_at
from asuna.channels import group_context, kept_raw
from asuna.config import ROOT
from asuna.people import People
from test_people import BOT, GROUP, row, setup

ADAPTER = ROOT / 'packages' / 'channels' / 'napcat-qq' / 'integration'
sys.path[:0] = [str(ADAPTER), str(ADAPTER / 'vendor')]          # as adapter.py sets it up
from qqadapter import fixtures                                     # noqa: E402
from qqadapter.catchup import MAX_PAGES, PAGE, Catchup             # noqa: E402
from qqadapter.config import Config, ConfigError                   # noqa: E402
from qqadapter.journal import Counters                             # noqa: E402

NOW = 1_800_000_000
ACCOUNT = '900000000'


def history_row(seq, at, sender='900000101', group='900000001'):
    return {'post_type': 'message', 'message_type': 'group', 'self_id': int(ACCOUNT), 'group_id': int(group),
            'user_id': int(sender), 'sender': {'user_id': int(sender), 'nickname': 'n'}, 'message_id': seq,
            'message_seq': seq, 'time': at, 'message': [{'type': 'text', 'data': {'text': 'x%d' % seq}}]}


class History:
    """NapCat's history endpoint over one list of rows: a page from an anchor (inclusive, newer) or the newest."""

    def __init__(self, rows):
        self.rows, self.calls = sorted(rows, key=lambda r: r['message_seq']), []

    def api_call(self, action, params=None, timeout=15.0, meta=None):
        self.calls.append((action, dict(params)))
        if 'message_seq' in params:
            page = [r for r in self.rows if r['message_seq'] >= params['message_seq']][:params['count']]
        else:
            page = self.rows[-params['count']:]
        return {'status': 'ok', 'retcode': 0, 'data': {'messages': [dict(r) for r in page]}}


def catchup(tmp_path, api, routes=('group-900000001',), hours=6, every=False):
    route = SimpleNamespace(route_id='group-900000001', message_type='group', target_id='900000001')
    dm = SimpleNamespace(route_id='owner-dm', message_type='private', target_id='900000010')
    known = {r.route_id: r for r in (route, dm)}
    cfg = SimpleNamespace(routes=known, napcat={'account_id': ACCOUNT}, route_by_id=known.get,
                          catchup_routes=frozenset(routes), catchup_lookback_hours=hours, catchup_every=every)
    fed = []
    return Catchup(cfg, str(tmp_path), api, fed.append, Counters(), log=lambda _m: None, clock=lambda: NOW), fed


def test_the_owner_names_the_routes_and_nothing_runs_by_default():
    assert fixtures.load_config().catchup_routes == frozenset()
    raw = fixtures.raw_config()
    raw['adapter']['catchup'] = {'routes': [fixtures.DM_ROUTE], 'lookback_hours': 2}
    cfg = Config(raw, 'x')
    assert cfg.catchup_routes == {fixtures.DM_ROUTE} and cfg.catchup_lookback_hours == 2 and 'catchup=owner-dm/2h' in cfg.describe()
    raw['adapter']['catchup'] = {'routes': 'all'}
    assert len(Config(raw, 'x').catchup_routes) == 5
    raw['adapter']['catchup'] = {'routes': ['nope']}
    with pytest.raises(ConfigError, match='unknown routes nope'):
        Config(raw, 'x')
    raw['adapter']['catchup'] = {'routes': ['auto-group-900000077']}       # explicit admission: no automatic routes
    with pytest.raises(ConfigError, match='unknown routes auto-group-900000077'):
        Config(raw, 'x')
    auto = fixtures.raw_config(admission='automatic')
    auto['adapter']['catchup'] = {'routes': ['auto-group-900000077']}
    cfg = Config(auto, 'x')
    assert cfg.catchup_routes == {'auto-group-900000077'} and cfg.route_by_id('auto-group-900000077').target_id == '900000077'
    assert cfg.route_by_id('group-900000001').route_id == 'group-900000001' and cfg.route_by_id('auto-dm-x') is None
    raw['adapter']['catchup'] = {'routes': 'all', 'lookback_hours': 24}
    assert Config(raw, 'x').catchup_every and 'catchup=all/24h' in Config(raw, 'x').describe()
    raw['adapter']['catchup'] = {'routes': 'all', 'lookback_hours': 25}
    with pytest.raises(ConfigError, match='1..24'):
        Config(raw, 'x')


def test_from_the_cursor_forward_oldest_first_without_her_own_lines(tmp_path):
    rows = [history_row(100 + i, NOW - 3600 + i * 10) for i in range(250)]
    rows.append(history_row(500, NOW - 100, sender=ACCOUNT))                 # her own line
    api = History(rows)
    job, fed = catchup(tmp_path, api)
    job.note('group-900000001', history_row(150, NOW - 3600 + 500))          # the newest she had seen live
    totals = job.run('reconnect')
    seqs = [r['message_seq'] for r in fed]
    assert seqs == sorted(seqs) and seqs[0] == 150 and seqs[-1] == 349 and 500 not in seqs
    assert all(r[CATCHUP_KEY]['reason'] == 'reconnect' for r in fed) and totals['rows'] == len(fed)
    assert all(params['disable_get_url'] is True and params['count'] == PAGE for _, params in api.calls)
    assert api.calls[0][1]['message_seq'] == 150                            # paged forward from the cursor


def test_without_a_cursor_the_newest_page_inside_the_window(tmp_path):
    old = [history_row(i, NOW - 8 * 3600 + i) for i in range(10)]           # before the six-hour window
    new = [history_row(1000 + i, NOW - 600 + i) for i in range(5)]
    job, fed = catchup(tmp_path, History(old + new))
    job.run('startup')
    assert [r['message_seq'] for r in fed] == [1000, 1001, 1002, 1003, 1004]
    assert job.cursor('group-900000001') == {}                               # the inbound path moves the cursor


def test_a_route_not_named_is_never_fetched_and_cursors_survive_a_restart(tmp_path):
    api = History([history_row(1, NOW - 60)])
    job, fed = catchup(tmp_path, api, routes=())
    job.request('startup')
    assert not job._due.is_set()                                             # off: no run is even asked for
    job.note('owner-dm', {'time': NOW - 5, 'message_id': 77})
    job.flush(force=True)
    again, _ = catchup(tmp_path, api)
    assert again.cursor('owner-dm')['seq'] == 77 and not api.calls


def test_paging_stops_at_its_limit_says_so_and_keeps_the_newest_lines(tmp_path):
    rows = [history_row(i, NOW - 3000 + i) for i in range(PAGE * (MAX_PAGES + 2))]
    job, fed = catchup(tmp_path, History(rows))
    job.note('group-900000001', rows[0])
    job.run('startup')
    seqs = [r['message_seq'] for r in fed]
    assert job.counters.snapshot().get('catchup_truncated') == 1 and seqs == sorted(seqs)
    newest = [r['message_seq'] for r in rows[-PAGE:]]
    assert seqs[-PAGE:] == newest and seqs[0] == 0 and len(seqs) < len(rows)  # the lines just before now are there


def test_the_cursor_comes_first_however_old(tmp_path):
    rows = [history_row(100 + i, NOW - 30 * 3600 + i * 60) for i in range(50)]   # a gap of more than a day
    job, fed = catchup(tmp_path, History(rows))
    job.note('group-900000001', rows[10])
    job.run('reconnect')
    assert [r['message_seq'] for r in fed] == [r['message_seq'] for r in rows[10:]]


def test_a_run_waits_for_the_api_socket_and_asks_again_instead_of_failing_every_route(tmp_path):
    api = History([history_row(1, NOW - 60)])
    up = []
    api.wait_up = lambda path, timeout: bool(up)
    job, fed = catchup(tmp_path, api)
    job.note('group-900000001', history_row(1, NOW - 120))
    assert job.run('reconnect') is None and not api.calls and job._due.is_set()
    assert job.counters.snapshot().get('catchup_waiting_api') == 1 and not job.counters.snapshot().get('catchup_api_error')
    up.append(True)
    job._due.clear()
    assert job.run(job._reason)['routes'] == 1 and len(api.calls) == 1


def test_all_also_catches_up_every_route_with_a_cursor(tmp_path):
    api = History([history_row(1, NOW - 60)])
    job, fed = catchup(tmp_path, api, routes=(), every=True)
    job.note('group-900000001', history_row(1, NOW - 120))
    job.note('auto-group-123456', {'time': NOW - 100, 'message_id': 5})         # no longer admitted: skipped
    job.request('startup')
    assert job._due.is_set()
    job.run('startup')
    assert [params.get('group_id') for _, params in api.calls] == [900000001]


def test_the_host_keeps_the_mark_and_shows_when_it_was_said(store):
    scene = setup(store)
    kept = kept_raw({'scene_id': scene['_id'], 'channel': {}}, {CATCHUP_KEY: {'reason': 'reconnect',
                    'fetched_at': '2026-10-08T00:00:00Z', 'age_seconds': 4000, 'extra': 'x' * 900}})
    assert kept[CATCHUP_KEY] == {'reason': 'reconnect', 'fetched_at': '2026-10-08T00:00:00Z'}
    late = row(20002, '还在吗', at='2026-10-04T03:00:00+00:00')
    late['occurred_at'] = '2026-10-04T01:00:00Z'
    late['event']['raw'][CATCHUP_KEY] = {'reason': 'reconnect', 'fetched_at': ''}
    assert said_at(late) == '2026-10-04T01:00:00Z'
    head = People(store).transcript(scene, late).split('\n')[0]
    from asuna.schedule_rules import line_stamp, scene_timezone
    assert head.endswith(line_stamp(scene_timezone(store.config, scene), '2026-10-04T01:00:00Z') + '（补读）')


def test_an_old_at_of_her_asks_first_a_fresh_one_still_wakes(store):
    scene = setup(store)
    route = {'scene_id': scene['_id'], 'target': {'type': 'group', 'id': GROUP}}
    old = (datetime.now(timezone.utc) - timedelta(minutes=40)).strftime('%Y-%m-%dT%H:%M:%SZ')
    fresh = (datetime.now(timezone.utc) - timedelta(minutes=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
    mark = {CATCHUP_KEY: {'reason': 'reconnect', 'fetched_at': ''}}
    body = lambda at, raw: {'account_id': BOT, 'mentioned_account_ids': [BOT], 'text': '@她', 'raw': raw, 'occurred_at': at}
    assert group_context(store, route, body(old, mark), 'e1')['wake_reason'] == 'catchup_mention'
    assert group_context(store, route, body(fresh, mark), 'e2')['wake_reason'] == 'mentioned_account'
    assert group_context(store, route, body(old, {}), 'e3')['wake_reason'] == 'mentioned_account'
    assert 'catchup_mention' in attend.GATED
