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
from asuna.memory_indexer import MemoryIndexer
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
    db = Store(load(CONFIG_PATH), TEST_DATABASE)
    db.migrate()
    db.config = workspace_config(db.config)
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


def test_summary_becomes_relationship_source(store):
    cases.seed_real(store)
    result = MemoryService(store).commit_understanding(cases.episode(), '他把日子说定了，工具我带。')
    assert result['state'] == 'COMMITTED', result
    assert result['source_ids'] == [cases.MONO, cases.SUMMARY], result
    assert result['auto_source_ids'] == [cases.SUMMARY], result
    head, revision = cases.head_pair(store)
    assert head['revision_id'] == result['accepted_revision']
    assert set(revision['processed_source_ids']) >= {cases.INBOUND, cases.OUTBOUND}, revision
    for source in revision['processed_source_ids']:
        assert (store.db.messages.find_one({'_id': source})
                or store.db.messages.find_one({'platform_event_id': source})), source
    logged = cases.audit_of(store, 'understanding.result')
    assert logged[-1]['payload']['auto_source_ids'] == [cases.SUMMARY], logged


def test_summary_not_shown_this_turn_is_not_cited(store):
    cases.seed_real(store)
    result = MemoryService(store).commit_understanding(
        cases.episode(selected=[]), '先记着，不催。')
    assert result['state'] == 'COMMITTED', result
    assert result['auto_source_ids'] == [] and result['source_ids'] == [cases.MONO], result


def test_expected_conflicts_are_audited_and_do_not_raise(store):
    '''同一批原文重跑与头版本被推前，都降级成 NOT_COMMITTED，不把本轮打成 FAILED_RUNTIME。'''
    cases.seed_real(store)
    service = MemoryService(store)
    assert service.commit_understanding(cases.episode(), '第一版。')['state'] == 'COMMITTED'
    moved = cases.head_pair(store)[0]['revision_id']
    stale = service.commit_understanding(cases.episode(base='rev-rel-0', ep_id='ep9'), '第二版。')
    assert stale['state'] == 'NOT_COMMITTED' and 'BASE_REVISION_STALE' in stale['reason'], stale
    assert cases.head_pair(store)[0]['revision_id'] == moved, '被拒的提交不许动头版本'
    assert cases.audit_of(store, 'understanding.result')[-1]['payload']['state'] == 'NOT_COMMITTED'


def test_summary_reaches_next_turn_context(store):
    cases.seed_real(store)
    _system, context, manifest = cases.prepare(store)
    entry = next((m for m in context['memories'] if m['_id'] == cases.SUMMARY), None)
    assert entry, context['memories']
    assert entry['kind'] == 'dialogue_summary', entry
    assert entry['epistemic_type'] == 'derived_summary', entry
    assert entry['source_window'] == [7, 8], entry
    assert entry['source_event_ids'] == [cases.INBOUND, cases.OUTBOUND], entry
    assert cases.SUMMARY in manifest['selected']
    assert 'derived_summary' in context['memory_source_rules']
    assert 'derived_summary' in context['understanding_update_from_program']['route']
    assert manifest['relationship_revision'] == 'rev-rel-0', '读取腿不改关系口径'


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
    assert saved['participants'] == sorted([cases.PERSON, cases.PERSON_B, 'xiaoman']), saved
    assert saved['source_by_speaker'][cases.PERSON] == ['in-grp-1-11', 'in-grp-1-14'], saved
    assert saved['attribution']['corrections'][0]['target_resolution'] == 'reply_link', saved
    assert saved['trigger']['signals'], saved
    assert store.db.audit_events.find_one({'type': 'summary.saved'}), evidence.kinds()
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


def test_group_trigger_fires_on_its_own_pause(store):
    """真行上的节奏画像：还在说话不动手，安静过本场景停顿线才动手。"""
    cases.seed_real(store, cases.group_rows())
    pending = list(store.db.messages.find(
        {'scene_id': cases.GROUP, 'summary_batch_id': {'$exists': False}}).sort('scene_seq', 1))
    _profile, mid = _decide(store, cases.GROUP, cases.T0 + 50)
    assert not mid['fire'] and mid['hold'] == 'scene_still_talking', mid
    profile, fired = _decide(store, cases.GROUP, cases.T0 + 95)
    assert fired['fire'] and 'pause_anomalous' in fired['signals'], fired
    assert profile['quiet_source'] == 'observed' and profile['samples'] >= 2, profile
    assert not cases.legacy_rule(pending, cases.T0 + 95, cases.T0), '反证：旧口径这会儿还在等第 4 条'


