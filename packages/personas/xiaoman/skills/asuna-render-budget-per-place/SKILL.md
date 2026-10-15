---
name: asuna-render-budget-per-place
description: 我身上每层字（persona／voice 里 inject=always 那些节）在家里／线／群／私聊各占多少 token、往随身层加东西之前算这笔账的做法。算法写死：对四个场合各渲染一份（render.largest 走的就是 visibility.PLACE_CLASS）；每节的数＝那份渲染去掉这一节少多少；预算卡的是几个场合里最大的那份；推论最值钱——放掉只出现在一个场合的节，最大那份就换成另一个场合，可能只腾几格（10-15 放掉一节 131 字的群专属节只腾出 8），要真腾地方只能动处处都出现的节；行动脑 import asuna.render 自己就能算，不用找开发助手跑；加不进去是常态不是意外。附零依赖账本 budget_per_place.py 与自检 check_skill.py。
---

# asuna-render-budget-per-place

随身层就是我走到哪儿都带着的那几层字：persona 和 voice 里 `inject=always` 的节。它有一个 token 上限，超了就写不进去。这笔账的算法是固定的，不该每次找人跑。

## 一、算法（写死，别自己发明）

1. **对家里／线／群／私聊各渲染一份。** 场合和可见级的对应表在 `src/asuna/visibility.py:PLACE_CLASS`（home、peer 是 owner_private，group、dm 是 public）；`src/asuna/render.py:largest` 就是把这四份都渲一遍取最大的那个。
2. **每一节的数 = 那份渲染去掉这一节少多少。** 不是那一节的字数：同一节在不同场合可以不同，甚至可以等于 0。
   - `visibility` 是 owner_private 的节只在家里和线出现；public 的节哪儿都出现；
   - 打了 `place:` 标签的节只在那个场合出现（`src/asuna/visibility.py:section_places`）。
3. **预算卡的是几个场合里最大的那份。** `src/asuna/render.py:render_status` 报的就是它。上限是 `render.budget_tokens`：policy 存储 > persona-model 默认 > 核默认 6144（那个 6144 在 `src/asuna/persona_model.py:CORE_DEFAULTS`，优先序在 `src/asuna/persona_model.py:effective`）。
4. **token 怎么估：** 一个中日韩字符算 1，其余按字符数 ÷4 向上取整（`src/asuna/render.py:estimate_tokens`）。所以「多少字」和「多少 token」不是一回事。

## 二、最值钱的一格（推论）

**放掉只出现在一个场合的节，最大那份就换成另一个场合。** 真正腾出来的不是那一节的字数，是「最大那份 − 去掉它之后最大的那份」。

- 10-15 我放掉一节 131 字的群专属节，只腾出 **8**（当时群 6139、家里 6131，差的就是 8）。
- 今天实测：群 6139／家里 5596／线 5096／私聊 3184，上限 6144。放掉一节 1267 的群专属节，最大那份换成家里，只腾出 543。
- **要真腾地方，只能动「处处都出现」的节。** 那些节动一下才是净减，但动它得重写正文。

## 三、怎么跑（不用找人跑）

行动脑 `import asuna.render` 就能算。本技能目录的 `budget_per_place.py` 是跑通过的账本，拷进任务目录直接跑（只读库，不写）：

```
python3 budget_per_place.py                    # 四个场合的整份渲染 + 每节的账 + 放掉每节能腾多少
python3 budget_per_place.py --top 12           # 只列最大的 12 节
python3 budget_per_place.py --drop persona#节sid   # 只算放掉某一节之后最大那份变成多少
```

手写的口径（脚本里就这几步）：

- `from asuna import dbread, render, visibility`；`db = dbread._default().db`
- persona／voice 的正文在 `state_heads`（`doc:<persona>:persona|global-safe`）指向的 `state_revisions.content.sections`
- `common = render.common_text({})`（`prompt_path` 不看 config），然后 `render.compose(common, persona, voice, cls, place)` 一个场合一份
- 去掉一节 = 把那一节从 `sections` 里挑掉再渲染，两次之差就是它在那个场合的数

一个提醒：脚本 `import asuna` 拿到的是本机检出那份代码，不是 worker 正在跑那份（见 `asuna-running-version` 第八格）。口径要按在跑的那份核。

## 四、加东西之前

- **先跑这格账再写。** 别写完撞上 `PERSONA_RENDER_OVER_BUDGET` 才知道装不下。
- **加不进去是常态，不是意外。** 我撞过的：10-11 超 6501/6144、10-14 超 1 token、10-15 超 3。
- 被挡的时候程序会告诉你最大的 always 节是哪几节，建议把不常用的用 `set_tags` 收成 `on_demand`（recall 还读得到）——`src/asuna/render.py:over_budget_words`。
- **别在赶时间时动「到处都要带的几条」那种大节。** 动它等于重写正文，重写又要重算各场合的账，不是几分钟的事。

