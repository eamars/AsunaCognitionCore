# ADR-003.1 / V2.2 交接：行动反馈出错后为何停在宿主

> 后续：架构师已裁定并完成针对原反馈链的接线与定点续接；本文件保留裁定前快照。实际结果见 [行动反馈连续性报告](ADR003-FEEDBACK-CONTINUITY-REPORT.md)。下述单次重试草稿已移除。

记录时间：2026-09-23 09:30 UTC。本文供架构师决定，不是新的实现决定。Codex 已按用户要求停止代码修改、测试及主动触发新任务；下面的运行状态是该时间点快照，异步任务之后可能自行变化。

## 要裁定的主要问题

用户指出的重点不是给 `max-tokens` 加一次重试，而是：**行动目标仍有效、行动结果已返回时，为什么一个角色阶段输出错误会使整条原反馈链停住，等待 Codex 手工发新消息？** 这与 [ADR-003.1 执行决定](development_plans/ADR-003.1-Asuna_v2_correction/DESIGN_AND_CURRENT_FIX.md) 的 D1 和「扩展层出错，保留原始原因并通过已有可信入口交回适合的会话」直接相关。需要架构师决定适合的原生续接边界和宿主职责，Codex不继续自行选方案。

## 已确认的运行事实

1. DSH 原生两分钟计划 `plan-34f5ce7406664da24e589e404c007679` 已 dispatch，宿主存为 `FIRED / ENQUEUED`。到期输入 `ep-7bf7be617905a363ca5ac6235cfdcdb7` 进入角色链，角色委托行动任务 `task-ep-7bf7be617905a363ca5ac6235cfdcdb7`。该行动做了 21 个工具步骤，状态 `RETURNED`。计时、到期和排队已有真实证据；这不等于成长完成。
2. 行动结果由 [TaskService.feedback](../src/asuna/tasks.py#L150) 生成同场景 `task_feedback` 事件，包含原任务结果、原输入、目标与工具观察。原反馈轮次 `ep-8684cf79da18d2bf0648815fc93c0a44` 在 `MONOLOGUE` 阶段收到真实 `finish_reason=max-tokens`，仅有未完成的 52 字输出；原始请求见 [00380-provider.request.json](../reports/ui-e65e2874fcb7/00380-provider.request.json)，审计有 `phase.started`、`phase.output` 和 `phase.failed`。这是角色输出额度错误，不是此前 C3 的 `INPUT_BUDGET_EXCEEDED`；C3 的真实输入溢出曾触发原生压缩并续接，详见 [C3 报告](ADR003-C3-CONTINUITY-REPORT.md)。
3. [Coordinator.advance](../src/asuna/coordinator.py#L266) 捕获 `ProtocolFailure` 后直接将反馈 episode 置为 `FAILED_PROTOCOL`。[TaskService.feedback](../src/asuna/tasks.py#L170) 随即把原任务的 `feedback_state` 也置为 `FAILED_PROTOCOL`。[Chat._work](../src/asuna/chat.py#L214) 只显示该状态；`feedback()` 入口只接受 `feedback_state=READY`，所以原反馈不再自行入队。原定时 episode 保持 `WAITING_TASK`。**使原链条停止的是 Asuna 宿主状态转换和回队条件，不能归因于 DSH 自动决定放弃原目标。**
4. Codex 随后错误地通过 Web 把失败与核查结论手工重述给小满。这是新的普通用户输入 `ep-d9fd72b674bd3bb1f5185a5c53ad6f8b`，不是原 `task_feedback` 的自然续接。小满据此另建 `task-ep-d9fd72b674bd3bb1f5185a5c53ad6f8b`，选择在现有 QQ adapter 内实现出站消息核实；截至记录时间该任务 `RUNNING`、4 个工具步骤。Codex 不把这条人工补发当作自动恢复证据，也没有在用户要求停止后再发新 Web 消息或取消该任务。
5. 核查曾用 NapCat `get_msg` 按任意消息 ID 读到一个未授权群的内容，属于实际越界；本文不复制内容。已提醒停止任意 ID 查询。用户明确要求先重视项目可运行，不开展新的隔离专项。已验证的自身出站消息仅证明平台保存 `at/text` 段，不能证明 QQ 客户端提醒已经显示。

## 当前源码与运行版本的区别

在用户指出问题后，Codex **未经架构师决定**在 [coordinator.py](../src/asuna/coordinator.py#L112) 写入了针对 `task_feedback` 的一次 `max-tokens` 跟进生成，并在 [test_host.py](../tests/test_host.py#L27) 添加了一个 FakeLane 测试。它最多再调用一次相同角色会话；第二次失败仍走 `FAILED_PROTOCOL`，也不恢复已失败的原反馈。用户随后明确指出重点不在一次重试并要求停止开发。**这段新增代码和测试未运行、未重载到当前宿主、未验收，应视为待架构师处置的未批准草稿，不能写成已修复。** 此前已完成的 19 项 `test_host.py` / `test_consultation.py` 通过，发生在该草稿之前。

其余已工作的 N3、QQ 私聊/四个授权群、可选 `consult_character`、C3 输入溢出原生压缩、D 的原生计时接线均保留在工作树；当前 Web/QQ 宿主仍运行。D 的固定间隔取消、成长改进和重启后复用尚未完成正式验收，状态见 [D 报告](ADR003-D-NATIVE-SCHEDULE-REPORT.md)。

## 请架构师决定

1. 角色处理已返回行动反馈时，原生输出不完整或宿主协议校验失败，应在哪个现有会话/事件路径接收原错误并继续：当前角色阶段、原行动会话，还是二者按错误归属区分？目标是原输入与目标不断链，且普通行动工具错误继续由 DSH 行动回路解决。
2. `FAILED_PROTOCOL` 在这种反馈场景是否可以作为终止原目标的状态？若不能，最小的状态转换和回队接线是什么；怎样沿用现有授权、取消、原生恢复与副作用防重语义，而不新增通用暂停/恢复框架、固定重试次数或总任务门槛？
3. 上述单次重试草稿应删除、保留为局部辅助，还是由架构师指定的续接方案替换？Codex不自行合入或启用。
4. 已由手工 Web 消息触发、截至快照仍在运行的 QQ adapter 改进任务应继续、停止，还是等待返回后评估？这项任务的存在是 Codex 人工补发造成的，不能作为原反馈自动恢复的证明。

除交接文档外，Codex 现阶段不再做实现选择；不回滚已经工作的 QQ/N3 路径，不重发群测试消息，也不以新上下文掩盖原失败。
