# 致架构师：小满当前工具面与自我迭代能力审计

> **状态：待架构师审计。** 本文记录当前实现并请求一份最小、可执行的工具暴露裁定；它不是实施授权，也不表示下列候选工具已经接通。

## 1. 目标与主体边界

用户希望审计小满可用的工具，按自我迭代需要添加或移除工具，让她能更自由、稳定地反思、延续工作、开发、核验和发布。

**用户不会限制小满的任何自我迭代行为。** 本文中“禁止过度开发”只约束 Codex 及其他开发 agent 的工程范围，不约束小满。不得以本次审计为由给小满增加自我迭代次数、频率、回合、工具调用数、目标数、发布次数或任务时长上限；不得增加必须产出改动、固定清单、增长评分、Codex 审批或每轮用户确认。是否开始、继续、暂停、改变方向、核验或发布，仍由小满依现有角色职责自行判断。

## 2. 当前实现快照

官方 Web 宿主以 `task_mode=workspace` 运行。应区分：**DSH 工具注册表中模型可见的 schema**、**单个任务 `allowed_capabilities` 允许执行的工具**，以及**Asuna 的结构化角色决策**。它们不是同一层。

### 角色脑

- 角色脑的模型请求不带工具；代理层会拒绝角色路由请求中的工具列表。[`provider_proxy.py`](../../../src/asuna/provider_proxy.py#L56)
- 角色脑仍可通过既有 DECIDE 协议选择是否委托、安排或更新/取消计划、继续任务、反思或保持沉默。这些是宿主处理的结构化决策，不是角色脑直接调用 DSH 工具。[`coordinator.py`](../../../src/asuna/coordinator.py#L232) [`schedule.py`](../../../src/asuna/schedule.py#L63)

### 行动脑：Asuna 工具 broker

正常 Web 工作区注册的基础工具：

| 工具 | 用途 / 边界 |
|---|---|
| `list_files`、`read_file`、`write_file` | 操作本任务获准的 `/task` 工作区 |
| `sandbox_run` | 在任务隔离环境执行命令；无网络和宿主凭据 |
| `task_status` | 可选地标记当前评估状态；不是 TODO 清单或任务完成门槛 |
| `query_authorized_history` | 只读查询任务绑定场景的历史原话 |
| `digest_authorized_discussion` | 只读整理任务绑定场景的群讨论 |
| `consult_character` | 向角色脑请求一次内部判断；不创建公开回复或新授权 |

本机授权工作区另有 DSH 原生技能发现/调用；本机配置提供持久技能目录。普通 Web 工作区由宿主提供 `WORKSPACE_TOOLS`，broker 注册代码还列出 owner 专用工具；每次调用最终受任务能力清单校验。[`tasks.py`](../../../src/asuna/tasks.py#L39) [`tasks.py`](../../../src/asuna/tasks.py#L227) [`dsh_lane.py`](../../../src/asuna/dsh_lane.py#L94)

本机 owner 配置目前启用了自我开发和集成能力，并与本机聊天身份绑定。因此本机 owner 委托任务可获准使用以下额外工具：

| 工具 | 用途 / 边界 |
|---|---|
| `development_files`、`development_read`、`development_write` | 查看、读取和修改持久项目候选 |
| `development_run` | 在候选隔离环境执行命令并返回原始结果 |
| `development_database_read` | owner 开发任务只读访问现有真实数据库记录 |
| `development_publish` | 冻结候选、做最低启动探针并自行发布可启动候选 |
| `integration_dev` | 在独立持久集成开发目录开发；此环境无网络 |
| `integration_test` | 对冻结集成副本运行检查；只可访问显式配置端点 |
| `integration_start`、`integration_stop`、`integration_status` | 管理并观察已配置的集成服务 |

这些工具已有实现，定义分别见 [`development.py`](../../../src/asuna/development.py#L23) 和 [`integration.py`](../../../src/asuna/integration.py#L18)。工具注册表会展示整组定义，而 broker 对每次调用再检查任务 grant；请审计这种“schema 可见但执行被拒”的设计是否符合预期，尤其是非 owner/QQ 任务。不要把它误报为未授权调用实际成功。

### 原生 DSH 能力及当前未暴露项

| DSH / Asuna 能力 | 当前情况 |
|---|---|
| Skills | 行动脑可使用 DSH 原生技能工具；优先用现有技能机制扩展可复用能力，不另造技能注册/加载服务。 |
| TODO | `@deepseek-ai/dsh-tool-todo` 随 DSH 分发，但当前 `sdk-minimal` 运行树未加载它；行动脑没有 `todo_write`。`task_status` 不能替代持续任务清单。 |
| Goal | `@deepseek-ai/dsh-tool-goal` 随 DSH 分发，但当前运行树未加载；行动脑没有 `get_goal`、`create_goal`、`update_goal`。任务输入中的 `goal` 字段只是当前委托目标，不等于 DSH 的持久 goal 工具。 |
| Scheduler | 当前 DSH 原生 schedule 插件由独立的宿主 scheduler lane 持有，行动脑没有直接 `schedule_*` 工具。角色脑通过既有 DECIDE 计划字段提出创建、更新或取消，宿主再调用原生 DSH schedule；没有第二个计时服务。 |
| Web | 当前行动脑运行树没有 `web_search` / `web_fetch`。但 ADR-007 的架构师补充裁定已要求所有合法进入行动脑的 Asuna 任务默认使用这两项 DSH 原生能力，不能按输入来源或开发 grant 裁剪；本项是已裁定但当前代码尚未接通的差距，见 [`DEVELOPMENT_GUIDE_APPEND.md`](DEVELOPMENT_GUIDE_APPEND.md#公共互联网搜索与网页读取架构师补充裁定)。 |

`fixture_*` 工具属于旧的非 Web fixture 执行配置，不是当前 `task_mode=workspace` Web 工具面，不应误列为小满当前可用工具。[`tasks.py`](../../../src/asuna/tasks.py#L30)

## 3. 请架构师裁定

请基于当前固定 DSH 版本和上述现有 ADR 决定，并明确指出“保留 / 添加 / 移除 / 仅内部使用”，尤其回答：

1. 是否把 DSH 原生 `todo_write` 和 goal 工具接入行动脑常规 DSH 会话，供小满自行组织、延续或修订长期迭代工作？若接入，请复用 DSH 原生服务及会话持久化，不制作 Asuna TODO/Goal 替代品；请说明其同一 DSH 会话语义如何服务 Asuna 跨任务反馈/自我开发延续。
2. 是否保持 scheduler 仅由宿主通过现有 DECIDE → ScheduleService → DSH 原生 schedule 路径管理？若现有路径已满足创建、更新、取消及到期唤醒，不再增加第二套调度工具、计划数据库或计时器。
3. 对 owner 专用 `development_*` 与 `integration_*`，工具 schema 是否应只向有相应 grant 的行动脑会话暴露，同时继续保留 broker 的执行校验？请裁定最小接线，不改变现有 QQ / 场景身份边界。
4. 按既有裁定补齐默认 `web_search` / `web_fetch`，复用固定版本 DSH 的 managed web 工具与 provider；不要把公网能力改成任意 shell 网络权限。
5. 核实当前 DSH 原生 skills、todo、goal、schedule、web 工具的真实插件/API/持久语义。依赖存在不等于运行时已暴露；不要仅凭 `package-lock.json` 推断。

请给出每项工具的最小结论和实现顺序；若某项不应直接暴露给行动脑，说明现有路径如何仍支持小满自主迭代。已经裁定的 Web 默认能力不要在本次重开。

## 4. 对 Codex / 开发 agent 的范围要求

以下是**只对开发 agent 的防过度开发要求**，不是对小满的运行限制：

- 先按架构师裁定接入/移除现有 DSH 插件，并补齐最窄的 Asuna 任务能力映射；已有 DSH 类似服务时，除非写明具体特殊理由，必须优先复用。
- 不新建 agent/harness、TODO 或 goal 后端、第二个 scheduler、技能市场、工具治理平台、增长管理器、审查 agent、质量评分器、发布管理器、通用网络 broker 或平行权限框架。
- 不增加自我迭代次数/频率/步数/重试/工具调用预算，不要求固定反思、TODO、测试清单、结果评分、Codex 审批或每轮人工确认。
- 不把“禁止过度开发”写进小满的 system prompt，不在角色脑或行动脑循环中新增行为拦截。行动脑可在已授权资源内自主调查、编辑、试用、修正、延续及发布。
- 修改范围、实现理由和差异应对应架构师逐项裁定；每项新增自建机制须说明 DSH 现有服务为何不能满足。没有特殊理由时，停止在最小接线处。

本请求不要求 Codex 现在开始工具接线或运行验收；它要求架构师先审计并给出裁定。收到裁定/启动指示后，才由 Codex 按上述窄范围执行。

## 5. 代码定位

- 角色工具禁用与实际 provider 请求：[`provider_proxy.py`](../../../src/asuna/provider_proxy.py#L56)
- Web 工作区和 broker 注册表 / grant 校验：[`tasks.py`](../../../src/asuna/tasks.py#L39) [`tasks.py`](../../../src/asuna/tasks.py#L227) [`tasks.py`](../../../src/asuna/tasks.py#L245)
- owner 开发 / 集成工具定义：[`development.py`](../../../src/asuna/development.py#L23) [`integration.py`](../../../src/asuna/integration.py#L18)
- DSH profile 和原生技能插件配置：[`dsh_lane.py`](../../../src/asuna/dsh_lane.py#L94)
- 角色结构化 schedule 决策与宿主 native scheduler：[`coordinator.py`](../../../src/asuna/coordinator.py#L232) [`schedule.py`](../../../src/asuna/schedule.py#L63)
