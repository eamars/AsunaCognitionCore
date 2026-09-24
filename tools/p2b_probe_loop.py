#!/usr/bin/env python3
"""ADR-005 P2 小探针：拿真代码在真路径上把「触发→整理→保存→下一轮使用」走一遍并打出来。

本机 python3 tools/p2b_probe_loop.py 直接跑（不需要 Mongo／pytest）：假集合真算，跑的是
仓库里那份 DialogueSummarizer／summary_trigger／summary_attribution／ContextBuilder／
MemoryService。这里不冒充验收，只把每一步的中间量摊开：能看见触发点是哪些真实数据算出来的、
摘要条目上带了什么、下一轮角色看见什么、来源登记给了谁。

要反证设计的三处都单独打：旧口径会在慢私聊抢话、在快群里迟到；只盖了别人的摘要不算本人证据；
被更正过的旧转述要带 corrected_by 才不会被当成现状。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'tests'))

import p2_summary_loop_cases as cases                      # noqa: E402
from asuna import summary_trigger                          # noqa: E402
from asuna.memory import MemoryService                     # noqa: E402


def show(title, payload):
    print('\n== %s ==' % title)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def step(index, text):
    print('\n[%d] %s' % (index, text))


def main():
    failures, total = [], {'n': 0}

    def check(label, condition, detail=''):
        total['n'] += 1
        print('   %s %s%s' % ('OK  ' if condition else 'FAIL', label,
                              (' — ' + str(detail)) if detail else ''))
        if not condition:
            failures.append(label)

    # ── 1. 触发：同一个场景，三个时刻，三个不同结论 ─────────────────────
    store = cases.bind_store(cases.group_rows())
    pending = cases.pending_rows(store, cases.GROUP)
    mid_profile, mid = cases.decide_for(store, cases.GROUP, pending, cases.T0 + 50)
    step(1, '群里刚说完三句、只安静了 10 秒（没跨过本场景实测的停顿线）')
    show('节奏画像（全部由这个场景已经落库的行算出）',
         {key: mid_profile[key] for key in ('samples', 'peer_gaps', 'quiet_after', 'quiet_source',
                                            'burst_rows', 'burst_bytes', 'rows_without_time')})
    show('决定', mid)
    check('还在说话时不动手', not mid['fire'] and mid['hold'] == 'scene_still_talking', mid['hold'])

    _profile, fired = cases.decide_for(store, cases.GROUP, pending, cases.T0 + 95)
    step(2, '同一个群、同一批原文，安静到 55 秒（对这个群已经算反常）')
    show('决定', fired)
    check('按本场景自己的停顿线动手', fired['fire'] and 'pause_anomalous' in fired['signals'],
          fired['signals'])
    check('旧口径（≥4 条／≥2 条且 120 秒）这会儿还不动手',
          not cases.legacy_rule(pending, cases.T0 + 95, cases.T0))

    slow = cases.bind_store(cases.slow_rows())
    slow_pending = cases.pending_rows(slow, cases.SLOW)
    _slow_profile, slow_decision = cases.decide_for(slow, cases.SLOW, slow_pending, cases.T0)
    step(3, '反证一：半小时一条的私聊，两条刚攒够 120 秒')
    show('决定', slow_decision)
    check('按它自己的节奏还得等', not slow_decision['fire'], slow_decision['hold'])
    check('旧口径这会儿会抢话', cases.legacy_rule(slow_pending, cases.T0, cases.T0 - 130))

    busy = cases.bind_store(cases.busy_rows())
    busy_pending = cases.pending_rows(busy, cases.BUSY)
    _busy_profile, busy_decision = cases.decide_for(busy, cases.BUSY, busy_pending, cases.T0 + 40)
    step(4, '反证二：快群里 5 秒一条已经攒满窗口（安静线还没到）')
    show('决定', busy_decision)
    check('窗口顶满这条是结构上限，照动', 'window_full' in busy_decision['signals'],
          busy_decision['signals'])

    # ── 2. 整理＋保存：一轮 tick 之后条目长什么样 ─────────────────────
    data = cases.group_rows()
    data['messages'] = data['messages'] + [cases.correction_row()]
    store = cases.bind_store(data)
    saved, evidence, lane = cases._saved_group_summary(store)
    step(5, '群场景一轮 tick：A 起话、B 应答、角色送达、A 用真实 reply 链更正自己那句')
    show('存下来的摘要条目（只挑关键字段）', {
        key: saved.get(key) for key in ('_id', 'kind', 'epistemic_type', 'body_markdown',
                                        'source_window', 'source_event_ids', 'participants',
                                        'source_by_speaker', 'attribution', 'trigger',
                                        'embedding_status')})
    check('条目带上了程序算出的归属', bool(saved.get('participants')) and
          bool(saved.get('source_by_speaker')), saved.get('participants'))
    fixes = saved['attribution']['corrections']
    check('更正按真实 reply 链认定，不靠猜',
          fixes and fixes[0]['corrects'] == 'in-%s-11' % cases.GROUP and
          fixes[0]['target_resolution'] == 'reply_link', fixes)
    check('四条原文都标了批次',
          all(store.db.messages.find_one({'_id': row['_id']})['summary_batch_id'] == saved['_id']
              for row in data['messages']))
    check('触发决定随条目与证据一起留下', 'summary.saved' in evidence.kinds(), evidence.kinds())
    check('送进模型的原文带上程序算出的归属（模型不自己认领）',
          'attribution' in lane.calls[0]['text'] and '老陈' in lane.calls[0]['text'])

    # ── 3. 下一轮使用：角色看见什么，程序登记成谁的来源 ───────────────
    _system, context, manifest = cases.prepare_group(store, cases.PERSON, '那到底周几去？')
    entry = next((m for m in context['memories'] if m['_id'] == saved['_id']), None)
    step(6, '下一轮（A 说话）：这条摘要在上下文里长什么样')
    show('角色这一轮看到的这条记忆', entry)
    show('程序给的读法说明', {'memory_source_rules': context['memory_source_rules'],
                             'understanding_route': context['understanding_update_from_program']['route']})
    check('下一轮真给角色看过了', saved['_id'] in manifest['selected'], manifest['selected'])
    check('条目说清了盖了谁', entry and entry.get('participants') ==
          sorted([cases.PERSON, cases.PERSON_B, 'xiaoman']), entry)
    check('读法说明里写清了摘要只在盖到本人时才算这个人的证据',
          'participants' in context['memory_source_rules'])

    cases.add_row(store, 'memory_units', cases.monologue_unit(cases.PERSON, 'ep-g1'))
    result = MemoryService(store).commit_understanding(
        cases.group_episode(cases.PERSON, selected=manifest['selected']), '他自己把日子改成周五了。')
    step(7, '这一轮把理解写回关系：来源登记给了谁')
    show('commit_understanding 结果', result)
    check('摘要登记成 A 这条关系的来源', result['auto_source_ids'] == [saved['_id']], result)
    revision = store.head('relationship:' + cases.PERSON, cases.GROUP_SCOPE)[1]
    roots = set(revision['processed_source_ids'])
    check('来源根全部落到真实原文行',
          all(store.db.messages.find_one({'_id': root}) for root in roots), sorted(roots))

    # ── 4. 归属：只盖了 B 的摘要不算 A 的证据 ─────────────────────────
    only_b = cases._summary_unit('summary-b-only', '小舟说他去，工具他带。',
                                 ['in-%s-12' % cases.GROUP], [cases.PERSON_B, 'xiaoman'], [12, 12])
    cases.add_row(store, 'memory_units', only_b)
    cases.add_row(store, 'memory_units',
                  cases.monologue_unit(cases.PERSON, 'ep-g2', body='小舟热心，但这事老陈没定。'))
    moved = store.head('relationship:' + cases.PERSON, cases.GROUP_SCOPE)[0]['revision_id']
    a_turn = MemoryService(store).commit_understanding(
        cases.group_episode(cases.PERSON, selected=['summary-b-only'], ep_id='ep-g2', base=moved),
        '小舟愿意去。')
    cases.add_row(store, 'memory_units',
                  cases.monologue_unit(cases.PERSON_B, 'ep-g3', body='我去，工具我带。'))
    b_turn = MemoryService(store).commit_understanding(
        cases.group_episode(cases.PERSON_B, selected=['summary-b-only'], ep_id='ep-g3'), '工具归我。')
    step(8, '反证三：只盖了 B 的摘要，A 那轮看得见但不算 A 的证据')
    show('A 这一轮', a_turn)
    show('B 那一轮', b_turn)
    check('A 这边没登记、带原因', a_turn['auto_source_ids'] == [] and
          a_turn['auto_source_skipped'][0]['reason'] == 'person_not_in_participants', a_turn)
    check('B 那边照常登记', b_turn['auto_source_ids'] == ['summary-b-only'], b_turn)

    # ── 5. 更正：被更正过的旧摘要要看得见 ─────────────────────────
    data = cases.group_rows()
    data['memory_units'] = [cases._summary_unit('summary-old', '老陈说他周三去修雾灯。',
                                                ['in-%s-11' % cases.GROUP],
                                                [cases.PERSON, 'xiaoman'], [11, 11])]
    data['messages'] = [dict(data['messages'][0], summary_batch_id='summary-old')] \
        + data['messages'][1:] + [cases.correction_row()]
    store = cases.bind_store(data)
    newer, evidence, _lane = cases._saved_group_summary(store)
    old = store.db.memory_units.find_one({'_id': 'summary-old'})
    step(9, '后一批里 A 更正了早一批已经被摘要盖住的那句')
    show('旧条目（只追加标注，正文没动）',
         {'_id': old['_id'], 'body_markdown': old['body_markdown'],
          'corrected_by': old.get('corrected_by'), 'corrected_at': old.get('corrected_at')})
    show('新条目盖住的范围', {'_id': newer['_id'], 'source_window': newer['source_window']})
    check('旧摘要追加了 corrected_by', old.get('corrected_by') == ['in-%s-14' % cases.GROUP], old)
    check('旧摘要正文没被改写', old['body_markdown'] == '老陈说他周三去修雾灯。', old)
    cases.add_row(store, 'memory_units', cases.monologue_unit(cases.PERSON, 'ep-g1'))
    stale = MemoryService(store).commit_understanding(
        cases.group_episode(cases.PERSON, selected=['summary-old']), '他改周五了，旧那句只当历史。')
    check('被更正的摘要仍算来源，但一起记为 stale',
          stale['auto_stale_source_ids'] == ['summary-old'], stale)

    print('\n探针结论：%d 项检查，%s' % (total['n'], '全部通过' if not failures
                                    else '失败：' + '、'.join(failures)))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
