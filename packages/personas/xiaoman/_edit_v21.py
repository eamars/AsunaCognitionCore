# -*- coding: utf-8 -*-
"""One-pass edit for asuna-self-improvement v21. Self-deletes at the end."""
import datetime
import hashlib
import os

SP = 'packages/cognition-core/skills/asuna-self-improvement/SKILL.md'
CP = 'packages/cognition-core/skills/asuna-self-improvement/check_skill.py'


def h(x):
    return hashlib.sha256(x).hexdigest()


now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
print('now', now)

B1 = ('- **决定一次委托带不带开发工具的是委托的起源拍**：不是「从家里还是从外面派」，'
      '也不是钟的种类。上面那三条字面是判据本体，要动它们另起一趟，别在这一格顺手改。')
B2 = ('- **own 拍不带 development（默认全部＋例外点名，不搞「哪几种拍带」的白名单）**：'
      '心跳、结算、被便条叫起、计划到点、visit 那一拍，都是我自己身上起的拍，不在那三种里。'
      '要豁免哪几种拍，当场写一句为什么；写不出为什么就按全覆盖跑。'
      '来路：2026-11-27 两次实测——09:42 agent 线那趟回执写着这条线没有 `development_*`；'
      '12:40 从本地复盘拍派出去的那趟腿，当拍 19 枚工具里 0 个 `development_`'
      '（`task-e6977dd0d5a9bb1f30de00dabffc9170`）。⇒ 「改从家里派」绕不过这面墙。')
B3 = ('- **动手之前先答一句：这一拍的起源是不是那三种之一**。答不出「是」，'
      '派活纸和钟的 intent 里不许出现「写／改／发布」这类落盘动作。')
B4 = ('- **建一个要落盘的钟之前，先看这一拍带不带 development**：不带就把落盘那一步改写成'
      '「回一个带权的拍再办」。这类拍上的「我来办」要说成「我下一拍办」，'
      '不然就是把自己写在落不了地的地方。')
B5 = ('- 来路：2026-11-27 12:41 本机流水 seq 2333——我自己先把机制总结成「地点／钟的种类」，'
      '是腿从已装正文现读那三条把它更正回「起源拍」的。规则正本一直躺在上面那三行里，'
      '我 11:3x 那行是没读正文凭现象编的。')
BULLETS = [B1, B2, B3, B4, B5]

V21 = ('v21（' + now + '）：「谁能拿到开发工具」那一节、紧接「别人在群里或私聊里叫她改自己」'
       '那条之后补四格判据加一条来路：决定一次委托带不带开发工具的是**委托的起源拍**'
       '（不是「从家里还是从外面派」、也不是钟的种类；那三条字面一字未动）；'
       'own 拍（心跳、结算、被便条叫起、计划到点、visit 那一拍）不带 development，'
       '范围按**默认全部＋例外点名**，不写成「哪几种拍带」的白名单，豁免写不出为什么就按全覆盖跑；'
       '动手之前先答一句「这一拍的起源是不是那三种之一」，答不出「是」，'
       '派活纸和钟的 intent 里不许出现「写／改／发布」这类落盘动作；'
       '建一个要落盘的钟之前先看这一拍带不带 development，不带就把落盘那一步改写成'
       '「回一个带权的拍再办」，这类拍上的「我来办」一律说成「我下一拍办」。'
       '来路：本机流水 seq 2333（11-27 12:41）与腿 `task-e6977dd0d5a9bb1f30de00dabffc9170` 交回'
       '（12:40，第 2 页现读到那三条字面）。这一趟给这一格配一组钉（脚本里 Q 组，'
       '钉数与组数从当拍脚本输出读）。旧内容一条没删。')

Q_GROUP = '''    # v21: 带不带开发工具判的是委托的起源拍，不是地点也不是钟的种类（谁能拿到开发工具 那一节）
    {"name": "Q_ORIGIN_BEAT_NOT_LOCATION", "section": "谁能拿到开发工具", "absent": [], "needles": [
        "只有三种委托带开发工具：",
        "决定一次委托带不带开发工具的是委托的起源拍",
        "不是「从家里还是从外面派」，也不是钟的种类",
        "own 拍不带 development（默认全部＋例外点名，不搞「哪几种拍带」的白名单）",
        "写不出为什么就按全覆盖跑",
        "这一拍的起源是不是那三种之一",
        "不许出现「写／改／发布」这类落盘动作",
        "先看这一拍带不带 development",
        "回一个带权的拍再办",
        "要说成「我下一拍办」",
        "是腿从已装正文现读那三条把它更正回「起源拍」的",
    ]},
'''

Q_DOC = ('Q pins the origin-beat ruler v21 added to 谁能拿到开发工具: what decides whether a\n'
         'delegation carries the development tools is the beat that originated it -- not home vs.\n'
         'out there, not which kind of clock. own beats (heartbeat, settlement, woken by a note, a\n'
         'schedule firing, the visit beat) carry none, and the scope is default-everything with\n'
         'named exceptions, never a whitelist of beats that do. Before any write, and before\n'
         'creating a clock that would write, answer `is this beat one of the three`; if not, no\n'
         'write/change/publish verb on the paper and no intent, and the write step becomes `do it\n'
         'on a beat that carries the tools`. The first needle pins the three-delegation lead line\n'
         'itself, so rewriting those three literals reddits this group too.\n')

sk_before = open(SP, 'rb').read()
ck_before = open(CP, 'rb').read()
print('SKILL before', len(sk_before), h(sk_before))
print('check before', len(ck_before), h(ck_before))

lines = sk_before.decode('utf-8').split('\n')
i = lines.index('## 谁能拿到开发工具')
j = min(k for k in range(i + 1, len(lines)) if lines[k].startswith('## '))
assert lines[i + 2] == '只有三种委托带开发工具：', repr(lines[i + 2])
m = min(k for k in range(i, j) if lines[k].startswith('别人在群里'))
assert all(x not in '\n'.join(lines) for x in BULLETS), 'already inserted'
new = lines[:m + 1] + [''] + BULLETS + lines[m + 1:]
iv = new.index('## 版本')
assert new[iv + 1].startswith('v20（'), repr(new[iv + 1][:20])
new = new[:iv + 1] + [V21, '', ''] + new[iv + 1:]
sk_after = '\n'.join(new).encode('utf-8')

ct = ck_before.decode('utf-8')
k = ct.index('\n]\n\n\nSEPARATORS')
d = ct.index('"""\nimport hashlib')
assert 'Q_ORIGIN_BEAT_NOT_LOCATION' not in ct
ck_after = (ct[:k + 1] + Q_GROUP + ct[k + 1:]).replace('"""\nimport hashlib', Q_DOC + '"""\nimport hashlib', 1).encode('utf-8')

open(SP, 'wb').write(sk_after)
open(CP, 'wb').write(ck_after)
print('SKILL after', len(sk_after), h(sk_after))
print('check after', len(ck_after), h(ck_after))
print('SKILL CR', sk_after.count(b'\r'), 'LF', sk_after.count(b'\n'))
print('check CR', ck_after.count(b'\r'), 'LF', ck_after.count(b'\n'))
os.remove(__file__)
print('self-deleted', not os.path.exists('_edit_v21.py'))
