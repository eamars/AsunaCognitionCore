# 推荐架构：把执行与显示放回同一个 DSH Host

## 1. 为什么这不是简单加 package.json

已抽查的 Asuna `DshLane` 通过 Python SDK 启动独立 `sdk-minimal`，各 lane 有自己的 home、代理与 HTTP bridge。原生 DSH Web 无法仅凭这些外部调用结果获得真实 SessionBinding；当前 Client 因而自己维护 scene 数据、请求 `/asuna/api/*`、组装消息与流。

本轮后续读取的 main 已有 delta/低频 idle polling 等修复，不能继续把它描述成完全未修的老代码。根本问题仍然是：Asuna 拥有一套平行会话显示，而 DSH Web 拥有另一套。迁移改变这个归属，不是否定所有已有修复。

## 2. 运行组成

```text
现有模型服务（只使用，不擅自改部署）
             ↑
单个 DSH Host / 既有 Web profile
  ├─ 原生 agents / sessions / tools / model adapters / stream / attachments
  ├─ 原生 Workspace、Chat、Trajectory、设置、右栏外壳
  ├─ @asuna/cognition-core
  │    ├─ scoped 角色阶段接线 + 行动会话关联
  │    ├─ 既有业务工具、QQ/计划来源、最终发布关联
  │    ├─ 一个受管理 Python 业务 worker（首版保留现有语言/逻辑）
  │    │    └─ 原 Mongo：历史/检索/关系/自我/业务任务/回执
  │    └─ 记忆右栏标签 + Asuna 插件设置卡
  └─ @asuna/xiaoman
       └─ 角色资料、技能、素材、开发项目贡献
```

单个 Host 不等于单个模型上下文；角色、行动和已有必要的总结/调度会话仍分别持有真实 native session。总结不是第三个人格，不能阻塞 Web 外壳可用。Mongo 仍是一套真实世界数据，不因插件化要求另建数据库。

保留 Python 是降低迁移成本，不是保留旧宿主控制全部 DSH 的方式。worker 不启动新的 DeepSeekHarness、不提供聊天 Web、不二次代理每个 token。模型请求和原生循环由 Host 内的真实 agent 驱动。

## 3. 三类身份不能混

| 对象 | 用处 | 不允许的推断 |
|---|---|---|
| 原生 session ID | DSH 持久会话、Chat 订阅、执行历史 | 不是数据库 scene，也不是新授权 |
| Asuna scene/source/actor | QQ/Web 来源、目标、可读数据与任务能力 | canonical owner 相同不自动扩 QQ 开发权限 |
| persona ID | 小满的自我、关系语义与插件资源 | 换 package version 不创建第二个人 |

沿已有任务绑定增加必要 native session 关联即可，不建新的身份平台。原生 Workspace 只能指向实际存在且授权的目录；不能为了漂亮分组伪造 cwd 或把所有 QQ 会话指向 owner 源码目录。会话标题可以是“本机私聊 / 某 QQ 群 / 当前行动”；标题不承担权限。

A2 的两端 transport scene 和各自发布目标保持；共享私聊连续性不等于把 Web/QQ 合为一个可冒用身份的 session。工具视图仍由当前绑定能力决定；公网 web 默认能力、owner 与可信 self-development 的能力组合维持已裁定语义。

## 4. 角色阶段怎样进入原生循环

采用固定版公开接点，不重写 agent-loop：

1. 通过 preset/scoped setup 给真实角色 agent 装入 Asuna 接线。原生 composer 原输入仍由 SessionController 接收。
2. 在 scoped `agent/pre-step` 等正确边界关联输入与原 episode；将已授权材料和阶段要求作为有真实来源的 native 上下文提交。保留原消息 id/source，不把系统反馈伪装成用户。
3. 原生循环执行模型请求，产生真实 `assistant/message` 或 `assistant/attempt` 及 live frames。Asuna 记录关联，不复制全文建立另一条“展示历史”。
4. 用实际会话事件处理该阶段产物；在公开 turn/step 边界决定是否继续已有阶段或委托。可利用 `agent/turn-stopping` 的最后 steering 边界。普通 action tools 继续由 DSH 执行。
5. 仅真正 SPEAK 发布候选进入现有 PublishService；MONOLOGUE、DECIDE、CONSULT 是内部内容，在操作者原生会话中可观察，但不自动发送 QQ。

