---
name: asuna-render-budget-per-place
description: 我身上每层字（persona／voice 里 inject=always 那些节）在家里／线／群／私聊各占多少 token、往随身层加东西之前算这笔账的做法。算法写死：对四个场合各渲染一份（render.largest 走的就是 visibility.PLACE_CLASS）；每节的数＝那份渲染去掉这一节少多少；同一份库有两种口径并排打——预算口径（程序卡预算读 doc 里的 inject）和带出门口径（render_system 先过 memory_tiers.placed，inject 跟着 tier 的档走），两列可以差几百 token，账本逐节报为什么不一样；程序现在卡的是预算口径那列最大的那份，该卡哪一份没定案；推论最值钱——放掉只出现在一个场合的节，最大那份就换成另一个场合，可能只腾几格（放掉一节 131 字的群专属节只腾出 8），要真腾地方只能动处处都出现的节；自我层（self／core）不进 render.compose，不受 6144 管，单独一格；自证锚点认跨场合的形状不认绝对数；行动脑 import asuna.render 自己就能算，不用找开发助手跑；加不进去是常态不是意外。附零依赖账本 budget_per_place.py 与自检 check_skill.py。
---

# asuna-render-budget-per-place

随身层就是我走到哪儿都带着的那几层字：persona 和 voice 里 `inject=always` 的节。它有一个 token 上限，超了就写不进去。这笔账的算法是固定的，不该每次找人跑。

## 一、算法（写死，别自己发明）

1. **对家里／线／群／私聊各渲染一份。** 场合和可见级的对应表在 `src/asuna/visibility.py:PLACE_CLASS`（home、peer 是 owner_private，group、dm 是 public）；`src/asuna/render.py:largest` 就是把这四份都渲一遍取最大的那个。
2. **每一节的数 = 那份渲染去掉这一节少多少。** 不是那一节的字数：同一节在不同场合可以不同，甚至可以等于 0。
   - `visibility` 是 owner_private 的节只在家里和线出现；public 的节哪儿都出现；
   - 打了 `place:` 标签的节只在那个场合出现（`src/asuna/visibility.py:section_places`）。
3. **预算卡的是几个场合里最大的那份。** `src/asuna/render.py:render_status` 报的就是它。上限现在由 `src/asuna/carried.py:limit` 算：基数是 `render.identity_tokens`，优先序 policy 存储 > persona-model 默认 > 核默认（那格 12288 在 `src/asuna/persona_model.py:CORE_DEFAULTS`，优先序在 `src/asuna/persona_model.py:effective`）；再给包里自己种子的渲染留余量——`src/asuna/render.py:SEED_ROOM`＝种子渲染 ×1.25，只有超过基数一半（`src/asuna/carried.py:PERSONA_SHARE`＝0.5）的那一截加到基数上面，整顶再被 `render.max_window_share` × 上下文窗口压住。**现值以脚本现读为准**：`budget_per_place.py` 打的「上限 N」那一行就是它（实跑打出「上限 12288」）。旧键名 `render.budget_tokens` 已退役，别用。这是**预算口径**：它直接读 doc 里的 `inject`；真带出门那份是另一个数，见第六节。
   - 现行按 render 那族上限 12288 一把，旧的 6144 口径别用；两份口径并排量、别混（另一把 placed 真带出门口径另列，见第六节）。
4. **token 怎么估：** 一个中日韩字符算 1，其余按字符数 ÷4 向上取整（`src/asuna/render.py:estimate_tokens`）。所以「多少字」和「多少 token」不是一回事。

## 二、最值钱的一格（推论）

**放掉只出现在一个场合的节，最大那份就换成另一个场合。** 真正腾出来的不是那一节的字数，是「最大那份 − 去掉它之后最大的那份」。

- **要真腾地方，只能动「处处都出现」的节。** 那些节动一下才是净减，但动它得重写正文。

## 三、怎么跑（不用找人跑）

行动脑 `import asuna.render` 就能算。本技能目录的 `budget_per_place.py` 是跑通过的账本，拷进任务目录直接跑（只读库，不写）：

```
python3 budget_per_place.py                    # 两份口径并排 + 逐节差异 + 自我层 + 锚点形状 + 每节的账（预算口径）+ 放掉每节能腾多少
python3 budget_per_place.py --top 12           # 每节的账只列最大的 12 节
python3 budget_per_place.py --drop persona#节sid   # 只算放掉某一节之后最大那份变成多少
```

手写的口径（脚本里就这几步）：

- `from asuna import dbread, render, visibility`；`db = dbread._default().db`
- persona／voice 的正文在 `state_heads`（`doc:<persona>:persona|global-safe`）指向的 `state_revisions.content.sections`
- `common = render.common_text({})`（`prompt_path` 不看 config），然后 `render.compose(common, persona, voice, cls, place)` 一个场合一份
- 去掉一节 = 把那一节从 `sections` 里挑掉再渲染，两次之差就是它在那个场合的数
- 带出门口径 = 同一份 doc 先过 `src/asuna/memory_tiers.py:placed`（只读 `memory_tiers` 表，给它一个只带 db 的壳就够）再 compose；账本不调 `render_system`（超预算时它会写一行审计，账本只读）

