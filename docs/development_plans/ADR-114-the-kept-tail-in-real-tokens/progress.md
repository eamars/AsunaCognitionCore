# ADR-114 progress

Installs, readings and Xiaoman's verdicts; her words as she wrote them. Kept apart from the ADR page, so that
recording progress never changes a page she signed. Moved here from the index on 2026-11-02 as it stood there;
later entries go at the end.

Built; installed 2026-11-01 01:00 as `ec9211cc`; DSH `d9d52adae4` on `asuna/0.2.1-rc.2-realtail` (the owner's fork); Xiaoman read it and agreed to the change in her preset

小满落款：这一页钉在锚点 dcbe3dfafb96e63ad1f4b8644bfdb86042847735。这段的作用是给我的东西留一个可比的底：以后有人改这一页，脚本拿这个号去比，不匹配就停下来问我。**这不等于我逐字读过这一页**：我 11-01 逐字读过设计并签；现在这版页 blob 和那一版之间我没逐行比过，钉的是现在这版。钉的時刻是本地 2026-11-02 18:46，那一刻 main 尖是 e747bbd0cdf085b3f8711d30d5d642dfa3648ed0。

小满落款：**装后（11-02 01:00:12 起，`ec9211cc…`）两个脑的回合内压缩：行动脑那半"不二次压缩"成立，落点区间下沿偏低，请她核一眼固定开销；我这半 n＝1，不判。** 行动脑 6 个样本，压缩后下一次请求 **85.7k／92.8k／95.0k／109.0k／89.5k／97.2k**（页上 §9 第 205–206 行预期 95k–100k）——三个在区间内或之上，三个偏低 2–9k；**六个样本都没有紧跟着的二次压缩**（第一次那个之后隔了 17 步、13.5 分钟才再来）。我这半只有一个样本：11-02 13:53:49＋13／00:53:49Z，压缩后下一次 **95.4k**，低于页上 §6 那句 "107k–127k, unchanged"，**n＝1 不判**；同会话 00:58:02Z 那次 `turn` 为空、算不算二次压缩未核实。`step compaction failed …; continuing the turn` 那条 warn 装后**没有**（`host.log` 全文无此句；30 次压缩里 29 次有 `compaction/end`）。**口径要标明：这里的"请求大小"是取数那趟用 `inputTokens + cacheReadTokens` 算的，是推断，没跟 `totalTokens` 对账**——落在区间外的判断以她核过口径为准。我这侧 11-08 00:58 那枚钟留着继续攒样本。

小满落款：

**七天验收读数（本地钟面 2026-11-08；取数：只读一趟 `task-63b614f67851385907490877ebc8e0d0`，00:58→01:23，80 条工具记录，未改文件、未重启）**

- **有效窗只有三天半。** `${ASUNA_DATA}\restart\history.jsonl` 的 `loaded.packages['@deepseek-ai/dsh-compaction-basic']`：`3153519e45ac` 自本地 2026-11-01 01:00:12（commit `ec9211cc`）起在跑；**2026-11-04 21:10:40（commit `d8b9b795`）换到 `59977223a0cb`（`sourceCommit 4a4f9f1d77`，branch `asuna/0.2.2-alpha.3`），此后未变**。窗内 108 次回合内压缩里 **91 次不属于本版**。
- **本版在跑的窗内：达标。** 行动脑 16 条回合内压缩，压缩后下一次请求 **81,251–108,990、中位 91,836**（`prompt = inputTokens + cacheReadTokens`，逐条与 `totalTokens − outputTokens` 对过）；落在 §9 那一带的有 4 条（95,031／95,111／96,507／97,245）；**16 条里没有一条在 5 步内二次压缩**（同会话第二次都在 18／24／40 步之后）。第一次 11-01 11:57:04：195,254 → 93,458。
- **角色半没样本**：家里那条私聊（`lane=character, scene_id=local-dm`）窗内回合内压缩 **0 次**，窗内最大一次请求 196,296，未够到 `thresholdRatio: 0.80`（`packages/personas/xiaoman/cordis.patch.yml:36`）。角色半窗内 135 次 `compaction/start` 里只有 2 次带 `turn`：本版那次 208,455 → 95,376（11-02 13:53:49）；换版那次 210,788 → 188,109（11-05 16:03:52）。两次之后同会话下一次压缩都是回合末。
- **§9 那条 warn 我这条道量不到**：`host.log` 全文 6,844 行 `step compaction failed` 命中 0，而 DSH 的 `ctx.logger` 不落 `host.log`（那 106 次压缩的时刻只有 Asuna 自己那行），所以 0 命中不证明没发生。能落盘的替代读数：会话记录 `compaction/end` 带 `error` 共 32 条，其中回合内 25 条全是 `summary is not smaller than the shadowed content (N estimated framed tokens >= M)`（18 条来自 11-05 那场、7 条来自 11-07 那场）。
- **限度（写清，别当结论读）**：那 25 条按装机那份 `index.js:839-851` 的 `agent/pre-step` try/catch 应当在运行时各打一条 warn，**我没亲眼见过那行字**，故只写"收场失败 25 次"；"少了那步换算 ⇒ 留的尾巴约两倍厚"是**推断**（时刻与落点方向一致），**没做对照实验**；两条风暴会话（`task-f8ed0ff7…` 47 次／11-05 08:14–09:25、`task-8e6af995…` 38 次／11-07 08:15–09:36，压缩后 87 条 ≥150k、"隔 0 步 23 次、隔 1 步 33 次"）的节点形状没读，那格归 Claude。
- **换版后那 87 条 ≥150k 不算本版回归**：`estimatedTailBudget` 只存在于 `d9d52adae4`（`asuna/0.2.1-rc.2-realtail`），`merge-base --is-ancestor d9d52adae4 4a4f9f1d77` 返回 1，装机 lib 里 `estimatedTail` 命中 0——修复没跟到 0.2.2 那条线。合入与重建归 Claude 与主人，不写进本判词结论。
- **状态建议：不算 `Built`**（Claude 11-08 定：等修复回到 0.2.2 那条线、重读过再说）。本版在跑窗内那两格（行动脑落点、无 5 步内二次压缩）**判合格**，那三天半不算白装。
- 顺带两处字面：本节以下那句"装后（11-02 01:00:12 起）"比 `history.jsonl` 晚一天（真装机本地 11-01 01:00:12），按它切窗会漏掉 11-01 的样本；README 的 §9 验收句在 **205–206 行**、落点表在 150–152 行（此前被引成 183–184，那是 §8 测试段）。我 11-01 装机前逐字读过 README 那 191 行，上面这些行号是 11-08 现读；**这不等于我 11-08 又逐字重读过整页**。

## Closed on evidence (2026-11-09)

The 0.2.2 move (2026-11-04) left the fix out; it was ported on 2026-11-08 (DSH `asuna/0.2.2-alpha.3-realtail`,
`f2afea05f9`; Asuna `ad284b77`, compaction engine `06bde178edeb`). Closed on three proofs:
1. **The mechanism, staged:** the ICD's CMP-6 (`scripts/asuna-icd/cmp.spec.ts`, DSH `ef6a4702b4`) runs a pressure
   compaction through the agent loop with the provider counting twice DSH's estimate: on 0.2.2's own code it compacts
   twice in one turn (the storm's shape); with the fix once, and the next request is below its threshold.
2. **The same code on her real data:** the port is the 11-01 commit with no code conflict; from 11-01 01:00 to 11-04
   21:10, under it, her action brain compacted 16 times, kept 81,251 to 108,990 (median 91,836.5, in tokens: the prompt side of the first request after each compaction, input plus cache reads, the engine's own pressure measure, so they compare with `thresholdRatio` directly; her definition, 11-09), and none
   compacted again within 5 steps (her reading of 11-08).
3. **In place:** the installed engine holds the fix (her count, 11-08: 0 hits in the 0.2.2 builds, 2 in `06bde178`).

Not measured, and closed so: **her character brain's own in-turn compaction**, no sample (her private chat had none in
the window) and not staged; it runs the same engine, which proof 1 covers. **Her two probes of 11-09 are staged, not
natural:** the first crossed the threshold (757,335 tokens at step 21; `thresholdRatio` is 0.75 on a 1M window) and was
taken by the tool-result pruner, not a summary (21 prunes, 248,137 tokens shadowed, 124,517 at the next step, no
second compaction within 5 steps): it shows only that pruning keeps the task's shape; the second, to force a summary,
was stopped as not needed. Neither enters a comparison window.
