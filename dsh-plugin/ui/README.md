# Asuna UI Elements V1

现有本机 `Chat` 的 DSH 原生插件视图。浅色三栏：左侧真实上下文列表，中间用户/角色气泡及可展开执行步骤，右侧只读记忆、偏好、群偏好和关系检查器。没有独立前端框架、构建工具或新增 npm 依赖。

## 本机运行

从仓库根目录运行；沿用项目 Python 3.12、固定 DSH `0.1.5-rc.2` 和现有 Mongo/模型配置。

```powershell
npm.cmd ci
uv sync --frozen
.venv/Scripts/python.exe -m asuna.cli ui --config config/local.json
```

打开 **http://127.0.0.1:8765/asuna/**。这是 DSH 注册的内嵌视图路由。也可以打开启动终端打印的带 token 的 DSH 主页面，点击原生侧栏 **Asuna**。

日常直接使用根目录 `start-asuna.cmd`，`start-asuna-ui.cmd` 是同一入口别名。正式交互、开发调试呈现和验收均在 Web 中进行。其他 CLI 命令需要显式 `--debug`，终端聊天只保留为故障诊断工具，Web 失败时不会自动回退到 CLI。

若尚无本机配置，可根据 `config/local.example.json` 创建 `config/local.json`，先核实其中地址、身份和授权工作区；不要重新 seed 已有数据库。有关现有运行环境见根目录 `RUN_ASUNA.md`。配置存在不代表模型已启动。

已有模型未启动时，可只读查看真实数据库，不启动模型进程、不迁移或 seed：

```powershell
.venv/Scripts/python.exe -m asuna.cli ui --config config/local.example.json --read-only
```

`--port 8766` 可更改端口。读写 UI 与原终端聊天使用同一运行锁；同一数据库/DSH home 不要同时启动两个读写入口。使用 Ctrl+C 关闭启动终端中的程序，沿用 Chat 的停止/取消行为；关浏览器标签页不会停止控制器。

## 使用

- 左侧“模型设置”：分别配置两脑地址、模型 ID、上下文/输出上限；可使用同一服务和模型。支持读取服务模型列表、写入 API key、高级 DSH 兼容/推理选项及计数方式；设置空闲应用，重启后保留。API key 不回显。当前协议范围、保存位置见根目录 RUN_ASUNA.md。
- Enter 发送，Shift+Enter 换行；中文输入法确认不会误发送。生成期间仍可入队。
- “新上下文”调用原 `/new`，保留身份、场景及记忆；行动未结束时原控制器会拒绝切换并显示系统消息。
- 左栏是当前本机场景已有的原生上下文代次，历史上下文只读。没有虚构 QQ 频道或会话。
- 角色最终公开回复为主。展开“内部执行过程”查看角色脑、行动脑、工具和其他真实事件；每步可展开原始 payload。错误摘要始终在折叠区外。
- 正文英文不单独强制字体；行内代码、代码围栏、JSON payload、检查器结构化值和模型 JSON 编辑框使用统一等宽字体。Markdown 只做代码片段的安全文本渲染，不执行内容中的 HTML。
- 检查器支持搜索和点击详情，始终展示当前场景记录，历史会话下也不是历史记忆快照。无独立偏好数据时显示空态，不推断或伪造偏好。

## 验证

后续交互验收使用 in-app browser 操作页面、查看消息/执行详情/检查器及浏览器日志。以下命令仅是底层非交互 debug 检查，不替代 Web 验收；不通过 CLI 注入正常聊天消息。

```powershell
.venv/Scripts/python.exe -m pytest tests/test_ui.py -q
node --check dsh-plugin/ui/static/workbench.js
```

测试沿用示例 Mongo 地址，在独立 `asuna_v2_test_ui_*` 数据库中运行并保留记录；角色输出使用明确的测试替身。测试跨越 HTTP → 现有 Chat → Mongo，不能替代真实模型和浏览器验收。

2026-09-21 已完成 `ACCEPTANCE.md` A–F 范围的验收，停止扩展 V1 功能：

