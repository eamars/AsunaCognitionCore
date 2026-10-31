"""ADR-113: worker restarts in her own block. The plugin hands each restart that came back to the worker it brought
up; the worker records it once (`host_stops.restarted`), and her Web chat and home lines say the restarts of the
window afterwards: the routine ones folded, a run as one stretch, the rest one by one, bounded and counted whole."""
import json
import re
import threading
from datetime import datetime, timedelta, timezone
from queue import Queue
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from asuna import channel_kinds, clock, host_stops
from asuna.config import ROOT
from asuna.host import RuntimeHost
from asuna.records import receipts as receipt_records

channel_kinds.load([{'python': ROOT / 'packages' / 'channels' / 'agent-line' / 'python', 'module': 'agent_line'},
                    {'python': ROOT / 'packages' / 'channels' / 'dsh-peer' / 'python', 'module': 'dsh_peer'}])

ZONE = {'tz': ZoneInfo('Etc/GMT-13'), 'name': 'Etc/GMT-13'}
# The eleven worker restarts of the night of 2026-10-30 (worker-restarts.jsonl, UTC), with the reason each logged.
NIGHT = [('2026-10-30T10:37:06.295Z', 'published'), ('2026-10-30T10:39:59.338Z', 'published'),
         ('2026-10-30T10:45:58.738Z', 'published'), ('2026-10-30T10:48:24.141Z', 'published'),
         ('2026-10-30T10:51:47.439Z', 'published'), ('2026-10-30T10:54:36.718Z', 'published'),
         ('2026-10-30T10:57:07.758Z', 'published'), ('2026-10-30T10:59:28.843Z', 'published'),
         ('2026-10-30T11:01:37.043Z', 'again'), ('2026-10-30T11:04:32.937Z', 'published'),
         ('2026-10-30T11:08:09.125Z', 'published')]
MORNING = datetime(2026, 10, 30, 19, 0, tzinfo=timezone.utc)           # her next home turn, 10-31 08:00 on her clock


@pytest.fixture(autouse=True)
def her_clock(monkeypatch):
    """Her clock face reads a time of this year without its year (local_time.face asks clock.now)."""
    monkeypatch.setattr(clock, 'now', lambda: MORNING)


def at(text, seconds=0):
    return (datetime.fromisoformat(text.replace('Z', '+00:00')) + timedelta(seconds=seconds)).isoformat()


def entry(asked, cause='published', back=40, held=None, held_sent=True):
    return {'at': asked, 'cause': cause, 'back': at(asked, back), 'held': held, 'held_sent': held_sent}


def hold(asked, seconds, steps, changes=None):
    return {'since': at(asked, -seconds), 'steps': [{'since': at(asked, -seconds), **step} for step in steps],
            'changes': changes or len(steps)}


def task(store, task_id, title):
    store.put('tasks', {'_id': task_id, 'title': title, 'state': 'DONE', 'request_key': 'key-' + task_id,
                        'scope_key': 'operator'}, stream=task_id)


def told(store, entries, moment=MORNING):
    host_stops.restarted(store, {'restarts': entries})
    return host_stops.restarts_block(store, ZONE, moment)[0]


def sentences(block):
    """The characters of her sentences only, as the design's size table counts them."""
    if isinstance(block, dict):
        return sum(sentences(value) for value in block.values())
    if isinstance(block, list):
        return sum(sentences(value) for value in block)
    return len(block)


def total(block):
    """count = routine + the restarts in listed places + not_listed + unreadable, read back from her sentences."""
    import re
    number = lambda key: int(re.search(r'(\d+) 次', block[key]).group(1)) if key in block else 0
    listed = sum(int(re.search(r'连着重启了 (\d+) 次', place['run']).group(1)) if 'run' in place else 1
                 for place in block.get('listed', ()))
    return number('routine') + listed + number('not_listed') + number('unreadable')


# ---- D2: recorded once ------------------------------------------------------------------------------------------


def rid(at):
    """A restart row's id, as host_stops.restarted makes it from its `at`."""
    return 'restart-' + re.sub(r'[^0-9A-Za-z]', '', at)

