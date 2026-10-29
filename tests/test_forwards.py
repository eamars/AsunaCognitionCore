"""Merged forwards (合并转发, Xiaoman's request 2026-10-11): the adapter reads what a forward carried, inline or with
one call, and shows the line as count + ref + the first three messages; the host keeps the messages on that line,
she reads them in full with recall only in that conversation, and the history query finds them."""
import sys

from asuna.config import ROOT

ADAPTER = ROOT / 'packages' / 'channels' / 'napcat-qq' / 'integration'
sys.path[:0] = [str(ADAPTER), str(ADAPTER / 'vendor')]          # as adapter.py sets it up
from qqadapter import forward, inbound                             # noqa: E402

SCENE, OTHER = 'qq:900000000:group:900000001', 'qq:900000000:group:900000002'


def node(name, text, uid='900000101', at=1_800_000_000):
    return {'type': 'node', 'data': {'user_id': uid, 'nickname': name, 'time': at,
                                     'content': [{'type': 'text', 'data': {'text': text}}]}}


def envelope(data, text_before='看这个'):
    message = [{'type': 'text', 'data': {'text': text_before}}, {'type': 'forward', 'data': data}]
    parsed = inbound.parse_message(message)
    return {'event_id': 'e1', 'text': parsed['text_with_at_media'], 'raw': {'message': message}}


def test_a_forward_with_its_messages_inline_needs_no_call_and_shows_three_short_lines():
    long = '这一条很长' * 20
    env = envelope({'id': 'abc', 'content': [node('甲', long), node('乙', '二'), node('丙', '三'), node('丁', '四')]})
    calls, logged = [], []
    assert forward.attach(env, lambda *a: calls.append(a), log=logged.append) == 1
    assert calls == [] and forward.PLACEHOLDER not in env['text']
    head, *shown = env['text'].split('\n')
    ref = forward.ref_of('abc')
    assert head == '看这个[合并转发｜4 条｜%s]' % ref and len(shown) == 3
    assert shown[0].startswith('  甲：') and shown[0].endswith('…') and len(shown[0]) < 50
    [block] = env['raw'][forward.FORWARD_KEY]
    assert block['source'] == 'inline' and block['nodes'][0]['text'] == long and block['nodes'][3]['text'] == '四'
    assert 'source=inline' in logged[0] and long not in logged[0]          # metadata only


def test_a_forward_by_id_is_fetched_once_and_a_forward_inside_it_is_read_one_level_deep():
    inner = {'type': 'forward', 'data': {'id': 'inner'}}
    outer = [{'sender': {'user_id': 1, 'nickname': '甲'}, 'time': 1, 'message': [{'type': 'text', 'data': {'text': '先看'}}, inner]}]
    answers = {'outer': {'retcode': 0, 'data': {'messages': outer}},
               'inner': {'retcode': 0, 'data': {'messages': [node('乙', '里面那条')]}}}
    calls = []

    def call(action, params):
        calls.append((action, params['id']))
        return answers[params['id']]
    env = envelope({'id': 'outer'})
    assert forward.attach(env, call) == 1
    assert calls == [('get_forward_msg', 'outer'), ('get_forward_msg', 'inner')]
    [block] = env['raw'][forward.FORWARD_KEY]
    assert block['source'] == 'fetched' and [n['name'] for n in block['nodes']] == ['甲', '↳ 乙']


def test_a_forward_that_cannot_be_read_keeps_its_placeholder():
    env = envelope({'id': 'gone'})
    logged = []

    def call(action, params):
        raise TimeoutError('no answer')
    assert forward.attach(env, call, log=logged.append) == 0
    assert env['text'] == '看这个' + forward.PLACEHOLDER and forward.FORWARD_KEY not in env['raw']
    assert logged[0].startswith('FORWARD_UNREAD') and 'TimeoutError' in logged[0]


