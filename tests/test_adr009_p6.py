"""ADR-009 P6 MongoDB tests: T6.1 history delta, T6.2 audit and receipt dedupe."""
import json
import threading

import pytest

from asuna.audit import projection, replay, trace_contents, verify, verify_documents
from asuna.coordinator import Coordinator
from asuna.ingress import persist_input
from asuna.lanes import FakeLane, LaneResult
from asuna.native_worker import NativeLane
from asuna.state import Store, content_digest, content_ref
from test_adr009_p2 import decide, owner


def said(store, key, text):
    """An input that is stored but does not wake her (like an unaddressed group line)."""
    persist_input(store, {'event_id': key, 'scene_id': 'dm-a', 'person_id': 'A', 'text': text})


def turn(coordinator, key, text, generation=None):
    coordinator.character.outputs = iter([LaneResult('想。', compaction_generation=generation), decide(),
                                          LaneResult('回' + text, compaction_generation=generation)])
    ep = coordinator.ingest({'event_id': key, 'scene_id': 'dm-a', 'person_id': 'A', 'text': text})
    return [row['text'] for row in ep['context']['delivered_history']], ep


def test_T6_1_history_is_given_once_per_session(store):
    coordinator = Coordinator(store, FakeLane(store, []))
    said(store, 'old-1', '旧一')
    said(store, 'old-2', '旧二')
    first, ep1 = turn(coordinator, 't1', '第一轮')
    assert first == ['旧一', '旧二'] and ep1['manifest']['history_delta']['full_window'] is True
    second, ep2 = turn(coordinator, 't2', '第二轮')
    assert second == [], 'rows given in turn 1, its input and her own reply are already in the session'
    assert ep2['context']['history_from_program']['omitted'] == 4
    said(store, 'side-1', '旁一')
    said(store, 'side-2', '旁二')
    third, _ = turn(coordinator, 't3', '第三轮')
    assert third == ['旁一', '旁二'], 'lines that never woke her arrive exactly once'
    fourth, _ = turn(coordinator, 't4', '第四轮', generation=1)       # the native session compacted during t4
    assert fourth == []
    fifth, ep5 = turn(coordinator, 't5', '第五轮', generation=1)
    assert ep5['manifest']['history_delta']['full_window'] is True and 'history_from_program' not in ep5['context']
    assert len(fifth) == 12 and fifth[-1] == '回第四轮', 'after compaction the full window is given again'
    sixth, _ = turn(coordinator, 't6', '第六轮', generation=1)
    assert sixth == []
    cursor = store.db.sessions.find_one({'_id': ep5['history_session']})
    assert cursor['history_only'] and cursor['compaction_generation'] == 1 and cursor['history_generation'] == 1


def test_T6_1_a_new_session_gets_the_full_window(store):
    coordinator = Coordinator(store, FakeLane(store, []))
    turn(coordinator, 't1', '第一轮')
    coordinator.character.outputs = iter([LaneResult('想。'), decide(), LaneResult('好')])
    ep = coordinator.ingest({'event_id': 'web-1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '新会话',
                             'native_session_id': 'web-session-2'})
    assert [r['text'] for r in ep['context']['delivered_history']] == ['第一轮', '回第一轮']
    assert ep['history_session'] == 'web-session-2'


def big_message(store, text):
    scene = store.db.scenes.find_one_and_update({'_id': 'dm-a'}, {'$inc': {'sequence': 1}}, return_document=True)
    return store.put('messages', {'_id': 'big', 'scene_id': 'dm-a', 'scope_key': scene['scope_key'], 'policy_epoch': 1,
                                  'scene_seq': scene['sequence'], 'direction': 'inbound', 'author': 'A', 'text': text},
                     stream='t62')


def test_T6_2_large_documents_are_audited_by_reference(store):
    text = '长文' * 6000                                         # 36 KB of UTF-8
    doc = big_message(store, text)
    commit = store.db.audit_events.find_one({'stream_id': 't62', 'type': 'state.commit'})
    assert 'document' not in commit['payload'] and text not in json.dumps(commit, ensure_ascii=False)
    assert commit['payload']['content_sha256'] == content_digest('messages', doc) and commit['payload']['bytes'] > 16 * 1024
    events = list(store.db.audit_events.find({}))
    verify(events)
    assert verify_documents(events, store) >= 1
    target = Store(store.config, store.name + '_replay')
    store.derived_databases = [target.name]
    with pytest.raises(ValueError, match='REPLAY_CONTENT_MISSING'):
        replay(events, target)
    target.client.drop_database(target.name)
    assert replay(events, target, trace_contents(events, store))['sha256'] == projection(store)['sha256']
    store.db.messages.update_one({'_id': 'big'}, {'$set': {'text': text + '改'}})
    with pytest.raises(ValueError, match='AUDIT_DOCUMENT_TAMPERED: messages/big'):
        verify_documents(events, store)
    small = store.put('messages', {**store.db.messages.find_one({'_id': 'big'}), '_id': 'small', 'text': '短'}, stream='t62')
    store.db.messages.update_one({'_id': 'small'}, {'$set': {'text': '改短'}})
    with pytest.raises(ValueError, match='messages/small'):
        verify_documents(list(store.db.audit_events.find({})), store)
    assert small['revision'] == 1


def test_T6_2_phase_output_and_native_receipt_keep_hashes(store, tmp_path):
    owner(store)
    store.config['chat']['workspace'] = str(tmp_path)
    lane = FakeLane(store, [LaneResult('私下想的长内容' * 50), decide(), LaneResult('好')])
    ep = Coordinator(store, lane).ingest({'event_id': 'e1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '你好'})
    outputs = list(store.db.audit_events.find({'stream_id': ep['_id'], 'type': 'phase.output'}))
    assert outputs and all('content' not in e['payload'] for e in outputs)
    assert '私下想的长内容' not in json.dumps([e['payload'] for e in outputs], ensure_ascii=False)
    assert outputs[0]['payload']['content_sha256'] == content_ref('私下想的长内容' * 50)['content_sha256']
    store.put('episodes', {**store.db.episodes.find_one({'_id': ep['_id']}), 'native_session_id': 'role-1'},
              expected=store.db.episodes.find_one({'_id': ep['_id']})['revision'], stream=ep['_id'])
    generated = []

    class Worker:
        pending_lock = threading.Lock()
        pending = {}

        def bind_session(self, session_id, values):
            return {'_id': session_id, **values}

        def emit(self, request):
            # A repeated token is answered from the saved native stage result (same text, no new generation).
            generated.append(request['token'])
            self.pending[request['token']].set_result({'content': '原生回答', 'request_refs': ['role-1:7']})

    native = NativeLane(Worker(), {'character': {'model': 'native-host'}}, store, None)
    first = native.generate('b', ep['_id'] + ':EXTRA:0', 'EXTRA', 'text', 'system')
    receipt = store.db.lane_receipts.find_one({'_id': ep['_id'] + ':EXTRA:0'})
    assert first.content == '原生回答' and 'content' not in receipt['result']
    assert receipt['result']['content_sha256'] == content_ref('原生回答')['content_sha256']
    assert receipt['result']['native_ref'] == 'role-1:7'
    again = native.generate('b', ep['_id'] + ':EXTRA:0', 'EXTRA', 'text', 'system')
    assert again.content == '原生回答' and store.db.lane_receipts.count_documents({'_id': ep['_id'] + ':EXTRA:0'}) == 1
    assert generated == [ep['_id'] + ':EXTRA:0'] * 2, 'the repeat is answered by the host from its saved result'
