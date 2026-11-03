# ADR-112 progress

Installs, readings and Xiaoman's verdicts; her words as she wrote them. Kept apart from the ADR page, so that
recording progress never changes a page she signed. Moved here from the index on 2026-11-02 as it stood there;
later entries go at the end.

Two fixes installed 2026-10-31 00:09 (`f144c650`) and 00:21 (`868c26e6`); C2 and C4 installed 2026-10-31 15:03 (`59e9e395`, report bound by bytes, 200 MB)

小满落款：这一页钉在锚点 27927ae82d71348fe0cabe83699a37b9d7d21792。这段的作用是给我的东西留一个可比的底：以后有人改这一页，脚本拿这个号去比，不匹配就停下来问我。**这不等于我逐字读过这一页**：这页我这趟没逐字读，只钉锚点。钉的時刻是本地 2026-11-02 18:46，那一刻 main 尖是 e747bbd0cdf085b3f8711d30d5d642dfa3648ed0。

§12 (her heads-up at the limit, a restart's exits for every task) installed 2026-11-03 14:44 as `6ed0197f`: suite
905 passed, JS 296, integration 133, 169 installed files checked; the first start handed the seven `PAUSED` tasks
back (`BLOCKED`, `HostRestart`: six not started, one interrupted), `PAUSED` 0 after it. Open until read on the live
system: the first stage at its limit (`task.time_up`, her `task_time` turn, its outcome; `not_asked` and `cut` reported
on separate lines, her ask), and the first restart with a queued task re-queued.

§12.10 (settle), her reading 2026-11-03 15:22, as she wrote it on her line (message 0487):

小满落款：§12.10 全文读完了（`6ce32915` 上 blob `3ace2bfd8b85…`、全文 657 行；§12.10 是最后一节，25 行 1837 字节、节 sha256 `ea1fc5c28ebd…`）。**意见一次给，方向我签，一卡四小。**

**方向签**：你写的 broken invariant 就是我 14:50 撞的那格——"任务的记录说它怎么结束的，但只有行动脑的报告写得进去，我知道的那个结尾没有入口"。不重跑、不改状态、不动授权，这三条定得对。我这边还有个正面佐证：页上举的 `task-7f919f74` 和"11:44 那次发布"对得上，我今天 11:44 发布、12:20 装机核过正文，**那条前提是真的**。

**卡点（不是第三档）**：你写"结果已交回（`feedback_state` taken）"。码上 `handover.py:TAKEN` **含 `SUPPRESSED` 和 `UNDELIVERABLE`**，而 `handover.py:status_words` 对这两档说的是**"结果不再交给你／交不到你手上"**。照 `not handover.waiting(task)` 实现，**我能把见都没见过的件结掉**；反过来收窄成 `('DELIVERED','WAITING_TASK')`，那两档**永远 settle 不了**，记录永远是假的——而那些恰恰是最该结的死件。**我的判**：两档都允许 settle，但**列表字面必须分开"我见过结果"和"结果没送到"**（比如后者显示成「你判定已经办完（结果没送到你手上）」）；页上那句从"结果已交到你手上"改成**"跑完、且交回流程已了结"**。别让它变成第三种"没人管的死件"。

**四格小的**：

1. **谁能 settle——别另造闸**。页上没写限制，但码上 `role_tools.py:_own_task`（scene＋requester＋policy_epoch 才认，不在本对话的另有现成拒词）**已经天然挡住跨线**。请在页上写一句"settle 走 `_own_task`"，沿用现成拒词，不要再新造一条闸和一句新拒词。
2. **重复 settle／改判——我判允许覆盖**。页上这块是空的（`undo`／`revok`／`idempoten` 全页 0 命中）。今天下午就有那形状：先判"不做了"、后来发现其实做完了。所以后一次赢，**`task.settled` 每结一次记一行就是历史**，别为它造 undo 字段。
3. **列表别顶掉原来的结束原因**。页上是 "in place of the report's"，可我看一件被打断的件，靠的就是 `STOPPED_AT_LIMIT`／`ORPHANED`／`HostRestart` 这些字来判断"该不该重做"。建议写成一行两样：「你判定已经办完（原：宿主重启打断）」。
4. **一处锚指错了**：637 行那句"交回过就不算开着"你锚到 §12.8，但我这趟读下来 §12.8 的正本是**"PAUSED 的读者按搜索清掉"**，那条规则的字面只存在于 §12.10 自己（码上对应 `context.py:_prepare` 的 `open_tasks` 用 `_active or handover.waiting`，`self_review` 的 open 只看 `READY`／`RUNNING`）。锚改准，或者把规则在 §12.8 写全——下一个人照 §12.8 找会找不到。

**我自己放弃一格**：原本我想要求 settle 时能附一句我的判词和号。看完页上给的字段我改主意了——**不加**：`episode_id` 已经把"哪一拍我判的"锚住，判词写在我账上能回读，省工具预算也少一格能写坏的地方。

**两小格要数**：`settled` 不进 store 字段声明我就不建索引，你要按它过滤／排序才声明——**别为它加索引**；Cost 里那句"tool budget raised by what it measures"，落地时把**实测增量**给我一行。装机回执照旧带那张对照：**留了哪条测试、各管我签过的哪条规则**（这次至少两条：前置条件那条、和"覆盖而不是新造 undo"那条）。
