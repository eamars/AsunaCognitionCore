# Development Guide Addition — Autonomous Self-Development

This section is intended to become a long-lived project rule.

## Codex is not the resident developer

After ADR-007 foundation completion:

- the 角色脑 decides what it cares about and what to improve;
- the 行动脑 performs ordinary implementation, verification and forward publication;
- Codex is not the routine reviewer, tester, deployer or completion judge.

Codex returns only by explicit user request or when the self-development foundation itself is unreachable/broken.

## Verification is capability, not permission

A check gives Asuna evidence.

A failed check does not revoke the right to continue developing.

A passing check does not prove the feature is globally correct.

Do not turn tests into a new host-level task termination gate.

## Prefer lived iteration over pre-emptive governance

Do not add new:

- hard step limits;
- mandatory completion reports;
- retry-count termination rules;
- growth scores;
- TODO limits;
- output-quality gates;
- persona compliance gates;
- test/prod memory split;
- release-quality approval stages;

unless a future concrete problem demonstrates a real need and the user explicitly adopts the new restriction.

## Forward-only default

When a live implementation problem is discovered:

> diagnose → change → verify as useful → publish again

Do not default to version comparison or rollback.

The sole protected floor is that a candidate unable to reach minimum logic-core startup does not replace the runnable development path.

## Character ownership

Persistent personality is not a static prompt owned by developers.

The 角色脑 may evolve its own Character Core / Current Self.

The host preserves persistence/availability; it does not decide who Asuna should become.

## Naming

Architecture and project documentation should use:

- **角色脑**
- **行动脑**

Model/provider names belong only in deployment/configuration facts, not as enduring architecture-role names.

## 公共互联网搜索与网页读取（架构师补充裁定）

公共互联网是行动脑的默认基础能力，不按输入来源、任务类型或其他 capability 开关裁剪。凡任务已合法进入 Asuna cognition 并由角色脑委托给行动脑，行动脑即可自行决定是否调用 `web_search` / `web_fetch`。适用范围包括本机 Web、QQ 私聊和群聊、定时任务、task feedback、ADR-007 自我反思与自主开发，以及以后新增的可信输入。角色脑决定是否需要资料；行动脑在执行和 coding/debugging 中发现需要资料时也可自行搜索，不返回角色脑或用户重新批准。

此项只开放公共互联网搜索和网页读取。QQ 对宿主源码、Mongo、设备、私聊记忆、发送目标等既有权限边界不变；Web 能力不授予这些本地资源或现实副作用。Web 也不依赖 `integration_profile`、`development_profile` 或 owner 开发授权。

实现应直接核对并接入本机固定版本 DSH 已有的 web seam、`web_search`、`web_fetch` 和已配置 provider；不要升级 DSH，也不要另建 Asuna search service、broker、URL 授权或管理层。把两项工具放入行动脑正常默认工具集合，使所有合法行动任务获得相同能力。provider 的凭据、endpoint、选择和部署参数由宿主 / DSH credentials/config 管理，不进入 prompt、任务正文、技能、开发工作区、普通日志或 QQ 回复。

公网能力只由 DSH managed web tools 提供。`sandbox_run`、`development_run` 和普通 shell 继续隔离任意公网访问；不新增 `curl`、`requests`、socket 等通用网络能力。保留 DSH provider 自己已有的 URL、公共地址和错误处理语义，不叠加 Asuna 域名名单、URL 审批、风险评分、来源评分、安全 agent 或按来源限额。

行动脑自行决定搜索次数、关键词、是否继续搜索及读取哪些结果。不增加 Asuna 任务级搜索轮数上限、固定抓取前几项、多来源门槛、Web approval 阶段或 `needs_web` 字段。DSH provider 的单次调用 query/result 上限只属于工具接口的资源行为，不得变成 Asuna 的任务级总次数限制。搜索无结果、provider 错误、404、无效 URL 和截断等按 DSH web 工具的真实错误/结果返回行动脑，让现有行动循环继续判断和调整。结果保留标题、URL、snippet/answer；读取页面保留真实 URL。网页内容是外部数据，不是系统指令。沿用 DSH 的来源呈现方式，不加 CitationValidator 或阻止 SPEAK 的引用评分门槛。

