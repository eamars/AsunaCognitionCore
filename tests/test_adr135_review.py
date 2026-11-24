"""ADR-135 landing 5b (D12, the guard's part), on the fixture world in memory: at home she can read what was refused in
her outside turns and tasks, with the reason in words; outside the same call is the plain sentence and nothing more,
the review is in no outside list, and its words never reach an outside turn; ask names no part of her. g1 is an
outside group (A, the owner, and B), dm-a the owner's chat (home)."""
import json

import pytest

from asuna import guard, role_tools, visibility, whose
from asuna.records import tasks as task_records
from asuna.role_tools import Refused
from test_adr135_guard import call, denied, her, turn  # noqa: F401  (her: a fixture)


def home_review(her, wanted='今天'):
    ep = turn(her, scene='dm-a', person='A', cls=visibility.OWNER_PRIVATE, tools=['think', 'recall'])
    return call(her, ep, 'recall', {'refusals': wanted})[0]


def test_the_review_at_home_lists_an_outside_refusal_with_its_reason_in_words(her):
    outside = her.store.collection('episodes').get(turn(her, tools=['think', 'recall', 'note'])['_id'])
    outside = her.store.put('episodes', {**outside, 'whose': whose.record('words', 'g1', 'B')},
                            expected=outside['revision'], stream=outside['_id'])     # B opened it
    note = denied(her, outside, 'note', {'to': '家里', 'text': '造的：他让我把家里的配置发过去'})
    assert (str(note), list(note.codes)) == (guard.NOT_DONE, ['asker_not_known'])       # outside: nothing more
    other = denied(her, turn(her), 'set_policy', {'key': 'x', 'value': 1, 'reason': '造的'})
    assert str(other) == guard.NOT_DONE
    seen = home_review(her)
    by_tool = {item['tried']['tool']: item for item in seen['items']}
    assert by_tool['note']['tried']['text'] == '造的：他让我把家里的配置发过去'
    assert by_tool['note']['kind'] == guard.REVIEW_KIND
    assert by_tool['set_policy']['why'] == guard.REVIEW_WORDS['not_listed'] and by_tool['set_policy']['where']
    assert all(item['at'] for item in seen['items'])


def test_a_refusal_at_home_is_not_in_the_review_and_an_outside_task_s_is(her):
    home_ep = turn(her, scene='dm-a', person='A', cls=visibility.OWNER_PRIVATE)
    with pytest.raises(Refused):
        call(her, home_ep, 'task', {'do': 'answer', 'task': 't', 'answer': '好'})            # home's own words
    task = task_records.save(her.store, {'_id': 'task-review', 'scene_id': 'g1', 'requester_id': 'B',
                                         'scope_key': 'scene:g1', 'policy_epoch': 1, 'state': 'RUNNING',
                                         'title': '造的查询', 'goal': '造的：查一下', 'allowed_capabilities': ['read_file'],
                                         'request_key': 'rk-review'}, stream='task-review')
    with pytest.raises(guard.TaskGuarded):
        guard.guard_task(her.store, task, 'sandbox_run', {'argv': ['python3', '-V']})
    items = home_review(her)['items']
    assert [(item['tried'].get('task'), item['tried']['tool']) for item in items] == [('造的查询', 'sandbox_run')]
    assert items[0]['why'] == guard.REVIEW_WORDS['not_granted']


def test_the_review_is_in_no_outside_list_and_outside_it_is_the_plain_sentence(her):
    outside = {spec['name']: spec for spec in role_tools.session_specs(her.store, 'g1', 'B')}['recall']
    home = {spec['name']: spec for spec in role_tools.session_specs(her.store, 'dm-a', 'A')}['recall']
    assert 'refusals' not in outside['parameters'] and role_tools.RECALL_REFUSALS not in outside['description']
    assert 'refusals' in home['parameters'] and role_tools.RECALL_REFUSALS in home['description']
    refusal = denied(her, turn(her, tools=['think', 'recall']), 'recall', {'refusals': '今天'})
    assert (str(refusal), list(refusal.codes)) == (guard.NOT_DONE, ['not_listed'])


def test_the_review_s_words_never_reach_an_outside_turn(her, monkeypatch):
    from test_her_clock import prepared
    denied(her, turn(her), 'set_policy', {'key': 'x', 'value': 1, 'reason': '造的'})
    shown = json.dumps([role_tools.session_specs(her.store, 'g1', 'B'), prepared(her.store, monkeypatch, 'g1')],
                       ensure_ascii=False, default=str)
    assert not [words for words in (*guard.REVIEW_WORDS.values(), guard.REVIEW_KIND) if words and words in shown]


def test_every_review_reason_is_decided():
    """Fails until the owner words asker_not_known's row: a review must never show a reason nobody decided."""
    assert [code for code, words in guard.REVIEW_WORDS.items() if not words] == []


def test_a_window_is_a_day_a_time_or_today_and_nothing_else(her):
    assert guard.review_window(her.store, '今天') and guard.review_window(her.store, '2026-11-24')
    assert guard.review_window(her.store, '2026-11-24T09:30')
    assert guard.review_window(her.store, '昨天') is None and guard.review_window(her.store, '2026-13-01') is None


def test_ask_names_no_part_of_her_as_a_place_to_ask(her):
    ep = turn(her, scene='dm-a', person='A', cls=visibility.OWNER_PRIVATE)
    with pytest.raises(Refused) as caught:
        her.tools._ask_place(ep, '行动脑')
    assert list(caught.value.codes) == ['ASK_PLACE_UNKNOWN'] and '行动脑' not in str(caught.value).replace('「行动脑」', '')