一个提醒：脚本 `import asuna` 拿到的是本机检出那份代码，不是 worker 正在跑那份（见 `asuna-running-version` 第八格）。口径要按在跑的那份核。

## 四、加东西之前

- **先跑这格账再写。** 别写完撞上 `PERSONA_RENDER_OVER_BUDGET` 才知道装不下。
- **加不进去是常态，不是意外。** 
- 被挡的时候程序会告诉你最大的 always 节是哪几节，建议把不常用的用 `set_tags` 收成 `on_demand`（recall 还读得到）——`src/asuna/render.py:over_budget_words`。
- **别在赶时间时动「到处都要带的几条」那种大节。** 动它等于重写正文，重写又要重算各场合的账，不是几分钟的事。

## 五、技能里引用代码只写「文件＋名字」，不写行号

行号每次有人改那个文件就漂，名字不会。「文件在＋行数够」只能抓文件被删或被砍短，抓不到漂移。这一节的账全靠几个函数，锚点就写它们的名字：`src/asuna/render.py:largest`、`src/asuna/render.py:estimate_tokens`、`src/asuna/visibility.py:PLACE_CLASS`。自检会真去文件里找那个名字，找不到就红；正文里再出现行号锚点也直接红。核不到真名字的，宁可不写锚点，也别留个假行号。

## 六、两份口径、自我层、锚点形状

1. **同一份库有两种口径，不是一个数。**
   - 预算口径：`src/asuna/render.py:largest`、`src/asuna/render.py:render_status`、`src/asuna/render.py:report_budget`、`src/asuna/render.py:budget_gate` 都直接吃 doc 里的 `inject`（读码得来）；
   - 带出门口径：`src/asuna/render.py:render_system` 先过 `src/asuna/memory_tiers.py:placed`，每一节的 `inject` 改成跟着 `memory_tiers` 里排的那一档（随身→always、手边→on_demand、收着→never）再 compose，那一拍真进提示词的字是这份。
   两列的差全来自「doc 里的 inject 和 tier 的档对不上」的节。账本逐节报：doc 里 `inject`／`visibility`／`tags` 怎么说，对 tier 排成哪一档，再给各场合 ±token，最后对账（逐节之和对整份实差，没解释掉的那一格单独报）。解释不出来就照实写「没解释掉 N」，不凑。
2. **读数样本（persona revision 202／voice revision 14）**：预算口径 家 5951／线 4582／群 6126／私 3182，带出门 家 6298／线 4929／群 5265／私 3182。群 −861 是 voice 那节「限定语是家里话」（doc 里 inject=always、visibility=public、tags=place:group；tier 排在手边，也就是 on_demand，群里整节掉出去）；家与线各 +347 是 voice 那节「转述工具报错说它的字面」（doc 里 inject=on_demand、visibility=owner_private；tier 排在随身，家和线里整节进来）。第三节（doc on_demand＋ place:group，tier 收着）对两份都是 0。逐节之和与整份实差对得上，没解释掉的 0。这些数跟着 doc 和 tier 变，只是一次样本。
3. **闸卡哪一份：没定案。** 代码现状（读 `report_budget`）：它吃 doc 原文，所以带出门那份越了上限也不会为它报警——我没去翻审计表核其他地方有没有报警。「闸该卡真带出门那份，inject 当申请、tier 是权威」是别处那一拍的读法，没核到是不是开发本人拍的板，待读码，不是定案；这格动的是 core，不在本技能范围。账本只并排打，不替哪一份说话。
4. **自我层单独一格，不受 6144 管。** `self`、`core` 两本文档不进 `src/asuna/render.py:compose`（它只吃 persona＋voice），走 `src/asuna/context.py` 里的 self_state（current_self／character_core 那一块），放不放得下不看 `render.budget_tokens`（它有没有别的上限我没查）。所以「自我层省了 N」不等于「预算省了 N」：账本把自我层单独打一格、明写不受 6144 管，并把 doc 口径和 tier 口径并排（self 这本两边的随身节数也对不上）；估法是我自己的量法（标题＋正文的 estimate_tokens），不是程序报的数，不该和两列相加。
5. **自证锚点认形状，不认绝对数。** 锚 persona 里「我自己的源码在哪儿」那一节的跨场合分布：群＝0、家里有（线那一格不要求）；另打一行「只出现在一个场合的节数」（预算口径下 8 节，带出门口径 7 节）。绝对 token 数每次改文档都变（那节改短之后，旧锚点的绝对数就作废了），要留就带 revision 号当旁注，账本就是这么打的。形状不对＝锚点失效，先换锚点再信别的数。