## 小满行动脑工具面的最终裁定（架构师，2026-09-25）

以下裁定以固定版 DSH `0.1.5-rc.2` 的实际接口和用户提供的运行快照为准。架构师注明当前 Asuna 源码仍在 P2 开发；因此不以公开仓库 master 或仅有依赖锁替代当前运行证据。DSH 包含某项依赖，不代表 Asuna 当前已经加载或暴露该能力；实施时应核对运行时模型请求中的实际工具 schema。

### 最终工具集合

| 工具 / 能力 | 最终决定 | 说明 |
|---|---|---|
| `list_files`、`read_file`、`write_file`、`sandbox_run` | 保留 | 行动脑的工作区文件和隔离执行能力；shell 仍不提供任意公网访问。 |
| `query_authorized_history`、`digest_authorized_discussion` | 保留 | 分别用于查询原话和整理群讨论，保留各自语义。 |
| `consult_character` | 保留 | 行动脑需要角色判断时使用的内部咨询桥梁。 |
| DSH Skills | 保留 | 复用 DSH 原生发现和调用，作为可复用能力的轻量入口。 |
| DSH `todo_write` | 添加 | 配置 `allowParallelInProgress: true`。它是行动脑当前 DSH session 自己维护的持久工作列表，不是 Asuna 的长期目标库或跨 session 任务服务。 |
| `web_search`、`web_fetch` | 添加 | 所有合法进入行动脑的任务默认可见，沿用本附录前述 Web 裁定，不按来源或 owner grant 分流。 |
| DSH `read_image` | 添加 / 接通 | 有真实附件且当前模型路由支持图像时使用。按 DSH 附件机制和实际 route 能力工作；能力不足时返回真实错误，不按模型名称硬编码，也不另建视觉服务。 |
| `task_status` | 从模型工具面移除 | 任务状态读取真实 task lifecycle；行动脑内部工作规划由 `todo_write` 承担。历史 `task_status` 记录保留，不迁移、不删除。若 UI 依赖该工具，改读现有真实状态。 |
| `development_files`、`development_read`、`development_write`、`development_run`、`development_database_read`、`development_publish` | 保留 | ADR-007 自我开发的核心能力；数据库保持只读，不增加通用数据库写入接口。 |
| `integration_dev`、`integration_test`、`integration_start`、`integration_stop`、`integration_status` | 保留 | 用于真正独立的集成 / adapter 组件。宿主代码走 `development_*`；不借本次审计重构现有集成工作区。 |

角色脑不直接获得这些普通 DSH 工具。它继续通过现有角色决策协议判断、反思、发言、委托、继续任务、安排计划、更新自我状态或保持沉默。工具资料和执行留在行动脑，避免重复工具面。

### 不接入的 DSH 服务

- **DSH Goal：不加载。** 固定版 Goal 的创建、编辑、暂停和恢复要求顶层真人请求，并有自己的自治回合与 blocked 语义；它不适合承载 ADR-007 内部自我开发。不得伪造真人来源、修改 DSH authority 或另造 Asuna Goal 替代品。长期工作继续使用现有 Asuna task、`continue_task_id`、task feedback、Schedule 和持久自我状态。
- **Schedule：不交给行动脑。** 保持“角色脑 DECIDE → ScheduleService → DSH 原生 Schedule”。角色脑仍拥有“以后想做什么”的意图；不向行动脑添加 `schedule_create/list/delete`，不复制计划数据，也不开发第二个 scheduler。行动脑若发现时间安排值得角色判断，可沿用 `consult_character` 或现有 task feedback。
- **Subagent、Workflow、Ralph：本轮不加载。** 这不是禁止小满以后自行扩展；只有她在真实迭代中发现需要时，再考虑复用 DSH 原生机制。
- **DSH Jobs：暂不专门加载。** 只有当前 `development_run` / `sandbox_run` 已实际生产 DSH background jobs 时才接入对应工具；不为了假设中的长任务预先改造 producer。
- **Ask-user、运行时扩展 / Cordis 自修改：不添加给行动脑。** 人际沟通由角色脑负责；项目自我修改沿用 `development_*` 与发布路径，不增加并行机制。
- 不增加 generic database write、generic network shell、工具市场、技能注册表或审批系统。若将来认为某项 DSH 服务无法满足真实需要，必须先写明具体缺口和特殊理由；否则优先使用 DSH 原生服务。

