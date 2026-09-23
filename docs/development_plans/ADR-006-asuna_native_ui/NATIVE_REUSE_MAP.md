# 固定版 DSH 复用地图与实际边界

> 用户已确认完整 WorkspaceBrowser/Chat 无公开 Asuna 数据绑定。本轮只复用本文件列出的公开基础组件，在现有 DSH `main` slot 组合 Asuna 三栏；不按下表完整视图接入方案继续开发。

## 依据与口径

核对日期：2026-09-24。Asuna 公共 `package.json` 锁定 `@deepseek-ai/dsh: 0.1.5-rc.2`；本文查看的是 **`dsh-v0.1.5-rc.2` 标签**，不是 master。本地若有 patch，以已安装导出和实际页面为准，不自动升级。

这是源码／契约核对，不是已连接用户本机的截图或运行验收。以下路径均是定位依据，不要求下载整个仓库。

## 1. 本轮实际复用

在固定版 DSH 的 `main` keyed slot 注册 Asuna 面板，复用同一份宿主 React 与 `@deepseek-ai/dsh-client-ui-primitives` 虚拟公开模块。左栏使用 `Input`、`Button`，消息正文使用 `MarkdownText`，工具和原包诊断使用 `DisclosureRow`、`CodeBlock`，状态使用 `StateDot`、`ConnectionIndicator`。Asuna 只负责原场景筛选和选择、消息来源/身份关联、现有输入回调和只读增量投影。

固定版 `@deepseek-ai/dsh-client-ui-chat` 的 `AssistantMarkdown` 将 `kind: 'reasoning'` 交给内部 `ReasoningRow`；该行用公开 `DisclosureRow` 和 `IconThinkOutline14` 折叠展示原思考文本，未将思考表达为 JSON。本轮不导入或复制内部 `ReasoningRow`，只用这两个公开基础组件组合 Asuna 已取得的 `reasoning_content` 或 DSH `reasoning`；来源标签保留，生成中的思考直接可见，完整原文可展开。网页折叠诊断只显示非内容元数据，真正的 wire 回包留在既有审计。

以下表格保留范围修订前的完整视图调查；表内 WorkspaceBrowser、Chat、SessionEventStream 路径**均未作为本轮交付接入**。

## 2. 范围修订前的完整视图调查

| 界面用途 | 固定版原生对象 | 接入方式与限制 |
|---|---|---|
| 左侧导航壳 | `ui-sidebar` | 使用原生已注册的 sidebar 和布局折叠；不写第二套侧栏 CSS。 |
| 会话浏览／搜索 | `ui-workspace` 的 `WorkspaceBrowser` | 原生插件注册到 `sidebar.workspaces`。它不是任意数组列表；需要实际 sessions/workspaces 数据与动作契约。 |
| 中间聊天窗口 | `ui-chat` 的 Chat 视图 | 原生插件注册到 `conversation.view`，id 为 `chat`。由 `ui-conversation` 提供会话与消息视图，不直接 import 私有 `ChatView.tsx`。 |
| 输入与队列交互 | `ui-conversation` 的 composer 插槽 | 只将已有同义 Asuna 动作接入。不能让默认 prompt 直达角色/行动模型而绕开宿主。 |
| 可读正文 | `MarkdownText` | 公共 `@deepseek-ai/dsh-client-ui-primitives` 导出；传完整累计文本与 `streaming`，复用原生 Markdown。 |
| 结构内容/诊断元数据/错误文本 | `CodeBlock`，必要时 `JsonBlock` | 网页 JSON 不重复已显示的正文、思考和工具内容；完整 wire 原包只留审计。 |
| 折叠诊断 | `DisclosureRow` | 同一消息内默认关闭；不要另写 details、手绘箭头或 accordion。 |
| 有实际活动/故障时的状态 | `StateDot`、`ConnectionIndicator` | 不新增全局脑状态卡；不把浏览器断线说成任务取消。 |
| 工具/附件 | 原生 chat node、tool renderer、`conversation.message.images` | 使用实际 content/attachment 引用，不新增视觉模型、下载器或媒体平台。 |
| 流式到持久记录 | `SessionEventStream`、`assistant/live-chunk`、`settle-assistant` | 原生组装处理瞬时片段与最终 assistant message/attempt；Asuna 仅关联业务来源，不再解析 provider SSE 作为正文。 |

### 重要：不要虚构独立组件导出

`ui-chat/client` 公开的是 apply/契约类型等，**没有导出可任意传 `messages` 的 `<ChatView>`**。`ui-workspace/client` 也**没有公开可任意传 `items` 的 `<WorkspaceBrowser>`**。

因此本包不提供那种看起来方便但实际不存在的 import 示例。完整控件使用原生插件/slot 组合。公开的 `MarkdownText` 示例只说明一个业务消息的内容如何渲染，**不是完成原生聊天和侧栏替换的证明**。