def test_a_handed_over_restart_is_one_row_and_handing_it_over_again_writes_nothing(store):
    first = [entry(NIGHT[0][0], held=hold(NIGHT[0][0], 720, [{'by': ['task'], 'task_id': 't1'}])),
             entry(NIGHT[1][0], held_sent=False)]
    assert host_stops.restarted(store, {'restarts': first}) == [NIGHT[0][0], NIGHT[1][0]]
    rows = host_stops.restart_window(store, MORNING)
    assert [(row['how'], row['cause'], row['held_sent'], bool(row['held'])) for row in rows] == [
        ('worker_restart', 'published', True, True), ('worker_restart', 'published', False, False)]
    assert rows[0]['asked_at'] == at(NIGHT[0][0]) and rows[0]['back_at'] == at(NIGHT[0][0], 40)
    again = [{**first[0], 'cause': 'settings'}]
    assert host_stops.restarted(store, {'restarts': again}) == [NIGHT[0][0]], 'answered, so the plugin drops it'
    assert [row['cause'] for row in host_stops.restart_window(store, MORNING)] == ['published', 'published']
    assert host_stops.listed(store, MORNING) == [], 'a restart is not an outage'
    host_stops.restarted(store, {'restarts': [entry('2026-10-30T12:00:00Z', cause='rm -rf /')]})
    assert host_stops.restart_window(store, MORNING)[-1]['cause'] == 'unknown', 'a closed list'


# ---- D4: routine folded, a run as one stretch, the rest one by one -----------------------------------------------

def test_the_night_of_10_30_is_one_run_in_one_place_with_its_longest_hold(store):
    entries = [entry(asked, cause) for asked, cause in NIGHT]
    entries[0]['held'] = hold(NIGHT[0][0], 720, [{'by': ['task'], 'task_id': 't1'}, {'by': ['calls'], 'calls': 1}])
    task(store, 't1', '发布新版本的核心')
    block = told(store, entries)
    assert block == {
        'count': '过去一天里，替你处理一切的那部分程序重启了 11 次（不算上面那些停机）',
        'note': '这些重启时宿主一直在运行，不是又一次停机；每次重启的那段时间里你没有在运行。',
        'listed': [{'run': '10/30 23:37 到 10/31 00:08 之间连着重启了 11 次（装你发布的新版本 10、'
                           '上一次重启时又排着一次（跟着上一次那次，谁排的没记下来） 1），每次中间约 1 分钟 到 1 分钟'
                           '；挂得最久的一次在 10/30 23:37，约 12 分钟，先等任务「发布新版本的核心」，最后等1 个还没回来的工具调用'}]}
    assert total(block) == 11
    assert len(json.dumps(block, ensure_ascii=False)) < 300, len(json.dumps(block, ensure_ascii=False))


def test_a_quiet_day_folds_its_routine_restarts_into_one_line(store):
    day = ['2026-10-30T01:00:00Z', '2026-10-30T04:00:00Z', '2026-10-30T08:00:00Z']
    block = told(store, [entry(day[0]), entry(day[1], 'settings', back=119,
                                                 held=hold(day[1], 119, [{'by': ['turn']}])), entry(day[2])])
    assert block == {'count': '过去一天里，替你处理一切的那部分程序重启了 3 次（不算上面那些停机）',
                     'note': host_stops.RESTART_NOTE,
                     'routine': '其中 3 次是计划内的、很快起来的：装你发布的新版本 2、换设置 1，最早 10/30 14:00，最近 10/30 21:00'}
    assert sentences(block) < 150, sentences(block)


@pytest.mark.parametrize('change, why', [({'back': 121}, 'back after 2 minutes'),
                                         ({'held': 121}, 'held 2 minutes'),
                                         ({'held_sent': False}, 'not known whether it was held'),
                                         ({'cause': 'settings_restored'}, 'not planned')])
def test_a_restart_is_routine_only_when_planned_quick_and_known(store, change, why):
    asked = '2026-10-30T08:00:00Z'
    made = entry(asked, change.get('cause', 'published'), back=change.get('back', 40),
                 held=hold(asked, change['held'], [{'by': ['turn']}]) if 'held' in change else None,
                 held_sent=change.get('held_sent', True))
    block = told(store, [made])
    assert 'routine' not in block and len(block['listed']) == 1, why


