"""ADR-129: one rule in every conversation. Only speak speaks; body text is hers and never sent (said once in the turn,
and her next turn there says so); not calling speak is silence; stay_silent is gone everywhere. A local conversation
(her local Web chat, an agent line) puts none of QQ's rules on speak; the page reads what a speak call sent only through
that call's own record; an agent line's poll carries her pictures and stickers as files, with QQ's receipt evidence.
On the unit run's store holding the fixture world (conftest.py)."""
import hashlib
import importlib.util
import os
import time
from types import SimpleNamespace

import pytest

from asuna import answers, channel_kinds, outbound_media, role_tools
from asuna.channels import Channels
from asuna.config import ROOT
from asuna.coordinator import UNSENT_NOTE, Coordinator
from asuna.lanes import FakeLane, FakeTurn
from asuna.records import episodes as episode_records
from asuna.records import scenes as scene_records
from asuna.state import Denied

channel_kinds.load([{'python': ROOT / 'packages' / 'channels' / 'agent-line' / 'python', 'module': 'agent_line'},
                    {'python': ROOT / 'packages' / 'channels' / 'napcat-qq' / 'python', 'module': 'napcat_qq'}])
spec = importlib.util.spec_from_file_location('agent_line_cli', ROOT / 'tools' / 'agent_line.py')
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)

LOCAL, OWNER, PERSONA = 'local-dm', 'local-user', 'P1'
LINE, AGENT = 'agent:home:dm:claude-code', 'agent:claude-code'
THINK = ('think', {'thought': '他在等我回话。'})


@pytest.fixture
def home(world, tmp_path):
    """The fixture world with her local Web chat and one agent line (two routes on the agent channel)."""
    config = world.config
    config['chat'] = {**config['chat'], 'scene_id': LOCAL, 'person_id': OWNER, 'persona': PERSONA,
                      'workspace': str(tmp_path / 'local')}
    def route(name):
        return {'scene_id': 'agent:home:dm:' + name, 'sender_id': name, 'person_id': 'agent:' + name,
                'target': {'type': 'dm', 'id': name}, 'workspace': str(tmp_path / name), 'read_only_paths': []}
    config['channels'] = {**(config.get('channels') or {}), 'agent': {
        'account_id': 'home', 'token': 'a' * 32, 'routes': {'claude-code': route('claude-code'), 'codex': route('codex')}}}
    scene_records.save(world, {'_id': LOCAL, 'kind': 'dm', 'scope_key': 'scene:' + LOCAL, 'policy_epoch': 1,
                               'sequence': 0, 'members': [OWNER]})
    scene_records.save(world, {'_id': LINE, 'kind': 'dm', 'channel_id': 'agent', 'scope_key': 'scene:' + LINE,
                               'policy_epoch': 1, 'sequence': 0, 'members': [AGENT, OWNER]})
    return world


def run(store, *turns, key='e1', text='在吗', kind='external', scene=LOCAL):
    lane = FakeLane(store, list(turns))
    person = OWNER if scene == LOCAL else AGENT
    channel = {} if scene == LOCAL else {'channel': {'id': 'agent', 'target': {'type': 'dm', 'id': 'claude-code'},
                                                     'account_id': 'home', 'platform_event_id': 'agent-' + key}}
    ep = Coordinator(store, lane).ingest({'event_id': key, 'scene_id': scene, 'person_id': person, 'text': text,
                                          'episode_kind': kind, **channel}, persona=PERSONA)
    return ep, lane


def outbound(store, ep):
    return sorted(store.collection('messages').find({'episode_id': ep['_id'], 'direction': 'outbound'}),
                  key=lambda row: row['scene_seq'])


def audits(store, ep, kind):
    return [row['payload'] for row in store.collection('audit_events').find({'type': kind, 'stream_id': ep['_id']})]


def test_a_local_turn_that_speaks_sends_its_parts_and_keeps_its_body(home):
    ep, _ = run(home, FakeTurn([THINK, ('speak', {'parts': [{'kind': 'text', 'text': '回来啦'},
                                                             {'kind': 'text', 'text': '今天怎么样'}]})],
                               '（自言自语）'))
    assert ep['state'] == 'COMMITTED'
    assert [row['text'] for row in outbound(home, ep)] == ['回来啦', '今天怎么样']
    assert audits(home, ep, 'turn.ending_body') == [{'chars': len('（自言自语）'), 'parts': 2}]
    assert not audits(home, ep, 'turn.rejected')