**需要调整当前 Coordinator 的同步控制边界**：提取已有“准备阶段输入”和“消费阶段结果”逻辑，保留一份角色语义；不能在自身 hook 里调用旧 `advance()` 再等待同一个角色 agent 生成，形成嵌套等待。也不能同时留下两个阶段推进器。

`agent/request` 只用于支持的请求选项；不要在那里秘密重写模型消息，造成日志与实际上下文不符。`whenIdle()` 观察整个 agent，不标识某个咨询或任务；用原 operation 与真实 attempt/step/turn 事件关联，不能收到任何 idle 就把任务标完成。

上述是拟实施方案，未在本地固定依赖中实际运行。P0 必须先证明 hook 顺序、任务回传和原生 UI 是否满足，发现缺口只修必要接点；不能宣称 API 存在即整体迁移成功。

## 5. 行动与咨询

行动任务由同一个 Host 的 `ctx.agents.create/resume` 持有真实会话。为它明确提供行动 preset/setup，不直接套一个从角色继承无工具配置的子 agent。已有 broker 工具可以经 worker 执行；DSH 原生 web/todo/skills 等仍用原生实现。

实际native session被Web重新打开或恢复时，scoped action插件必须从已有持久任务绑定恢复同一工作目录/能力/目标；不能只在首次create时配置，而在native resume后跌回全局默认工具。仅打开日志不重发已消费业务事件。

每个需延续的开发目标保留既有 execution binding 对应的 native session。新 task 记录不必是新冷会话。事实内容与角色意图交换继续按需，不固定每 N 个工具咨询一次。

CONSULT 在原角色会话队列中生成内部判断，原行动工具等待真实结果；等待期间不持有角色所需共享锁。角色需要进一步材料时先返回缺项，使行动能够继续调查，而不是双方同步相等。既有取消和错误回到原调用链。

后台计划通过已有 ScheduleService 连接 Host 内的原生 schedule；不新增第二个 scheduler，不启用与自主来源语义冲突的 Goal 插件。原生 prompt 源是插件/计划就如实记录，不伪造真人来源来通过原生限制。

## 6. Python 业务边界

保留 context/retrieval/history/state/memory/tasks/publication/channels/schedule 的可复用业务逻辑；从 Application/RuntimeHost 中剥离重复启动 DSH/Web 的职责。

Host 插件与 worker 使用一个私有受管连接；优先复用当前可用 transport，若旧 `/run` 本质依赖嵌套 SDK，则改为最小 stdio JSON 请求/事件。不要同时实施 HTTP、WebSocket、消息队列三套方案。

消息只携带准备/结果/查询/工具/状态等必要业务数据。不得为 UI 传每 token 的原始 provider body。新的模型请求结果由 DSH 正常记录；需要旧格式诊断时按需读取，不让它成为执行成功条件。

插件 apply 先注册既有服务/界面贡献，不把所有lane、Mongo或可选总结的长初始化同步变成Web外壳挂载前提。业务未就绪如实显示，不宣称Asuna已可用。

worker 挂掉只能让相关 Asuna 功能显示真实错误/待恢复，不应关掉整个 DSH Web 或其他 agent。最低开发/发布入口必须能在 mutable worker 加载失败时工作：复用已有 ADR-007 地板，而不是把该地板也放进一个导入失败就消失的业务模块。

## 7. 生命周期与配置

DSH 管理 profile/plugin 生命周期；Core 管理自己创建的 agents/worker/监听器，并在 dispose 时释放。卸载插件不删除 Mongo 或会话文件，不复活已取消目标。

人格文本/技能变化尽量作为数据更新；不每轮重写 preset。Python 业务更新可只替换受管 worker；涉及 Host 插件 JS、依赖或 preset composition 的更新，可能需要安全的 agent/plugin 重建或 DSH 重启。**不承诺任何修改都热更新，也不开发跨版本 HMR 平台。**

现有长寿命 Web 修复可保留到迁移完成；最终正常业务 worker 更换不必杀掉 DSH Web。DSH 自身升级/重启仍会中断 Web，沿原生连接恢复语义呈现，不假称零停机。

## 8. 迁移不是限制能力

现有单库、错误继承、角色自我可写、工具自主调用、forward-only 发布继续有效。迁移检查是一次工程接线验证，不是每次小满发布的质量门槛。

Core 没装小满包不应悄悄变成小满；可以正常加载并提示未选择角色资源。禁用本插件不影响普通 DSH preset。其他插件已有注册同一名字时按原生规则处理具体冲突，不覆盖全部默认设置。
