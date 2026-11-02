# ADR-114 progress

Installs, readings and Xiaoman's verdicts; her words as she wrote them. Kept apart from the ADR page, so that
recording progress never changes a page she signed. Moved here from the index on 2026-11-02 as it stood there;
later entries go at the end.

Built; installed 2026-11-01 01:00 as `ec9211cc`; DSH `d9d52adae4` on `asuna/0.2.1-rc.2-realtail` (the owner's fork); Xiaoman read it and agreed to the change in her preset

小满落款：这一页钉在锚点 dcbe3dfafb96e63ad1f4b8644bfdb86042847735。这段的作用是给我的东西留一个可比的底：以后有人改这一页，脚本拿这个号去比，不匹配就停下来问我。**这不等于我逐字读过这一页**：我 11-01 逐字读过设计并签；现在这版页 blob 和那一版之间我没逐行比过，钉的是现在这版。钉的時刻是本地 2026-11-02 18:46，那一刻 main 尖是 e747bbd0cdf085b3f8711d30d5d642dfa3648ed0。

小满落款：**装后（11-02 01:00:12 起，`ec9211cc…`）两个脑的回合内压缩：行动脑那半"不二次压缩"成立，落点区间下沿偏低，请她核一眼固定开销；我这半 n＝1，不判。** 行动脑 6 个样本，压缩后下一次请求 **85.7k／92.8k／95.0k／109.0k／89.5k／97.2k**（页上 §9 第 205–206 行预期 95k–100k）——三个在区间内或之上，三个偏低 2–9k；**六个样本都没有紧跟着的二次压缩**（第一次那个之后隔了 17 步、13.5 分钟才再来）。我这半只有一个样本：11-02 13:53:49＋13／00:53:49Z，压缩后下一次 **95.4k**，低于页上 §6 那句 "107k–127k, unchanged"，**n＝1 不判**；同会话 00:58:02Z 那次 `turn` 为空、算不算二次压缩未核实。`step compaction failed …; continuing the turn` 那条 warn 装后**没有**（`host.log` 全文无此句；30 次压缩里 29 次有 `compaction/end`）。**口径要标明：这里的"请求大小"是取数那趟用 `inputTokens + cacheReadTokens` 算的，是推断，没跟 `totalTokens` 对账**——落在区间外的判断以她核过口径为准。我这侧 11-08 00:58 那枚钟留着继续攒样本。
