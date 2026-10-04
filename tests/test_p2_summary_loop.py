"""ADR-005 P2 宿主定向检查：后台摘要能写进关系、能读进下一轮（真实 Mongo 那一层）。

配置入口沿用既有约定：环境变量 ASUNA_P2_CONFIG（默认 config/local.json），文件缺失就
直接报错 fail closed。只用固定授权库 asuna_v2_test_p2_host_20260924（可用 ASUNA_P2_DATABASE
换同等受限的库）：操作员账号只有这一库读写权，随机库名会在 listCollections 就 Unauthorized；
库内隔离靠用例开头与结尾清空本套件写的集合。不依赖 ADR-001 seed 夹具，不碰生产库，
不发 QQ 消息（这条路径全程不调模型）。

逻辑本身另有一份离线用例（tests/p2_summary_loop_cases.py，假集合真算，本机已跑）；
这里补的是真驱动、真集合校验、真 CAS 那一层，外加把离线用例一起跑一遍防漂移。

P2 第二片在这里补的是群场景：真驱动下的自适应触发、多主体归属与更正回标。
全程不调模型、不发 QQ：摘要那条 lane 用假替身，只验落库与读取／登记。
"""
import os

import pytest

from asuna.config import load
from asuna.dialogue_summary import DialogueSummarizer
from asuna.memory import MemoryService
from conftest import isolated_database, drop_database
from asuna.state import Store
from asuna import summary_trigger

import p2_summary_loop_cases as cases

CONFIG_PATH = os.environ.get('ASUNA_P2_CONFIG', 'config/local.json')
TEST_DATABASE = os.environ.get('ASUNA_P2_DATABASE', 'asuna_v2_test_p2_host_20260924')
CLEARED = ('identities', 'scenes', 'messages', 'memory_units', 'state_heads', 'state_revisions',
           'audit_events')


def workspace_config(config):
    return dict(config, task_mode='workspace', chat={'scene_id': cases.SCENE, 'person_id': cases.PERSON,
                                                     'workspace': '/task'})


@pytest.fixture
def store():
    db = Store(load(CONFIG_PATH), isolated_database(TEST_DATABASE))
    db.migrate()
    db.config = workspace_config(db.config)
    for name in CLEARED:
        db.db[name].delete_many({})
    yield db
    for name in CLEARED:
        db.db[name].delete_many({})
    db.client.close()
    drop_database(db.config, db.name)


# ── P2 第二片：群场景的自适应触发、归属与更正（真 Mongo 那一层）────────────
def _tick_group(store, moment=None):
    """跑一轮真 DialogueSummarizer：只把模型那条 lane 换成假替身，落库走真集合。"""
    evidence, lane = cases.FakeEvidence(), cases.FakeLane()
    summarizer = DialogueSummarizer(store, evidence, lane, [cases.GROUP],
                                    clock=lambda: cases.T0 + 95 if moment is None else moment)
    return summarizer.tick(cases.GROUP), evidence, lane


def _decide(store, scene_id, moment):
    scene = store.db.scenes.find_one({'_id': scene_id})
    pending = list(store.db.messages.find(
        {'scene_id': scene_id, 'summary_batch_id': {'$exists': False}}).sort('scene_seq', 1))
    profile = summary_trigger.observe(store, scene, now_ts=moment)
    return profile, summary_trigger.decide(profile, pending, now_ts=moment,
                                           window_rows=DialogueSummarizer.WINDOW_ROWS)


