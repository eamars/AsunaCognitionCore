# 现状审计（基线 `8b5a94a1`）

> 行号以 `8b5a94a1` 为准；实施者动手前须在本机工作树复核（本机可能有未提交改动）。本审计**未运行**任何模型、浏览器或 QQ；DSH 事实来自对固定版 npm 包内容的只读核对，详见 [DSH_ALIGNMENT.md](DSH_ALIGNMENT.md)。

## 1. 审计范围

- Python 业务包 `src/asuna/**`（约 11k 行，54 个模块）、`config/prompts/*`、`tests/**`、`tools/**`。
- 两个插件包 `packages/cognition-core/**`、`packages/xiaoman/**`。
- ADR-001…008 设计文档（只作背景，不作现行权威）。
- DSH 0.2.0-rc.2 相关包的 README/导出（`dsh-system-prompt`、`dsh-schedule`、`dsh-agent-loop`、`dsh-compaction-*`、`dsh-subagent`、`dsh-session-query`、`dsh-time-context` 等）。

## 2. 运行拓扑

```text
start-asuna.cmd → tools/asuna-launch.mjs → dsh ui --profile asuna-native（DSH_HOME=.runtime/…）
单个 DSH Host
 ├─ 原生：agents / sessions(JSONL) / tool loop / model adapters / compaction / schedule / Web
 ├─ @asuna/cognition-core（packages/cognition-core/src/index.js：CognitionCore）
 │    ├─ role / action / summary / scheduler / recovery preset
 │    ├─ floor.js（ADR-007 发布地板）、persistence.js（0.2 缺 ignorable 的补丁）
 │    └─ worker.js ──stdio JSONL──▶ python -m asuna.native_worker
 │                                   ├─ RuntimeHost（host.py）：Chat 队列、ChannelServer(:8766)、
 │                                   │   IntegrationRunner、MemoryIndexer、ScheduleService
 │                                   └─ Application：Store、Retrieval、Coordinator、TaskService、ToolBroker…
 └─ @asuna/xiaoman（packages/xiaoman/src/index.js）：registerPersona(id, character_id, persona/core.md, skills, QQ adapter)
```

- JS↔Python 协议：JS→Py `{id, method, args}`，Py→JS `{id, value|error}`；Py 主动事件 `stage` / `host_request` / `episode_finished` / `restart_requested`（`worker.js:11-51`，`native_worker.py:248-320`）。
- Worker 方法：`initialize`、`status`、`input`、`result`、`session`、`memory.page`、`memory.detail`、`tool`、`tool_specs`、`schedule.deliver`、`persona.resources`、`publication.activated`、`host_result`（`native_worker.py:248-320`）。

## 3. 一轮认知的真实路径

### 3.1 入站

- **Web**：原生 composer → 角色作用域 `agent/inbox/claimed`（`index.js:260`）→ `system-prompt/assemble` 中调用 worker `input`（`index.js:265-288`）→ `Chat.submit`（`chat.py:162`）→ `ingress.persist_input` → `SceneQueue` → `asuna-chat` 线程（`chat.py:86`）→ `Router.receive` → `Coordinator.ingest`（`coordinator.py:61`）。
- **QQ**：NapCat 适配器作为受管集成进程，带 bearer token POST `/v1/channels/<id>/events`（`channels.py:84`）；`group_context`（`channels.py:35`）算 `wake_reason`；未被唤醒的群消息记 `RECORDED_NO_WAKE`、不调模型；P5 主动闸门可能再入队（`chat.py:223-233`）。

### 3.2 阶段机（`Coordinator.advance`，`coordinator.py:174` 起）

所有阶段在**同一个持久原生角色会话**内进行；会话 id 由（场景、人物、人格、纪元、`character_context`）哈希得出（`native_worker.py:185`）。