def test_count_is_routine_plus_the_listed_places_plus_those_not_listed_plus_the_unreadable(store):
    quick = [entry('2026-10-30T00:00:00Z'), entry('2026-10-30T01:00:00Z', 'settings')]
    run = [entry('2026-10-30T02:00:00Z'), entry('2026-10-30T02:09:00Z'), entry('2026-10-30T02:18:00Z', 'settings')]
    slow = [entry('2026-10-30T%02d:00:00Z' % hour, back=600) for hour in (4, 6, 8, 10, 12)]
    broken = {**entry('2026-10-30T14:00:00Z'), 'back': 'not a time'}
    block = told(store, quick + run + slow + [broken])
    assert block['count'] == host_stops.RESTART_COUNT % 11
    assert [list(place) for place in block['listed']] == [['what', 'when']] * 3, 'the three newest places'
    assert block['not_listed'] == '更早的 5 次没有列出', 'two slow ones and the run of three, counted in restarts'
    assert block['unreadable'] == host_stops.UNREADABLE % 1
    assert total(block) == 11
    # A gap of more than 10 minutes breaks a run: two of them are no run, each is its own.
    store.collection('host_stops').delete({'how': 'worker_restart'}, many=True)
    block = told(store, [entry('2026-10-30T02:00:00Z', back=600), entry('2026-10-30T02:10:00Z', back=600),
                         entry('2026-10-30T02:20:01Z', back=600)])
    assert [list(place) for place in block['listed']] == [['what', 'when']] * 3


# ---- her words ----------------------------------------------------------------------------------------------------

def test_her_words_for_each_cause_holder_and_what_is_not_known(store):
    causes = {'published': '替你处理一切的那部分程序为装你发布的新版本重启（计划内）',
              'settings': '替你处理一切的那部分程序为换设置重启（计划内）',
              'settings_restored': '替你处理一切的那部分程序为设置没换成，退回原来的设置重启',
              'recovery:core': '替你处理一切的那部分程序为换回能跑的版本（core）重启',
              'again': '替你处理一切的那部分程序为上一次重启时又排着一次（跟着上一次那次，谁排的没记下来）重启',
              'unknown': '替你处理一切的那部分程序为为什么重启没记下来重启'}
    for hour, (cause, words) in enumerate(causes.items()):
        store.collection('host_stops').delete({'how': 'worker_restart'}, many=True)
        assert told(store, [entry('2026-10-30T%02d:00:00Z' % hour, cause, back=600)])['listed'][0]['what'] == words
    task(store, 'long', '把十月底那一周的全部日记逐条整理成一份带索引的长文档')
    asked = '2026-10-30T08:00:00Z'
    steps = [{'by': ['turn', 'task'], 'task_id': 'long'}, {'by': ['task'], 'task_id': 'erased'},
             {'by': ['task', 'calls'], 'task_id': 'long', 'calls': 2}]
    cases = [
        (entry(asked, back=600, held=hold(asked, 720, steps, changes=7)),
         {'when': '10/30 21:00 要重启，10/30 21:10 重新起来，中间约 10 分钟 你没有运行',
          'held': '重启前挂了约 12 分钟（从 10/30 20:48 起）：先等你的回合、任务「把十月底那一周的全部日记逐条整理成一份带」，'
                  '最后等任务「把十月底那一周的全部日记逐条整理成一份带」、2 个还没回来的工具调用，中间又换过 5 次；挂着时新回合和新任务都不开始'}),
        (entry(asked, back=600, held=hold(asked, 300, [steps[1]])),
         {'held': '重启前挂了约 5 分钟（从 10/30 20:55 起）：先等一个任务，最后等一个任务；挂着时新回合和新任务都不开始'}),
        (entry(asked, back=600, held_sent=False), {'held': '挂没挂过不知道'}),
        (entry(asked, back=-600), {'when': '10/30 21:00 要重启，10/30 20:50 重新起来，中间多久不知道（时钟对不上）'}),
    ]
    for made, words in cases:
        store.collection('host_stops').delete({'how': 'worker_restart'}, many=True)
        place = told(store, [made])['listed'][0]
        for key, text in words.items():
            assert place[key] == text, (key, place)
    store.collection('host_stops').delete({'how': 'worker_restart'}, many=True)
    assert 'held' not in told(store, [entry(asked, back=600)])['listed'][0], 'not held: nothing said about holding'