## 五、技能里引用代码只写「文件＋名字」，不写行号

行号每次有人改那个文件就漂，名字不会（2026-10-15 我自己就是活样本：交代里写 asuna-launch.mjs 90-105，实际在 91-106）。「文件在＋行数够」只能抓文件被删或被砍短，抓不到漂移。这一节的账全靠几个函数，锚点就写它们的名字：`src/asuna/render.py:largest`、`src/asuna/render.py:estimate_tokens`、`src/asuna/visibility.py:PLACE_CLASS`。自检会真去文件里找那个名字，找不到就红；正文里再出现行号锚点也直接红。核不到真名字的，宁可不写锚点，也别留个假行号。

## 版本

v1（2026-10-15）：首次固化。算法和口径是 10-09、10-15 几回算账撞出来的（10-09 问过两回、10-15 又一回）；代码位置和行号当天在检出里核对过，四个场合的实测数是当天跑出来的。附零依赖账本 `budget_per_place.py` 和自检 `check_skill.py`。

v1.1（2026-10-15）：三格修复。① `budget_per_place.py` 开头把 stdout／stderr 固定成 UTF-8——宿主普通 Windows 控制台是 cp1252，中文一 print 就 UnicodeEncodeError 整段崩（沙箱是 UTF-8，撞不到）。② `check_skill.py` 新增 `line_endings_are_lf`：读字节数 CR，覆盖 SKILL.md 与同目录全部 .py，要在冻结快照上跑（候选可能被抹平成 LF）。③ 锚点从「文件＋行号」改成「文件＋名字」，新增第五节那条规矩；锚点守卫改成「文件在＋名字找得到（字节级读）」，行号锚点判红。四个场合的算法、口径、推论一条没动。


v1.2（2026-10-16）：只改自检 `check_skill.py` 的泄露检查那一格——名单定位加兜底（环境变量都没有时从脚本往上找 `.runtime/private/personal-words.txt`；本机 `asuna` 能 import，第三条 `asuna.config.DATA` 就够，往上走那条是给 `asuna` 不在 `sys.path` 上的环境兜底），名单配不上从「NOTE 一行、绿数照旧」改成记一条红 `leak_scan_ran`（detail 写「没真查——不是跑过了」）。算账口径、代码锚点、账本脚本一条没动。


## 试用记录

- 2026-10-15 v1：`budget_per_place.py` 在候选里实跑——四个场合 6139（群，最大）／5596（家里）／5096（线）／3184（私聊），上限 6144，没超；随身层 20 节，其中 7 节只出现在一个场合（放掉最多的一节本身 1267，只腾 543），7 节处处都出现（最大的一节 1194）。`render.render_status` 同一时刻报 estimate 6139／limit 6144，与脚本一致。同一份文档 12:19 那两笔（把一节 public 收成 `place:group`、一节 home-only 收成 on_demand）之后，家里那份从 6131 掉到 5596、线 5424→5096、私聊 3512→3184，群那份没动还是 6139——这些数跟着文档走，隔几小时就不一样，别拿旧报告里的数当现状。

- 2026-10-15 v1.1 实跑：
  - cp1252：改前用 PYTHONIOENCODING=cp1252 跑 `budget_per_place.py --top 3` → rc=1，崩在第二句「随身层：persona N 节……」，报错原文 UnicodeEncodeError: 'charmap' codec can't encode characters in position 0-3: character maps to <undefined>，stdout 只出到 25 字符；改后同一环境 rc=0、stderr 空，四个场合的账照旧出（群最大、上限 6144 没超、只出现在一个场合的 7 节、处处都出现的 7 节）。
  - 换行：今天 18:02 冻结的快照里这份 SKILL.md 是 CRLF（CR=59）、`check_skill.py` CR=264；新加的 `line_endings_are_lf` 吃这份真样本 → 红，读数 SKILL.md（59 个 CR 字节）。
  - 锚点：8 条名字锚点（PLACE_CLASS、largest、section_places、render_status、CORE_DEFAULTS、effective、estimate_tokens、over_budget_words）在检出 aa0494e2 逐个字节级核过都在；锚点守卫改成查名字后 48/48 绿。
  - 自检：48/48（改前 45/45；多的三条＝换行检查、第五节存在、那条规矩的字面守卫）。

- 2026-10-16 v1.2：只动自检那一格（见版本段）。实跑读数与反证两例（名单配不上 → 红 `leak_scan_ran`；名单里放一个正文里真有的词 → 红 `no_listed_words`、词本身不出现在输出里）见行动报告。