1. **MONOLOGUE**：整份上下文 JSON 只前置给本阶段（`coordinator.py:150-151`）；输出另存为 `memory_units` kind `monologue`（`coordinator.py:208`）。
2. **DECIDE**：输出按 `WORKSPACE_DECISION_SCHEMA` 校验（`coordinator.py:15-43`），`next ∈ {speak, delegate, recall, silent}`，可带 `reflect_understanding`、`reflect_self`、`schedule`、`update_plan`、`cancel_plan_id`、`cancel_task_id`、`continue_task_id`；一次修复重试。计划类无效会走 `_plan_rejected` 记录而不打断回合（`coordinator.py:123`）——**本 ADR 的新增可选字段沿用这一失败语义**。
3. 可选 **SELF**（仅 owner 内部自开发回合，`coordinator.py:217-226`）、计划控制、**REFLECT**（`commit_understanding`，`coordinator.py:267`）、取消任务。
4. 分支：`silent`（`coordinator.py:279`）、`recall`（至多 2 轮，`coordinator.py:285-287`）、`delegate`（建 `tasks` 行，`coordinator.py:293`）。
5. **SPEAK**（`coordinator.py:345`）：一条出站 `<ep>:speak:0` 经 `PublishService`（`publish.py:13`）发布；Web 本地回执即 `DELIVERED`，渠道场景 `QUEUED_EXTERNAL` 由适配器经 outbox `claim`（`channels.py:135`）取走。

### 3.3 角色系统提示与原生传输