def test_body_text_alone_is_never_sent_and_her_next_turn_there_says_so(home):
    # D8 on an agent line: no message row, told once in the turn; written again, her next turn there carries it.
    ep, lane = run(home, FakeTurn([THINK], '我说一句'), FakeTurn([], '还是写在这里'), scene=LINE)
    assert ep['state'] == 'COMMITTED' and outbound(home, ep) == []
    assert [row['problem'] for row in audits(home, ep, 'turn.rejected')] == ['unsent']
    assert lane.calls[1]['messages'][-1]['content'] == UNSENT_NOTE % '我说一句'
    after, _ = run(home, FakeTurn([THINK, ('speak', {'parts': [{'kind': 'text', 'text': '刚才那句'},
                                                                {'kind': 'text', 'text': '再说一句'}]})], ''),
                   key='e2', scene=LINE)
    assert episode_records.get(home, after['_id'])['context']['unsent_from_program'] == '没发出去：「还是写在这里」'
    # With speak its parts are rows for the line, queued as they left, with no typing pace there (D4, D9).
    rows = outbound(home, after)
    assert [(row['text'], row['delivery_state'], row.get('not_before')) for row in rows] == [
        ('刚才那句', 'QUEUED_EXTERNAL', None), ('再说一句', 'QUEUED_EXTERNAL', None)]


def test_a_local_turn_with_no_speak_and_no_words_ends_silent_and_a_consult_is_still_handed_back(home):
    ep, lane = run(home, FakeTurn([THINK], ''))
    assert ep['state'] == 'COMMITTED' and outbound(home, ep) == []
    assert not audits(home, ep, 'turn.rejected') and len(lane.calls) == 1
    # The action brain waits for her answer: a consult turn with none is handed back, as before.
    done = episode_records.get(home, ep['_id'])
    consult = home.put('episodes', {**{k: v for k, v in done.items() if k not in ('revision', 'tool_calls', 'reply')},
                                    '_id': 'ep-consult', 'source_event_id': 'consult-1', 'episode_kind': 'consult',
                                    'state': 'PREPARED'}, stream='ep-consult')
    lane = FakeLane(home, [FakeTurn([THINK], '')] * 3)
    after = Coordinator(home, lane).advance(consult['_id'])
    assert after['state'] == 'FAILED_PROTOCOL' and 'INVALID_TURN_OUTPUT' in after['failure']
    assert [row['problem'] for row in audits(home, consult, 'turn.rejected')][:1] == [
        '你还没回答行动脑：用 task 的 answer 写下回答；这里写的正文不会发给任何人。']


def test_a_local_turn_cut_at_its_length_limit_is_not_her_silence(home):
    # No speak and nothing written, cut: handed back, and what she then says through speak leaves.
    ep, lane = run(home, FakeTurn([THINK], '', finish_reason='length'),
                   FakeTurn([('speak', {'parts': [{'kind': 'text', 'text': '刚才没说完，回来啦'}]})], ''))
    assert [row['problem'] for row in audits(home, ep, 'turn.rejected')] == ['length']
    assert lane.calls[1]['messages'][-1]['content'] == answers.CUT
    assert ep['state'] == 'COMMITTED' and [row['text'] for row in outbound(home, ep)] == ['刚才没说完，回来啦']
    # Parts already left: the turn commits whatever its finish.
    ep, lane = run(home, FakeTurn([THINK, ('speak', {'parts': [{'kind': 'text', 'text': '回来啦'}]})], '',
                                  finish_reason='length'), key='e2')
    assert ep['state'] == 'COMMITTED' and not audits(home, ep, 'turn.rejected') and len(lane.calls) == 1
    assert [row['text'] for row in outbound(home, ep)] == ['回来啦']


def test_local_speak_has_no_line_rules_and_still_refuses_a_text_sent_twice(home):
    seven = '\n'.join('第%d行' % n for n in range(1, 8))
    ep, lane = run(home, FakeTurn([THINK, ('speak', {'parts': [{'kind': 'text', 'text': seven},
                                                               {'kind': 'text', 'text': '看〔12〕那句'}]}),
                                   ('speak', {'parts': [{'kind': 'text', 'text': seven}]})], ''))
    done = [result for *_, result, ok in lane.tool_results if ok]
    refused = [result for *_, result, ok in lane.tool_results if not ok]
    assert [row['text'] for row in outbound(home, ep)] == [seven, '看〔12〕那句']
    assert 'lines' not in done[-1]                               # no line count in a local conversation
    assert len(refused) == 1 and '这回合已经发过一样的' in refused[0]


def test_no_conversation_lists_stay_silent_and_nothing_runs_a_call_of_it(home):
    for scene in (LOCAL, LINE, 'qq:10001:group:20002'):
        listed = role_tools.toolbox(home, {'scene_id': scene, 'manifest': {'session_class': 'owner_private'}})
        assert 'speak' in listed and 'stay_silent' not in listed, (scene, listed)
    assert 'stay_silent' not in role_tools.aliases()
    ep, lane = run(home, FakeTurn([THINK, ('stay_silent', {'reason': '不想说'})], ''))
    assert [result for *_, name, _args, result, ok in lane.tool_results if name == 'stay_silent'] == ['NOT_EXPOSED']
    assert ep['state'] == 'COMMITTED' and outbound(home, ep) == []


