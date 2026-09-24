#!/usr/bin/env python3
"""ADR-005 P2 边界自测：拿真代码在假集合上撞边界，不撞运气。

覆盖六组：自适应节奏（MAD／Settle 闸的极端分布）、冷启动、多人与同名归属、
跨批次更正与找不到回复对象、来源隔离、失败后继续。跑的是仓库里那份
summary_trigger／summary_attribution／DialogueSummarizer／MemoryService，假集合真算。
这里不冒充真 Mongo 证据：真驱动、真集合校验、真 CAS 那一层由操作员在隔离库跑
 tests/test_p2_summary_loop.py。本机 python3 tools/p2b_edge_probe.py 直接跑。
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'tests'))
sys.path.insert(0, os.path.join(ROOT, 'src'))

import p2_summary_loop_cases as cases                                   # noqa: E402
from asuna import summary_attribution, summary_trigger                  # noqa: E402
from asuna.dialogue_summary import DialogueSummarizer                   # noqa: E402
from asuna.memory import MemoryService                                  # noqa: E402
from asuna.state import Conflict                                        # noqa: E402

T0 = cases.T0
PERSON, PERSON_B, XIAOMAN = cases.PERSON, cases.PERSON_B, 'xiaoman'
CHECKS = []


def check(label):
    def decorate(fn):
        CHECKS.append((label, fn))
        return fn
    return decorate


def scaffold(scene_id, rows, persons=(PERSON,), kind='group', names=None, sequence=None):
    data = cases._scaffold(scene_id, kind, list(persons), list(rows), 0,
                           sequence if sequence is not None
                           else max([row.get('scene_seq', 0) for row in rows] or [0]))
    for person, display in (names or {}).items():
        row = {'_id': person, 'person_id': person, 'platform': 'qq',
               'account_id': 'acct-' + person.replace(':', ''), 'display_name': display,
               'revision': 1}
        for index, existing in enumerate(data['identities']):
            if existing['_id'] == person:
                data['identities'][index] = row
                break
        else:
            data['identities'].append(row)
    return data


def store_of(data):
    return cases.bind_store(data)


def paced(scene_id, gaps, authors=(PERSON,), text='雾灯这事先这么定 %d', start_seq=1, at=T0,
          overrides=None):
    """按给定间隔造一串入站行：gaps[i] 是第 i 条相对上一条的延迟（第一条相对 at）。"""
    rows, moment = [], float(at)
    for index, gap in enumerate(gaps):
        moment += gap
        row = cases._in(scene_id, start_seq + index, authors[index % len(authors)],
                        text % index if '%d' in text else text, moment,
                        **(overrides or {}).get(index, {}))
        rows.append(row)
    return rows


def profile_of(store, scene_id, moment):
    return summary_trigger.observe(store, store.db.scenes.find_one({'_id': scene_id}),
                                   now_ts=moment)


def decide(store, scene_id, pending, moment, pooled=None, window=DialogueSummarizer.WINDOW_ROWS):
    profile = profile_of(store, scene_id, moment)
    return profile, summary_trigger.decide(profile, pending, pooled_prior=pooled, now_ts=moment,
                                           window_rows=window)


def last_at(rows):
    return max(row['_at'] for row in rows) if '_at' in rows[0] else None


def at_of(row):
    from datetime import datetime
    return datetime.fromisoformat(row['occurred_at']).timestamp()


def summarizer_for(store, scenes, lane=None, moment=None, can_run=lambda: True):
    lane = lane or cases.FakeLane()
    return DialogueSummarizer(store, cases.FakeEvidence(), lane, list(scenes), can_run,
                              clock=lambda: T0 + 95 if moment is None else moment), lane


# ── A 自适应节奏：MAD 与 Settle 闸的极端分布 ─────────────────────────
@check('A1 全等间隔（MAD=0）：停顿线就是那个间隔，不被离散度放大')
def a1():
    rows = paced('grp-even', [0] + [30] * 9, authors=(PERSON, PERSON_B))
    store = store_of(scaffold('grp-even', rows, names={PERSON: '老陈', PERSON_B: '小舟'}))
    profile = profile_of(store, 'grp-even', T0 + 300)
    assert profile['quiet_after'] == 30.0 and profile['samples'] == 9, profile
    assert profile['burst_rows'] == 10 and profile['quiet_source'] == 'observed', profile
    return '间隔恒定 30 秒的场景，停顿线算成 30 秒、典型一簇 10 条'


@check('A2 双峰节奏（一半秒回一半隔半小时）：不被快片段带成抢话')
def a2():
    rows = paced('grp-bi', [0, 5, 3000, 5, 3000, 5, 3000], authors=(PERSON, PERSON_B))
    store = store_of(scaffold('grp-bi', rows))
    profile = profile_of(store, 'grp-bi', T0 + 9015)
    assert profile['quiet_after'] > 1000, profile
    return '两种节奏混在一起时停顿线落在中间偏慢（%.0fs），快片段不触发整理' % profile['quiet_after']


@check('A3 一条隔夜离群间隔不带走停顿线（用中位数+MAD 而不是均值）')
def a3():
    rows = paced('grp-out', [0] + [10] * 7 + [259200], authors=(PERSON, PERSON_B))
    store = store_of(scaffold('grp-out', rows))
    profile = profile_of(store, 'grp-out', T0 + 259270)
    assert profile['quiet_after'] == 20.0, profile          # 中位数 10 秒 → 钳到下界
    assert max(profile['peer_gaps']) > 250000, profile      # 离群那条照实留着，看得见
    return '三条里夹一条隔三天的，停顿线仍按这个群的日常 20 秒下界算'


@check('A4 极慢场景有上界兜底（不会永远不整理）')
def a4():
    rows = paced('grp-slow', [0, 259200, 259200, 259200])
    store = store_of(scaffold('grp-slow', rows))
    profile = profile_of(store, 'grp-slow', T0 + 777600)
    assert profile['quiet_after'] == summary_trigger.QUIET_CAP_SECONDS, profile
    return '三天一条的场景，停顿线钳在 6 小时上界，原文不会无限期等'


@check('A5 极快场景有下界兜底（比一轮轮转还短的停顿不打断）')
def a5():
    rows = paced('grp-fast', [0, 1, 1, 1, 1], authors=(PERSON, PERSON_B))
    store = store_of(scaffold('grp-fast', rows))
    profile = profile_of(store, 'grp-fast', T0 + 5)
    assert profile['quiet_after'] == summary_trigger.QUIET_FLOOR_SECONDS, profile
    return '一秒一条的场景，停顿线钳在 20 秒下界'


@check('A6 Settle 闸边界：差一点没说就不整理，过了半条线就整理')
def a6():
    rows = paced('grp-settle', [0, 10, 10, 10], authors=(PERSON, PERSON_B),
                 text='雾灯这事第 %d 句')
    rows[-1]['text'] = '那就这么办'
    store = store_of(scaffold('grp-settle', rows))
    pending = cases.pending_rows(store, 'grp-settle')
    end = at_of(rows[-1])
    _profile, just_before = decide(store, 'grp-settle', pending, end + 9.8)
    assert not just_before['fire'] and just_before['settled'] is False, just_before
    _profile, just_after = decide(store, 'grp-settle', pending, end + 12)
    assert just_after['fire'] and 'cluster_complete' in just_after['signals'], just_after
    return '停顿线 20 秒的场景：安静 9.8 秒不动手，12 秒（过半条线）按“一簇说完”动手'


@check('A7 时间戳跑到钟前面（时钟回拨／乱序）不炸也不整理')
def a7():
    rows = paced('grp-future', [0, 20, 20], authors=(PERSON, PERSON_B))
    rows[-1]['occurred_at'] = cases._iso(T0 + 3600)          # 最新一条“来自未来”
    store = store_of(scaffold('grp-future', rows))
    pending = cases.pending_rows(store, 'grp-future')
    _profile, decision = decide(store, 'grp-future', pending, T0 + 60)
    assert decision['silence'] < 0 and not decision['fire'], decision
    assert decision['hold'] == 'scene_still_talking', decision
    return '最新一条时间戳在钟前面时安静时长是负的：不动手，也不抛异常'


@check('A8 时间戳格式混杂：读不出的照实计数，不拿 scene_seq 冒充时间')
def a8():
    rows = paced('grp-mixed', [0, 60, 60, 60], authors=(PERSON, PERSON_B))
    rows[0]['occurred_at'] = '2026-09-24T06:00:00Z'                       # 带 Z
    rows[1]['occurred_at'] = '2026-09-24T14:01:00+08:00'                  # 带偏移
    rows[2]['occurred_at'] = '2026-09-24T06:02:00'                        # 裸时间按 UTC 认
    rows[3]['occurred_at'] = '昨天下午'                                    # 读不出来
    rows[3]['received_at'] = None
    store = store_of(scaffold('grp-mixed', rows))
    profile = profile_of(store, 'grp-mixed', T0 + 600)
    assert profile['rows_without_time'] == 1, profile
    assert profile['samples'] == 2 and profile['quiet_after'] == 60.0, profile
    return '四种时间戳混着也能算：一条读不出被计数，其余三支照常参与节奏归纳'


@check('A9 只有角色自己说过话（对方从没开口）也能归纳节奏')
def a9():
    rows = [cases._in('dm-only', 1, PERSON, '先这样', T0)] + \
           [cases._out('dm-only', 2 + index, '收到 %d' % index, T0 + 60 * (index + 1))
            for index in range(3)]
    store = store_of(scaffold('dm-only', rows, kind='dm'))
    profile = profile_of(store, 'dm-only', T0 + 300)
    assert profile['quiet_source'] == 'observed' and profile['samples'] >= 2, profile
    return '对方只说了一句的场景退回全量间隔，不至于算不出停顿线'


@check('A10 待整理积压超出观察窗口：按下界算等待时长，不假装知道')
def a10():
    rows = paced('grp-backlog', [0] + [10] * 129, authors=(PERSON, PERSON_B))
    for index, row in enumerate(rows):                      # 前 20 条没整理，其余已整理
        if index >= 20:
            row['summary_batch_id'] = 'summary-old'
    store = store_of(scaffold('grp-backlog', rows))
    pending = cases.pending_rows(store, 'grp-backlog')
    assert len(pending) == 20, len(pending)
    _profile, decision = decide(store, 'grp-backlog', pending, T0 + 1300)
    assert decision['pending_times_missing'] == 10, decision   # 120 行窗口外还有 10 条
    assert decision['pending_age'] >= 1200 and 'window_full' in decision['signals'], decision
    return '积压比观察窗口还老时，等待时长按最早看到的那一刻下界算，并靠窗口上限切批'


@check('A11 空场景：没原文就没决定，不编一个触发点')
def a11():
    store = store_of(scaffold('grp-empty', []))
    profile = profile_of(store, 'grp-empty', T0)
    assert profile['samples'] == 0 and profile['quiet_after'] is None, profile
    _profile, decision = decide(store, 'grp-empty', [], T0)
    assert not decision['fire'] and decision['hold'] == 'nothing_pending', decision
    return '零行场景：停顿线是 None 而不是某个默认数'


@check('A12 没送达的出站既不进摘要也不参与节奏（排队／失败不算说过的话）')
def a12():
    rows = [cases._in('grp-send', 1, PERSON, '雾灯周三修', T0),
            cases._out('grp-send', 2, '好', T0 + 10, delivery_state='SENT'),
            cases._out('grp-send', 3, '那就周三', T0 + 20, delivery_state='DELIVERED')]
    store = store_of(scaffold('grp-send', rows))
    scene = store.db.scenes.find_one({'_id': 'grp-send'})
    summarizer, lane = summarizer_for(store, ['grp-send'])
    pending = summarizer._pending(scene)
    assert [row['_id'] for row in pending] == ['in-grp-send-1', 'grp-send:speak:3'], pending
    assert profile_of(store, 'grp-send', T0 + 30)['observed_rows'] == 2, 'SENT 那条不该被当说过'
    return 'delivery_state=SENT 的出站被排除在来源与节奏之外'


@check('B1 全新场景只有一条碎片：先验值不为一句话动手')
def b1():
    rows = paced('grp-cold1', [0])
    rows[0]['occurred_at'] = cases._iso(T0 - 300)
    store = store_of(scaffold('grp-cold1', rows))
    _profile, decision = decide(store, 'grp-cold1', cases.pending_rows(store, 'grp-cold1'), T0)
    assert decision['hold'] == 'cold_start_needs_more_than_a_fragment', decision
    assert decision['quiet_source'] == 'seed', decision
    return '没有任何间隔可看的场景，先验值选择再等等'


@check('B2 冷启动攒够两条（其中一条时间戳读不出）：先验值也能动，并照实报缺')
def b2():
    rows = paced('grp-cold2', [0, 10], authors=(PERSON, PERSON_B))
    rows[0]['occurred_at'] = '昨天下午'
    rows[0]['received_at'] = None
    store = store_of(scaffold('grp-cold2', rows))
    _profile, decision = decide(store, 'grp-cold2', cases.pending_rows(store, 'grp-cold2'), T0 + 700)
    assert decision['fire'] and decision['quiet_source'] == 'seed', decision
    assert decision['pending_times_missing'] == 1 and decision['rows_without_time'] == 1, decision
    return '先验值不是禁令：攒够两条就整理，读不出的时间戳在决定里带得清清楚楚'


@check('B3 冷启动借同部署别的场景的实测节奏（pooled_prior 顶掉先验）')
def b3():
    donor = store_of(scaffold('grp-donor', paced('grp-donor', [0] + [30] * 5,
                                                authors=(PERSON, PERSON_B))))
    prior = summary_trigger.pooled({'grp-donor': profile_of(donor, 'grp-donor', T0 + 180)},
                                   exclude='grp-new')
    assert prior and prior['quiet_after'] == 30.0 and prior['source'] == 'pooled_prior', prior
    rows = paced('grp-new', [0])
    rows[0]['occurred_at'] = cases._iso(T0 - 300)
    store = store_of(scaffold('grp-new', rows))
    _profile, decision = decide(store, 'grp-new', cases.pending_rows(store, 'grp-new'), T0,
                                pooled=prior)
    assert decision['fire'] and decision['quiet_source'] == 'pooled_prior', decision
    return '新场景一句“在吗”不动手，但同部署已经实测到 30 秒节奏后按 30 秒判'


@check('B4 只有一个场景可看时不跟自己借先验')
def b4():
    donor = store_of(scaffold('grp-solo', paced('grp-solo', [0, 30, 30], authors=(PERSON, PERSON_B))))
    assert summary_trigger.pooled({'grp-solo': profile_of(donor, 'grp-solo', T0 + 90)},
                                  exclude='grp-solo') is None
    return 'pooled 把自己排除后没有别的样本就返回 None，不拿自己的分布冒充“别人的”先验'


@check('B5 不是 dm／group 的场景：摘要器一眼不看，也不写任何东西')
def b5():
    store = store_of(scaffold('ch-1', paced('ch-1', [0, 10, 10]), kind='channel'))
    summarizer, lane = summarizer_for(store, ['ch-1'])
    summarizer.initialize()
    assert summarizer.tick('ch-1') is None and lane.calls == [], lane.calls
    assert store.db.audit_events.rows == {} or not any(
        row['type'].startswith('summary.') for row in store.db.audit_events.rows.values())
    return '未支持的场景 kind 直接跳过：不整理、不调模型、不留证据'


@check('B6 没设起点线的场景：initialize 补上，tick 之前不会乱整理历史')
def b6():
    data = scaffold('grp-nostart', paced('grp-nostart', [0, 10, 10], authors=(PERSON, PERSON_B)))
    data['scenes'][0].pop('summary_start_seq')
    store = store_of(data)
    summarizer, lane = summarizer_for(store, ['grp-nostart'])
    assert summarizer.tick('grp-nostart') is None, '起点线没定就不该动'
    summarizer.initialize()
    scene = store.db.scenes.find_one({'_id': 'grp-nostart'})
    assert scene['summary_start_seq'] == data['scenes'][0]['sequence'], scene
    summarizer.initialize()                      # 再跑一次不重复写
    assert store.db.scenes.find_one({'_id': 'grp-nostart'})['revision'] == scene['revision']
    return '启动只把起点线定在当前末尾，不把上线前的历史一次性灌进模型'


# ── C 多人、同名、缺资料的归属 ───────────────────────────
def attribution_of(store, scene_id, rows):
    return summary_attribution.attribute(store, store.db.scenes.find_one({'_id': scene_id}), rows)


@check('C1 两个人同名：归属仍按 person_id 分开，给模型的顺句标签也不合并')
def c1():
    rows = [cases._in('grp-same', 1, PERSON, '雾灯周三去修', T0),
            cases._in('grp-same', 2, 'qq:B1', '我去', T0 + 25),
            cases._in('grp-same', 3, 'qq:C1', '我也去', T0 + 40)]
    store = store_of(scaffold('grp-same', rows, persons=(PERSON, 'qq:B1', 'qq:C1'),
                              names={PERSON: '老陈', 'qq:B1': '小舟', 'qq:C1': '小舟'}))
    saved, lane, _s = tick(store, 'grp-same')
    assert saved and saved['participants'] == sorted([PERSON, 'qq:B1', 'qq:C1']), saved
    assert sorted(saved['source_by_speaker']) == sorted([PERSON, 'qq:B1', 'qq:C1']), saved
    assert '小舟（qq:B1）' in lane.calls[0]['text'], lane.calls[0]['text']
    assert '小舟（qq:C1）' in lane.calls[0]['text'], '同名必须带 person_id，否则两个人会长成一个'
    return '两个“小舟”在条目里是两个 person_id，送进模型的标签也各自带 ID'


@check('C2 行上缺 author：照实记 unknown，不摊到别人头上')
def c2():
    rows = [cases._in('grp-noauth', 1, PERSON, '雾灯周三去修', T0),
            cases._in('grp-noauth', 2, PERSON_B, '我去', T0 + 25)]
    del rows[1]['author']
    store = store_of(scaffold('grp-noauth', rows, persons=(PERSON, PERSON_B)))
    result = attribution_of(store, 'grp-noauth', rows)
    assert 'unknown' in result['participants'] and None not in result['participants'], result
    assert result['source_by_speaker']['unknown'] == ['in-grp-noauth-2'], result
    assert summary_attribution.covers_person(store, {'participants': result['participants'],
                                                     'source_event_ids': []},
                                             PERSON_B) == (False, 'person_not_in_participants')
    return '缺 author 的那条进 unknown，不会被当成当前说话人说过什么'


@check('C3 身份表没有这个人：标签退回 person_id，不编显示名')
def c3():
    rows = [cases._in('grp-noid', 1, PERSON, '雾灯周三去修', T0),
            cases._in('grp-noid', 2, 'qq:Z1', '我去', T0 + 25)]
    store = store_of(scaffold('grp-noid', rows, persons=(PERSON, 'qq:Z1')))
    summarizer, _lane = summarizer_for(store, ['grp-noid'])
    labels = summarizer._labels(rows)
    assert labels['qq:Z1'] == 'qq:Z1' and labels[PERSON] == '老陈', labels
    return '身份表缺行时用 person_id，不拿昵称凑数'


@check('C4 单说话人批次：不查身份、不标多主体')
def c4():
    rows = paced('grp-single', [0, 20, 20])
    store = store_of(scaffold('grp-single', rows))
    summarizer, _lane = summarizer_for(store, ['grp-single'])
    assert summarizer._labels(rows) == {}, '一个人说话没必要带标签'
    assert attribution_of(store, 'grp-single', rows)['multi_speaker'] is False
    return '私聊里不产生多主体噪声，也不为标签去读身份表'


@check('C5 更正带的 reply 指向不存在的行：照实说取不到，不猜被推翻的是哪句')
def c5():
    rows = [cases._in('grp-miss', 1, PERSON, '雾灯周三去修', T0),
            cases._in('grp-miss', 2, PERSON, '更正一下：改周五', T0 + 30,
                      {'group_context': {'reply_message_id': 'in-nowhere-99',
                                         'reply_to': None, 'topic_id': None,
                                         'mentioned_account_ids': []}})]
    store = store_of(scaffold('grp-miss', rows))
    fix = attribution_of(store, 'grp-miss', rows)['corrections'][0]
    assert fix['corrects'] is None, fix
    assert fix['target_resolution'] == 'reply_link_unresolved', fix   # 引用带在行上，但落不到行
    assert fix['actor'] == PERSON and fix['cue'] == '更正', fix
    return '回复对象取不到时只记“有人更正了”，不替角色指哪句被推翻'


@check('C6 只有平台消息 ID 的回复也能认定对象（标成按平台 ID）')
def c6():
    rows = [dict(cases._in('grp-plat', 1, PERSON, '雾灯周三去修', T0), platform_message_id='msg-77'),
            cases._in('grp-plat', 2, PERSON, '更正一下：改周五', T0 + 30,
                      {'group_context': {'reply_to': 'msg-77', 'topic_id': None,
                                         'mentioned_account_ids': []}})]
    store = store_of(scaffold('grp-plat', rows))
    fix = attribution_of(store, 'grp-plat', rows)['corrections'][0]
    assert fix['corrects'] == 'in-grp-plat-1' and fix['in_batch'] is True, fix
    assert fix['target_resolution'] == 'reply_link_by_platform_id', fix
    return '宿主没绑消息 _id 时退回平台 ID，认定依据写清是哪一个'


@check('C7 更正的是角色自己说过的话：对象是 xiaoman，不算自我更正')
def c7():
    rows = [cases._in('grp-self', 1, PERSON, '雾灯周三去修', T0),
            cases._out('grp-self', 2, '那我记周三', T0 + 20),
            cases._in('grp-self', 3, PERSON, '更正一下：别记周三', T0 + 40,
                      {'group_context': {'reply_message_id': 'grp-self:speak:2',
                                         'reply_to': None, 'topic_id': None,
                                         'mentioned_account_ids': []}})]
    store = store_of(scaffold('grp-self', rows))
    fix = attribution_of(store, 'grp-self', rows)['corrections'][0]
    assert fix['corrects'] == 'grp-self:speak:2' and fix['target_author'] == XIAOMAN, fix
    assert fix['self_correction'] is False, fix
    return '更正小满自己说过的话，不会被写成“某人更正了自己”'


@check('C8 两条更正指向同一句旧话：旧摘要上的标注合并去重、有界')
def c8():
    rows = [dict(cases._in('grp-two', 11, PERSON, '雾灯周三去修', T0), summary_batch_id='summary-old'),
            cases._in('grp-two', 12, PERSON, '更正一下：改周五', T0 + 30,
                      {'group_context': {'reply_message_id': 'in-grp-two-11', 'reply_to': None,
                                         'topic_id': None, 'mentioned_account_ids': []}}),
            cases._in('grp-two', 13, PERSON, '再更正一次：还是周三', T0 + 60,
                      {'group_context': {'reply_message_id': 'in-grp-two-11', 'reply_to': None,
                                         'topic_id': None, 'mentioned_account_ids': []}})]
    data = scaffold('grp-two', rows, persons=(PERSON,))
    data['memory_units'] = [cases._summary_unit('summary-old', '老陈说周三去修雾灯。',
                                                ['in-grp-two-11'], [PERSON, XIAOMAN], [11, 11])]
    store = store_of(data)
    scene = store.db.scenes.find_one({'_id': 'grp-two'})
    items = summary_attribution.corrections(store, scene, rows[1:])
    applied = summary_attribution.annotate_corrected(store, scene, items, 'summary-new')
    old = store.db.memory_units.find_one({'_id': 'summary-old'})
    assert old['corrected_by'] == ['in-grp-two-12', 'in-grp-two-13'], old
    assert len(applied) == 2 and len({row['corrected_by'][-1] for row in applied}) == 2, applied
    return '两条更正都追加到那条旧摘要上，去重且按消息 ID 排序'


@check('C9 回复引用指向别的场景的行：不跨场景认定对象')
def c9():
    rows = [cases._in('grp-here', 1, PERSON, '先说个别的', T0),
            cases._in('grp-here', 2, PERSON, '更正一下：改周五', T0 + 30,
                      {'group_context': {'reply_message_id': 'in-grp-there-1', 'reply_to': None,
                                         'topic_id': None, 'mentioned_account_ids': []}})]
    data = scaffold('grp-here', rows)
    data['messages'].append(cases._in('grp-there', 1, PERSON_B, '那是另一个群的事', T0))
    data['scenes'].append(cases._scene('grp-there', 'group', [PERSON_B, XIAOMAN], 0, 1))
    store = store_of(data)
    fix = attribution_of(store, 'grp-here', rows)['corrections'][0]
    assert fix['corrects'] is None and fix['target_resolution'] == 'reply_link_unresolved', fix
    return '另一个场景里确实有这条行，但本场景的摘要不拿它当对象（不跨场景串）'


@check('C10 回复指向自己这条：不算更正对象，也不崩')
def c10():
    rows = [cases._in('grp-same_ref', 1, PERSON, '先说个别的', T0),
            cases._in('grp-same_ref', 2, PERSON, '更正一下：我重说', T0 + 30,
                      {'group_context': {'reply_message_id': 'in-grp-same_ref-2', 'reply_to': None,
                                         'topic_id': None, 'mentioned_account_ids': []}})]
    store = store_of(scaffold('grp-same_ref', rows))
    fix = attribution_of(store, 'grp-same_ref', rows)['corrections'][0]
    assert fix['corrects'] is None and fix['target_resolution'] == 'self_reference_to_self', fix
    return '自己引用自己时照实标出来，不把这条行写成被自己推翻'


@check('C11 没有 reply 链但明说“刚才那句”：退回同一人前一条并标低置信')
def c11():
    rows = [cases._in('grp-selfref', 1, PERSON, '雾灯周三去修', T0),
            cases._in('grp-selfref', 2, PERSON_B, '我去', T0 + 20),
            cases._in('grp-selfref', 3, PERSON, '更正一下，刚才那句改周五', T0 + 40)]
    store = store_of(scaffold('grp-selfref', rows, persons=(PERSON, PERSON_B)))
    fix = attribution_of(store, 'grp-selfref', rows)['corrections'][0]
    assert fix['corrects'] == 'in-grp-selfref-1', fix
    assert fix['target_resolution'] == 'same_author_previous_in_batch', fix
    assert fix['self_correction'] is True and fix['in_batch'] is True, fix
    return '宿主没给引用结构时按“同一人前一条”兜底，并把依据标成低置信'


def tick(store, scene_id, moment=T0 + 95, lane=None, can_run=lambda: True):
    summarizer, lane = summarizer_for(store, [scene_id], lane=lane, moment=moment,
                                      can_run=can_run)
    return summarizer.tick(scene_id), lane, summarizer


# ── D 跨批次更正与重跑 ────────────────────────────────
@check('D1 更正晚于原摘要两批：只回标那条旧条目，新摘要自己带 in_batch 标记')
def d1():
    rows = [dict(cases._in('grp-late', 11, PERSON, '雾灯周三去修', T0 - 86400),
                 summary_batch_id='summary-old'),
            cases._in('grp-late', 20, PERSON_B, '我去', T0),
            cases._in('grp-late', 21, XIAOMAN and PERSON, '那我记周三', T0 + 25),
            cases._in('grp-late', 22, PERSON, '更正一下：改周五', T0 + 40,
                      {'group_context': {'reply_message_id': 'in-grp-late-11', 'reply_to': None,
                                         'topic_id': None, 'mentioned_account_ids': []}})]
    rows[2]['author'] = PERSON
    data = scaffold('grp-late', rows, persons=(PERSON, PERSON_B))
    data['memory_units'] = [cases._summary_unit('summary-old', '老陈说周三去修雾灯。',
                                                ['in-grp-late-11'], [PERSON, XIAOMAN], [11, 11])]
    store = store_of(data)
    saved, _lane, _s = tick(store, 'grp-late')
    assert saved and saved['source_window'] == [20, 22], saved
    fix = saved['attribution']['corrections'][0]
    assert fix['corrects'] == 'in-grp-late-11' and fix['in_batch'] is False, fix
    old = store.db.memory_units.find_one({'_id': 'summary-old'})
    assert old['corrected_by'] == ['in-grp-late-22'] and old['revision'] == 2, old
    assert old['body_markdown'] == '老陈说周三去修雾灯。', '旧转述正文一个字都不改'
    return '两批之后的更正只给旧条目追加更正标注，历史照原样留着'


@check('D2 同一批里的更正不回标旧条目（这条摘要自己就写清了）')
def d2():
    rows = [cases._in('grp-inbatch', 1, PERSON, '雾灯周三去修', T0),
            cases._in('grp-inbatch', 2, PERSON_B, '我去', T0 + 25),
            cases._in('grp-inbatch', 3, PERSON, '更正一下：改周五', T0 + 40,
                      {'group_context': {'reply_message_id': 'in-grp-inbatch-1', 'reply_to': None,
                                         'topic_id': None, 'mentioned_account_ids': []}})]
    store = store_of(scaffold('grp-inbatch', rows, persons=(PERSON, PERSON_B)))
    saved, _lane, _s = tick(store, 'grp-inbatch')
    assert saved['attribution']['corrections'][0]['in_batch'] is True, saved
    assert 'corrected_by' not in saved, '本批更正不需要回标，也不该给自己挂 stale 标记'
    return '同一批里的更正由这条摘要自己承担，不产生多余的回标'


@check('D3 旧摘要已失效（tombstone）：不回标，也不报错')
def d3():
    rows = [dict(cases._in('grp-dead', 11, PERSON, '雾灯周三去修', T0 - 86400),
                 summary_batch_id='summary-dead'),
            cases._in('grp-dead', 20, PERSON, '更正一下：改周五', T0,
                      {'group_context': {'reply_message_id': 'in-grp-dead-11', 'reply_to': None,
                                         'topic_id': None, 'mentioned_account_ids': []}})]
    data = scaffold('grp-dead', rows)
    unit = cases._summary_unit('summary-dead', '老陈说周三去修雾灯。', ['in-grp-dead-11'],
                               [PERSON, XIAOMAN], [11, 11])
    unit['status'] = 'tombstone'
    data['memory_units'] = [unit]
    store = store_of(data)
    scene = store.db.scenes.find_one({'_id': 'grp-dead'})
    items = summary_attribution.corrections(store, scene, rows[1:])
    assert summary_attribution.annotate_corrected(store, scene, items, 'summary-new') == []
    assert 'corrected_by' not in store.db.memory_units.find_one({'_id': 'summary-dead'})
    return '已失效的条目不再被追加标注'


@check('D4 回标时撞上并发修改（CAS 失败）：跳过不硬来，也不打断本轮')
def d4():
    rows = [dict(cases._in('grp-cas', 11, PERSON, '雾灯周三去修', T0 - 86400),
                 summary_batch_id='summary-old'),
            cases._in('grp-cas', 20, PERSON, '更正一下：改周五', T0,
                      {'group_context': {'reply_message_id': 'in-grp-cas-11', 'reply_to': None,
                                         'topic_id': None, 'mentioned_account_ids': []}})]
    data = scaffold('grp-cas', rows)
    data['memory_units'] = [cases._summary_unit('summary-old', '老陈说周三去修雾灯。',
                                                ['in-grp-cas-11'], [PERSON, XIAOMAN], [11, 11])]
    store = store_of(data)
    scene = store.db.scenes.find_one({'_id': 'grp-cas'})
    items = summary_attribution.corrections(store, scene, rows[1:])
    original = store.put

    def racing(collection, doc, *, expected=None, stream='x'):
        if collection == 'memory_units' and doc.get('corrected_by'):
            raise Conflict('STALE_REVISION')
        return original(collection, doc, expected=expected, stream=stream)
    store.put = racing
    assert summary_attribution.annotate_corrected(store, scene, items, 'summary-new') == []
    store.put = original
    assert 'corrected_by' not in store.db.memory_units.find_one({'_id': 'summary-old'})
    return '有人同时在动那条旧摘要时跳过回标：下一轮还会看见这条更正，不硬写也不抛'


@check('D5 同一批重跑不重复调模型，也不重复标记')
def d5():
    rows = [cases._in('grp-twice', 1, PERSON, '雾灯周三去修', T0),
            cases._in('grp-twice', 2, PERSON_B, '我去', T0 + 25),
            cases._in('grp-twice', 3, PERSON, '那就这么定', T0 + 40)]
    store = store_of(scaffold('grp-twice', rows, persons=(PERSON, PERSON_B)))
    saved, lane, _s = tick(store, 'grp-twice')
    again, lane2, _s2 = tick(store, 'grp-twice', lane=lane)
    assert saved and again is None, '第二批还没攒起来，不该再整理一次'
    assert len(lane.calls) == 1, lane.calls
    marked = {store.db.messages.find_one({'_id': row['_id']})['summary_batch_id'] for row in rows}
    assert marked == {saved['_id']}, marked
    return '重复 tick 不会把同一段话讲两遍'


@check('D6 崩在标记之前（摘要已存、原文没标）：下次先补标记，不重新整理一遍')
def d6():
    rows = [cases._in('grp-crash', 1, PERSON, '雾灯周三去修', T0),
            cases._in('grp-crash', 2, PERSON_B, '我去', T0 + 25),
            cases._in('grp-crash', 3, PERSON, '那就这么定', T0 + 40)]
    data = scaffold('grp-crash', rows, persons=(PERSON, PERSON_B))
    store = store_of(data)
    saved, lane, _s = tick(store, 'grp-crash')
    for row in rows:
        current = store.db.messages.find_one({'_id': row['_id']})
        store.put('messages', {k: v for k, v in current.items() if k != 'summary_batch_id'},
                  expected=current['revision'], stream='crash')
    store.db.memory_units.rows[saved['_id']]['_id'] = saved['_id']
    again, lane2, _s2 = tick(store, 'grp-crash', lane=lane)
    assert again is None and len(lane.calls) == 1, '恢复期不该再调一次模型'
    assert all(store.db.messages.find_one({'_id': row['_id']})['summary_batch_id'] == saved['_id']
               for row in rows), '补标记要补齐'
    return '崩溃恢复按原口径：先补来源标记，同一条原文不会被讲两遍'


# ── E 来源隔离 ────────────────────────────────────
def dm_store(extra_units=()):
    data = cases.rows()
    data['memory_units'] = data['memory_units'] + list(extra_units)
    return store_of(data)


def unit(unit_id, **fields):
    base = {'_id': unit_id, 'kind': 'dialogue_summary', 'scope_key': cases.SCOPE,
            'policy_epoch': cases.EPOCH, 'character_id': 'xiaoman',
            'epistemic_type': 'derived_summary', 'status': 'active',
            'body_markdown': '一段转述。', 'source_event_ids': [cases.INBOUND],
            'scene_id': cases.SCENE, 'source_window': [7, 8], 'participants': [PERSON, XIAOMAN],
            'generated_at': '2026-09-24T06:05:00+00:00', 'embedding_status': 'READY', 'revision': 1}
    return dict(base, **fields)


@check('E1 别的场景／别的纪元／已失效／不是摘要 kind：一律不算这个人的来源')
def e1():
    store = dm_store([
        unit('u-other-scene', scope_key='scene:grp-1', scene_id='grp-1'),      # 群里的摘要
        unit('u-other-person-scene', scope_key='scene:dm-b'),                  # 别人的私聊
        unit('u-other-epoch', policy_epoch=cases.EPOCH + 1),
        unit('u-dead', status='tombstone'),
        unit('u-chunk', kind='chat_chunk')])
    result = MemoryService(store).commit_understanding(
        cases.episode(selected=['u-other-scene', 'u-other-person-scene', 'u-other-epoch',
                               'u-dead', 'u-chunk']), '他把日子改到周五了。')
    assert result['auto_source_ids'] == [], result
    assert result['auto_source_skipped'] == [], '跨场景的条目连展示都不该有，不该混进跳过名单'
    return '群摘要、别人的私聊、旧纪元、已失效、非摘要 kind 都进不了这条关系'


@check('E2 旧条目没有 participants：回读原文作者判定，读不到就照实说')
def e2():
    store = dm_store([
        unit('u-legacy-covers', participants=None, source_event_ids=[cases.INBOUND]),
        unit('u-legacy-other', participants=None, source_event_ids=[cases.OUTBOUND]),
        unit('u-legacy-gone', participants=None, source_event_ids=['in-gone-1'])])
    result = MemoryService(store).commit_understanding(
        cases.episode(selected=['u-legacy-covers', 'u-legacy-other', 'u-legacy-gone']),
        '他把日子改到周五了。')
    assert result['auto_source_ids'] == ['u-legacy-covers'], result
    assert {'id': 'u-legacy-other', 'reason': 'person_not_in_sources'} in result['auto_source_skipped'], result
    assert {'id': 'u-legacy-gone', 'reason': 'sources_unreadable'} in result['auto_source_skipped'], result
    return 'P2 之前的摘要靠原文作者判定；原文回读不到时不默认放行'


@check('E3 被更正过的摘要仍算来源，但一起记成 stale')
def e3():
    store = dm_store([unit('u-stale', corrected_by=['in-x-1'])])
    result = MemoryService(store).commit_understanding(
        cases.episode(selected=['u-stale']), '他改周五了，旧那句只当历史。')
    assert result['auto_source_ids'] == ['u-stale'] and result['auto_stale_source_ids'] == ['u-stale'], result
    return '更正不抹掉来源，只多带一个 stale 标记，读法交给上下文说明'


# ── F 一个场景整理失败时，别的场景与本轮行动照旧 ───────────────
class FlakyLane(cases.FakeLane):
    def __init__(self, fail_for=(), finish='stop'):
        super().__init__()
        self.fail_for, self.finish = tuple(fail_for), finish

    def generate(self, session, operation, phase, text, system, *, scope_key=None, policy_epoch=None):
        self.calls.append({'session': session, 'operation': operation})
        if any(token in session for token in self.fail_for):
            raise RuntimeError('LANE_DOWN')
        from types import SimpleNamespace
        return SimpleNamespace(content=self.content, finish_reason=self.finish,
                               request_refs=['fake-ref'])


def three_rows(scene_id, author_b=PERSON_B):
    return [cases._in(scene_id, 1, PERSON, '雾灯周三去修', T0),
            cases._in(scene_id, 2, author_b, '我去', T0 + 25),
            cases._in(scene_id, 3, PERSON, '那就这么定', T0 + 40)]


@check('F1 一个场景的模型调用挂了：只有那个场景退避，别的场景照整，恢复后补上')
def f1():
    rows = three_rows('grp-fail') + three_rows('grp-ok')
    data = scaffold('grp-fail', rows, persons=(PERSON, PERSON_B))
    data['scenes'].append(cases._scene('grp-ok', 'group', [PERSON, PERSON_B, XIAOMAN], 0, 6))
    store = store_of(data)
    lane = FlakyLane(fail_for=('grp-fail',))
    summarizer = DialogueSummarizer(store, cases.FakeEvidence(), lane, ['grp-fail', 'grp-ok'],
                                    clock=lambda: T0 + 95)
    try:
        summarizer.tick('grp-fail')
        raise AssertionError('模型挂了应该往上招')
    except RuntimeError:
        pass
    assert summarizer.failures['grp-fail'] == 1, summarizer.failures
    assert summarizer.next_attempt['grp-fail'] > time.monotonic(), '该场景要进退避'
    assert store.db.memory_units.rows == {}, '失败时不留半条摘要'
    assert all('summary_batch_id' not in store.db.messages.find_one({'_id': row['_id']})
               for row in rows[:3]), '失败时不许把原文标成已整理'
    calls = len(lane.calls)
    assert summarizer.tick('grp-fail') is None and len(lane.calls) == calls, '退避期内不再试'
    saved = summarizer.tick('grp-ok')
    assert saved and saved['scene_id'] == 'grp-ok', saved
    summarizer.next_attempt.pop('grp-fail')
    lane.fail_for = ()
    assert summarizer.tick('grp-fail') and summarizer.failures['grp-fail'] == 0
    return '失败只关在该场景自己的退避里：不污染别的场景，也不留下半截状态'


@check('F2 模型回了一半（finish_reason 不是 stop）：当失败处理，不落库')
def f2():
    data = scaffold('grp-partial', three_rows('grp-partial'), persons=(PERSON, PERSON_B))
    store = store_of(data)
    lane = FlakyLane(finish='length')
    summarizer = DialogueSummarizer(store, cases.FakeEvidence(), lane, ['grp-partial'],
                                    clock=lambda: T0 + 95)
    try:
        summarizer.tick('grp-partial')
        raise AssertionError('截断的输出不能当成功')
    except RuntimeError as exc:
        assert 'DIALOGUE_SUMMARY_INCOMPLETE' in str(exc), exc
    assert store.db.memory_units.rows == {} and summarizer.failures['grp-partial'] == 1
    return '截断的转述不落库：宁可下一批重来，也不存一段不知道缺了什么的摘要'


@check('F3 选批后有人先把这条原文标走了：撞车就整轮放弃，不覆盖别人的批次')
def f3():
    rows = three_rows('grp-race')
    store = store_of(scaffold('grp-race', rows, persons=(PERSON, PERSON_B)))
    summarizer, lane = summarizer_for(store, ['grp-race'])
    scene = store.db.scenes.find_one({'_id': 'grp-race'})
    selected = summarizer._pending(scene)
    first = store.db.messages.find_one({'_id': selected[0]['_id']})
    store.put('messages', {**first, 'summary_batch_id': 'summary-someone-else'},
              expected=first['revision'], stream='race')
    decision = summary_trigger.decide(profile_of(store, 'grp-race', T0 + 95), selected,
                                      now_ts=T0 + 95, window_rows=DialogueSummarizer.WINDOW_ROWS)
    try:
        summarizer._summarize(scene, selected, decision)
        raise AssertionError('来源已被别人标走，应该报冲突')
    except Conflict as exc:
        assert 'SUMMARY_SOURCE_ALREADY_PROCESSED' in str(exc), exc
    assert store.db.messages.find_one({'_id': rows[0]['_id']})['summary_batch_id'] == \
        'summary-someone-else', '不覆盖别人已经标的批次'
    return '并发整理同一批原文时后到的那个放弃，不出现一条原文挂两个摘要'


@check('F4 前台正忙或已暂停：摘要直接不动，一行都不写')
def f4():
    store = store_of(scaffold('grp-busy', three_rows('grp-busy'), persons=(PERSON, PERSON_B)))
    summarizer, lane = summarizer_for(store, ['grp-busy'], can_run=lambda: False)
    assert summarizer.tick('grp-busy') is None and lane.calls == []
    summarizer.can_run = lambda: True
    summarizer.paused.set()
    assert summarizer.tick('grp-busy') is None and lane.calls == []
    summarizer.paused.clear()
    assert summarizer.tick('grp-busy'), '让开前台之后能接上'
    return '摘要始终给前台行动让路：can_run 与暂停两个口子都真的能拦住'


def main():
    failed = []
    for label, fn in CHECKS:
        try:
            note = fn()
            print('OK   %s — %s' % (label, note or ''))
        except AssertionError as exc:
            failed.append(label)
            print('FAIL %s — %s' % (label, (str(exc) or '断言失败')[:300]))
        except Exception as exc:
            failed.append(label)
            print('FAIL %s — %s: %s' % (label, type(exc).__name__, str(exc)[:300]))
    print('\n边界自测：%d 项，%s' % (len(CHECKS),
                                    '全部通过' if not failed
                                    else '%d 项未过：%s' % (len(failed), '、'.join(failed))))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
