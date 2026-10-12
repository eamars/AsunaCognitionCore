# ADR-008：DSH 原生插件化迁移

状态：**已实施**。修订两次（2026-10-03 主会话内连续展示双脑记录；2026-10-04 重启后等待明确续接），均已批准并实施。取代 ADR-004、ADR-006 的自绘工作台方向。之后：阶段协议由 ADR-011 的工具化回合取代，主会话里的双脑展示演变为 ADR-011 §7.1 的协作线程；分发方式见 ADR-010。

## 决定

采用 **DSH Host 原生插件 + 独立的人格插件**。原生 DSH 负责真实 agent/session、工具循环、模型请求、流式聊天、分页、导航与设置外壳。Asuna 保留双脑认知、Mongo 业务数据、身份与场景、角色自我、任务关联、QQ 与自主开发发布。人格的资源、技能和自己开发的项目独立分发。

两个（现为多个）发布包，都在本仓库 `packages/` 下：
- `@asuna/cognition-core`：Host 插件、少量 Client 插槽、可复用 Python 业务代码。不依赖、不硬编码任何人格。
- 人格包（`packages/personas/*`）：角色贡献、persona/preset 文件、技能、素材、自己开发的集成。默认不带 Client UI，依赖 Core 的公开小接口。

## 不合格的做法（任何时候都不是交付）

- iframe 指向旧 Asuna Web；插件内部再启动各 lane 的 `sdk-minimal` 和旧 UI、再用轮询拼回；
- 覆盖全局 `assistant-step`，把所有 DSH 助手都变成她；全局占用 `main.conversation`、`sidebar.workspaces` 等已占用位置；
- 伪造 `SessionBinding`、手工实现 `ISessions` 假装 Mongo episodes 是原生会话、为了让原生 Chat 显示而复制一份假历史；
- 改 DOM、私有导入、修改 node_modules、复制 DSH 的 apps/web 或完整 Chat 源码；
- 在显示层给输出加口癖冒充独立角色；为省 token 裁剪工具或把角色缩成一句形容词；
- 新增全局原生 hook 截获非 Asuna 会话：作用域只限注册好的角色/行动绑定；
- 先建通用总线、工作流、技能市场、人格管理平台、跨版本 HMR 平台。

## 架构

- 单个 DSH Host 不等于单个模型上下文：角色、行动、总结、调度会话各自是真实 native session。Mongo 仍是一套真实世界数据，不因插件化另建数据库。
- Python 是一个受管的业务 worker：不启动新的 DeepSeekHarness、不提供聊天 Web、不代理 token。Host 插件与 worker 用一条私有受管连接（不同时实施几套 transport）。
- worker 挂掉只让相关 Asuna 功能显示真实错误，不关掉 DSH Web 或其他 agent。最低开发/发布入口在 worker 加载失败时也能工作（ADR-007 的地板）。
- 插件 apply 先注册服务与界面贡献，不把 Mongo 或总结的长初始化变成 Web 外壳挂载的前提；业务未就绪如实显示。
- 三类身份不能混：原生 session ID（持久会话与订阅，不是 scene，也不是授权）；Asuna scene/source/actor（来源、目标、可读数据、任务能力）；persona ID（她的自我与资源；换包版本不创建第二个人）。会话标题不承担权限；原生 Workspace 只指向实际存在且授权的目录。
- 行动任务由同一 Host 的 `ctx.agents.create/resume` 持有真实会话，用行动自己的 preset/setup，不继承角色的无工具配置；原生 resume 后从持久任务绑定恢复同一工作目录、能力与目标。DSH 原生 continuable manager 会继承父预设和 cwd，所以保留公开 create/resume 和业务拥有的运行 handle。
- 后台计划通过 ScheduleService 连接 Host 内的原生 schedule，不新增第二个 scheduler。原生 prompt 来源是插件或计划就如实记录，不伪造真人来源。
- 工具 RPC 绑定实际未完成 operation 捕获的 task 和 workspace，旧回调不能借新任务的授权；同一任务的修订推进 fence，迟到的旧通知只匹配原 operation。
- 生命周期：DSH 管 profile/plugin；Core 管自己创建的 agents、worker、监听器并在 dispose 时释放。卸载插件不删 Mongo 或会话文件。人格文本与技能变化作为数据更新，不每轮重写 preset；涉及 Host JS、依赖或 preset 组成的更新可能需要重启，不承诺热更新。
- 角色、行动、摘要、恢复预设都复用 DSH 原生 compaction backend、`/compact` 与 tool-result pruner。