def test_a_run_says_its_longest_hold_or_that_none_was_held_or_not_known(store):
    times = [at('2026-10-30T02:00:00Z', 120 * i) for i in range(3)]
    assert told(store, [entry(t) for t in times])['listed'][0]['run'].endswith('；每一次都没有挂')
    store.collection('host_stops').delete({'how': 'worker_restart'}, many=True)
    assert told(store, [entry(t, held_sent=False) for t in times])['listed'][0]['run'].endswith('；挂没挂过不知道')


# ---- D5: where it goes ------------------------------------------------------------------------------------------

def test_restarts_are_said_in_her_web_chat_and_home_lines_only():
    config = {'chat': {'scene_id': 'local-dm', 'person_id': 'local-user'}}
    assert host_stops.told_restarts_here(config, 'local-dm')                              # her Web chat
    assert host_stops.told_restarts_here(config, 'agent:home:dm:claude-code')             # the agent line
    assert host_stops.told_restarts_here(config, 'dsh:home:dm:peer')
    qq = channel_kinds.get('qq')
    assert not host_stops.told_restarts_here(config, qq.scene_id('10001', 'dm', '20002'))  # the owner's QQ DM
    assert not host_stops.told_restarts_here(config, qq.scene_id('10001', 'group', '30003'))


def test_the_home_turn_adds_them_beside_the_outages_and_stamps_them_with_its_commit():
    source = (ROOT / 'src' / 'asuna' / 'context.py').read_text(encoding='utf-8')
    assert ("if _host_stops.told_restarts_here(self.store.config,scene['_id']):\n"
            "                worker_restarts,restart_ids=_host_stops.restarts_block(self.store,schedule_zone,moment)\n"
            "                if worker_restarts:away={**(away or {}),'restarts':worker_restarts}\n"
            "                shown_stops+=restart_ids\n") in source


# ---- D2: the 7-day delete; the window ---------------------------------------------------------------------------

def test_shown_restarts_older_than_a_week_go_at_a_worker_start_and_unshown_ones_stay(store):
    now = datetime(2026, 11, 8, 0, 0, tzinfo=timezone.utc)
    host_stops.restarted(store, {'restarts': [entry('2026-10-30T01:00:00Z'), entry('2026-10-30T02:00:00Z'),
                                              entry('2026-11-06T02:00:00Z')]})
    host_stops.shown(store, [rid('2026-10-30T01:00:00Z')], at('2026-10-31T01:00:00Z'))
    host_stops.shown(store, [rid('2026-11-06T02:00:00Z')], at('2026-11-07T01:00:00Z'))
    host_stops.forget_restarts(store, now)
    left = [row['_id'] for row in store.collection('host_stops').find({'how': 'worker_restart'})]
    assert sorted(left) == [rid('2026-10-30T02:00:00Z'), rid('2026-11-06T02:00:00Z')]
    # The window: one shown and asked more than a day ago is no longer said; one never shown still is.
    assert [row['_id'] for row in host_stops.restart_window(store, now)] == [rid('2026-10-30T02:00:00Z')]


# ---- D6: the most it can be -------------------------------------------------------------------------------------

