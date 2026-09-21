# ADR-003 B：受管理集成环境阶段报告

2026-09-22，时间按 Pacific/Auckland。上一阶段提交为 `50b617ef`。本次完成 B 的运行器基础设施与本机真实模型/Web 验收，B 的 QQ 自主开发与收发仍为 PARTIAL / BLOCKED_EXTERNAL。

## 当前怎样使用

继续用 `start-asuna.cmd`；本次工作台为 `http://127.0.0.1:8767/asuna/`。本机 `integration.local.json` 已启用 owner profile，但端点列表为空，没有平台凭据。勾选“本条授权集成开发”后发出开发任务，角色可委托行动脑使用独立集成开发目录、受管理试运行、显式持久启用和状态查询。普通消息没有这项授权。

检查器“集成”显示进程状态和日志，“停止集成”取消运行及自动恢复。测试服务已从 Web 停止，保留开发文件和冻结副本，当前没有已启用的 adapter。宿主继续可用。完整配置、权限、工具与恢复契约见根目录 `RUNTIME_API.md`。

## 实际验证

| 子项 | 状态与证据 |
|---|---|
| WSL 低权限及端点边界 | VERIFIED：真实 UID 1000、私有网络命名空间；指定转发端点可达，直接访问同一宿主端点失败；owner home 与 Windows mount 不可见。`reports/integration-transport-*/result.json` |
| 独立开发、冻结试运行/启用 | VERIFIED：`tests/test_integration.py` 实际运行 WSL；只读副本写入失败并保留 traceback；开发目录改动不进入重启恢复的服务 |
| 明确 owner 授权 | VERIFIED：输入正文不能授予工具；普通任务和其他身份拒绝；修改任务按新事件重新核定；跨进程锁拒绝第二个 owner |
| 模型自主使用新工具 | VERIFIED（本机运行器）：原配置两条模型路由；由行动脑写 `runner_service.py`，完成 test → start → status，角色收到实际回执。任务 `task-ep-3b9eececf069d28088876a7a77e4a7f3` 为 DONE，反馈 DELIVERED |
| 浏览器关闭/重开 | VERIFIED：同一运行 ID `0458da2d32394f3aa6e564815a36d6ea` 继续 RUNNING；期间普通聊天得到“能收到。服务我会让它继续跑着。” |
| 宿主停止/重启 | VERIFIED：通过 Web 停止宿主，心跳停止；重新启动后，Web 显示冻结副本恢复 RUNNING，新运行 ID `c0cf3b18a6044a57a4c5e9f63eec5497` |
| Web 停止集成 | VERIFIED：页面 STOPPED、退出码 -15、启用清单 false；补充文件观察确认心跳不再变化。`reports/adr003-b-20260922/web-stop.json` |
| 宿主异常退出 | VERIFIED：独立诊断进程 `os._exit(0)`，未调用 close；实际 WSL 子服务因控制管道 EOF 停止，心跳不再变化。`reports/crash-probe-*/result.json` |
| NapCat adapter 与真实私聊 | BLOCKED_EXTERNAL / NOT_RUN：没有已核实 NapCat 配置、账号和明确授权目标；未连接平台、未发送 QQ |

核心假设是：长驻脚本既能使用明确授权的 TCP 端点，又不获得 owner 宿主网络和文件访问。先运行实际 WSL/Windows loopback 探针，再接工具、补测试、做 Web 验收；不是以 mock 推断部署可行。

相关回归完整运行 32 项通过；最终日志收尾/脱敏加固后，6 项运行器测试和两条真实边界探针再次通过。Python compileall、两份 JS 语法检查和 git diff --check 通过。测试 Mongo 使用独立测试库，没有 seed/reset 真实记忆，没有升级 DSH、换模型或改预算。

## 真实对话、错误和恢复

Web 请求：由行动脑自主写一个打印 `RUNNER_READY`、每秒更新 `/data/heartbeat` 的最小服务，短时试运行后启用并保留等待 Web 停止；不写 QQ adapter、不联网、不装依赖。

实际工具回执：`integration_test(timeout=5)` 返回 timed_out=true、STOPPED、exit_code=-15；`integration_start` 与随后一次 `integration_status` 返回 RUNNING，stdout 为 `RUNNER_READY pid=3 heartbeat=/data/heartbeat`。长期服务测试到期被终止是该探针的预期行为，原始非零退出仍保留在 Web 执行详情。

遇到并保留了以下失败：

1. 宿主旧 Router 白名单丢弃 `integration_profile`，先持久化的输入与后续路由冲突，报 `INPUT_IDENTITY_OR_CONTENT_CONFLICT`。Codex 修复完整路由并补回归，模型当时尚未运行。
2. 原角色上下文在 DECIDE 阶段实际计数 60,420 tokens，上限 60,416，报 `INPUT_BUDGET_EXCEEDED`，没有提交到上游。通过现有 Web“新上下文”保留数据库记忆后继续同一验收目标；不宣称恢复了原生旧上下文，也没有调整模型、预算或 seed。原证据：`reports/ui-701acee12ecc/00030-provider.error.json`。
3. 行动脑误用普通 `read_file` 读取集成目录的 RUNTIME_API.md，得到真实 FileNotFoundError；随后在原行动会话改用 `integration_dev` 继续。Codex 未修改其脚本。
4. 模型把“Web 可看 /data 文件”“首行日志一定被截断”“-15 证明优雅清理”等推论写成能力。通过同一 Web 会话给出实际契约反馈，角色回复：“是我把推论当成事实说出口了……Web 侧没文件浏览器，-15 只能证明被停止而不能证明清理完成。”这只是本轮纠正，未声称已经形成并跨恢复验证持久偏好。

完整模型任务、工具记录、输入与角色输出在 `reports/adr003-b-20260922/final-evidence.json`；早期抓取保留为 `model-runner-evidence.json`。实际脚本在 `.runtime/integration/owner/development/runner_service.py`，已启用过的版本保留在 snapshots 下。它只是本机运行器探针，不是 QQ 能力或 NapCat adapter。

## 贡献与限制

Codex 编写宿主运行器、WSL supervisor/固定端点转发、工具授权、Web 接入与工程探针；同时修复通道授权目录与 sandbox 默认根目录不兼容的问题。角色形成运行器验收目标，行动脑自行编写、调试并试运行服务，Codex 没有提供成品测试脚本或代修模型代码。

已启用的服务以只读快照恢复；网络配置改变会暂停自动恢复，须重新明确启用。普通取消行动任务不等同停止此前启用的持久服务。当前仅支持向指定端点主动发起 TCP 连接，没有反向入站、默认互联网或自动包下载；Web 仅展示进程及日志。退出码属于被监督的命名空间，强制停止不证明 adapter 完成了应用层清理。

当前主要阻塞是缺少 NapCat 连接、已核实机器人账号和授权私聊目标（包括是否与旧机器人共用账号）。唯一下一步是补齐这些已授权信息，配置实际端点后，让小满从现有 Web 原开发回路自主实现 adapter，并验收一条真实入站、一条角色公开输出及平台回执。不得把本机运行器验收算作 N1–N3 QQ 通过。
