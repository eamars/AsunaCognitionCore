# ADR-003.1：行动反馈原链续接

2026-09-23，依据架构师对行动反馈消费路径的裁定实施。保留 N3、QQ、可选角色咨询、原 DSH 会话和任务结果；没有建立恢复框架或重跑行动。

## 真实断点与预算

DSH 两分钟计划到期后，原行动任务 `task-ep-7bf7be617905a363ca5ac6235cfdcdb7` 已做 21 个工具步骤并 `RETURNED`。其原反馈 episode `ep-8684cf79da18d2bf0648815fc93c0a44` 在 `MONOLOGUE` 阶段收到 HTTP 200、上游 `finish_reason=length`、DSH `max-tokens`，仅有 52 字未完成输出。原始 [请求](../reports/ui-e65e2874fcb7/00380-provider.request.json)与[响应](../reports/ui-e65e2874fcb7/00390-provider.response.json)显示 `max_tokens=4096`，`prompt_tokens=68578`、`completion_tokens=30`、`total_tokens=68608`；部署上下文容量也为 68608。此次是输入逼近窗口后只剩 30 token 的**输出截断**，并非 HTTP 400 输入溢出，也不是 JSON 协议缺字段。该轮没有完成原生压缩；之后其他正常轮次的原生压缩使同会话后续请求有较多余量。没有证据指向模型容量配置写错，本次不调高上限或用配置改动替代反馈生命周期修复。

先前 [C3 报告](ADR003-C3-CONTINUITY-REPORT.md)中的 `INPUT_BUDGET_EXCEEDED` 与这次分开处理：那次上游真实输入溢出触发原生压缩并继续原请求；这里上游接受了请求，只是输出被窗口截断。

旧接线在 [Coordinator.advance](../src/asuna/coordinator.py) 将该阶段错误持久记为 `FAILED_PROTOCOL`，随后 [TaskService.feedback](../src/asuna/tasks.py) 把任务 `feedback_state` 也设为同一状态，而反馈入口只允许 `READY`。因此原反馈失去队列资格。Codex 曾错误地通过 Web 人工重述，生成独立输入 `ep-d9fd72b674bd3bb1f5185a5c53ad6f8b` 和另一行动任务；它不是原链续接。未经裁定写入的 `task_feedback` 专用单次 `max-tokens` 重试草稿及其 FakeLane 测试已单独移除，其余工作树改动保留。

## 最小接线与验证

- 原反馈一次生成失败时，episode 仍记录 `FAILED_PROTOCOL`、原失败输出及请求引用；任务 `feedback_state` 保持现有 `READY`。现有 [Chat 队列](../src/asuna/chat.py)再次交付同一个内部 feedback 事件，不产生用户消息。
- `TaskService.feedback` 找回已存 feedback episode，核对原任务、版本、场景和人物后直接调用 `advance`；不重新 ingest、不创建另一条反馈或行动任务。宿主重启沿已有 `READY` 任务回队逻辑继续，不扫描重放所有历史失败。
- `Coordinator.advance` 对该原 `task_feedback` 的失败阶段在相同 Gemma 绑定中用新的原生 followup 接续，失败阶段和旧错误来自持久记录。MONOLOGUE 续接不再次注入整份约 57 KB 的冻结上下文；此前输入、行动结果和截断输出仍留在原会话与数据库。已提交的独白、决策和公开发布沿原有幂等阶段前进；取消及权限 epoch 仍按现有路径核对。没有固定重试终止次数，也没有让 Qwen 重领任务或重写 CONSULT。
- 局部自动队列测试先产生一次 `max-tokens`/`FAILED_PROTOCOL`，再由同一 feedback episode 完成，只有一条反馈输入、一项行动任务和一条公开输出。`tests/test_host.py` 与 `tests/test_consultation.py` 共 **20 passed**，`git diff --check` 通过。

