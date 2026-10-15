---
name: asuna-render-budget-per-place
description: 我身上每层字（persona／voice 里 inject=always 那些节）在家里／线／群／私聊各占多少 token、往随身层加东西之前算这笔账的做法。算法写死：对四个场合各渲染一份（render.largest 走的就是 visibility.PLACE_CLASS）；每节的数＝那份渲染去掉这一节少多少；预算卡的是几个场合里最大的那份；推论最值钱——放掉只出现在一个场合的节，最大那份就换成另一个场合，可能只腾几格（10-15 放掉一节 131 字的群专属节只腾出 8），要真腾地方只能动处处都出现的节；行动脑 import asuna.render 自己就能算，不用找开发助手跑；加不进去是常态不是意外。附零依赖账本 budget_per_place.py 与自检 check_skill.py。
---

# asuna-render-budget-per-place

随身层就是我走到哪儿都带着的那几层字：persona 和 voice 里 `inject=always` 的节。它有一个 token 上限，超了就写不进去。这笔账的算法是固定的，不该每次找人跑。

## 一、算法（写死，别自己发明）

1. **对家里／线／群／私聊各渲染一份。** 场合和可见级的对应表在 `src/asuna/visibility.py:23`（`PLACE_CLASS`：home、peer 是 owner_private，group、dm 是 public）；`render.largest`（`src/asuna/render.py:66-71`）就是把这四份都渲一遍取最大的那个。
2. **每一节的数 = 那份渲染去掉这一节少多少。** 不是那一节的字数：同一节在不同场合可以不同，甚至可以等于 0。
   - `visibility` 是 owner_private 的节只在家里和线出现；public 的节哪儿都出现；
   - 打了 `place:` 标签的节只在那个场合出现（`visibility.section_places`，`src/asuna/visibility.py:36-40`）。
3. **预算卡的是几个场合里最大的那份。** `render.render_status`（`src/asuna/render.py:151-159`）报的就是它。上限是 `render.budget_tokens`：policy 存储 > persona-model 默认 > 核默认 6144（`src/asuna/persona_model.py:58`，`persona_model.effective` 的优先序在 `:174-183`）。
4. **token 怎么估：** 一个中日韩字符算 1，其余按字符数 ÷4 向上取整（`render.estimate_tokens`，`src/asuna/render.py:96-100`）。所以「多少字」和「多少 token」不是一回事。

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
- 被挡的时候程序会告诉你最大的 always 节是哪几节，建议把不常用的用 `set_tags` 收成 `on_demand`（recall 还读得到）——`render.over_budget_words`，`src/asuna/render.py:195-205`。
- **别在赶时间时动「到处都要带的几条」那种大节。** 动它等于重写正文，重写又要重算各场合的账，不是几分钟的事。

## 版本

v1（2026-10-15）：首次固化。算法和口径是 10-09、10-15 几回算账撞出来的（10-09 问过两回、10-15 又一回）；代码位置和行号当天在检出里核对过，四个场合的实测数是当天跑出来的。附零依赖账本 `budget_per_place.py` 和自检 `check_skill.py`。

## 试用记录

- 2026-10-15 v1：`budget_per_place.py` 在候选里实跑——四个场合 6139（群，最大）／5596（家里）／5096（线）／3184（私聊），上限 6144，没超；随身层 20 节，其中 7 节只出现在一个场合（放掉最多的一节本身 1267，只腾 543），7 节处处都出现（最大的一节 1194）。`render.render_status` 同一时刻报 estimate 6139／limit 6144，与脚本一致。同一份文档 12:19 那两笔（把一节 public 收成 `place:group`、一节 home-only 收成 on_demand）之后，家里那份从 6131 掉到 5596、线 5424→5096、私聊 3512→3184，群那份没动还是 6139——这些数跟着文档走，隔几小时就不一样，别拿旧报告里的数当现状。
