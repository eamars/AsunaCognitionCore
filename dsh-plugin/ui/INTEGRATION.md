# 薄集成说明

核对版本：仓库 `package.json` / `package-lock.json` 的 DSH `0.1.5-rc.2`，对应源码提交 `fb2c4b9e698e30edb738bca4cf0618587db7d203`；没有按本机旁边较新 DSH checkout 的 API 编写或升级版本。

## DSH 原生能力

- `package.json` 的 `dsh.client` / `exports["./client"]`：原生客户端发现与交付。
- `window.__ModuleLoader__.load`：固定版本的客户端 bundle 格式，复用宿主 React。
- `ctx.slots.inject/register`：`main` keyed 面板 `asuna` 与 `sidebar.panellist` 入口；注册由宿主生命周期管理。
- `ctx.webServer.register`：`/asuna` 前缀路由，交付静态内嵌视图和转发 API；不改 DSH 核心。
- `--profile web --patch`：加载本目录 `cordis.patch.yml`。UI shell 使用 `.runtime/ui-shell`，原有角色/行动 lane 的 home 和行为不变。

## 现有 Asuna 路径

`asuna ui` → `Application` → `Chat.submit/new_context` → 现有 Router / Coordinator / Executor / Publish。复用 MemoryIndexer、凭据脱敏、场景授权和停止逻辑。只读模式只创建 Store，读取真实记录。

模型配置参考固定 DSH 同 commit 的 `ui-settings-models/ProviderEditor`、`ModelListEditor` 与 `llm-pi-ai` schema：连接地址、模型 ID、上下文/输出能力及 `compat`、`reasoningEfforts` 分开。两条 Asuna lane 各自仍通过原生 `dsh-llm-pi-ai` 注册模型；模型可相同，lane 的身份、会话、权限和队列保持独立。UI shell 自己的 DSH 模型页不等于 Asuna 两条 lane 的模型选择，因此工作台只补两组职责配置，不复制完整提供商管理系统。

`POST /asuna/api/models/discover` 从已校验的本机/LAN OpenAI 兼容端点读取 `/models`。`POST /asuna/api/models` 在无排队消息/任务时异步重建两条 lane，保留浏览器与数据；应用中拒绝新消息。设置带版本检查，成功后原子保存到基础配置旁的 `*.models.local.json`，失败尝试恢复原路由。API key 不回显，换地址时不继承旧 key。页面如实显示应用进度与错误；模型可配置不代表目标服务已经在线。

Asuna 的现有请求审计/预算边界目前只实现 OpenAI Chat Completions 和本机/LAN 地址；DSH 原生支持的其他协议/云端路由尚未在本桥接中启用，不以界面选项伪称支持。计数器和推理兼容改为模型字段，通用计数采用保守 UTF-8 字节预算；专用计数器要求服务确实提供对应接口。展示按 `actorRole` 区分角色脑/行动脑/工具，不解析模型名称决定颜色或职责。

DSH `/asuna/api/state` 转发至 `UiBridge /state`；`/send` 和 `/new` 接收 POST。桥接使用标准库临时 loopback HTTP 端口，只向启动的 DSH 子进程传递随机 bearer token；不向浏览器暴露数据库或模型凭据。DSH 路由限制 loopback、Host/Origin 和写请求自定义头，不开放跨域。该界面是本机操作者检查器，包含私有独白与调试 payload，不是供聊天参与者访问的公共接口。

## 实时原始流的局部适配

固定版本 DSH 的原生会话流和 Chat 组件连接的是 UI shell 会话，而角色脑和行动脑分别在独立 DSH home 运行。通用 `StreamChunk` 提供规范化的 reasoning/text 增量，不保留 provider 的 `reasoning_content`/`content` 字段与完整原始 JSON。现有 Asuna provider 边界还会先把上游流收齐、保存审计，再交给 DSH。因此直接复用原生 Chat 增量显示既不能接到这两条会话，也不能满足原字段显示。

仅在当前代理收到原始字节时增加可失败的只读 UI 观察回调，由现有 `/asuna` 路由转发 SSE。页面沿用当前执行步骤的 `<details>`/`<pre>`，按原始到达顺序显示字节解码后的文本，不提取或改名字段；脑别、阶段、状态放在外层。浏览器连接先取得当前临时快照，再接收更新；断线重连只恢复观察，不提交用户消息、模型请求或工具任务。已结算的 `phase.output`/`execution.output` 以审计请求引用替换对应临时行，仍从原有 `provider-response` 端点读取完整回包。临时流只保留短时间用于衔接，不是新的持久记录或恢复平台；观察失败不改变代理执行。

没有公开回复的真实回合不生成系统聊天气泡。状态与执行步骤附在触发它的输入下；任务反馈附在原任务的可见回合下，并按事件 ID 去重。普通群消息只记录而未唤醒角色时不产生回合状态提示，更不把 `RECEIVED_NO_WAKE` 的临时提示堆到本机聊天末尾。

## 已有数据与事件

| 来源 | UI 映射 |
| --- | --- |
| scenes.character_context / episodes.character_context | 当前与历史本机上下文；原 `/new` 创建代次 |
| messages | inbound 用户气泡；仅 DELIVERED + SPEAK 的 outbound 角色气泡；内部任务反馈不冒充用户输入 |
| episodes / tasks | 回答归属、任务关联、失败或沉默状态 |
| audit_events `phase.*` | 角色脑阶段与输出 |
| audit_events `execution.*` / `skills.native_calls` | 行动脑执行与技能调用 |
| `state.commit` 的 artifacts INTENT / DONE | 工具调用 / 工具结果，保留参数、结果和错误 |
| `tool.failed` / `chat.error` / episode.failure | 可见错误摘要和原始 payload |
| 其他语义 audit event | 通用事件行，保留 type 与 payload；存储 bookkeeping 不展示 |
| active memory_units | 记忆；已存在的显式 preference / group_preference 等 kind 可直接映射 |
| 当前 relationship state head/revision | 关系详情及来源 |

所有场景数据按授权成员、scope、当前 policy_epoch 限制；记忆可包含当前版本 `global-safe`。关系读取沿用 `Store.head`。每两秒串行轮询刷新，消息显示最近 80 条，记忆最近 100 条，额外包含关系记录。新事件类型使用同一事件行；新记录类型/字段使用通用标签和字段值详情，不需要新增页面。

## 验收证据范围

真实 HTTP 探针确认：内嵌页 200、DSH 启动 manifest 包含插件 bundle、初始快照 9 个上下文/101 条检查器记录；新上下文验收后为 10 个上下文。历史读取覆盖工具调用、工具结果和错误。外部 Origin 返回 403，只读发送返回 403。

自动回归在真实隔离 Mongo 上验证 HTTP 发送、现有 Chat 入队/发布、新上下文、历史只读、错误、授权、epoch 隔离、脱敏与未知事件。4 项 UI 和 6 项 Chat 测试通过；这些自动测试使用模型替身。

另在 in-app browser 中完成了真实模型验证：普通消息收到 Gemma 回复；新上下文中的最小委托由 Qwen 调用隔离沙箱执行 `print(6 * 7)`，stdout=`42\n`、exit_code=0，再由 Gemma 发布最终回复。已点击 DSH 原生侧栏打开内嵌工作台，展开工具 payload，检查记忆/关系详情、偏好空态、搜索、历史只读、错误折叠和完整 traceback。重启后再次确认真实数据可恢复、阶段状态和错误提示修正有效。具体事件标识与截图位置见 README。
