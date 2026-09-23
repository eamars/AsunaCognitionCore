# ADR-003 补充：行动期间的可选角色咨询

2026-09-23。按用户确认保留 N3 已通过的基线；本次只增加内部咨询。QQ adapter、回合级交接、原行动续接及发布路径未改动。

## 使用与实现

行动脑可在现有原生 agentic loop 中选择 `consult_character(question, context?)`。参数只含问题和可选材料，不接受任务 ID、角色会话 ID、人物或场景选择。ToolBroker 从已授权的执行会话取当前任务，Coordinator 使用该任务原角色会话绑定、当前授权的关系/记忆/现场和原目标，调用既有角色生成入口完成一次 `CONSULT`。

DSH 沿用本机固定版本 0.1.5-rc.2 的 `defineTool` 执行、`followup` 消息投递、`whenIdle` 和原生工具结果返回；没有修改 TS 桥或另建暂停/恢复系统。结果标明 `character_interpretation` 与 `internal`，交还原行动调用链。角色咨询本身不进入 `ingest/advance`、DECIDE、任务 claim 或发布器，不要求任务结束、不创建新目标，也不强制每次工具先咨询。普通回合结束后的角色反馈照旧。

咨询等待期间释放任务/副作用共享锁；角色生成仍通过既有 Coordinator 和角色 lane 串行锁排队，角色路径不等待行动结束，也不占用行动 workspace。模型端点锁原本按单次 provider 请求释放，工具等待不持有它。既有任务续租继续运行。调用前、获得角色队列后、结果返回时均检查任务 fence；撤销后迟到的咨询不能恢复授权，后续工具仍被拒绝。

缺信息由角色明确回答；上下文缺失、服务异常、非法输出通过原工具 HTTP 错误路径回传。非法输出保留 finish reason、原始诊断和请求引用。可选检索失败沿用已有降级行为，并将诊断附入咨询结果。没有添加任务终止门槛。

## 实际 Web 验证

入口：`start-asuna.cmd --port 8767`，页面 `http://127.0.0.1:8767/asuna/`。本会话无法调用 Browser 所需的 Node REPL 工具，因此通过本机已安装 Playwright 操作现有 Web 页面，没有 CLI 注入聊天或替代模型。

Web 提交只读目标：先算 `17×19`；在原任务中咨询角色如何根据已有交流偏好呈现结果，以及是否知道尚未告知的午饭菜单；咨询后再用 Python 核对；禁止改文件、联网或发 QQ 消息。

首个成功任务：`task-ep-61203cea340465670d743315e49dacd9`。记录目录：`reports/ui-0ab3414981c0`。

| 实际路径 | 观察 |
| --- | --- |
| `sandbox_run` | stdout `323`，exit code 0 |
| `consult_character` | 角色依据当前关系记录建议“结论前置，细节后置”；对午饭菜单明确回答“不知道” |
| 再次 `sandbox_run` | stdout `recheck: 323`、`cross-check: 323 323`，exit code 0 |
| 原行动返回 | 同一任务保持 intent revision 1、fencing token 1，3 个工具步骤，最终 RETURNED |
| 既有角色反馈 | Web 最终显示“323。另外，关于午饭菜单，确实不知道，你还没告诉我。” |

原生执行回执中三个工具及结果都位于原行动会话的同一次 execution 操作；角色另有独立 CONSULT 消息回执。观察到本次行动 native turn 为 1，但实现不以相同 turn ID 为约束。没有咨询专用公开消息或新任务。

加固后通过 Web 停止空闲宿主并重载最终代码，再从同一页面重复只读验收。第二次记录为 `reports/ui-32ac9742b3c0`，任务 `task-ep-aaf8d667378bbbba0ec977467f815556`：仍是 `sandbox_run → consult_character → sandbox_run` 三步，任务 RETURNED、intent revision 1、fencing token 1；最后核对输出包含 `result: 323`、`verify 323//17: 19 remainder 0`、`match: True`。Web 回复“323。午饭菜单依然不知道。”原生会话恢复后的咨询链路也已实际完成。结束时没有 READY/RUNNING 行动，Web 宿主保留运行。

页面身份、可见聊天内容和执行详情均已检查，无本次页面运行异常；截图保存在本机临时文件 `asuna-consult.png`。执行详情实际显示咨询前后的工具调用及结果。

首次尝试 `ep-b80c3c11c148cca28eb38715cbe61f21` 在 MONOLOGUE 阶段即因既有历史超出输入预算失败，`provider.error` 为 `INPUT_BUDGET_EXCEEDED`、`upstream_submitted=false`，未创建行动任务。通过页面“新上下文”保留数据库记忆后完成上述探针；没有清库、改模型、删除历史或隐藏失败记录。

## 回归与边界

`python -m pytest tests/test_consultation.py tests/test_workspace_tasks.py tests/test_integration.py tests/test_chat.py tests/test_host.py tests/test_ui.py -q`：45 passed。`git diff --check` 通过。

新增测试覆盖原角色上下文绑定、重复调用回执、无新增任务/消息/记忆、缺资料、实际 HTTP 错误回传后原任务仍可继续、等待期间跨线程取得共享锁和续租、取消后拒绝迟到结果、越界角色来源、缺原文、撤销 epoch 和异常角色输出的原始诊断。确定性测试中的模型替身仅用于这些局部契约，不计作真实模型证据。

本次真实咨询验证来自 Web 本机场景；没有为补证据向 QQ 发测试消息。QQ N3 采用用户已确认的基线；同端点双路由、并发 QQ 收件时咨询、运行中人工取消等未另做真实模型验收，取消/锁边界由局部并发回归验证。长期角色历史的自动压缩不在本次补充范围。
