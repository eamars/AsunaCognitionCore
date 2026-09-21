# Asuna：Web 启动与使用

2026-09-21：正式交互、开发调试呈现和交互验收统一使用现有 Web UI。CLI 仅用于显式 debug/维护，Web 故障时不回退终端聊天。后续开发规则见 [AGENTS.md](AGENTS.md)，ADR-003 的入口指示已同步修订。

## 启动与打开

日常启动 `start-asuna.cmd`，`start-asuna-ui.cmd` 是它的别名。两者都只启动 `asuna ui`，默认读取 `config/local.json`，端口为 8765。浏览器打开 http://127.0.0.1:8765/asuna/；也可在 DSH 原生页面侧栏点击 Asuna。

当前本机尚无 `config/local.json`；本轮沿用已核实的示例配置和端口 8767，实际启动方式为：

```powershell
.\start-asuna.cmd --config config/local.example.json --port 8767
```

当前工作台：[打开 Asuna Web](http://127.0.0.1:8767/asuna/)。需要持久本机配置时，从示例复制并核实服务地址、身份和授权目录；已有 local.json 时不要覆盖。启动不安装依赖、不重新 seed、不升级 DSH。沿用项目 .venv、node_modules、现有 Mongo、模型及 WSL/bubblewrap。

入口修订时通过浏览器确认页面、历史和消息入队可用；当时两次对话的模型 MONOLOGUE 返回空内容及 error，Web 如实显示 INVALID_STAGE_OUTPUT。后续模型设置验证发现原角色服务连接失败；临时将两脑指向在线的同一模型后，真实工具往返与公开回复均成功，完成后已恢复原来的分配。原角色服务尚未恢复连通。详见 UI 说明末尾。

## 正常使用与调试呈现

- 左侧选择会话；“新上下文”保留身份、场景和数据库记忆，旧会话只读。
- 中间输入自然语言，Enter 发送、Shift+Enter 换行。角色公开回复以 bubble 显示；生成和行动期间仍可入队。
- 展开“内部执行过程”查看双脑阶段、工具参数、真实结果及原始错误。折叠后仍保留错误摘要。
- 右侧查看和搜索记忆、偏好、群偏好、关系；无记录时显示空态。

所有正常消息和开发任务通过这里发送。不要在宿主日志窗口输入聊天文本、/new 或 /trace。原有 Chat 队列和行动回传继续复用，Web 不调用终端适配器。

关浏览器标签页不停止宿主；在启动进程中按 Ctrl+C 停止整套本次宿主。停止会取消尚未完成的任务，不自动重放。启动窗口只是服务日志/进程控制，不是聊天界面。同一数据库与 DSH home 同时只运行一个读写宿主；已有窗口时直接使用现有 Web 页面。

## 配置与记录

配置中的 `chat.person_id`、`chat.scene_id`、`chat.display_name` 和工作区限制仍有效。每次 Web 运行记录保存在 `reports/ui-*`；数据继续使用既有 Mongo。完整集成和限制见 [UI 说明](dsh-plugin/ui/README.md)。凭据不写入浏览器聊天、代码或公开 trace。

模型未启动时，可用 `start-asuna.cmd --config config/local.example.json --read-only --port 8767` 查看真实数据；只读模式不能发送。它不是失败后的自动降级。

## 模型设置

点击 Web 左侧“模型设置”，分别修改角色脑、行动脑的连接地址、模型 ID、上下文窗口和输出上限。两脑可指向不同服务/模型，也可填同一模型。点击“读取服务模型列表”获取实际候选，模型 ID 也可手动填写。

高级区沿用 DSH 的 `compat` 和 `reasoningEfforts` 含义，推理强度、采样和 token 计数随模型配置，不再由“角色/行动”决定。未知服务可选通用保守计数；专用计数需要服务实际支持。当前保留本机/LAN 与 OpenAI Chat Completions 审计桥边界，尚不支持直接套用 DSH 的全部云端/其他协议。

空闲时“保存并应用”会重建两条 DSH lane，浏览器继续显示应用状态；有回复、排队消息或行动时拒绝切换。API key 只写入本地，不从接口回显；更换地址时不沿用旧密钥。配置保存到所选配置文件旁的 `*.models.local.json`（Git 忽略），下次启动自动恢复，不改写基础配置文件。历史执行标签只表示职责，不用当前模型冒充历史所用模型。

## 仅限 debug 的命令行

除 `ui` 外，CLI 操作均必须显式指定 `--debug`；缺少标志时在读取配置、连接数据库或调用模型前拒绝。`chat()` 和 `terminal()` 直接调用也要求 `debug=True`。Web 不加载 prompt-toolkit 输入组件。

CLI 保留给必要的故障诊断/维护，不能用于正式交互或替代 Web 验收。历史 /trace、/compact 等终端功能不等于 Web 已提供对应按钮；当前 Web 功能以 UI Elements V1 验收范围为准。

## 历史证据（2026-09-20，终端命令不再是正式入口）

用户：你不用为了让我满意才选。你真的更偏向哪个？

小满：比起单纯的小物件，我更偏向逻辑谜题。把混乱的东西理顺、最后拼凑完整的那个过程，很有趣。

完整六轮 C1、重开追问、生成中退出的原始错误、普通 Gemma 对照与当前缺口见 [P1-A 开发回报](docs/P1-A-REPORT.md)。

P1-B 另已实跑：“在授权工作区运行 Python，打印解释器版本和当前工作目录，把实际输出告诉我。”Qwen 实际运行 `python3`，小满回复：“解释器版本是 3.14.4 (main, Aug 20 2026, 10:41:58) [GCC 15.2.0]，当前工作目录是 `/task`。”

完整行动往返见 [P1-B 开发回报](docs/P1-B-REPORT.md)，新记忆与更正见 [P1-C 开发回报](docs/P1-C-REPORT.md)。单次压缩／恢复／场景隔离及摘要缺口见 [P1-D 开发回报](docs/P1-D-REPORT.md)，真实 FileNotFound 自主恢复见 [P2 开发回报](docs/P2-REPORT.md)。技能生成、重启发现／复用和反向反馈见 [P3-A/B 开发回报](docs/P3-AB-REPORT.md)。P3-C 的实际理解更新见 [P3-C 开发回报](docs/P3-C-REPORT.md)，最终主线结论和提交包见 [V1 最终交付](docs/V1-FINAL-DELIVERY.md)。下一阶段 V2 由用户启动。

2026-09-20 Gemma 切换验证：部署上下文已按 `/props` 更新为 68,608 token（训练容量不作为部署容量）。实跑欢迎返回的对话已完成 MONOLOGUE → DECIDE → SPEAK，并接续此前顿悟话题。

P3-A/B：当前已有 Qwen 自行生成的 `note-consistency-check` 技能。可直接聊“帮我重新核实备用线和支架螺丝的位置，便条有没有和笔记冲突”，由角色决定是否委托；无需输入技能名。它依赖具体规则，当前只实测同类笔记核对，媒体表达尚未验证。`/trace` 可看到角色收到的原生目录和行动侧实际 skill 加载回执。

角色可在 DECIDE 中选择一次有界反思，生成当前人物／场景的关系理解正文，由程序提交来源与版本。没有变化可以不更新；不修改权限、不把某人的偏好推广到其他人。/trace 显示实际修订结果，后续 ContextBuilder 注入新版本。
