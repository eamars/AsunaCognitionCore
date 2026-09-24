"""P5-b 离线自检：Web 上「程序拦下」与「角色选择沉默」必须分得开。

跑法（无 Mongo、无 pytest、无模型、不联网）：

    python3 tools/p5b_ui_offline_check.py                    # 检查改过的工作树
    python3 tools/p5b_ui_offline_check.py --baseline          # 反证：改之前这条链把程序拦下说成「本轮已结束」

测的是 _snapshot 实际走的那两步：入站行 → ingress_projection(row) → turn_status(ep)。
行形状按真宿主写下的字段来（ingress.py 写 ingress_state／result_state，router.py 写
RECORDED_NO_WAKE，proactive.py 写 PROACTIVE_HOLD＋proactive.holds，chat.py 再核写
PROACTIVE_HELD＋recheck_hold），不自己发明字段。
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import re
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
def _default_src():
    for root in (REPO, os.path.dirname(HERE)):
        candidate = os.path.join(root, 'src', 'asuna')
        if os.path.exists(os.path.join(candidate, 'ui.py')):
            return candidate
    return os.path.join(REPO, 'src', 'asuna')


DEFAULT_SRC = _default_src()

# ui.py 的模块级依赖里有 httpx／pymongo：这里只加载模块本身，不连库也不发请求。
STUB_MODULES = {'httpx': ('Client',),
                'bson': ('BSON',),
                'pymongo': ('ASCENDING', 'MongoClient', 'ReturnDocument', 'WriteConcern'),
                'pymongo.errors': ('DuplicateKeyError',)}

SCENE = 'qq:3768713357:group:1124198125'
EPISODE = 'ep-6431991ccce9b202a4032624ffa05ab5'

BASE_ROW = {'_id': 'in-' + EPISODE, 'episode_id': EPISODE, 'scene_id': SCENE,
            'scope_key': 'scene:' + SCENE, 'policy_epoch': 1, 'scene_seq': 7,
            'text': '这个 agent 的上下文又爆了', 'author': 'qq:673225019', 'direction': 'inbound',
            'delivery_state': 'RECEIVED', 'occurred_at': '2026-09-24T13:02:09.000Z',
            'received_at': '2026-09-24T13:02:10.000Z', 'character_context': 'initial',
            'adapter_id': 'qq', 'platform_event_id': '456646474', 'host_managed': True}

# 真 P5 旁听行：闸门拦下，没建 episode、没调模型
HOLD_ROW = {**BASE_ROW, 'ingress_state': 'COMPLETE', 'result_state': 'RECEIVED_NO_WAKE',
            'processing_outcome': 'PROACTIVE_HOLD',
            'proactive': {'fire': False, 'wake': False,
                          'holds': ['quiet_hours', 'candidate_merge_window'], 'signals': [],
                          'quiet_now': True, 'local_minutes': 1391,
                          'quiet_windows': [['23:00', '08:00']], 'dense_median': 4.1,
                          'burst_rows': 3, 'since_wake': None, 'since_utterance': None,
                          'utterances_last_hour': 0, 'topic_id': 'tp-1', 'topic_attempts': 0,
                          'topic_responded': False, 'note': '',
                          'decided_at': '2026-09-24T13:02:10.000Z'}}

# 再核才拦下：第一次评估闸门是开着的（holds 空），再核名单在 recheck_hold
RECHECK_ROW = {**BASE_ROW, 'ingress_state': 'COMPLETE', 'result_state': 'PROACTIVE_HELD',
               'processing_outcome': 'PROACTIVE_HOLD',
               'proactive': {'wake': False, 'holds': [], 'signals': ['unprompted_group_message'],
                             'recheck_hold': ['foreground_busy'],
                             'recheck_at': '2026-09-24T13:02:12.000Z'}}

# 没开主动模式的旁听行：P5 之前长什么样，现在还是什么样
LISTENER_ROW = {**BASE_ROW, 'ingress_state': 'COMPLETE', 'result_state': 'RECEIVED_NO_WAKE',
                'processing_outcome': 'RECORDED_NO_WAKE'}

# 还没轮到的行（刚落库／正在准备）
ACCEPTED_ROW = {**BASE_ROW, 'ingress_state': 'ACCEPTED'}
PROCESSING_ROW = {**BASE_ROW, 'ingress_state': 'PROCESSING'}

# 角色真跑过一轮并选了沉默：episode 上有 silent_reason
SILENT_EPISODE = {'_id': EPISODE, 'state': 'COMMITTED', 'silent_reason': '这句不是问我的，我继续听'}

PRESCRIPTIVE = ('该说', '应该说', '去说', '说点什么', '必须发', '固定发言', '该发言')

RESULTS = []


def check(name, ok, detail=''):
    RESULTS.append((name, bool(ok), detail))
    print('%s %s%s' % ('PASS' if ok else 'FAIL', name, (' — ' + detail if detail and not ok else '')))


def install_stubs():
    for name, attrs in STUB_MODULES.items():
        module = sys.modules.get(name) or types.ModuleType(name)
        for attr in attrs:
            if not hasattr(module, attr):
                setattr(module, attr, type(attr, (Exception,), {}) if 'Error' in attr else object)
        sys.modules[name] = module


def load_ui(src_dir):
    install_stubs()
    package = types.ModuleType('asuna')
    package.__path__ = [src_dir]
    sys.modules['asuna'] = package
    spec = importlib.util.spec_from_file_location('asuna.ui', os.path.join(src_dir, 'ui.py'))
    ui = importlib.util.module_from_spec(spec)
    sys.modules['asuna.ui'] = ui
    spec.loader.exec_module(ui)
    return ui


def legacy_projection(row):
    """P5-b 之前 _snapshot 里内联写的那份投影。"""
    return {'_id': row['episode_id'], 'state': row['ingress_state'],
            'character_context': row.get('character_context', 'initial'),
            'no_wake': row.get('processing_outcome') == 'RECORDED_NO_WAKE',
            **({'failure': row['failure']} if row.get('failure') else {})}


def badge(ui, row):
    """_snapshot 现在实际做的事：先投影这一行，再算本轮状态。"""
    ep = (ui.ingress_projection(row) if hasattr(ui, 'ingress_projection')
          else legacy_projection(row))
    return ep, ui.turn_status(ep, row.get('occurred_at', ''))


def p5_gates(path):
    if not os.path.exists(path):
        return set()
    source = open(path, encoding='utf-8').read()
    found = set(re.findall(r"holds\.append\('([a-z_]+)'\)", source))
    found.add('decision_write_conflict')      # consider() 里 CAS 撞车那条
    return found


def run_current(ui):
    check('helpers_exist', hasattr(ui, 'ingress_projection') and hasattr(ui, 'program_hold'),
          'ui.py 里缺 ingress_projection／program_hold')

    # 1. P5 闸门拦下：说清是程序拦的、模型没跑，并带上闸门名单
    ep, status = badge(ui, HOLD_ROW)
    check('p5_hold_is_not_turn_over', status and '本轮已结束' not in status['label'], str(status))
    check('p5_hold_says_program', status and status.get('kind') == 'program_hold'
          and '未进入模型' in status['label'], str(status))
    check('p5_hold_names_gates', status and all(
        gate in status['detail'] for gate in HOLD_ROW['proactive']['holds']), str(status))
    check('p5_hold_carries_holds_list',
          status and status.get('holds') == ['quiet_hours', 'candidate_merge_window'], str(status))
    check('p5_hold_translates_known_gate', status and '安静时段' in status['detail'], str(status))
    check('p5_hold_says_model_not_called', status and '模型未被调用' in status['detail'], str(status))

    # 2. 再核才拦下：用 recheck_hold，不拿第一次那份空 holds 冒充「没原因」
    ep, status = badge(ui, RECHECK_ROW)
    check('recheck_hold_uses_recheck_gates', status and 'foreground_busy' in status['detail']
          and '再核' in status['detail'], str(status))
    check('recheck_hold_still_program', status and status.get('kind') == 'program_hold', str(status))

    # 3. 模型决定沉默：口径一个字不改
    status = ui.turn_status(SILENT_EPISODE, '2026-09-24T13:02:09.000Z')
    check('model_silence_unchanged', status and status['label'] == '角色选择不发言'
          and status['detail'] == SILENT_EPISODE['silent_reason'], str(status))

    # 4. 没开主动模式的旁听行：照旧不给本轮状态
    ep, status = badge(ui, LISTENER_ROW)
    check('plain_listener_still_no_badge', status is None, str(status))

    # 5. 还没轮到的行不许说「本轮已结束」
    for row, expect in ((ACCEPTED_ROW, '排队'), (PROCESSING_ROW, '处理')):
        ep, status = badge(ui, row)
        check('pending_%s_not_claimed_over' % row['ingress_state'],
              status and '本轮已结束' not in status['label'] and expect in status['label'], str(status))

    # 6. 失败仍然优先于「程序拦下」
    ep, status = badge(ui, {**HOLD_ROW, 'ingress_state': 'FAILED', 'failure': 'boom'})
    check('failure_beats_hold', status and status['label'] == '本轮未完成', str(status))

    # 7. 没见过的闸门名原样显示，不替它编解释
    unknown = {**HOLD_ROW, 'proactive': {**HOLD_ROW['proactive'], 'holds': ['brand_new_gate']}}
    ep, status = badge(ui, unknown)
    check('unknown_gate_kept_verbatim', status and 'brand_new_gate' in status['detail']
          and '（brand_new_gate）' not in status['detail'], str(status))

    # 8. 空名单也不冒充原因
    empty = {**HOLD_ROW, 'proactive': {**HOLD_ROW['proactive'], 'holds': []}}
    ep, status = badge(ui, empty)
    check('empty_gate_list_admitted', status and '没写闸门名单' in status['detail'], str(status))

    # 9. 投影只留状态要用的几项（不把整块 proactive 塞进 Web 负载）
    ep, status = badge(ui, HOLD_ROW)
    check('projection_is_bounded',
          set(ep.get('proactive', {})) <= {'holds', 'recheck_hold', 'wake', 'decided_at'}
          and set(ep) <= {'_id', 'state', 'character_context', 'no_wake', 'processing_outcome',
                          'result_state', 'proactive', 'failure'}, str(sorted(ep)))

    # 10. 老形状的行（没有这些字段）行为不变
    old_shape = {**BASE_ROW, 'ingress_state': 'COMPLETE'}
    ep, status = badge(ui, old_shape)
    check('old_shape_row_unchanged', status and status['label'] == '本轮已结束'
          and status['detail'] == '没有公开回复', str(status))

    # 11. 真 episode（被唤醒的那轮）与既有分支不受影响
    check('woken_episode_not_hold', ui.program_hold({'_id': EPISODE, 'state': 'COMMITTED'}) is None)
    check('running_phase_still_not_a_badge',
          ui.turn_status({'_id': EPISODE, 'state': 'PREPARED'}, '') is None)
    status = ui.turn_status({'_id': EPISODE, 'state': 'WAITING_TASK'}, '')
    check('waiting_task_unchanged', status and status['label'] == '行动处理中', str(status))
    status = ui.turn_status({'_id': EPISODE, 'state': 'COMMITTED', 'episode_kind': 'task_feedback'}, '')
    check('task_feedback_unchanged', status and status['label'] == '行动反馈已处理', str(status))

    # 12. 不给角色规定固定发言内容
    texts = []
    for row in (HOLD_ROW, RECHECK_ROW, ACCEPTED_ROW, PROCESSING_ROW, LISTENER_ROW, old_shape,
                {**HOLD_ROW, 'ingress_state': 'FAILED', 'failure': 'boom'}):
        ep, status = badge(ui, row)
        if status:
            texts.append(status['label'] + status['detail'])
    check('no_prescribed_words_for_character',
          not any(word in text for text in texts for word in PRESCRIPTIVE), ' | '.join(texts))

    # 13. 闸门名单与 P5 源码对账：P5 加了新闸门而这里没跟上，先红
    gates = p5_gates(os.path.join(os.path.dirname(ui.__file__), 'proactive.py'))
    missing = sorted(gates - set(ui.HOLD_GATES)) if gates else []
    check('hold_gate_names_track_p5', not gates or not missing,
          'ui.HOLD_GATES 缺：' + ','.join(missing) if gates else '（这份树里没有 proactive.py，跳过对账）')


def run_baseline(ui):
    """反证：改之前，一条 P5 拦下的旁听行在 Web 上长成什么样。"""
    check('baseline_has_no_program_hold_helper',
          not hasattr(ui, 'program_hold') and not hasattr(ui, 'ingress_projection'))
    for name, row in (('program_hold', HOLD_ROW), ('recheck_hold', RECHECK_ROW),
                      ('before_processing', ACCEPTED_ROW)):
        ep, status = badge(ui, row)
        check('baseline_shows_turn_over_for_' + name,
              status and status['label'] == '本轮已结束' and status['detail'] == '没有公开回复', str(status))
    status = ui.turn_status(SILENT_EPISODE, '')
    check('baseline_model_silence_label', status and status['label'] == '角色选择不发言', str(status))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--src', default=DEFAULT_SRC, help='宿主 src/asuna 目录')
    parser.add_argument('--baseline', action='store_true', help='按 P5-b 之前的 ui.py 跑反证')
    args = parser.parse_args()
    ui = load_ui(args.src)
    (run_baseline if args.baseline else run_current)(ui)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print('\n%d/%d 通过（%s，src=%s）' % (passed, len(RESULTS),
                                        'baseline 反证' if args.baseline else 'P5-b 行为', args.src))
    return 0 if passed == len(RESULTS) else 1


if __name__ == '__main__':
    sys.exit(main())