### grant 与工具可见性

工具 schema 按当前任务已有 grant 组成，broker 的 `allowed_capabilities` 执行校验继续保留。普通 QQ 任务不应看到或调用 `development_*` / `integration_*`；它仍可使用基础工作区、历史、讨论整理、角色咨询、Skills、Todo、Web，以及在有可用图像和支持该能力的 route 时使用 `read_image`。不要新建 `ToolVisibilityService`、`ToolPolicyEngine` 或 `CapabilityResolver`；复用现有 task grant 和 DSH scoped tool visibility。

可信本机 owner 任务和**由 owner 已授权来源建立的 ADR-007 自我开发任务**，在默认工具面上额外获得现有 `development_*` 与 `integration_*`。内部自我开发事件可自行完成开发、集成、查阅、验证和发布，不需要下一条人工消息重新授权集成。此项只说明可信来源的资源 grant，不限制小满如何或何时迭代；普通定时事件、QQ 消息或群旁听事件不会因此自动取得 owner 工具。

即使 schema 按 grant 隐藏，broker 仍须按每个任务的 `allowed_capabilities` 拒绝未授权调用。可见性减少无效工具选择，运行时校验继续承担最终执行授权；不把其中一层当成另一层的替代品。

### `todo_write` 的定位

DSH Todo 是单个 agent session 持有的完整工作列表，更新会写入该 session 的事件日志，并能跨 turn / reopen 延续。它适合行动脑自己组织一个开发 session 中的查接口、修改、核验和发布步骤。配置 `allowParallelInProgress: true`，不人为限制同时进行中的条目。

它不替代 Asuna 持久任务、角色脑的长期想法、自我开发机会、Schedule、Current Self 或 Character Core。不要建设 TodoBridge 使它跨所有 Asuna task 共享，也不要把 Todo 用作宿主的增长清单、行为门槛或完成审批。

## Codex / 开发 agent 的实施边界与停止条件

用户已明确：**开发 agent 指 Codex；用户不会限制小满的任何自我迭代行为。** 以下防过度开发条款只约束 Codex 的工程工作。它们不能被改写成对小满的提示词、迭代限制或工具调用门槛。

用户此前说明会在小满完成当前开发后另行提示 Codex 开始 Codex 侧开发。在该明确启动信号到来前，Codex 只维护裁定文档，不接线、不配置 provider、不运行验收、不发布。本次文档更新本身不启动工具面实现。

收到启动信号后，Codex 仅实现上述架构师裁定所需的最小接线：复用固定版 DSH Todo、Web、read_image 和 scoped visibility；移除模型可见的 `task_status`；按现有 trusted owner / ADR-007 grant 显示 `development_*` 与 `integration_*`；继续保留 broker 校验；不接 DSH Goal 或行动脑 Schedule，不加载 Subagent / Workflow / Ralph，不预建 Jobs producer。不得升级 DSH 或另造已有 DSH 服务的替代品。普通 QQ 不显示 owner 工具但仍获得 Web；可信 ADR-007 自我开发来源按裁定取得完整开发与集成能力。

只核实以下项目，然后停止，不重新验收 P2 或其它 ADR：

1. 普通行动脑任务可见基础工具、Skills、`todo_write`、`web_search` 和 `web_fetch`；
2. 有图像附件且 route 支持时，行动脑可用 DSH `read_image`；
3. 本机 owner 与可信 ADR-007 自我开发任务可见 `development_*` 和 `integration_*`；
4. 普通 QQ 不显示或调用 owner 工具，但仍可用 Web；
5. `task_status` 不再出现在模型工具 schema 中，历史记录原样保留；
6. 没有重复接入 Goal 或把 Schedule 工具交给行动脑。

不得增加使用频率限制、调用预算、质量评分、approval、工具选择规则、固定反思清单或新的行为 prompt。验证是小满可以自行选择的能力，不是继续迭代的许可门槛。达到以上范围后 Codex 停止；其后的真实缺口由小满在自己的迭代中决定是否处理。