## 人格打包

- Core 提供一个小的 Asuna 内部资源登记接口（稳定 persona id、展示名、资源根、persona/skill/preset 路径）；DSH 本身没有这个接口。Core 没装人格包时正常加载并提示未选择角色，不悄悄变成某个人格。
- 包里的文档只是新安装的默认值。已有的 Character Core / Current Self / 人格头不因包版本增长被重置；要把文件修改应用到已有自我，走她自己的写入接口，不靠启动时强覆盖。
- 角色脑可以修改核心自我、近况、偏好和声音；程序保存版本，不判断「像不像」。行动脑不替她编自我。
- 用一个薄的角色 preset；稳定角色资料放稳定 section，当前自我、关系、本轮现场走 `systemPrompt.context()` 或日志化上下文路径，不每条消息拼整份系统指令。
- 拆包不缩窄她的自主开发能力：她仍能在已有授权内改 Core；按职责归属，不按作者搬家。普通 QQ 不因同一 Host 有 owner 终端而取得源码或凭据。
- 打包：`files` 显式列出运行代码与选定资源，不把 `.runtime`、DSH_HOME、数据库 dump、模型权重、.venv、node_modules、本机 token 打进包。实际加载的是选定的构建产物，源码工作树可写。

## 界面

- 默认页面是 DSH 原生会话导航、原生 Chat/Trajectory、原生右侧栏。不自绘左栏、composer、消息 store、流式缓冲、分页器、会话切换或连接状态条；原生 New Session 属于 DSH，新会话不会自动接管已绑定的 QQ 场景或获得 owner 权限。
- 只批准两处业务正文：右栏「记忆」标签（`sidebarRightTabs.register` + `sidebar.right.pane.tab`；列表有界分页、点开才取详情，原文和模型理解分开，关闭时不轮询；群会话不因打开标签继承 owner 的可见范围）和 DSH Settings → Plugins 里的 Asuna 设置卡（模型凭据留在 DSH 原生模型设置，Asuna 只保存路由引用；非 LLM 凭据显示「已配置」而非原值；保存不等于生效，说清楚）。
- **修订 2026-10-03（owner 批准）**：操作者留在角色主会话，在同一记录流里读两个脑的实际产出，不必打开行动子会话。紫色「角色脑」、蓝色「行动脑」标签默认可见、放在折叠区外。两脑保留独立模型路由、上下文和原生 session；展示组合引用原始记录，不向角色上下文复制行动历史，不建第二份消息库、缓冲、分页器或渲染器。需要的 DSH 层接点是最小可审阅扩展（Session 作用域的 native Chat 内容工厂，`tools/dsh-inline`）。不批准新侧栏、第二个输入区、独立滚动的嵌入聊天窗。观察或重载页面不触发任务重放或发布。

## 修订 2026-10-04：重启后等待明确续接（owner 选定）

起因：重启恢复了一条旧任务反馈，角色据此重新委托自修复。决定：未完成的旧行动和未处理完的行动反馈在重启后暂停（PAUSED），保留任务身份、原生执行上下文、结果、工具回执与失败记录，不自动调用两脑、不自动再执行；已完成的反馈只核对持久状态。只有操作者在本地会话里明确要求继续，角色才通过新的决策续接原执行关联；新行动先核实已有结果，不盲目重做没有回执的操作。普通聊天、内部自我开发机会、旧反馈都不构成续接授权；明确取消的任务不复活。取消、修订或暂停发生在反馈处理期间时，已有的模型输出保留为内部记录，旧反馈不再产生决策、授权或公开回复。

## 其他仍有效的约束

- 单库、forward-only 发布、失败候选不激活的最低生存地板；不增设测试/生产库、回滚选择器、质量评分或逐次人工审批。
- 模型服务、权重、启动脚本和进程不归 Asuna 管；不自动升级 DSH（升级见 ADR-037）。
- 任务上下文优先列 READY/RUNNING，其余按真实输入时间排列，保持条数上限。
- 测试拥有的 Mongo 库在导出证据后删除，包括失败的 teardown。

Full text: git 47a7434e