def test_the_page_reads_only_the_rows_a_call_s_own_record_names(home):
    ep, lane = run(home, FakeTurn([THINK, ('speak', {'parts': [{'kind': 'text', 'text': '一'}]}),
                                   ('speak', {'parts': [{'kind': 'text', 'text': '二'}]})], ''))
    calls = [call_id for operation, call_id, name, *_ in lane.tool_results if name == 'speak']
    operation = lane.tool_results[0][0]
    first = role_tools.sent_parts(home, LOCAL, operation, calls[0])
    assert [part['text'] for part in first['parts']] == ['一']
    assert [part['text'] for part in role_tools.sent_parts(home, LOCAL, operation, calls[1])['parts']] == ['二']
    # Not her call in this conversation, not a speak call, or a call whose record names no rows: nothing.
    assert role_tools.sent_parts(home, 'dm-a', operation, calls[0]) is None
    assert role_tools.sent_parts(home, LOCAL, operation, lane.tool_results[0][1]) is None      # her think
    assert role_tools.sent_parts(home, LOCAL, 'ep-other:TURN', calls[0]) is None
    with pytest.raises(Denied):
        role_tools.sent_picture(home, LOCAL, operation, calls[0], 0)      # a text: no picture to serve


def test_a_route_key_fetches_the_pictures_of_its_own_line_only(home):
    home.collection('messages').insert({'_id': 'pub-1', 'channel_id': 'agent', 'target': {'type': 'dm', 'id': 'claude-code'}})
    channels = Channels(SimpleNamespace(app=SimpleNamespace(store=home)))
    channels.scope_check('agent', 'claude-code', 'GET', ['outbox', 'pub-1', 'attachment'], {})
    with pytest.raises(Denied, match='ROUTE_KEY_OTHER_ROUTE'):
        channels.scope_check('agent', 'codex', 'GET', ['outbox', 'pub-1', 'attachment'], {})


PNG = b'\x89PNG\r\n\x1a\n' + bytes(range(64))


class Answer:
    def __init__(self, data):
        self.data = data

    def read(self, limit=None):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_poll_writes_her_picture_to_a_file_and_its_receipt_carries_the_evidence(monkeypatch, tmp_path):
    digest = hashlib.sha256(PNG).hexdigest()
    attachment = {'artifact_id': 'blob-1', 'media_type': 'image/png', 'sha256': digest}
    items = [{'publication_id': 'p1', 'attempt_id': 'a1', 'text': '', 'sticker': {'kind': 'custom'},
              'attachment': attachment},
             {'publication_id': 'p2', 'attempt_id': 'a2', 'text': '', 'attachment': {**attachment, 'sha256': 'f' * 64}}]
    calls, served = [], {'a1': PNG, 'a2': PNG}
    def call(line, method, path, body=None, timeout=None):
        calls.append((method, path, body))
        return {'items': items} if method == 'GET' and len(calls) == 1 else {'items': []} if method == 'GET' else {}
    monkeypatch.setattr(cli, 'call', call)
    monkeypatch.setattr(cli, 'MEDIA_DIR', tmp_path)
    monkeypatch.setattr(cli.urllib.request, 'urlopen', lambda request, timeout=None: Answer(
        served[request.full_url.split('attempt_id=')[1].split('&')[0]]))
    stale = tmp_path / 'claude-code' / ('0' * 64 + '.png')
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b'old')
    os.utime(stale, (time.time() - cli.KEEP_SECONDS - 60,) * 2)
    got, state, _ = cli.poll({'url': 'http://127.0.0.1:9/v1/channels/agent', 'key': 'k', 'route_id': 'claude-code'}, 0)
    assert not stale.exists(), 'a file older than its days stays'
    assert calls[0][1].startswith('/outbox?supports=image,sticker&')
    kept = tmp_path / 'claude-code' / (digest + '.png')
    assert kept.read_bytes() == PNG and got == ['[sticker] %s' % kept, '[picture not received: attachment_sha256_mismatch]']
    receipts = {path.split('/')[2]: body for method, path, body in calls if method == 'POST'}
    assert receipts['p1']['status'] == 'platform_accepted' and receipts['p1']['response']['attachment'] == {
        **attachment, 'bytes': len(PNG), 'sha256_verified': True}
    assert receipts['p2']['status'] == 'failed' and 'platform_message_id' not in receipts['p2']
    assert receipts['p2']['response']['reason'] == 'attachment_sha256_mismatch'
    # The core reads that receipt as QQ's: a picture the line attested it received.
    row = {'direction': 'outbound', 'delivery_state': 'DELIVERED', 'attachment': {**attachment, 'size': len(PNG)},
           'platform_receipt': receipts['p1']}
    assert outbound_media.sent_attachment(row)['attested'] is True


def test_a_sticker_she_sent_stays_viewable_after_she_drops_it(home):
    """D10: the page shows what left; a sticker row already delivered passes the sticker fence whatever her shelf holds
    now. One not yet sent still needs the shelf."""
    item = {'_id': 'att-gone-from-shelf'}
    row = {'sticker': {'kind': 'custom', 'name': '晚安'}, 'delivery_state': 'DELIVERED'}
    assert outbound_media.kept_sticker(home, row, item)
    assert not outbound_media.kept_sticker(home, {**row, 'delivery_state': 'SENDING'}, item)
    assert not outbound_media.kept_sticker(home, {'delivery_state': 'DELIVERED'}, item)       # not a sticker row
