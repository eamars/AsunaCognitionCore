# 我的 Asuna：本机启动与使用

2026-09-20：P1-A/B/C 已实跑；P1-D 单次原生压缩、重启恢复与两场景隔离，以及 P2 一次真实工具错误恢复已完成有限验证。当前角色为简版沈小满，显示名“小满”。摘要仍有偏好归属／引用误差；P3-A/B 一次技能生成与跨恢复复用已验证，P3-C 的一次关系理解修订与恢复使用也已验证；QQ 尚未开始。

## 在哪里启动

**交付清理后的准备：** 本工作区现在只保留可提交内容，本机配置、依赖与运行目录已原样存入 `C:\workspace\asuna-v1-core-raw-20260920.zip`。先将包内 `asuna_cognition_core_v2/` 下的 `.venv/`、`node_modules/`、`.runtime/` 和 `config/local.json` 恢复到本项目的原路径；`reports/` 可按需恢复查看历史证据。无需覆盖源码或重新 seed。依赖中的绝对路径按本机原目录保存，不能据此宣称可以直接移植到其他机器。外部 Mongo、模型服务、WSL Ubuntu 与 bubblewrap 仍须可用。

在本机 Windows PowerShell 或命令提示符执行以下已实跑的命令：

```powershell
C:\workspace\asuna_cognition_core_v2\start-asuna.cmd
```

脚本自动进入项目目录，使用现有 `.venv` 执行 `python -m asuna.cli chat`。Python 与 DSH 在 Windows 本机运行，Gemma 使用本机服务，Qwen 和 Mongo 沿用局域网服务。正常启动不安装依赖、不清空记忆、不升级 DSH。

归档前的一次性准备已完成：增加终端输入依赖 `prompt-toolkit`；填写 `config/local.json` 的 `chat` 和 `prompts_dir`；初始化 `local-user`、私聊 `local-dm` 和角色 `local-xiaoman`。这些本机配置与依赖需按上文恢复，数据库未清理。未导入测试故事。不要再次运行 `seed` 来开始聊天。

## 正常怎样用

启动后直接输入中文。每次回车将消息入队；生成期间可以继续输入，同场景回复依次生成。这里没有宣称两个模型推理并行。

- `/help`：显示用法。
- `/new`：在同一身份和场景开启新的 DSH 角色上下文，保留数据库记忆、人格和最近消息；下一条输入自动检索。它不是清空记忆，也不是压缩。行动未结束时暂不切换。
- `/compact`：请求压缩当前角色上下文；在下一次完整认知轮次边界由 DSH 实际生成摘要并替换旧片段。命令入队不等于已经压缩，实际摘要和次数见 `/trace`。可在行动期间继续聊天并压缩角色侧，行动状态由外部任务记录保留。当前未启用按阈值自动压缩。
- `/trace`：查看最近输入的真实人格、关系、召回来源、独立独白、决策、公开发言、发布回执、最近任务的工具调用／结果与原始错误；同时保存一份可读 `.txt`，终端会显示路径。
- `/quit`：结束当前前台应用和本次拥有的 DSH 进程；Ctrl+C 在输入处同样退出。生成中的一轮可能中断，不会假装在后台继续。尚在队列中的输入记录留在本次日志，重开不自动执行。

上述命令不进入角色记忆，不调用模型。默认画面只显示新发布的角色内容和必要的 `[系统]` 状态。

重开后仍使用同一用户、场景、数据库和最近使用的原生角色会话，恢复已经保存的消息、独白与人设。本次已验证：新细节离开最近 12 条消息后，重启并用 `/new` 开启全新角色上下文，能通过真实 Mongo 向量检索找回。中断的回复不会自动重试。

输入、已发布回复和独白会自动进入后台记忆索引，不需手工 `index`。长消息分段保存；embedding 不占用角色生成线程。索引失败保留待处理记录并重试，重开会继续处理；`/trace` 显示当前索引状态、实际召回原文／来源和最近索引错误。待索引回读与向量召回分别标明。

角色决定委托后，Qwen 自动在配置的授权工作区执行，结果交回小满表达。行动期间可以继续聊天，无需手工运行 executor。工具在 WSL Ubuntu 的隔离环境执行，工作区映射为 `/task`；网络隔离，不注入宿主机凭据。当前 `notes` 目录为只读，其他工作区文件允许按委托读写。退出应用会撤销本次尚未完成的任务，不自动重放。

同一数据库和 DSH home 同时只开一个应用。已打开聊天窗口时直接在那个窗口继续使用；再开第二个会被运行锁拒绝。

