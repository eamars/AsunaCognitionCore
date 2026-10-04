# DSH 对齐：已核实事实与集成改动

## 1. 版本口径

- 实际运行：`@deepseek-ai/dsh` **0.2.0-rc.2**（`package.json`、`NATIVE_PLUGIN.md`）。
- ADR-008 文本锁定 0.1.5-rc.2（其 `CODEX_START.md` 与 `examples/core.package.json`）。那是设计史，不改；**本 ADR 以 0.2.0-rc.2 为准**。
- 下列事实来自对固定版 npm 包（README、类型与导出）的只读核对，**未在本机运行**。实施者在 P0 第一步必须在 `npm ci` 后的依赖树中复核下表中的每一个名字。**任何一项与实际不符，就停下来报告**确切签名与可用替代，不要自行发明接口（见 [AGENT_START.md](AGENT_START.md#停下来问的条件)）。

## 2. 已核实的 DSH 0.2 事实

| 主题 | 事实 | 对本 ADR 的影响 |
|---|---|---|
| 系统提示段 | `systemPrompt.section({name, order, text, interpolate, complete})` 进入 system 角色；压缩不会缩减 system prompt | 人格段放 `section`，且必须有预算上限 |
| 上下文快照 | `systemPrompt.context({name, order, text})` 进入**持久的 user 角色快照**；压缩覆盖快照后会整体重发；**任何一个 context 变化都会重新追加整份拼接快照** | **人格不得放 `context()`**；高频变化的情感/时钟放在阶段文本里 |
| harness 身份 | 组成默认带 harness 自述（`includeHarnessIdentity`），可由完整替换段 + 抑制运行时上下文的接口去掉 | D-1 |
| 调度 | `dsh-schedule` 支持 `after_seconds`、`at`、`every_seconds`（**最小 60**）、`daily`、`weekly`（ISO 星期，**周一=1…周日=7**）、5 字段 `cron`；`daily/weekly/cron` 需要显式 IANA 时区；有 `schedule_update` 和投递 `history` | D-5、D-7 |
| 调度工具可见性 | Schedule 服务按设计把 `schedule_*` 工具注册进**每个**活动根 agent 的作用域 | 不能"作用域化"，只能决定是否由 Asuna 自己挂载；Asuna preset 已限制工具（D-6） |
| 时间上下文 | `dsh-time-context` 用浏览器时区；没有时区时用英文提示模型"请用户澄清"；QQ 会话没有浏览器时区 | **不采用**（D-10） |
| 长期记忆 | 0.2 **没有**长期记忆包（只有 `AGENTS.md` 指令链、会话查询、压缩） | Mongo 记忆层不是重复建设 |
| 会话查询 | `dsh-session-query` 可以检索原生转录 | 本 ADR 不采用（D-10） |
| 子 agent | `dsh-subagent` 提供可续的子会话与完成通知 | 本 ADR 不替换现有委托（D-10） |
| 注入与维护 | `agent.inject()` 可以在不唤醒的情况下排入上下文；`Agent.runMaintenance()` 在空闲窗口执行 | 记为后续候选，本 ADR 不依赖 |
| 持久化 | 0.2 缺少可忽略事件的标志 | 保留 `persistence.js` 补丁（D-9） |

## 3. 改动清单

### D-1 角色系统提示：人格段与 harness 身份句

- **现状**：在 `PERSONA_PREFIX_SECTION` 上按阶段覆写文本（`index.js:257-259, 287`）；harness 身份句没有被抑制。
- **目标**：
  - 角色作用域注册一个完整替换段（`complete: true`），其文本就是 [ARCHITECTURE.md §8.1](ARCHITECTURE.md#81-系统提示角色作用域每会话) 的渲染结果；
  - 调用抑制运行时上下文的接口，系统提示中不再出现 harness 自述；
  - 渲染结果按会话缓存，只在文档修订或会话类变化时重算。
- **文件**：`packages/cognition-core/src/index.js`（`attachPreset`）、`role.js`；Python 侧新增渲染（`src/asuna/render.py`）和 worker 方法 `render.system`。
- **验收**：T0.5。

### D-2 行动脑：public 价值段

- **现状**：`tasks.py:414` 把完整人格正文接在 `executor.md` 后面。
- **目标**：只接 [ARCHITECTURE.md §8.3](ARCHITECTURE.md#83-行动脑系统提示) 的 public 价值段。
- **验收**：T0.6（P0，只给显示名）、T2.10（P2 起的 public 价值段）。

### D-3 历史只注入增量

- **现状**：每个 MONOLOGUE 都前置近 12 条历史（`context.py:66`、`coordinator.py:150-151`），私聊中同一消息在原生会话里重复出现。
- **目标**：
  - `sessions` 行新增 `history_hwm: {<source_scene_id>: scene_seq}` 和 `compaction_generation`；
  - 构建 `history` 块时，只给出 `scene_seq > hwm` 的行；以下几类按原规则给出，并更新高水位：
    1. 未被唤醒的群消息（它们从未进入会话）；
    2. 其他成员的发言；
    3. A2 链接场景的行；
  - 压缩代数变化（从原生会话事件读出）时，清零高水位并重发完整窗口（仍是 12 条）。
  - 若固定版没有可观测的压缩事件或计数，按停止条件报告，不要用"上下文长度变短"之类的启发式猜测。
- **文件**：`context.py`、`native_worker.py`（会话绑定）、`index.js`（把压缩代数随 `result` 回传）。
- **验收**：T6.1。

### D-4 写入量与转录去重

- **目标**：
  - `episodes` 不再存 `system` 全文，改存 `system_ref`；`context` 改存块 id、修订 id 和选中的 id。
  - `audit_events` 中 `state.commit` 对大于 16 KB 的文档只存 `{collection, id, revision, content_sha256, bytes}`；哈希链不变，篡改检测改为比对集合中文档的 sha。
  - `lane_receipts` 与 `phase.output` 改存 `{content_sha256, bytes, native_ref}`。
  - 必须先改造依赖审计全文的现有测试（重放与篡改相关的 m 系列），保持其**检测能力**不降。
  - `system_ref` 本身在 P0 引入（T0.4）；升级前在途的回合仍带 `system` 全文，读取兼容，P7 删除兼容（见 [ARCHITECTURE.md §8.1](ARCHITECTURE.md#81-系统提示角色作用域每会话)）。
- **文件**：`state.py`、`coordinator.py`、`native_worker.py`、相关测试。
- **验收**：T0.4、T6.2。

### D-5 调度：60 秒下限与原生规则（P5，先于心跳）

- **现状**：300 秒下限分散在三处（`schedule_rules.py:25`、`coordinator.py:28`、`stage_decide.md`）；墙钟规则换算成一次性定时后重挂。
- **目标**：
  - 三处统一为 60 秒，常量只定义在 `schedule_rules.py` 一处，另两处从它生成或引用。
  - `clock` 规则在时区为 IANA 名称时直接映射为原生 `daily`/`weekly`；星期映射 Asuna `0…6`（周一…周日）→ ISO `1…7`。
  - 固定偏移时区（非 IANA）保留一次性重挂路径。
  - `packages/cognition-core/src/schedule.js` 目前只处理 `/schedule/create` 与 `/schedule/delete`：新增 `/schedule/update`（调用原生 `schedule_update`），并把 `update` 操作写入同一 `asuna/schedule` 会话日志，与 create/delete 的对账逻辑一致。
  - 核心默认时区的删除在 P0 完成（未设置时以 UTC 明示），见 [IMPLEMENTATION.md P0](IMPLEMENTATION.md#p0-卫生与地基)。
- **验收**：T5.8。

### D-6 Schedule 挂载开关

- **目标**：`CognitionCore` 配置项 `mount_schedule`（缺省 `true`，仅在 Host 未安装 Schedule 时生效，即现行为）。文档中写明 DSH 设计下 `schedule_*` 工具对所有根 agent 可见；Asuna 的角色和行动 preset 已经限制了工具。
- **验收**：T6.3。

### D-7 心跳与夜间沉淀走原生调度

- `plans.kind ∈ {presence, settlement}` 由核心按人格模型和政策创建与更新，使用原生 `every_seconds` 和 `daily`；改节奏用 `schedule_update`，不删建。
- 投递回调走现有 `schedule.deliver` → 新的回合种类 `presence`/`settlement`（见 [ARCHITECTURE.md §10](ARCHITECTURE.md#10-节律心跳与夜间沉淀)）。
- **验收**：T5.2、T5.3。

### D-8 `Coordinator.advance` 拆分为准备与消费（最后做）

- ADR-008 要求"提取准备阶段输入与消费阶段结果"，而不是在 worker 线程上阻塞等待原生结果（`native_worker.py:82`）。
- 目标：阶段推进改为事件驱动的续接——`stage` 请求发出后立即释放线程，`result` 到达时由消费函数续推。阶段语义、幂等键和崩溃点保持不变。
- 风险高：必须在 P7 进行，并以现有崩溃矩阵测试作为门槛。
- **验收**：T7.1、T7.2。

### D-9 保留与记录

- `persistence.js`：保留，直到 DSH 提供可忽略事件。
- 设置卡：接受现行实现（`plugins.bundle.config` + `ctx.remote.settings.mutate`）对 ADR-008 UI_SPEC 的偏离，在 `NATIVE_PLUGIN.md` 中记录。新增的源根、心跳目标、评估路由设置项放在同一张卡。
- `NATIVE_PLUGIN.md` 与 `RUN_ASUNA.md` 中写明运行时固定版本。

### D-10 明确不采用（本 ADR 内）

| 能力 | 理由 |
|---|---|
| `dsh-time-context` | 浏览器时区、无时区时的英文提示与角色语境冲突；节律块更丰富 |
| `dsh-goal` | ADR-008 已裁定不启用 |
| `dsh-session-query` | 记忆权威在 Mongo；对原生转录检索的需求未出现 |
| 原生 fs/sandbox 工具替换 `ToolBroker` 文件工具 | 授权语义属于业务；替换风险大于收益，记为后续候选 |
| 用 `dsh-subagent` 显示替换 `asuna/action-linked` | 现行可用；记为后续候选 |
| 用 DSH 队列替换 `SceneQueue` | 承载跨场景公平与业务回执，替换收益低 |

## 4. ADR-008 剩余项闭环

| ADR-008 项 | 本 ADR 处理 |
|---|---|
| 准备/消费拆分 | D-8（P7） |
| Schedule 外溢 | D-6（记录 + 开关） |
| CONSULT 无 JS 测试 | P6 补一条 JS 测试（T6.4）：CONSULT 期间角色会话不持锁，行动工具等待的是真实结果；隐私面由 T4.12 覆盖 |
| Core 部署工具默认人格 | [CLEANUP.md §8](CLEANUP.md#8-人格中立化) |
| 人格贡献接口缺默认值 | [PERSONA_CONTRACT.md §2](PERSONA_CONTRACT.md#2-registerpersona-v2) |
| 设置卡偏离 | D-9（接受并记录） |
| 原生压缩死路径 | 随终端删除（P0） |
| 实机浏览器证据 | 每个 P 阶段的人工 Web 检查留截图与说明（见 [ACCEPTANCE.md §4](ACCEPTANCE.md#4-人工-web-检查)），存放在被忽略的本地 `reports/`，不入库 |