- Codex in-app browser 实测 DSH 原生侧栏 → Asuna 内嵌页面；三栏浅色布局、气泡、折叠执行步骤、四个检查器标签、搜索与详情均可用。
- Enter 发送真实消息，Gemma 回复“收到了。”；点击新上下文保留既有记忆，历史会话只读。
- 在页面发送最小委托，Qwen 通过现有隔离工具执行 `python3 -c "print(6 * 7)"`，真实 stdout 为 `42\n`、退出码 0；Gemma 最终回复“实际输出是 `42`。验收通过，链路通了。”工具回执与双脑步骤在 UI 中可展开。
- 用真实历史错误验证：折叠时保留简短错误提示，展开后完整 traceback 仍可见。修复了完成阶段仍显示 running、历史排序缺失时间，以及长 traceback 挤占聊天区的问题。
- 桌面 1280×800 实测无横向溢出；1440×1000 原生嵌入截图通过。390×844 维持 960px 桌面布局并横向滚动，移动优化不在 V1 范围。
- 新增 4 项 UI 回归及原有 6 项 Chat 回归全部通过；语法/编译和 diff 检查通过。测试进程将默认配置路径指向仓库示例，未创建或改写本机配置。最终新打开页面控制台无错误或警告；旧 DSH 标签仅记录了主动重启期间的连接重试警告。

普通对话 episode：`ep-1089a5ef02aaaa20e5eed1a00a68a921`；真实工具任务：`task-ep-91200fd00bbab0d5ad70094caf11d24e`。验收截图保存在本机临时目录 `C:/Users/rba90/AppData/Local/Temp/asuna-ui-qa/`（不提交到源码）。前期 Playwright 探针因其字符串求值与页面 CSP 不兼容中止，未放宽 CSP；最后的完整交互验收使用 in-app browser。

接口与边界见 [INTEGRATION.md](INTEGRATION.md)，限制见 [LIMITATIONS.md](LIMITATIONS.md)。

## 2026-09-21 Web 入口修订回归

`start-asuna.cmd` 与别名 `start-asuna-ui.cmd` 均已实际启动现有 Web 宿主（本轮使用示例配置、端口 8767）。CLI 除 `ui` 外需显式 `--debug`；非交互入口诊断确认未启用 debug 时在加载配置前拒绝，直接终端适配器也拒绝，且未加载终端输入组件。Web 继续复用 Chat 控制器。系统提示已移除 /trace、/new 等终端操作指引。ADR-003、根目录使用说明和 AGENTS.md 已同步。

in-app browser 实测重启后历史恢复、页面发送和展开执行 payload；浏览器控制台无 error/warn。此次两次简短招呼均在角色 MONOLOGUE 阶段返回空内容、`finish_reason=error`，页面显示 `FAILED_PROTOCOL / INVALID_STAGE_OUTPUT`，没有伪造回复或回退 CLI。首次 episode 为 `ep-b0d68b056682eb0ed1a45087320d5898`；提示修正后的第二次页面显示“请展开本轮执行详情查看原始过程”。当前模型回复链路未恢复，不能用此前成功的工具验收宣称本次模型通过。入口修订未更改模型路由或协议。截图：`C:/Users/rba90/AppData/Local/Temp/asuna-ui-qa/iab-web-entry-policy.png`。

## 2026-09-21 模型独立配置验证

DSH 原生 Models 页面和固定版本的 ProviderEditor / llm-pi-ai schema 已核对。工作台以两组配置复用原生 provider adapter；运行代码与 UI 不再绑定具体模型名称，计数器、推理兼容和预算字段归模型配置。名称只来自部署配置或真实历史内容；旧文档中的部署名作为历史保留。

在 in-app browser 中读取服务模型列表，原角色服务返回 ConnectError，行动服务返回真实模型 ID。将角色脑临时指向行动脑同一模型后，“保存并应用”成功，真实新上下文完成角色判断 → 行动工具 → 角色公开回复。工具 `sandbox_run` 实际 stdout=`42\n`、exit_code=0，角色回复“实际输出是 `42`。这次最小验证通过。”任务：`task-ep-12c9b6285d5a99592453bebc41318a43`。该验证没有通过 CLI 注入消息。

已验证生成期间拒绝切换、无效上下文预算拒绝、重启后同模型配置保留，随后在 Web 恢复原来的独立模型分配。浏览器页面身份/非空/无错误覆盖层/控制台/交互/截图检查通过；7 项非交互配置与 UI 回归通过。新上下文后发送按钮的 busy 状态恢复也已修正。原角色服务仍不连通，恢复原分配不代表它已经上线。未验证其他协议或每一种兼容参数组合。

截图（本机临时目录，不提交）：`C:/Users/rba90/AppData/Local/Temp/asuna-ui-qa/iab-same-model-result.png`、`C:/Users/rba90/AppData/Local/Temp/asuna-ui-qa/iab-model-settings.png`。当前界面、测试和未来工作遵守根目录 AGENTS.md 的 Web 入口及模型独立配置约束。