## 2. 实施前的 Asuna 与原生 UI 落差

实施前，`dsh-plugin/ui/client.js` 在 DSH `main` 插槽嵌入 `/asuna/` iframe；内部 `static/workbench.js` 自己绘制会话按钮、气泡和 details。本轮已改为 `main` slot 中直接组合公开基础组件，以下条目保留为问题基线，不描述当前实现。

重点位置：

- `renderTrace` 对 `phase.output` / `execution.output` 显示 `原始 provider response`，覆盖可读正文；应拆开这两个来源。
- `renderMessages` 每次 `replaceChildren()`；不能继续依赖整段重建来模拟原位流式。
- 当前 `/stream` 主要传 raw provider `body_utf8`；native assistant 内容流与网络字节流不是一个东西。
- 原 `/stop` 停的是宿主服务；不得绑定成原生“停止本次生成”。
- UI shell 与模型 lane 使用的会话环境可能不同。不能假定一启用原生侧栏就自动列出全部 Asuna 场景。

这些是相关代码事实，不意味 Codex 可以借机重写整个 host、合并 DSH_HOME 或重建数据库。

## 3. 批准的接入架构

**一套原生 DSH UI 组合 + 现有 Asuna 业务绑定 + 保留的右侧检查器。**

导航选的是现有 Asuna 场景；消息来源仍是它已经关联的真实角色/行动会话与宿主记录。必须保持两种身份：

- **用户观察的场景身份**：QQ 私聊/群、本机对话。
- **真实源记录身份**：lane、session、request/operation/attempt、原事件位置。

跨脑合并是只读展示投影，不创建另一套 agent、不复制整个日志到新 session、不让侧栏选择启动模型。

接线只负责列表/选择、原文来源、动作回调及当前视图订阅。优先使用现有 DSH/Asuna 已提供的同义契约；不实现一个庞大的假 `ISessions` 来迎合控件，不全局劫持原生服务，不读取注册表里的私有 component 来绕开注入生命周期。

### 无法直接组合时的处理（不是默许自绘）

固定版完整原生控件依赖特定 SessionBinding 与 Host Workspace。本包**没有宣称**这些契约已经接受任意 Asuna 场景数组。

Codex 在相关本地类型核对中若发现没有公开方式绑定当前业务，需给出：具体导出/插槽/动作缺口、已有可复用部分、最小替代建议。**不得擅自复制控件、假造 workspace、重写 native controller 或自行画一个“看起来差不多”的侧栏。** 该处暂记集成缺口，继续不受影响的正文恢复等工作；agent 服务与已工作的 UI 不应被停掉。

这是一条真实 API 可用性边界，不是要求每个组件重新申请批准。已批准的文字标签、业务字段映射和使用原生 primitives 的小型业务节点无需再审批。

## 4. 固定版源码入口

- [Asuna package.json](https://github.com/eamars/AsunaCognitionCore/blob/main/package.json)
- [当前 Asuna UI 包装](https://github.com/eamars/AsunaCognitionCore/blob/main/dsh-plugin/ui/client.js)
- [当前 Asuna workbench](https://github.com/eamars/AsunaCognitionCore/blob/main/dsh-plugin/ui/static/workbench.js)
- [当前 Asuna UI 宿主](https://github.com/eamars/AsunaCognitionCore/blob/main/src/asuna/ui.py)
- [固定版 ui-workspace 注册](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.1.5-rc.2/packages/client/ui-workspace/src/client/index.ts)
- [固定版 Workspace 契约](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.1.5-rc.2/packages/client/ui-workspace/src/client/contract/slots.ts)
- [固定版 ui-chat 注册](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.1.5-rc.2/packages/client/ui-chat/src/client/apply.ts)
- [固定版 Chat 契约](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.1.5-rc.2/packages/client/ui-chat/src/client/contract/slots.ts)
- [固定版 Conversation 组装与扩展](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.1.5-rc.2/docs/subsystems/conversation.md)
- [固定版 Session Controller 流与结算](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.1.5-rc.2/packages/api/session-controller/README.md)
- [固定版 primitives 真实导出](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.1.5-rc.2/packages/client/ui-primitives/src/index.ts)
- [固定版 MarkdownText 实现](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.1.5-rc.2/packages/client/ui-primitives/src/markdown/MarkdownText.tsx)
- [固定版 CodeBlock 实现](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.1.5-rc.2/packages/client/ui-primitives/src/markdown/CodeBlock.tsx)
- [固定版 Slot 规则](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.1.5-rc.2/packages/client/ui-slots/README.md)
- [固定版 renderer](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.1.5-rc.2/packages/client/ui-renderer/README.md)

文档链接固定到标签以免 master 变化；Asuna 路径使用 main，只是本次抽查，不假定用户未提交代码与之完全一致。