## 配置与记录在哪里

有效配置：`C:\workspace\asuna_cognition_core_v2\config\local.json`（本机文件，含连接信息，不提交到 Git）。

| 项目 | 实际值 |
| --- | --- |
| Asuna 数据库 | `asuna_cognition_core_v2` |
| 角色路由 | `http://127.0.0.1:8083/v1`，`gemma4-31b-isometry-fabled-persona-4090-6-context-checkpoints-google-mtp` |
| 行动路由 | `http://192.168.2.13:1919/v1`，`qwen38-next-uncensored-freetoken-vision` |
| 运行提示词 | `C:\workspace\asuna_cognition_core_v2\config\prompts` |
| 本机身份／场景／显示名 | 配置的 `chat.person_id`／`chat.scene_id`／`chat.display_name` |
| 授权任务目录 | `C:\workspace\asuna_cognition_core_v2\.runtime\work\local-user`（工具内为 `/task`） |
| 持久技能目录 | `C:\workspace\asuna_cognition_core_v2\.runtime\skills\local-user`（工具内为 `/skills`，DSH 原生发现，仅配置的私聊身份与场景可用） |
| 每次运行原记录 | `C:\workspace\asuna_cognition_core_v2\reports\chat-日期-唯一标识`，实际路径由 `/trace` 显示 |

凭据值不写入启动脚本或公开 trace。启动失败会显示原始 traceback 和记录路径。模型失败、空输出、角色明确沉默分别呈现；不生成固定台词替代回答。

此前 Gemma 26B 服务开启原生 thinking 时实测出现推理混入正文、空输出和空白生成至上限。因此本机 `character.native_thinking` 暂设为 `false`，通过现有 DSH provider 配置传递；独立 MONOLOGUE → DECIDE → SPEAK 流程保留。现已按用户要求切换本机 Gemma 31B，保留该设置；DSH 版本和采样参数未变。这是服务兼容性绕行，不代表其根因已修复。

## 本次实跑原文

用户：你不用为了让我满意才选。你真的更偏向哪个？

小满：比起单纯的小物件，我更偏向逻辑谜题。把混乱的东西理顺、最后拼凑完整的那个过程，很有趣。

完整六轮 C1、重开追问、生成中退出的原始错误、普通 Gemma 对照与当前缺口见 [P1-A 开发回报](docs/P1-A-REPORT.md)。

P1-B 另已实跑：“在授权工作区运行 Python，打印解释器版本和当前工作目录，把实际输出告诉我。”Qwen 实际运行 `python3`，小满回复：“解释器版本是 3.14.4 (main, Aug 20 2026, 10:41:58) [GCC 15.2.0]，当前工作目录是 `/task`。”

完整行动往返见 [P1-B 开发回报](docs/P1-B-REPORT.md)，新记忆与更正见 [P1-C 开发回报](docs/P1-C-REPORT.md)。单次压缩／恢复／场景隔离及摘要缺口见 [P1-D 开发回报](docs/P1-D-REPORT.md)，真实 FileNotFound 自主恢复见 [P2 开发回报](docs/P2-REPORT.md)。技能生成、重启发现／复用和反向反馈见 [P3-A/B 开发回报](docs/P3-AB-REPORT.md)。P3-C 的实际理解更新见 [P3-C 开发回报](docs/P3-C-REPORT.md)，最终主线结论和提交包见 [V1 最终交付](docs/V1-FINAL-DELIVERY.md)。下一阶段 V2 由用户启动。

2026-09-20 Gemma 切换验证：部署上下文已按 `/props` 更新为 68,608 token（训练容量不作为部署容量）。实跑欢迎返回的对话已完成 MONOLOGUE → DECIDE → SPEAK，并接续此前顿悟话题。

P3-A/B：当前已有 Qwen 自行生成的 `note-consistency-check` 技能。可直接聊“帮我重新核实备用线和支架螺丝的位置，便条有没有和笔记冲突”，由角色决定是否委托；无需输入技能名。它依赖具体规则，当前只实测同类笔记核对，媒体表达尚未验证。`/trace` 可看到角色收到的原生目录和行动侧实际 skill 加载回执。

角色可在 DECIDE 中选择一次有界反思，生成当前人物／场景的关系理解正文，由程序提交来源与版本。没有变化可以不更新；不修改权限、不把某人的偏好推广到其他人。/trace 显示实际修订结果，后续 ContextBuilder 注入新版本。
