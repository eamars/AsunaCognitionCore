"""ADR-005 P5 宿主定向检查：话题线认得出、旁听行能被问一次（真实 Mongo 那一层）。

配置入口沿用既有约定：环境变量 ASUNA_P5_CONFIG（默认 config/local.json），文件缺失就
直接报错 fail closed。只用固定授权库 asuna_v2_test_p5_host_20260924（可用 ASUNA_P5_DATABASE
换同等受限的库）：操作员账号只有这一库读写权，随机库名会在 listCollections 就 Unauthorized；
库内隔离靠用例开头与结尾清空本套件写的集合。不发 QQ 消息、不调模型：分寸判断全程不碰 lane。

逻辑本身另有一份离线用例（tests/p5_proactive_cases.py，假集合真算，本机已跑 17/17）；
这里补的是真驱动、真集合校验、真 CAS 那一层，外加把离线用例与 P2 那批一起跑一遍防漂移。
真群里的舒适度不在这份检查里：那要 owner 真启用一个场景才知道。
"""
import os

import pytest

from asuna import proactive
from asuna.channels import group_context
from asuna.config import load
from asuna.context import ContextBuilder
from asuna.state import Store

import p2_summary_loop_cases as p2
import p5_proactive_cases as cases

CONFIG_PATH = os.environ.get('ASUNA_P5_CONFIG', 'config/local.json')
TEST_DATABASE = os.environ.get('ASUNA_P5_DATABASE', 'asuna_v2_test_p5_host_20260924')
CLEARED = ('identities', 'scenes', 'messages', 'memory_units', 'state_heads', 'state_revisions',
           'audit_events')


@pytest.fixture
def store():
    db = Store(load(CONFIG_PATH), TEST_DATABASE)
    db.migrate()
    for name in CLEARED:
        db.db[name].delete_many({})
    yield db
    for name in CLEARED:
        db.db[name].delete_many({})
    db.client.close()


def test_offline_cases_all_pass():
    '''假集合那批用例跟着跑一遍：同一结论不许两套口径各自漂移。'''
    bad = [row for row in cases.run_all() if not row[1]]
    assert not bad, bad


def test_p2_offline_cases_still_pass():
    '''P2 的自适应节奏底线不许被这次改动带偏（离线那批一起跑）。'''
    bad = [row for row in p2.run_all() if not row[1]]
    assert not bad, bad


def test_unprompted_row_asks_once_on_real_store(store):
    cases.seed_real(store)
    row = store.db.messages.find_one({'_id': 'in-%s-13' % cases.GROUP})
    decision, updated = proactive.consider(store, cases.EVIDENCE(), cases.config_for(cases.ENABLED),
                                           cases.scene_of(store), row, now_ts=cases.T0 + 60,
                                           can_run=True)
    assert decision['fire'], decision
    stored = store.db.messages.find_one({'_id': row['_id']})
    assert stored['processing_outcome'] == proactive.OUTCOME_WAKE, stored['processing_outcome']
    assert stored['proactive']['wake'] is True and stored['proactive']['holds'] == []
    assert stored['event']['group_context']['wake_reason'] == proactive.WAKE_REASON
    assert stored['revision'] == row['revision'] + 1, '真 CAS：一次改写只推一个版本'
    assert updated['processing_outcome'] == proactive.OUTCOME_WAKE


def test_quiet_hour_records_which_gate_on_real_store(store):
    cases.seed_real(store)
    row = store.db.messages.find_one({'_id': 'in-%s-13' % cases.GROUP})
    decision, updated = proactive.consider(store, cases.EVIDENCE(), cases.config_for(cases.ENABLED),
                                           cases.scene_of(store), row, now_ts=cases.NIGHT + 60,
                                           can_run=True)
    assert not decision['fire'] and 'quiet_hours' in decision['holds'], decision
    stored = store.db.messages.find_one({'_id': row['_id']})
    assert stored['processing_outcome'] == proactive.OUTCOME_HOLD, stored['processing_outcome']
    assert 'quiet_hours' in stored['proactive']['holds'], stored['proactive']
    assert stored['event']['group_context']['wake_reason'] is None, '拦下来就不算被唤醒'


def test_unenrolled_scene_row_is_untouched_on_real_store(store):
    cases.seed_real(store)
    row = store.db.messages.find_one({'_id': 'in-%s-13' % cases.GROUP})
    decision, updated = proactive.consider(store, cases.EVIDENCE(), cases.config_for(None),
                                           cases.scene_of(store), row, now_ts=cases.T0 + 60,
                                           can_run=True)
    assert decision['holds'] == ['not_enrolled'] and updated is None, decision
    after = store.db.messages.find_one({'_id': row['_id']})
    assert after['revision'] == row['revision'] and 'proactive' not in after, after


def test_topic_line_reaches_context_on_real_store(store):
    cases.seed_real(store)
    current = {'event_id': 'evt-next', 'scene_id': cases.GROUP, 'person_id': cases.PERSON_B,
               'text': '那我搬两个',
               'group_context': {'wake_reason': proactive.WAKE_REASON, 'topic_id': 'topic-1',
                                 'topic_via': 'proactive', 'reply_to': None,
                                 'reply_message_id': 'in-%s-13' % cases.GROUP,
                                 'mentioned_account_ids': []}}
    store.put('messages', {'_id': 'in-ep-proactive', 'scene_id': cases.GROUP,
                           'scope_key': cases.GROUP_SCOPE, 'policy_epoch': cases.EPOCH,
                           'scene_seq': 14, 'direction': 'inbound', 'author': cases.PERSON_B,
                           'text': '那我搬两个', 'platform_event_id': 'evt-next',
                           'occurred_at': cases._iso(cases.T0 + 30),
                           'received_at': cases._iso(cases.T0 + 30),
                           'event': {'group_context': current['group_context']}}, stream='p5')
    _system, context, _manifest = ContextBuilder(store, retrieval=None).prepare(current)
    continuity = context['group_continuity_from_program']
    ids = {row['_id'] for row in continuity['related_messages']}
    assert {'in-%s-13' % cases.GROUP, 'in-ep-proactive'} <= ids, ids
    assert '沉默不需要理由' in continuity['proactive_from_program']


def test_topic_is_derived_on_real_store(store):
    recent = p2._iso(cases.T0)
    store.put('messages', {'_id': 'in-parent', 'scene_id': cases.GROUP, 'policy_epoch': cases.EPOCH,
                           'direction': 'inbound', 'author': cases.PERSON, 'received_at': recent,
                           'event': {'channel': {'platform_event_id': 'evt-parent'},
                                     'group_context': {'wake_reason': None, 'topic_id': 'topic-A',
                                                       'topic_via': 'new'}}}, stream='p5')
    from datetime import datetime, timedelta, timezone
    fresh = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
    store.db.messages.update_one({'_id': 'in-parent'}, {'$set': {'received_at': fresh}})
    bound = group_context(store, {'scene_id': cases.GROUP},
                          {'account_id': cases.BOT, 'mentioned_account_ids': [],
                           'reply_to': 'evt-parent'}, 'evt-new')
    assert bound['wake_reason'] is None and bound['topic_id'] == 'topic-A', bound
    assert bound['topic_via'] == 'reply_chain', bound