- 角色作用域工具为空（`index.js:250`）；人格通过覆写 `PERSONA_PREFIX_SECTION` 注入（`index.js:257-259, 287`），文本 = `common.md` + 人格头正文（`context.py` 末尾组装）。
- **仓库内没有任何地方关闭 DSH 的 harness 身份句**；角色会话的系统提示开头仍是原生的 harness 自述。人格若不愿自称 AI，这是冲突（见 [DSH_ALIGNMENT.md D-1](DSH_ALIGNMENT.md#d-1-角色系统提示人格段与-harness-身份句)）。
- 每阶段 `ensureAgent`（`index.js:177`）→ `followup`；`turn-stopping`（`index.js:307`）把结果交还 worker，并在同一原生 turn 内 steer 下一阶段。`NativeLane.generate` 在 worker 线程上阻塞等待 `Future`（`native_worker.py:82`）。

### 3.4 行动脑

- `Chat._tasks`（`chat.py:108`）→ `Executor`（`tasks.py:362`）→ `_run_workspace`（`tasks.py:411`）。系统提示 = `executor.md` + **完整人格正文**（`tasks.py:414`）——群任务、带 `web_search/web_fetch` 的任务也一样。**这是隐私缺口**（人格正文将来会含 owner 私密段）。
- 原生会话 `asuna-action-<hash>`；按授权注册工具（`index.js:352-386`）由 `ToolBroker.call`（`tasks.py:237`）执行；`consult_character` 回到角色会话跑 CONSULT（`coordinator.py:83`）。结果经 `TaskService.feedback` 生成 `task_feedback` 回合再走一遍 MONOLOGUE→DECIDE→SPEAK。

## 4. 记忆现状

### 4.1 Mongo 集合（`state.py:12-13`）

| 集合 | 用途 |
|---|---|
| `identities` | 平台账号 → `person_id`（含 `canonical_person_id`） |
| `scenes` | `kind` dm/group、成员、`scope_key`、`policy_epoch`、序号、渠道、`character_context` |
| `messages` | 入站 `in-ep-*`、出站 `*:speak:0`（投递状态、回执） |
| `episodes` | 阶段状态、**完整 `context` 与 `system` 文本**、manifest、决策、发言 |
| `tasks` / `plans` | 行动任务（授权快照、栅栏）/ 计划（规则、时区、原生 schedule id） |
| `memory_units` | `chat_chunk`、`monologue`、`dialogue_summary`（带 `source_window`、`epistemic_type`） |
| `state_heads` / `state_revisions` | CAS 修订账，键 `entity|scope` |
| `sessions` | 原生会话绑定 |
| `audit_events` | 哈希链审计；`state.commit` **复制整份文档** |
| `artifacts`、`sink_receipts`、`lane_receipts` | 工具回执/blob、本地发布回执、阶段结果（**含全文**） |

另：GridFS `artifact_blobs`；`memory_units` 上的向量索引（768 维 cosine，`retrieval.py:64-77`）。

### 4.2 修订账实际使用的实体

`persona:<p>|global-safe`、`character_core:<p>|global-safe`、`current_self:<p>|global-safe`、`relationship:<person>|scene:<scene>`（或 A2 规范目标）。`Store.mutate`（`state.py:176`）只允许 `persona:/overlay:/relationship:/scene_affect:` 前缀与 `body/familiarity/trust/closeness/tension` 字段，且必须有 memory 来源；`scene_affect:` 与数值关系字段**从未被写**。

### 4.3 检索（`retrieval.py:79` 起）

向量（`$vectorSearch` 192 候选取 24）+ CJK 二元组词法（近 4096 条）→ RRF `1/(60+rank)` → 复核权限、排除已在 12 条尾巴里的来源 → 取前 6。**无衰减、无显著度、无"证据够不够"判定**。

### 4.4 巩固

`MemoryIndexer` 每 2 秒轮询各场景：分块 → 嵌入 → 摘要触发（`memory_indexer.py:34`）。摘要按场景自身节奏触发，带作者归属与更正标注；无摘要的摘要、无合并、无晋升。

### 4.5 markdown 在哪里

- **运行时记忆不在 md 里**。md 只有：prompt（`config/prompts/*.md`）、人格种子、skills、`RUNTIME_API.md`（拷入集成开发目录）。
- **人格正文有三份**：`config/prompts/persona_local.md`、`packages/xiaoman/persona/core.md`（两者逐字节相同）、Mongo `persona:<id>` 头（仅在缺失时种一次，`chat.py:63-64`）。之后包内修改**永远到不了**运行中的头——三份会漂移。
- **对话历史有三份**：Mongo `messages`（权威）、原生会话 JSONL（含每次 MONOLOGUE 前置的整份上下文）、每轮再注入的近 12 条（`context.py:66`）。私聊里同一条消息在原生会话中可能出现十余次。

## 5. 类人能力：有 / 无

| 能力 | 现状 | 证据 |
|---|---|---|
| 内心独白 | **有**，每轮 1–4 句，存为可检索记忆 | `coordinator.py:208` |
| 选择沉默 | **有**，`next=silent`；群聊默认只听 | `coordinator.py:279` |
| 关系理解 | **有**，自由文本、按场景、由角色选择性更新 | `memory.py:28` |
| 自我模型 | **有**，Character Core / Current Self 两层，只在 owner 内部自开发回合可写 | `self_state.py` |
| 自开发 | **有**，改代码/skill、自发布、重启探针回执 | ADR-007，`floor.js` |
| 主动发言 | **部分**：群聊闸门只在有新入站时评估；自排计划；每日自开发机会 | `proactive.py:6`，`schedule.py:111` |
| 情绪 / 心情 | **无**（报告自述"no per-turn emotion model"） | `reporting.py:171` |
| 关系数值 | **无**（字段允许但从未写；反思提示禁止打分） | `state.py:200-202`，`stage_reflect.md` |
| 人物积累档案 | **无**（只有按场景的关系头） | — |
| 记忆淡忘/钉住 | **无** | `retrieval.py` |
| 节律 / 作息 | **无**（只有主动闸门的静默时段） | `proactive.py` |
| 心跳 / 无事时的在场 | **无**（"没有任何定时器会去重开旧话题"） | `proactive.py:6` |
| 夜间消化 / 晋升 | **无** | — |
| 多条发言 / 节奏 | **无**（每回合一条 SPEAK） | `coordinator.py:345` |
| 人格/口吻自我修订 | **无**（人格头只种不改；`overlay:` 只读不写） | `chat.py:63`，`context.py` |

## 6. ADR-008 落地状态

| 要求 | 状态 | 证据 / 缺口 |
|---|---|---|
| 退役 SDK lane、旧 UI、token 代理 | 完成 | 提交删除 `dsh_lane.py`、`provider_proxy.py`、`ui*.py`、`dsh-plugin/**`；`tests/test_native_worker.py` 断言不再导入 |
| 薄启动器 | 完成 | `start-asuna.cmd` → `tools/asuna-launch.mjs` |
| 原生 composer → 作用域阶段 | 完成 | `index.js:260-330` |
| 不嵌套自等 / 单一阶段推进器 | **部分** | JS 不自等；但 `Coordinator.advance` 整体保留，`NativeLane.generate` 阻塞线程（`native_worker.py:82`）；ADR-008 要求拆"准备/消费" |
| 作用域 hook，不影响普通会话 | **基本完成，有一处外溢** | Core 在 Host 作用域挂载 `ScheduleService`（`index.js:62`）；按 DSH 设计 `schedule_*` 工具注册进每个根 agent |
| 行动会话恢复绑定 | 完成 | `index.js:352-358` |
| CONSULT 不死锁 | 部分 | 锁在 consult 前释放（`tasks.py`）；无 JS 测试 |
| 单一 stdio 传输 | 完成 | `worker.js`，`native_worker.py:380-405` |
| worker 失败隔离 / 地板 | 完成 | `index.js:218`，`recovery.js`，`floor.js` |
| 无人格时 Core 惰性 | 完成 | `index.js:55` |
| 两包本地 tgz | 完成 | `tools/pack_plugins.py`、`tools/setup_native_profile.py` |
| Core 不硬编码人格 | **基本**，部署工具仍有默认 | `tools/setup_native_profile.py`、`config/local.example.json`、`config/prompts/persona_local.md` |
| 人格贡献接口 | 部分 | `registerPersona` 无自我/口吻默认、无模型参数 |
| 升级不重置自我 | 完成 | `chat.py:63-64` 仅缺失时种 |
| 记忆右栏 | 完成 | `client.js`，`native_api.py` |
| 设置卡 | 完成但偏离 UI_SPEC | 用 `plugins.bundle.config` + `ctx.remote.settings.mutate`，非 `settings.installSection`；本 ADR 接受此偏离并记录 |
| 原生调度 | 完成，有旧假设 | 一次性 `after_seconds` 重挂；300 秒下限是 0.1.5 时代假设（`schedule_rules.py:25`，`coordinator.py:28`，`stage_decide.md`） |
| 原生压缩 | 完成，但留死路径 | `chat.py:353` 调不存在的 `NativeLane.compact`（仅终端可达） |
| 实机浏览器证据 | 声称完成，仓库无证据 | `NATIVE_PLUGIN.md` 末行 |

## 7. 与 DSH 重复 / 可用未用

**重复**（具体改动见 [DSH_ALIGNMENT.md](DSH_ALIGNMENT.md)）：

1. 回合队列：Python `SceneQueue`/`FairQueue` + 两个轮询线程（`chat.py:81-88`，`router.py:8`）与 JS 阶段队列并存。**本 ADR 不动**（承载跨场景公平与业务回执，替换收益低、风险高）。
2. 工具系统：`ToolBroker` 自带能力闸、幂等、租约；文件工具在自建 WSL bubblewrap 沙箱执行。**本 ADR 不动**（授权语义是业务的），记为后续候选。
3. 委托：`Executor` + 自建 `asuna-action-*` 会话 + 自建 `asuna/action-linked` 显示，未用 `dsh-subagent`。**本 ADR 不动**。
4. 转录：同一内容存于 `messages`、`episodes`、`audit_events` 的 `phase.output`、`lane_receipts`、monologue 记忆，外加历史重复注入。**本 ADR 处理**（D-3、D-4）。
5. 调度：把墙钟规则换算成一次性 `after_seconds` 再重挂；0.2 原生已有 daily/weekly/cron。**本 ADR 处理**（D-5）。
6. 人格注入手工覆写段而非作用域段注册。**本 ADR 处理**（D-1）。

**可用未用**：原生 schedule 的 daily/weekly/cron 与 `schedule_update`（心跳、夜间沉淀）；作用域 `systemPrompt.section` 完整替换与 harness 身份抑制；`agent.inject`（无唤醒地排入上下文）。**DSH 0.2 没有长期记忆包**——Asuna 的 Mongo 记忆层填的是真实空缺，不是重复。

## 8. 遗留代码（摘要）

完整清单与验证方式见 [CLEANUP.md](CLEANUP.md)。要点：

- 终端适配器与依赖：`chat.py:578 terminal()`、`chat.py:623 chat()`、`pyproject.toml` 的 `prompt-toolkit`；以及只为终端存在的 `new_context`（`chat.py:154`）、`compact`（`chat.py:158`，调用不存在的方法 `chat.py:353`）、读旧绑定格式的 `trace`（`chat.py:453`）。
- ADR-001 夹具模式：`task_mode` 被强制为 `workspace`（`host.py:147`，`native_worker.py:143`），使 `tasks.py` 的夹具 `TOOLS`/结果 schema/非工作区执行路径、`router.py:54` 的 `cli-fixture`、`Router.batch`（`router.py:79`）、`Coordinator.recover`（`coordinator.py:361`）不可达。
- **运行时仍依赖设计文档目录**：`config.py:10` 在未打包时把 `BUNDLE` 指向 `docs/development_plans/ADR-001-…`，schema、`executor.md`/`common.md`/`reflect.md`、世界夹具都从那里读。
- `privacy.py:25,48` 读 `sessions.dsh_home`，原生会话行没有此字段 → 擦除命令会 `KeyError`。
- 旧 lane 锁（`native_worker.py:146`）、`floor.js:252` 排除列表里已删除的模块名、`reporting.py:211` 引用不存在的 `dsh-plugin` 目录、ADR-001 验收/实验/评分工具链。

## 9. 隐私与公开就绪发现（只列类别与位置，不列值）

| 类别 | 位置 | 风险 |
|---|---|---|
| 真实平台账号标识出现在 docstring 示例里 | `src/asuna/scene_links.py:9-13` | 个人信息入库 |
| 局域网地址出现在示例配置里 | `config/local.example.json` | 个人信息入库 |
| 主机名、用户名出现在工具里 | `tools/probe_embedding_host.py` | 个人信息入库 |
| 群号出现在文件名里 | `tools/` 下一个以群号命名的检查脚本 | 个人信息入库 |
| owner 所在时区写死为核心默认值 | `src/asuna/schedule_rules.py:24`（及模块头注释） | 位置信息入库；也违反"人格/部署参数不进核心" |
| 人格默认值写在核心部署工具/配置里 | `tools/setup_native_profile.py`、`config/local.example.json`、`config/prompts/persona_local.md` | 违反 R-5 |
| 完整人格正文进入所有行动会话 | `src/asuna/tasks.py:414` | 未来私密段经行动脑外流（含联网工具） |
| harness 身份句未抑制 | `packages/cognition-core/src/index.js`（无抑制调用） | 与人格自述冲突 |
| 规范人物判定不看场景 | `src/asuna/scene_links.py`（`canonical_person_id`） | 若按人物挂档案，owner 在群里说话时会被注入私密档案 |
| 历史设计文档可能含个人标识 | `docs/development_plans/**` | 设计史；只报告，不擅改（owner 决定） |

## 10. 结论

**值得保留并作为地基的**：认知类型分层与 `source_window` 可回读；出口诚实（`RETURNED≠完成`、未投递不算说过、`SENDING→UNKNOWN` 不重发）；CAS 修订账与哈希链审计；A2 跨场景只读与规范人物映射；ADR-007 自开发地板；原生单会话多阶段（每轮 3–4 次调用，前缀可缓存）。

**缺的**：情绪、积累式人物档案、淡忘与钉住、节律与在场、夜间消化、表达质感、人格/口吻的可修订文档层、人格参数化，以及一个明确的隐私可见类。**多出来的**：三份人格、三份历史、全文审计副本、对已退役结构的引用与只为终端存在的路径。