def test_slow_dialogue_is_not_interrupted_on_real_store(store):
    """半小时一条的私聊：旧口径那 120 秒在这儿会抢话，本场景自己的停顿线说还得等。"""
    cases.seed_real(store, cases.slow_rows())
    _profile, decision = _decide(store, cases.SLOW, cases.T0)
    assert not decision['fire'] and decision['hold'] == 'scene_still_talking', decision
    assert decision['quiet_after'] > 1000, decision


def test_summary_covering_someone_else_is_not_cited_on_real_store(store):
    """只盖了 B 的摘要：A 那轮看得见但不算 A 的证据；B 那轮照常算。"""
    data = cases.group_rows()
    data['messages'] = data['messages'] + [cases.correction_row()]   # 独白的来源根要真存在
    cases.seed_real(store, data)
    cases.add_row(store, 'memory_units', cases._summary_unit(
        'summary-b-only', '小舟说他去，工具他带。', ['in-grp-1-12'],
        [cases.PERSON_B, 'xiaoman'], [12, 12]))
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


def test_correction_marks_earlier_summary_on_real_store(store):
    """更正指向已被旧摘要盖住的原文：旧条目只追加 corrected_by，正文不动，来源记为 stale。"""
    cases.seed_real(store, cases.stale_summary_rows())
    saved, evidence, _lane = _tick_group(store)
    assert saved and saved['source_window'] == [12, 14], saved
    old = store.db.memory_units.find_one({'_id': 'summary-old'})
    assert old['corrected_by'] == ['in-grp-1-14'], old
    assert old['body_markdown'] == '老陈说他周三去修雾灯。', old
    assert old['revision'] == 2, '只追加标注：版本推前一次'
    assert store.db.audit_events.find_one({'type': 'summary.corrected'}), evidence.kinds()
    cases.add_row(store, 'memory_units', cases.monologue_unit(cases.PERSON, 'ep-g1'))
    result = MemoryService(store).commit_understanding(
        cases.group_episode(cases.PERSON, selected=['summary-old']), '他改周五了，旧那句只当历史。')
    assert result['auto_source_ids'] == ['summary-old'], result
    assert result['auto_stale_source_ids'] == ['summary-old'], result


def test_indexer_hands_every_scene_to_the_summarizer_on_real_store(store):
    """接线：本机场景与每个授权群都交给摘要器；线程没 start 之前不动任何场景。"""
    store.config['embedding'] = {'base_url': 'http://stub/v1', 'model': 'stub', 'dimensions': 768}
    indexer = MemoryIndexer(store, cases.FakeEvidence(), [cases.SCENE, cases.GROUP],
                            summary_lane=cases.FakeLane(),
                            summary_scenes=[cases.SCENE, cases.GROUP])
    assert indexer.summarizer.scene_ids == [cases.SCENE, cases.GROUP], indexer.summarizer.scene_ids
    assert not indexer.worker.is_alive(), '构造不该把后台线程拉起来'
    legacy = MemoryIndexer(store, cases.FakeEvidence(), cases.SCENE, summary_lane=cases.FakeLane(),
                           summary_scene=cases.SCENE)
    assert legacy.summarizer.scene_ids == [cases.SCENE], '旧接线参数还得能用'


def test_outbound_timing_falls_back_to_sink_receipt_on_real_store(store):
    """真库那一层的出站时间：行内没 receipt_at 也要经送达回执算成“说过的话”，没送达的不算。"""
    rows = [cases._in(cases.GROUP, 11, cases.PERSON, '雾灯周三去修', cases.T0),
            cases._out(cases.GROUP, 12, '那我记周三', cases.T0 + 20, receipt_at=None,
                       receipt={'_id': 'rcpt-12'}, delivery_state='DELIVERED'),
            cases._out(cases.GROUP, 13, '还在排队', cases.T0 + 30, delivery_state='SENT')]
    data = cases.group_rows(messages=rows)
    data['messages'] = rows
    cases.seed_real(store, data)
    store.put('sink_receipts', {'_id': 'rcpt-12', 'received_at': cases._iso(cases.T0 + 45),
                                'revision': 1}, stream='p2')
    scene = store.db.scenes.find_one({'_id': cases.GROUP})
    profile = summary_trigger.observe(store, scene, now_ts=cases.T0 + 300)
    assert profile['rows_without_time'] == 0, profile      # 缺内联回执不等于没有时间
    assert profile['observed_rows'] == 2, profile           # SENT 那条不算说过
    assert sorted(profile['times']) == [11, 12], profile
    assert profile['sink_note'] == '', profile


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
