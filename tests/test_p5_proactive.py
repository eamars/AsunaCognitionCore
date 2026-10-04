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
from asuna.config import load
from conftest import isolated_database, drop_database
from asuna.state import Store

import p5_proactive_cases as cases

CONFIG_PATH = os.environ.get('ASUNA_P5_CONFIG', 'config/local.json')
TEST_DATABASE = os.environ.get('ASUNA_P5_DATABASE', 'asuna_v2_test_p5_host_20260924')
CLEARED = ('identities', 'scenes', 'messages', 'memory_units', 'state_heads', 'state_revisions',
           'audit_events')


@pytest.fixture
def store():
    db = Store(load(CONFIG_PATH), isolated_database(TEST_DATABASE))
    db.migrate()
    for name in CLEARED:
        db.db[name].delete_many({})
    yield db
    for name in CLEARED:
        db.db[name].delete_many({})
    db.client.close()
    drop_database(db.config, db.name)


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


def test_unenrolled_scene_row_is_untouched_on_real_store(store):
    cases.seed_real(store)
    row = store.db.messages.find_one({'_id': 'in-%s-13' % cases.GROUP})
    decision, updated = proactive.consider(store, cases.EVIDENCE(), cases.config_for(None),
                                           cases.scene_of(store), row, now_ts=cases.T0 + 60,
                                           can_run=True)
    assert decision['holds'] == ['not_enrolled'] and updated is None, decision
    after = store.db.messages.find_one({'_id': row['_id']})
    assert after['revision'] == row['revision'] and 'proactive' not in after, after