实际加载前确认零个 `READY/RUNNING` 行动和零个未完成角色阶段；通过 Web 停止宿主，**只**将上述旧任务的 `feedback_state` 从 `FAILED_PROTOCOL` 标回 `READY`，保留 `feedback_episode`、原行动结果、定时记录与失败审计，随后重启原 Web 宿主。正常恢复队列交付了 `ep-8684cf79da18d2bf0648815fc93c0a44`，其 `MONOLOGUE:0:resume:1` 和 `DECIDE:0:resume:1` 均在原 Gemma 会话正常停止。对应上游用量分别为 `prompt=29853/completion=80` 与 `prompt=30611/completion=66`；反馈 episode 最终 `COMMITTED`，原任务仍 `RETURNED` 且 `feedback_state=DELIVERED`。角色知道人工任务已先行汇报，于是 `next=silent`，没有重发同一内容。Web 页面已重新连接并可见原执行状态。

## D 阶段边界

人工补发任务 `task-ep-d9fd72b674bd3bb1f5185a5c53ad6f8b` 已自行 `RETURNED`，其反馈 `COMMITTED`。小满在该独立路径实现并启用了 adapter 0.2.3 的自身出站 ID 读回核实，报告离线 126 项通过及 NapCat 只读用例；代码只从本次发送返回的 ID 调用 `get_msg`，不再沿任意历史 ID 查询。它是实际改动，**不是**原定时反馈自动恢复，也不能据此宣布 N8 自主成长验收通过。首次新版自然群出站读回、QQ 客户端提醒显示和重启后自主复用仍未验证。

另经本机 Web，自然对话创建 `every_seconds=300` 的计划 `plan-a0329d52e7782a90efd31a22b533e604`，随后明确取消。宿主状态 `CANCELLED`，DSH 原生 scheduler 记录同一 `schedule-2` 的 create seq 7、delete seq 8；没有等待到期或制造外部发送。D 的一次定时触发和固定间隔创建/取消有实际证据；真正的角色自主改善链仍为 **PARTIAL**。

## 2026-09-23 输出空间后续核对

按架构师后续裁定核对了那次最终模型请求：角色反馈用户段为 42,387 字，配置输出预算 4,096 token，而 DSH 原生 `agent/pre-step` 压力检查发生在新消息写入会话表面之前。结果上游接收了 68,578 prompt tokens，却只剩 30 completion tokens。它没有发出输入溢出错误，因此原生 request-error 压缩没有机会接管。宿主额外硬预算门槛仍保持关闭。

宿主与 DSH 桥只补一条待注入输入的压力衔接：共享原生 0.8 阈值，用 DSH token meter 估算当前已领取但未写入的消息；预计越过压力阈值或输出预留边界时，委托既有原生压缩引擎先处理旧会话表面，然后原消息照常进入本轮。不把压力估算作为拒绝生成的资格，不增加固定续写次数，也不改模型上限。隔离数据库、安装版 DSH、本机假模型接口的执行探针显示，第二段长输入到来后顺序为普通生成→原生摘要→普通生成，第二轮 `projected=8072`、`threshold=6553`、压缩一次，两轮均 `stop`；证据 `reports/pressure-prestep-probe-a219278671/`。局部回归与相关检查 26 项通过。此为接线验证；正式 Web 宿主尚未重载该补丁，真实 68k 请求不重复采样。

N6 按独立能力分别保留旧证据，只有长消息保存与尾部召回必须针对同一条消息。N8 的 `silent` 不构成失败；人工触发的 0.2.3 是真实改进，但不追认原定时链成长。N5 的实际原始 NapCat `/api` 读面仍需定点收束，不能以 adapter 默认用法代替访问边界。

针对 N6 已保存的 465 字长笔记，另做一次**只读检索诊断**：不含答案的查询通过现有 `server_vector_rrf` 路径选中同一原文的第 2 个尾块，`vector_verified=true`，证据 `reports/n6-readonly-retrieval-138d7a4259/`。这只表明索引与检索路径可找到尾块；尚未通过 Web 自然提问，也未声称角色实际回忆成功。当前会话没有可调用的 in-app browser 控制工具，因此未用终端聊天或 CLI 输入取代 Web 验收。
