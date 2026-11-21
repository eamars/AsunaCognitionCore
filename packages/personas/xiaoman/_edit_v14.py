#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-off edit for asuna-self-improvement v14. Replaces three exact lines and
inserts one bullet + the v14 changelog line. Asserts every anchor is unique."""
import difflib
import hashlib
import io
import os

P = 'packages/cognition-core/skills/asuna-self-improvement/SKILL.md'
raw = io.open(P, 'rb').read()
old_sha = hashlib.sha256(raw).hexdigest()
text = raw.decode('utf-8')
lines = text.split('\n')
print('BEFORE bytes', len(raw), 'sha256', old_sha, 'CR', raw.count(b'\r'))


def find_line(prefix):
    idx = [i for i, ln in enumerate(lines) if ln.startswith(prefix)]
    assert len(idx) == 1, ('anchor not unique', prefix, idx)
    return idx[0]


def cut(prefix):
    """Remove and return the whole line starting with prefix (plus a trailing
    blank line if one follows and keep_blank says to)."""
    i = find_line(prefix)
    ln = lines.pop(i)
    return i, ln


olds = {}
news = {}

# ---------------- 1) 挑发布窗口那一格（「发布」一节） ----------------
NEW1 = '''- **挑发布窗口要算的实测代价（core 那一路）：挂多久不是一个数，取决于那一刻还有没有在跑的活。** `development_publish` 只把当次调用记成 `APPLIED`；worker 每 0.5 秒看一眼 `controller.active`（回合）／`active_task`（任务）／`calls_in_flight`（在飞的工具调用），三者有忙就**不**请求重启（`src/asuna/host.py:_watch_published_restart` 与 `_maybe_restart_after_publish`；每换一次占用记一行 `restart.blocked` 证据，占用内容落在库 `host_stops` 那行的 `held` 里），腾空那一刻才 shutdown → 自重启 → selection 转 `ACTIVE` 补 `activated_at`。⇒ 两枚发布的挂起时长能差一个量级，**拿其中任何一枚当规格都是错的**；挑窗口不只看主人睡没睡，还要看有没有别处在等我的回话，以及**我自己刚派出去那一趟腿什么时候收尾**——两枚个案挂住的占用都是发布那一趟腿自己。旧字面把下面个案一那一枚读当成了性质（那串数这里不重抄，重抄就会被下次抄走），作废，两枚读数留下并标「个案」。同拍现读（`.runtime/adr008/activation.json` 加库 `host_stops`，11-21）：
  - 个案一（core，candidate `4154645a…`）：`published_at 2026-11-20T15:13:51.015Z` → `activated_at 2026-11-20T15:28:06.164Z`＝**855.149 秒**；`host_stops` 行 `restart-20261120T152723860Z`：`held.since 11/21 04:13`、`held.changes 20`、`held.steps` 里的 `task_id` 就是发布那一趟腿 `task-a91c29eddb554d076d825379b6e877e7`，占用内容是 `task` 与 `calls`。同窗口库 `tasks` 零新建任务，第一枚 04:32（本地钟面）才建。
  - 个案二（core，candidate `1995dec7…`，同一趟的下一枚）：`published_at 2026-11-20T20:44:14.678Z` → `activated_at 2026-11-20T20:45:54.310Z`＝**99.632 秒**；`host_stops` 行 `restart-20261120T204513738Z`：`held.changes 6`、`held.steps` 里同样是发布那一趟腿 `task-e38bca1f6000607f00e32a8e69da7eea`。
  - 人格包那一枚对照（同拍现读，走当场生效那一路、没有 worker 重启这一段）：candidate `c5e2edf0…` 的 `published_at` → `activated_at`＝**0.242 秒**。
  - **「重启那一段多久」有两本账，别混**：`worker-restarts.jsonl` 每行只落一个 `at`，它到 `activated_at` 是 42.304 秒（个案一）与 40.572 秒（个案二）；`host_stops` 行的 `asked_at`→`back_at` 按分钟级显示读到 04:27→04:31、09:45→09:49，旧字面「worker 自重启约 4 分钟」对上的就是这一格——那个 `back` 是插件交来的（`host_stops.py:restarted`），它比 `activated_at` 还晚，**既不是生效时刻也不能当「切换花了多久」**，成因未查。'''

i, olds['1'] = cut('- **挑发布窗口要算的实测代价（core 那一路）**：')
lines[i:i] = NEW1.split('\n')
news['1'] = NEW1

# ---------------- 2) 钉那一格（「发布前自检」一节） ----------------
NEW2 = '''- **这一本正文自己的钉**：`python3 packages/cognition-core/skills/asuna-self-improvement/check_skill.py`（在候选根跑；已装的那一份里同路径去掉 `packages/cognition-core/` 前缀，也可以直接拿已装正本当参数喂它）。它只判字面在不在，不跑任何东西，且**没有旗标**：`argv[1]` 一律被当成 SKILL.md 的路径，喂 `--help` 会死在 `FileNotFoundError`（rc 1，11-21 现读），用法读脚本开头那段 docstring。体例是**每组规矩配一套自己的钉，钉字面不钉我的意图：删掉哪一格就红哪一组，各组不会合成一发**。**组数不在正文里写死**（有一组钉专钉这条）——数从当拍脚本输出读：`GROUPS <n>` 是当拍脚本里分了几组，`RESULT 通过数/总数` 是钉数，`RED_GROUPS` 是红了哪几组。规矩改了顺手补那一组的钉，别攒到下一趟。'''

i, olds['2'] = cut('- **这一本正文自己的钉**：')
lines[i:i] = NEW2.split('\n')
news['2'] = NEW2

# ---------------- 3) 新格：派活纸里的历史前提（插在「入站行」那一格之后） ----------------
NEW3 = '''- **派活纸里的「历史前提」：不当拍现读，就整句删掉**：纸上凡是「上次／首趟／昨天那一步没成／从哪天开始积的」这类句子，落笔前得真去读上一趟交回的原文（或库里那一行、盘上的 mtime、日志那一行）；说不出它是从哪一行读来的，就不许上纸，也不许拿它决定这一跑要干什么。触发问句：**「这句历史前提我是读了哪一行知道的？」** 来路：11-21 11:47 那张每日备份交代纸（`task-1254593e4b3ec72c2d98a715895d0d10`）写着「NAS 写入段当时在 /task 沙箱写不出局域网那台机」，还拿它当「这跑是 NAS 写入段第一次真出输出」的理由；腿现读 NAS 上 11-20 那份 size／sha 与昨天导出逐字一致、NAS 侧 mtime 换本地钟面 11-20 11:49:53，昨天那趟（`task-7232c113c5bffe38009ed8f68eed7254`）交回里自己也写着「拷 177,272,678 B」——那句是我凭印象补的，被腿用现读顶回。同模子同一天另一次，就是上面「挑发布窗口」那一格里被作废的那个数。'''

i = find_line('- **取「某人说过 X」只认本人打字的入站行**')
lines[i + 1:i + 1] = ['', NEW3]
news['3'] = NEW3

# ---------------- 4) 版本节顶部补 v14 ----------------
NEWV = '''v14（2026-11-21）：撤一个我自己 v13 写进去的假规格，补上 v13 那三格半缺的自检钉，另加一格派活纸的「历史前提」闸。①「发布」那一格旧字面「`APPLIED` 之后挂约 14 分钟」是个案当规格：同拍现读两枚 core 发布 `APPLIED`→`ACTIVE` 分别 855.149 秒（`4154645a…`，`host_stops` 行 `restart-20261120T152723860Z` 的 `held.changes 20`，占用者就是发布那一趟腿自己）与 99.632 秒（`1995dec7…`，`held.changes 6`），同拍人格包一枚 0.242 秒；那一格改成形状句（挂多久＝那一刻有没有活在等：回合／任务／在飞的工具调用，判据在 `src/asuna/host.py`），两枚读数标「个案」，旧数不重抄。同一格另分「重启那一段」两本账：`worker-restarts.jsonl` 那行到 `activated_at` 是 42.304／40.572 秒，`host_stops` 的 `asked_at`→`back_at` 才是旧字面「约 4 分钟」那一格、且晚于 `activated_at`。②「发布前自检」里写死的钉组数（旧字面「四组钉」）删成形状句＋脚本自印的 `GROUPS`／`RESULT`／`RED_GROUPS`，并给 v13 那三格半与新格各补一组钉（派低档、core 用版本节不用 CHANGELOG、候选根新建要回读、挑窗口那一格的形状、历史前提），`check_skill.py` 另加一组钉「正文不许把组数写死、也不许把被作废的那个分钟数抄回来」。③「派活交代」加一格：纸上的历史前提不当拍现读就整句删，触发问句「这句历史前提我是读了哪一行知道的？」，案例是 11-21 那张每日备份交代纸被腿用 NAS 现读顶回（`task-1254593e…`、`task-7232c113…`）。旧内容一条没删。'''

i = find_line('v13（2026-11-21）：')
lines[i:i] = [NEWV, '']
news['v'] = NEWV

new_text = '\n'.join(lines)
new_raw = new_text.encode('utf-8')
assert new_raw.count(b'\r') == 0
io.open(P, 'wb').write(new_raw)
print('AFTER  bytes', len(new_raw), 'sha256', hashlib.sha256(new_raw).hexdigest(),
      'CR', new_raw.count(b'\r'), 'delta bytes', len(new_raw) - len(raw))
print()
for k in ('1', '2', '3', 'v'):
    print('=== OLD', k, '===')
    print(olds.get(k, '(insert-only)'))
    print('=== NEW', k, '===')
    print(news[k])
    print()
print('=== DIFF（每行截 150 字；全文见上面 OLD/NEW）===')
for ln in difflib.unified_diff(text.split('\n'), new_text.split('\n'),
                               'before', 'after', lineterm='', n=0):
    print(ln[:150] + ('…' if len(ln) > 150 else ''))
