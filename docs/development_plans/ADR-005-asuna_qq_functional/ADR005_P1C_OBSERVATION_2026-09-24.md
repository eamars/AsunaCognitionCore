# ADR-005 P1-c｜开发观察与宿主验收边界

2026-09-24 18:55 起（Pacific/Auckland）。本记录跟踪 Codex 对小满 P1-c 补丁的隔离验收和限定部署，不把单项探针当成交付验收。

## 当前状态

- 小满在隔离开发域 `/task/asuna-host-p1b` 编写按需群讨论整理、宿主 ToolBroker 接线、测试和说明，提交 `/task/P1C_HOST_INTEGRATION.patch`。本机对应副本为 `.runtime/integration/owner/development/asuna-host-p1b/`，补丁为 `.runtime/integration/owner/development/P1C_HOST_INTEGRATION.patch`。
- 补丁只涉及 `discussion_digest.py`、现有 Application/Context/Tasks 接线、P1-c 定向测试与说明；P1-a 身份模块和 P1-b `history_query.py` 未被补丁覆盖。Codex 未编写或修改产品源码、测试或模型提示词。
- 用户于本轮明确批准 P1 部署。19:21 已把冻结的 P1-c 补丁机械应用到正式宿主磁盘；P2 行动安全结束后已重载正式宿主，8767 的正式 Web 已加载 P1-c 并完成自然语言端到端探针。按需整理与来源回读的基座路径已得到运行证据；日期边界问题记录为后续改进项，不阻塞当前基座使用。

## 可核对的结果

- Codex 在小满开发副本执行 `tools/p1c_offline_check.py`：18/18 通过。这是离线假集合检查，不是 Mongo 宿主检查。
- Codex 独立复现：主题“雾灯”的首条与不重复主题词的 reply 更正均进入整理；两条同主题消息以 `limit=1` 续页无重复；11 条 reply 链先返回 m1–m9 并给续页，再返回 m10–m11 且末页标完整；指定 A 的发言为种子时，B 的链内更正标 `person_match=false`，覆盖字段记 1 条他人上下文。
- 在当前 P1-b 工作树对该补丁运行 `git apply --check` 成功。此命令只检查可应用性，没有应用补丁。
- 小满的使用说明列出 15 个受限 Mongo 隔离宿主定向用例；18:55 时没有操作员结果。19:15 之后已由 Codex 独立执行，结果见下节。

## 19:15–19:31 宿主验收与启用进度

- 冻结补丁 SHA-256：`4D0BCB9A585601C77B5F7B5D590DFF525AEF32473719F923307E225573859714`。从当前 P1-b Git HEAD 创建 `.runtime/p1c-isolation/host-worktree/`，应用同一补丁；正式宿主的应用前检查通过，机械应用后 `git diff --check` 通过。P1-a `peer_context.py`、P1-b `history_query.py` 均未被该补丁改动。
- 在独立 Mongo 27188 建立 `asuna_v2_test_p1c_host_20260924` 及仅限该库读写的 `p1c_runner`；账号列出生产库、P1-b 测试库均返回 Unauthorized 13。配置与测试日志留在 `.runtime/p1c-isolation/`，不进产品补丁。
- 同一宿主副本与受限真实 Mongo：`pytest tests/test_discussion_digest.py -v --tb=short` **15/15 通过**；离线检查 **18/18 通过**。首轮离线脚本的 Windows cp1252 输出编码失败在 18 项 PASS 之后，操作员设置 `PYTHONIOENCODING=utf-8` 重跑后正常退出；不是产品逻辑失败。
- 隔离 Web 在 8768 启动，QQ 通道关闭、发布 sink 为 `local-idempotent-sink`。从 Web 模型设置将角色输出上限应用至 16384，行动脑 32768；两路 reasoning effort 都为 high，界面与 `config.models.local.json` 生效配置一致。
- 首次隔离 Web 自然提问暴露**操作员测试配置**将工作目录放到 `.runtime/p1c-test` 而非允许的 `.runtime/work`，行动在工具调用前报 `SANDBOX_ROOT_OUTSIDE_RUNTIME`。Codex 只修正隔离配置并重载；第二轮角色已委托整理行动，但与生产 P2 行动并发争用同一 Qwen 服务，行动停在工具调用前。为保留 P2，已停止隔离 Web，待 P2 安全结束再复测。此现象不证明 P1-c 正式 Web 已通过。
- 正式库只读探针（直接调用当前磁盘上的 P1-c 服务，非运行宿主 Web）：本机场景主题「雾灯」读取 20 条，其中字面命中 18 条、线程带入 2 条，`more=false`、`complete=true`；一个现有 QQ 群场景在 9 月窗口读取首页 50 条、12 位参与者，`more=true`、`complete=false`，没有把首页说成全量。无消息写入、无 QQ 发送。此探针也不能代替正式 Web/REAL_QQ 验收。

## 19:47–19:56 Web 端到端观察