def test_group_summary_loop_on_real_store(store):
    """群现场一轮：触发→整理→落库带归属→下一轮读得到→登记成 A 这条关系的来源。"""
    data = cases.group_rows()
    data['messages'] = data['messages'] + [cases.correction_row()]
    cases.seed_real(store, data)
    saved, evidence, lane = _tick_group(store)
    assert saved and saved['kind'] == 'dialogue_summary', saved
    assert saved['participants'] == sorted([cases.PERSON, cases.PERSON_B, 'demo']), saved
    assert saved['source_by_speaker'][cases.PERSON] == ['in-grp-1-11', 'in-grp-1-14'], saved
    assert saved['attribution']['corrections'][0]['target_resolution'] == 'reply_link', saved
    assert saved['trigger']['signals'], saved
    assert 'summary.saved' in evidence.kinds(), evidence.kinds()      # summarizer events go to run evidence
    for row in data['messages']:
        marked = store.db.messages.find_one({'_id': row['_id']})
        assert marked['summary_batch_id'] == saved['_id'], row['_id']
    assert '老陈' in lane.calls[0]['text'] and 'in-grp-1-11' in lane.calls[0]['text'], lane.calls[0]['text']
    _system, context, manifest = cases.prepare_group(store, cases.PERSON, '那到底周几去？')
    assert saved['_id'] in manifest['selected'], manifest
    entry = next(m for m in context['memories'] if m['_id'] == saved['_id'])
    assert entry['participants'] == saved['participants'], entry
    cases.add_row(store, 'memory_units', cases.monologue_unit(cases.PERSON, 'ep-g1'))
    result = MemoryService(store).commit_understanding(
        cases.group_episode(cases.PERSON, selected=manifest['selected']), '他自己把日子改成周五了。')
    assert result['state'] == 'COMMITTED' and result['auto_source_ids'] == [saved['_id']], result
    head, revision = store.head('relationship:' + cases.PERSON, cases.GROUP_SCOPE)
    assert head['revision_id'] == result['accepted_revision']
    for root in revision['processed_source_ids']:
        assert store.db.messages.find_one({'_id': root}), root


def test_summary_covering_someone_else_is_not_cited_on_real_store(store):
    """只盖了 B 的摘要：A 那轮看得见但不算 A 的证据；B 那轮照常算。"""
    data = cases.group_rows()
    data['messages'] = data['messages'] + [cases.correction_row()]   # 独白的来源根要真存在
    cases.seed_real(store, data)
    cases.add_row(store, 'memory_units', cases._summary_unit(
        'summary-b-only', '小舟说他去，工具他带。', ['in-grp-1-12'],
        [cases.PERSON_B, 'demo'], [12, 12]))
    cases.add_row(store, 'memory_units', cases.monologue_unit(cases.PERSON, 'ep-g2'))
    a_turn = MemoryService(store).commit_understanding(
        cases.group_episode(cases.PERSON, selected=['summary-b-only'], ep_id='ep-g2'), '小舟愿意去。')
    assert a_turn['auto_source_ids'] == [], a_turn
    assert a_turn['auto_source_skipped'] == [{'id': 'summary-b-only',
                                             'reason': 'person_not_in_participants'}], a_turn
    cases.add_row(store, 'memory_units', cases.monologue_unit(cases.PERSON_B, 'ep-g3'))
    b_turn = MemoryService(store).commit_understanding(
        cases.group_episode(cases.PERSON_B, selected=['summary-b-only'], ep_id='ep-g3'), '工具归我。')
    assert b_turn['state'] == 'COMMITTED' and b_turn['auto_source_ids'] == ['summary-b-only'], b_turn


def test_two_persons_with_same_display_name_on_real_store(store):
    """真库那一层的同名：身份表两行同名不合并，摘要里仍是两个 person_id。"""
    rows = [cases._in(cases.GROUP, 11, cases.PERSON, '雾灯我周三去修', cases.T0),
            cases._in(cases.GROUP, 12, 'qq:B1', '我去', cases.T0 + 25),
            cases._in(cases.GROUP, 13, 'qq:C1', '我也去', cases.T0 + 40)]
    data = cases.group_rows(messages=rows)
    data['messages'] = rows
    data['identities'] = [row for row in data['identities']
                          if row['_id'] not in (cases.PERSON, cases.PERSON_B)] + [
        {'_id': person, 'person_id': person, 'platform': 'qq', 'account_id': 'acct-' + tail,
         'display_name': name, 'revision': 1}
        for person, tail, name in ((cases.PERSON, 'A', '老陈'), ('qq:B1', 'B1', '小舟'),
                                   ('qq:C1', 'C1', '小舟'))]
    cases.seed_real(store, data)
    saved, _evidence, lane = _tick_group(store)
    assert saved and saved['participants'] == sorted([cases.PERSON, 'qq:B1', 'qq:C1']), saved
    assert saved['source_by_speaker']['qq:B1'] == ['in-grp-1-12'], saved
    assert saved['source_by_speaker']['qq:C1'] == ['in-grp-1-13'], saved
    assert '小舟（qq:B1）' in lane.calls[0]['text'] and '小舟（qq:C1）' in lane.calls[0]['text'], \
        lane.calls[0]['text']