def test_the_constructed_worst_case_stays_within_its_bound(store):
    """D6: routine with every cause; three runs of all six causes, every step held by a turn, a 20-character title
    and calls; every span at its widest; not_listed; unreadable."""
    task(store, 'long', '把十月底那一周的全部日记逐条整理成一份带索引的长文档')
    widest = [{'by': ['turn', 'task', 'calls'], 'task_id': 'long', 'calls': 99}]
    entries = [entry('2026-10-30T00:00:00Z'), entry('2026-10-30T00:30:00Z', 'settings')]           # every routine cause
    causes = ['published', 'settings', 'settings_restored', 'recovery:' + 'a' * 40, 'again', 'unknown']
    for place in range(3):                               # three places, each a run of every cause, its longest hold
        start = '2026-10-30T%02d:00:00Z' % (2 + 2 * place)
        for i, cause in enumerate(causes):
            asked = at(start, 540 * i)
            longest = 47 * 3600 + 59 * 60                # '47 小时 59 分钟', the widest a span reads
            entries.append(entry(asked, cause, back=longest - i * 60,
                                 held=hold(asked, longest, widest * 2, changes=99) if i == 0 else None))
    entries += [entry('2026-10-29T%02d:00:00Z' % hour, 'again', back=600) for hour in range(10, 24)]   # not listed
    entries += [{**entry('2026-10-29T%02d:30:00Z' % hour), 'back': 'x'} for hour in range(10)]          # unreadable
    block = told(store, entries, moment=datetime(2026, 10, 30, 23, 59, tzinfo=timezone.utc))
    assert len(block['listed']) == 3 and all('run' in place for place in block['listed'])
    assert total(block) == len(entries) == 44
    assert 'routine' in block and 'not_listed' in block and 'unreadable' in block
    assert len(json.dumps(block, ensure_ascii=False)) <= 1320, len(json.dumps(block, ensure_ascii=False))


# ---- D1, the Host's side: what held it ----------------------------------------------------------------------------

def test_the_host_keeps_what_held_a_restart_and_discards_it_when_sent_or_withdrawn(monkeypatch):
    host = RuntimeHost({}, SimpleNamespace(record=lambda kind, payload: None))
    receipt = [{'_id': 'publish-receipt'}]
    monkeypatch.setattr(receipt_records, 'sink_of_kind', lambda store, kind, **where: SimpleNamespace(
        first=lambda **kw: receipt[0]))
    host.app, host.schedule = SimpleNamespace(store=SimpleNamespace()), None
    host.controller = SimpleNamespace(active=None, active_task=None, calls_in_flight=lambda: 0, pending=Queue(),
                                      task_queue=Queue(), state_lock=threading.Lock(),
                                      restart_pending=host.restart_pending)
    holders = [('turn', None, 0), ('task', 't1', 0), ('calls', None, 2), ('turn', None, 0), ('task', 't2', 0),
               ('calls', None, 1), ('task', 't3', 0)]
    for active, task, calls in holders:                  # seven changes of what holds it
        host.controller.active, host.controller.active_task = ('character' if active == 'turn' else None), task
        host.controller.calls_in_flight = lambda calls=calls: calls
        host._maybe_restart_after_publish()
    trail = host._restart_hold
    assert trail['changes'] == 7 and len(trail['steps']) == 5, 'the first and the newest 4'
    assert [step['by'] for step in trail['steps']] == [['turn'], ['turn'], ['task'], ['calls'], ['task']]
    assert trail['steps'][2]['task_id'] == 't2' and trail['steps'][3]['calls'] == 1
    assert host.restart_hold() == trail and host.restart_hold() is None, 'taken once: discarded when sent'
    # A restart withdrawn before it was asked for leaves no trail behind for a later one.
    host2 = RuntimeHost({}, SimpleNamespace(record=lambda kind, payload: None))
    host2.app, host2.schedule, host2.controller = host.app, None, host.controller
    host2.controller.restart_pending = host2.restart_pending
    host2._maybe_restart_after_publish()
    assert host2._restart_hold['steps']
    receipt[0] = None
    host2._maybe_restart_after_publish()
    assert host2._restart_hold is None
    # Never held: asked at once, and nothing is sent.
    receipt[0] = {'_id': 'publish-receipt'}
    host3 = RuntimeHost({}, SimpleNamespace(record=lambda kind, payload: None))
    host3.app, host3.schedule = host.app, None
    host3.controller = SimpleNamespace(active=None, active_task=None, calls_in_flight=lambda: 0, pending=Queue(),
                                       task_queue=Queue(), state_lock=threading.Lock(), restart_pending=host3.restart_pending)
    host3._maybe_restart_after_publish()
    assert host3.restart_requested.is_set() and host3.restart_hold() is None