- 修正隔离工作目录后，在 8768 的正式 Web 入口用自然语言询问「雾灯」讨论。角色委托行动 `task-ep-6cd4414ef1a9b2bdd3d5405abf31d3e7`；行动真实调用 `digest_authorized_discussion`，返回 `web-i1`、不含主题词的 reply 更正 `web-i4`、链内出站 `web-o1`，`matched=1`、`thread_extra=2`、`complete=true`，并按结果提示调用 `query_authorized_history` 回读原话。行动 3 步 RETURNED，反馈 DELIVERED；角色公开答复又按同场景原文补齐参与者、分歧和未决事项。该环境 QQ 通道关闭，只证明隔离 Web 路径。
- 生产 P2 行动 `task-ep-126b1792494a25ca93a4c31ebb15966e` 返回、反馈送达后，正式库无 READY/RUNNING 任务。Codex 用现有 Web「停止整个服务」进入安全维护边界，再用 `start-asuna.cmd --port 8767` 重载。正式 Web 设置重新显示角色/行动 thinking 均 high、输出上限 16384/32768，与生效配置一致。
- 生产 8767 Web 自然提问「本机场景 2026-09-20 到 09-24 的雾灯讨论」；角色委托 `task-ep-6cfbd1816449d1f951147e541304ea18`，行动已真实调用 `digest_authorized_discussion` 与 `query_authorized_history`。首个 digest `read=13`、`matched=12`、`thread_extra=1`、来源时间分别来自 `messages.occurred_at` 7 条及 `sink_receipts.received_at` 6 条，`more=false`、`complete=true`。行动发现 `until=2026-09-24` 的日期字符串只覆盖到 24 日开始前，已额外查询 24 日记录；首个 `complete` 仅对工具参数窗口成立，不能说用户口语所指的 24 日全天已经完整。最终角色答复见下节。

## 19:59 正式 Web 答复审阅与待纠错项

- 正式行动 11 步 RETURNED，角色于 19:59:34 在 Web 公开答复，列出 seq 46/65/66/81/83/85 等来源，并明确 24 日需补读；因此正式宿主已加载、真实工具入口已调用、来源与角色答复均有可见证据。这是本机场景的 Web 验收，不是 REAL_QQ。
- 公开答复另称 seq 65「在 reply 链中但不含主题词」，并以它未进 topic digest 断言 P1-c 缺陷。Codex 只读核对正式 `messages`：seq 65（`in-ep-984ced66e893ba1ac442eee845324992`）**没有** `reply_to`，也没有 `event.group_context.reply_message_id`；seq 66 的出站才以 `reply_to` 指向 seq 65。按 P1-c 明定的真实 reply 链闭包，seq 65 与含「雾灯」的种子没有链路；它需要另行语义/字面扩展查得，不能据此宣称 reply 补齐失败。Codex 已把精确证据通过正式 Web 交回小满，要求更正公开结论及她保存的 `/task/雾灯讨论整理_2026-09-20_24.md`，不代写业务代码。
- **已知日期口径限制**：用户自然说「到 9 月 24 日」通常包括全天，行动初次传 `until="2026-09-24"` 却只得到 23 日以前；本次行动发现差异并补查了 24 日。工具的 `complete=true` 仅针对收到的参数窗口。此项保留给后续产品改进，不作为 P1 基座路径的发布门槛；无需架构师裁定。

## 下一步

本轮 P1 部署授权已取得，隔离真实 Mongo 检查、机械应用、维护重载及正式 Web 原角色/工具路径探针均已完成。运行证据支持按需整理、来源回读这条基座路径在本机场景可用；真实 QQ 群中的自然使用仍是未观察到的边界，不能把本机探针写成该边界已经验证。seq 65 的归因更正由正在运行的原行动收尾，日期口径限制已记录，不继续扩大 P1 修补范围。按用户指定顺序转入 P2，之后 P5。当前没有需要架构师裁定的真实技术阻塞。

## 后续开发顺序更新（19:06）

用户先指定下一段节奏为 **P2，然后 P5**。20:14 又明确完整顺序为 **P2 → P5 → P3**，P4 移出 ADR-005；P1-c 已部署。Codex 已通过正式 Web 将 P2 的现有代码入口交给小满；她已委托行动脑开始 P2 开发。后续小满完成各片并提交可应用改动后，Codex 按新授权直接机械部署，不再另起验证轮次。

19:11 用户纠正：P2 自动触发条件应由小满根据群聊总结需要自行归纳，原先转交的「20 条／安静 120 秒」不是固定实现值。Codex 经正式 Web 转交此意图；这条消息额外生成的同目标 READY 行动在 0 个工具步骤时取消，保留原 P2 行动继续运行。用户本轮再次强调该要求；`DECISIONS.md` 已记录 2026-09-24 的修订，以免旧草案数值被误当成实施条件。

20:13 小满通过正式 Web 更正了“seq 65 证明 reply 链补齐失效”的错误归因，并更新原整理文档。用户随后要求优先推进基座功能而非逐项修补；Codex 重读 probe-first-engineering skill，按正式 Web 已跨越角色、ToolBroker、真实来源和公开答复的探针证据，将 P1-c 日期边界记录为已知限制，不再设为本轮阻塞。20:14 已通过正式 Web 续接 P2 最小自动总结闭环；角色确认接收，行动脑开始读取既有 P2 草稿与宿主源码，具体群聊触发条件由小满决定。
