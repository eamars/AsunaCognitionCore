# 架构审查：A2 更新后的宿主重启与 Web 反馈延迟

**状态：** 待架构师审查  
**观察日期：** 2026-09-25（Pacific/Auckland，UTC+12）  
**范围：** 描述 A2 更新发布后，宿主重新启动和 Web 界面反馈的实际表现；不包含代码修改或修复方案。

## 问题摘要

A2 更新最终成功进入 `ACTIVE`，自我开发发布回执中的 `boot_probe.exit_code` 为 `0`。但从发布回执记录到新宿主进程首次出现约 **8 分 54 秒**；从该 Python 宿主进程出现到 Web 监听端口启动约 **6 分 22 秒**；发布到新版本被标记为 `ACTIVE` 合计 **15 分 16 秒**。用户报告更新后网页反馈很慢；本次浏览器检查也曾停留在“正在读取对话…”状态，手动刷新后才显示内容。

这是真实的启动/反馈延迟问题。运行最终恢复且没有证据显示永久启动失败，但“最终恢复”不改变上述等待时间及用户可见的迟缓体验。8 分 54 秒是发布到新宿主进程出现的时间差，不等同于已精确测得的连续停机时长；这段时间里旧宿主和 Web 的可用性没有连续监测记录。

## 运行证据与时间线

| Pacific/Auckland 时间 | 证据 | 含义 |
|---|---|---|
| 20:25:51.772 | 发布回执 `published_at`；UTC 值为 `2026-09-25T08:25:51.772170+00:00` | 更新已写入有效项目，回执处于发布等待激活的生命周期 |
| 20:34:46 | 运行报告 `reports/ui-55e004640d62` 中的首批 runtime fingerprint；宿主 Python 进程也在此时启动 | 比 `published_at` 晚约 8 分 54 秒 |
| 20:41:06 | 同一报告的 `host.channels_started` 事件，端口 8766 | 距宿主 Python 进程启动约 6 分 20 秒 |
| 20:41:08 | Node Web 服务开始监听 8765；发布回执 `activated_at` 为 `2026-09-25T08:41:08.214933+00:00` | 距宿主 Python 进程启动约 6 分 22 秒；距发布回执约 15 分 16 秒；回执转为 `ACTIVE` |

当时的发布回执记录了 `boot_probe.exit_code = 0`。检查时 8765 和 8766 均处于监听状态，服务进程仍在运行。浏览器控制台未见 JavaScript 错误或警告；页面初始显示“正在读取对话…”，手动刷新后才加载出内容。用户另报告 Web 反馈非常慢。现有证据没有记录该页面请求的开始/结束时间、HTTP 耗时或服务端处理阶段，因此不能把反馈延迟精确归因到浏览器、UI 桥接、宿主、模型/提供方或数据库中的某一层。

## 代码中的实际发布与启动路径

1. `Development.publish()` 先检查是否已有仍处于 `APPLIED` 的发布，再比较候选文件与基线、执行地板保护检查并冻结候选快照。之后它运行 `_boot_probe()`；探针成功才将变更复制进有效项目，写入 `APPLIED` 回执及 `published_at`，更新基线，并返回 `APPLIED_AWAITING_RESTART`。因此“探针通过”与“新 Web 服务已经可用”是两个不同阶段。
2. 当前 `_boot_probe()` 对冻结候选创建 Store、ping 数据库、验证场景/用户授权，并构造 ContextBuilder、Coordinator、TaskService、ToolBroker 和 DevelopmentWorkspace。探针输出还明确记载 `live_consumers: none`。它没有构造完整 `RuntimeHost`，也没有启动完整模型通道、8766 通道服务器或 8765 Web 服务；所以退出码 0 只证明该探针覆盖的路径可用，不证明完整冷启动耗时或 Web 已就绪。
3. 运行中的 `RuntimeHost` 将 `_maybe_restart_after_publish()` 注册为 Chat 的 `on_turn_finished` 回调。Chat 在记录 `chat.completed` 后调用该回调。回调发现 `active_task` 存在或任务队列非空时立即返回；只有任务空闲且发现 `APPLIED` 回执时，才设置 `restart_requested` 和 `shutdown_requested`。这使切换等待正在进行的任务/反馈回合结束。此次没有保存发布时的 `active_task`、队列长度、每次回调检查结果或旧宿主实际退出时间，因此无法确认 8 分 54 秒中的多少时间由排空任务造成。
4. 重启后，`ui()` 先进入 `RuntimeHost`，构造成功后才创建 Workbench 并调用 `serve()` 启动 Node Web UI。宿主进入阶段会依次启动 Application 内的 character、executor、summary 三个 DSH lane，然后准备场景和 channels、恢复发送中消息/输入/任务、启动索引器及 channel server、恢复集成和 schedule，启动 worker，最后将发布回执转为 `ACTIVE`。Web 服务因此要等宿主构造完成后才开始监听。DSH lane 配置了每个 `DeepSeekHarness` 45 秒的初始化超时，但本次没有逐阶段时长记录，不能由此确定 6 分 22 秒具体耗在哪一步。
5. `start-asuna.cmd` 在 `ui` 返回退出码 75 时重新进入启动循环。当前观测符合“新宿主完成构造后 Web 服务重新启动并回执激活”的流程；问题在于整体可见等待过长、期间 Web 反馈迟缓，而不是有证据表明重启循环最终没有执行。

## 本次发布内容

回执中的状态为 `ACTIVE`，发布探针退出码为 0。回执记录的变更文件如下：

- `config/asuna-channel.example.json`
- `docs/development_plans/ADR-005-asuna_qq_functional/ARCHITECT_BLOCKER-2026-09-25-A2-FLOOR.md`
- `docs/development_plans/ADR-005-asuna_qq_functional/LINKED_SCENES_A2_USAGE.md`
- `src/asuna/chat.py`
- `src/asuna/config.py`
- `src/asuna/context.py`
- `src/asuna/discussion_digest.py`
- `src/asuna/history_query.py`
- `src/asuna/host.py`
- `src/asuna/memory.py`
- `src/asuna/retrieval.py`
- `src/asuna/scene_links.py`
- `src/asuna/state.py`
- `src/asuna/ui.py`
- `tests/p3_schedule_cases.py`
- `tools/linked_scenes_offline_check.py`

## 尚不能从现有记录得出的结论

- 发布回执至新 Python 宿主进程出现之间，旧 Web 服务是否仍可接受请求，以及何时停止服务，没有连续可用性探针记录。
- 未记录发布时及重启等待期间的 Chat 活跃任务、队列状态和重启回调结果，不能确认延迟是否由任务排空等待造成。
- 宿主启动缺少分阶段耗时，不能识别 6 分 22 秒主要消耗在哪个 lane、恢复步骤或其他初始化调用。
- 没有浏览器网络面板、UI bridge 请求耗时或服务端对应请求的关联计时，不能将用户感知的慢反馈归为某一组件的根因。

## 请架构师审查

请根据上述证据判断：当前发布后的静默等待、宿主就绪顺序和 Web 反馈表现是否符合预期服务行为，并确认该延迟问题的严重度及需要进一步定位的边界。本说明只提交观测事实和代码生命周期描述，没有实施修复，也没有提出实现方案。

