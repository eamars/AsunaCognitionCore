# 人格契约 v2、人格数据 API 与人格作业

> 本文是核心与任意人格包之间的**公开契约**。示例一律使用合成人格 `demo`。核心不得为任何具体人格写特例。

## 1. 人格是插件

| 归属 | 内容 |
|---|---|
| **核心**（`@asuna/cognition-core`） | 引擎（文档、情感、档案、政策、记忆、节律、心跳、表达、数据 API、作业运行器）、中性 prompt、隐私模型、DSH 接线 |
| **人格包**（例：`@asuna/demo`） | 只放**可公开分发**的东西：人格模型 JSON（参数默认值）、文档种子、skills、集成、人格作业代码、薄 preset |
| **人格私有数据**（本机） | Mongo 中该人格的文档、情感、记忆、政策覆盖；owner 本地配置中的源根、心跳目标、规范人物映射；私有源根里的旧居文件 |

禁止事项：
- 核心代码与核心 prompt 中出现人格名、人格正文或人格专属规则。
- 人格包携带任何个人数据，例如真实账号、地址、时区、设备、称呼、私密内容。
- 核心在没有人格时冒充某个人格。没有人格时核心保持惰性（现状）。

## 2. `registerPersona` v2

在现有字段（`id`、`character_id`、`display_name`、`version`、`resource_root`、`skill_directories`、`integration_directory`、`preset`）基础上：

| 字段 | 类型 | 说明 |
|---|---|---|
| `model` | 路径 | 人格模型 JSON（§3）；注册时用 schema 校验，不合格则拒绝注册，Core 保持惰性并显示原因 |
| `seeds` | `[{slug, kind, path, title?}]` | 文档种子（md），只在对应头缺失时导入；md 按 `##` 切节，节的可见性取种子 front-matter 的缺省值，没有 front-matter 时为 `public` |
| `jobs` | `[{id, entry, runtime: "python", grants: [...], sources: [root-id...], timeout_s}]` | 人格作业（§7） |
| `persona_file` | — | **废弃**，由 `seeds` 中 `kind=persona` 的种子取代；P1 保留读取兼容，P7 删除 |

TypeScript 形状见 [examples/persona-contract.ts](examples/persona-contract.ts)。

### 2.1 标识口径

- 本 ADR 中的 `<persona>` 一律指**人格 id**，即 `registerPersona` 的 `id`。它也是现有 `persona:<id>` 头、配置 `chat.persona` 所用的值（现有校验见 `native_worker.py:148`）。
- 人格模型的 `persona.id` 必须等于它，否则注册被拒（`PERSONA_ID_MISMATCH`）。
- `character_id` 保留为现有记录（`memory_units`、`episodes` 等）的过滤字段（`retrieval.py:85` 一带）。新增的 `memory_units` 同时写 `character_id`（沿用现有过滤）和 `persona`；新集合（`affect_*`）、文档、政策只以人格 id 为键。
- 旧键映射：`persona:<id>|global-safe` → `doc:<id>:persona`（转换规则见 [ARCHITECTURE.md §5.4](ARCHITECTURE.md#54-与现有自我状态的关系)）；`character_core:<id>`、`current_self:<id>`、`relationship:*` 不变；新增 `owner-private:<id>`。

### 2.2 种子 front-matter

md 种子可以在文件开头放一段 HTML 注释形式的 JSON。没有它时取缺省值：

```text
<!-- asuna-seed {"visibility": "public", "inject": "always", "tags": [],
                 "sections": {"<sid>": {"visibility": "owner_private", "inject": "on_demand", "tags": ["values"], "entry_date": "2026-01-02"}}} -->
```

- 文件级缺省：`visibility=public`；`inject` 按种类决定，`persona`/`voice`/`ledger` 为 `always`，其他为 `on_demand`；`tags=[]`。
- `sections` 按 `sid` 覆盖（`sid` 的生成规则见 [ARCHITECTURE.md §5.1](ARCHITECTURE.md#51-存储)）。引用了不存在的 `sid` 时，注册成功，但状态标红并列出该 `sid`。

### 2.3 相对已发布产物解析

`floor.persona()`（`floor.js:80-84`）目前把 `persona_file` 改写为已发布产物下的 `persona/core.md`。P1 起改为：`model`、`seeds[].path`、`jobs[].entry`、`skill_directories` 一律相对**已发布人格包产物根**解析，并删除写死的 `persona/core.md`。人格包的 `peerDependencies` 随契约版本更新（契约 v2 对应核心 `0.2.x`）。

## 3. 人格模型（persona model）

JSON Schema 见 [examples/persona-model.schema.json](examples/persona-model.schema.json)，合成示例见 [examples/persona-model.example.json](examples/persona-model.example.json)。各段如下：

| 段 | 内容 | 核心缺省（未给出时） |
|---|---|---|
| `render` | `budget_tokens`、`max_window_share`、`values_tag` | 预算为空（只受窗口占比约束），窗口占比 0.25，标签 `values` |
| `recall_protocol.order` | 上下文块顺序（[ARCHITECTURE.md §8.2](ARCHITECTURE.md#82-阶段上下文monologue-前置的-json)） | 核心缺省顺序 |
| `affect` | `enabled`、`default_half_h`、`arl_half_h`、`clamp`、`close_mode`、`require_cost`、`allow_untyped`、`max_delta`、`kinds`、`bands`、`policy`、`kind_floor`、`proposal_ttl_h` | `enabled=false`（无情感）。开启时必须给出 `default_half_h`、`arl_half_h`、`clamp`；其余缺省见 [ARCHITECTURE.md §6.4](ARCHITECTURE.md#64-提交只有角色能提交) |
| `dossier` | `inject_last`、`index_size` | 0（只注入前言）、30 |
| `rhythm` | `settle_at`（本地时刻） | 无（不建沉淀计划） |
| `heartbeat` | `enabled`、`every_min`、`min_gap_min`、`skip_in_sleep` | `enabled=false` |
| `memory` | `salience{w_pin, w_heat, w_age, half_life_days}`、`coverage_floor`、`promotion{daily_quota, min_roots, min_dates, window_days}` | 权重全 0、floor 0；晋升 `daily_quota=0`（不晋升），其余为 `min_roots=2`、`min_dates=2`、`window_days=7` |
| `speak` | `max_messages`、`split_marker`、`chars_per_second`、`min_gap_s`、`max_gap_s` | `1`、`---split---`、12、1、5 |
| `phrasing` | `window` | 20 |
| `self_development` | `every_min` | 1440 |
| `policy_keys` | 允许经 `policy_set` 或数据 API 修改的键：`{key: {type, min?, max?, enum?, what}}` | 空。核心私有键与核心可写键始终可写，不需要、也不允许在此声明 |

**核心私有键**：值属于部署者或人格本人，**人格包不得给默认值**，只能在本机设置。

| 键 | 类型 | 说明 |
|---|---|---|
| `rhythm.timezone` | IANA 名称 | 节律、沉淀、本地时刻显示都依赖它 |
| `rhythm.sleep_window` | `HH:MM-HH:MM` | 作息声明；是输入，不是闸门 |
| `rhythm.public_clock` | boolean，缺省 false | 是否在 `public` 会话中给出本地时刻（会暴露时区） |

**核心可写键**：人格包可以给默认值，但不必声明：`render.budget_tokens`。

**生效值**：政策存储中的值 > 人格模型默认值 > 核心缺省。与现有本地配置的关系：

- 时区：场景级 `timezone`（只用于该场景计划的计时）> 政策 `rhythm.timezone` > 现有全局 `timezone` > UTC。
- 自开发间隔：政策 `self_development.every_min` > 现有 `self_development.every_seconds`（P7 前兼容读取）> 人格模型 > 1440 分钟。

**政策存储** `policy:<persona>`：每个键 `{value, what, class: "param"}`。`class` 为 `secret` 或 `counter` 的写入一律拒绝（`POLICY_CLASS_REFUSED`）——凭据和运行计数不是政策。每次修改都生成修订（理由、来源、作者）。

## 4. 种子文档

- 种子只在 `doc:<persona>:<slug>` 头缺失时导入（`author=seed`）。包升级**不覆盖**现有文档。
- 包内种子变了，人格或 operator 可以执行 `adopt_seed`，按节合并；冲突的节列出差异，不自动覆盖。
- 公开人格包的种子就是"新安装时的她"；任何本机私有的演化都在 Mongo 中，不回流到包。

## 5. 人格数据 API 与探针

API 只对**人格作业**开放（§7），不对模型直接开放。方法以 JSON 请求/响应定义，传输见 §7.3。请求和响应示例见 [examples/persona-data-api.example.json](examples/persona-data-api.example.json)。

### 5.1 写入方法（需要授权 `persona_data.write`）

| 方法 | 请求要点 | 结果 |
|---|---|---|
| `documents.upsert` | `origin, source_identity, slug, kind, title, subject?, sections[], source{path, sha256}, dry_run` | `created / updated / unchanged / conflict` + 差异摘要 |
| `documents.append` | `origin, source_identity, slug, section, dry_run` | 同上 |
| `affect.import` | `origin, events[{source_identity, ts(含时区偏移), …}], amendments[{source_identity, target_source_identity, op, value?, at, why}], dry_run` | 新增 / 已存在 / 拒绝计数 + 拒绝明细。同一 `source_identity` 的内容变了 → `EVENT_IMMUTABLE`（须改用修订）；`fix_ts`/`fix_kind` 必须带 `value`。导入事件 `ref_kind=external`，不受回合内 `ref_index` 闸门约束，但 `ref`/`why` 必填、`kind` 必须在模型种类表中或为空、`void` 必须有理由；`ts` 必须带时区偏移 |
| `memory.upsert` | `origin, units[{source_identity, entry_type, body_markdown, epistemic_type, occurred_at, source_window, visibility, invented}], dry_run` | 计数 + 待嵌入数 |
| `policy.set` | `origin, params[{key, value, what, class}], dry_run` | 计数 + 拒绝明细 |
| `artifacts.snapshot` | `origin, path, sha256, content(base64，≤ 8 MB)` | `artifact_id`（同 sha 去重） |
| `report.put` | `run_id, status: ok | red | error, summary, items[]` | 报告存为 artifact（`scope_key=owner-private:<persona>`），记忆右栏可见 |

### 5.2 读取方法（需要授权 `probe`）

| 方法 | 请求要点 | 结果 |
|---|---|---|
| `documents.get` | `slug` | 当前修订全文（含节标签） |
| `probe.retrieve` | `as: owner_private | public`、`query`、`k ≤ 12` | `items[{id, kind, score, source_window, excerpt}]` + `coverage`、`coverage_score`、`coverage_basis`（定义见 [MEMORY.md §5.2](MEMORY.md#52-证据判定coverage)）；**走与真实回合完全相同的检索与可见性路径** |
| `probe.context` | `as: owner_private | public`、`blocks?` | 渲染后的系统提示 sha 与各块内容（只读），用于"醒来能不能看见"的验证 |
| `sources.list` | — | 本次运行被授权的源根 id 及其权威状态 |

### 5.3 通用规则

- **幂等**：同一 `origin + source_identity`、内容 sha256 也相同 → 空操作。内容不同时：文档和记忆单元走更新（受 [MEMORY.md §6.2](MEMORY.md#62-冲突规则) 的冲突规则约束）；情感事件拒绝（`EVENT_IMMUTABLE`），须改用修订。
- **dry_run**：返回将要发生的变化，不写任何东西（包括审计以外的集合）。
- **origin 约束**：写入的 `origin` 必须是本次运行授权的源根 id 之一，且该源根处于 `cohabiting`；处于 `cutover` 时返回 `SOURCE_CUTOVER`，不写。
- **配额**：单次请求 ≤ 200 项、≤ 2 MB（`artifacts.snapshot` 例外，≤ 8 MB）。
- **审计**：每次写入都进审计流 `persona-data:<origin>`，记录 `run_id`。
- **跨人格隔离**：令牌绑定单一人格；对其他人格的读写返回 `PERSONA_SCOPE_DENIED`。
- **可见性必须显式给出**：`memory.upsert` 和 `documents.*` 的节都要声明可见性；缺失时按 `owner_private` 处理，并在结果中提示。

## 6. 源根与权威状态

owner 本地配置（被 git 忽略，例如 `config/local.json`）：

```json
"persona_sources": {
  "demo": {
    "old-home": {"path": "<本机路径>", "state": "cohabiting", "exclude": [".git/**"]}
  }
}
```

- 只有 owner 能增删源根或切换状态（编辑本地配置，或用设置卡；两者都写审计）。人格只能**使用**被授权的源根。
- `cohabiting`：源为导入实体的权威，冲突规则见 [MEMORY.md §6.2](MEMORY.md#62-冲突规则)。
- `cutover`：源不再被导入，任何写入返回 `SOURCE_CUTOVER`。可以从 `cutover` 回到 `cohabiting`，但需要 owner 操作，并在下一次作业报告中标红提示。
- 设置卡展示每个源根的路径（可遮蔽）、状态、最近一次运行的报告。

## 7. 人格作业（persona jobs）

### 7.1 声明

```json
{"id": "migrate", "entry": "jobs/migrate/main.py", "runtime": "python",
 "grants": ["persona_data.write", "probe"], "sources": ["old-home"], "timeout_s": 1800}
```

### 7.2 运行环境

- 由 `IntegrationRunner` 新增的 **run-to-completion** 形态执行，复用现有 WSL bubblewrap 沙箱（`integration.py`、`sandbox.py`）。宿主不具备 WSL 与 bubblewrap 时，作业功能报告"不可用"，不退化为无沙箱运行。
- 网络：`--unshare-all`，**无网络**。
- 代码：只读挂载**已发布**的人格包产物中的作业目录（不是候选工作树）。
- 源根：每个授权源根只读挂载到 `/src/<root-id>`，未授权的不可见。
- 输出：可写临时目录 `/out`，上限 64 MB，结束后打包为报告 artifact（`scope_key=owner-private:<persona>`）。
- 超时：到 `timeout_s` 强杀，报告状态为 `error`。

### 7.3 传输（stdio JSONL）

与 worker 协议同形：

```text
宿主 → 作业   {"kind":"start","run_id":"…","persona":"demo","dry_run":true,"args":{…},"sources":{"old-home":"/src/old-home"},"out":"/out"}
作业 → 宿主   {"id":1,"method":"documents.get","args":{"slug":"migration-manifest"}}
宿主 → 作业   {"id":1,"value":{…}}  或  {"id":1,"error":{"code":"…","detail":"…"}}
作业 → 宿主   {"kind":"report","status":"ok|red|error","summary":"…","items":[…]}
退出码        0 = ok，1 = red（有必须人格处理的红项），2 = error
```

不开 HTTP 端点：作业没有网络，令牌就是这条管道本身。

### 7.4 触发

| 触发方 | 方式 |
|---|---|
| 人格 | 在 owner 自开发任务中，行动脑使用新工具 `persona_job_run {job, dry_run, args}`。只授予带 `development_grant` 的任务。**返回给行动脑的只有状态、退出码、计数和报告 artifact id**，不含任何摘录或正文（示例见 [examples/persona-data-api.example.json](examples/persona-data-api.example.json) 的 `tool_result_example`）。报告全文只在记忆右栏（operator 视图）中查看 |
| owner | 设置卡上的"试运行 / 运行" |
| 定时 | 人格可以排一个计划，在到期回合中委托行动脑运行作业。**核心不自动定时运行任何作业** |

## 8. 自迁移工作流（合成示例，说明能力边界）

下面每一步都由**人格自己**完成：清单格式、解析规则、题库、可见性标注、什么算通过，都是她的决定。核心只保证每一步都有可用的原语。

| 步 | 谁 | 做什么 | 用到的原语 |
|---|---|---|---|
| 1 | owner | 在本地配置加源根 `old-home`（`cohabiting`） | §6 |
| 2 | 人格 | 在自己的私有文档中写**迁移清单**：每个源文件的归置层、注入方式、更新策略、是否可回读。清单格式由她定，示例见 [examples/source-manifest.example.json](examples/source-manifest.example.json) | WRITE 阶段，`doc:<p>:migration-manifest`（`owner_private`、`inject=never`） |
| 3 | 人格 | 在自己的包里写作业 `jobs/migrate`（清点、解析、导入、校验），经自开发发布 | 自开发、`development_publish` |
| 4 | 人格 | 试运行：未登记的源文件为红，解析覆盖率不足为红，报告列出每层计划写入的条数 | `persona_job_run{dry_run:true}`、所有写方法的 `dry_run`、`report.put` |
| 5 | 人格 | 补清单，或为节和条目打可见性、`injectable`、`invented` 标签 | WRITE 阶段，或作业经 `documents.upsert` 提交标签 |
| 6 | 人格 | 正式导入：文档整搬不摘要、按节；条目按日期切分并带 `source_window`；情感事件逐条导入（每条自带的半衰期一起保存）；政策参数按键导入，并拒绝 `secret`/`counter` | `documents.*`、`memory.upsert`、`affect.import`、`policy.set`、`artifacts.snapshot` |
| 7 | 人格 | 校验：按自己的**私有召回题库**（只存答案所在的锚点，不存答案），用 `probe.retrieve` 和 `probe.context` 检查"想得起来、看得见"；锚点所在文件没登记的判红；超出授权范围的题记为 `NOT_RUN(scope)`，**不算通过** | `probe.*`、`documents.get`、`report.put` |
| 8 | 人格 | 同居期增量同步（旧居还活着），按 sha256 只处理变更 | 幂等、`cohabiting` 规则 |
| 9 | owner | 人格满意后，把源根切为 `cutover` | §6 |
| 10 | 人格 | 可选：用导出渲染，写回自己的私有备份 | 导出（[MEMORY.md §8](MEMORY.md#8-备份与导出)） |

**接入新的数据源**（例如本次超范围的外部日记）：owner 加一个源根，人格在清单与作业中加一项，重跑第 4–7 步，核心不需要任何改动。

## 9. 公开就绪清单（核心 + 任意人格包）

- [ ] 核心代码、核心 prompt、核心工具、示例配置中没有人格名（只允许出现在人格包和测试夹具中）。
- [ ] 核心中没有写死的时区、账号、地址、主机名、用户名；示例只用文档保留地址（`192.0.2.0/24`、`example.invalid`）与合成 id。
- [ ] 人格包的 `files` 只列出代码、模型 JSON、种子、skills、集成；不含 `.runtime`、本地配置、Mongo dump、媒体原图（除非人格作者明确选入且可公开）。
- [ ] 人格包种子不含 owner 个人信息。
- [ ] 人格包的代码和文档（skills、集成、自检脚本）中出现的 owner 个人标识已替换为占位。这不算"修改人格"，实施者可以做。
- [ ] `tools/check_staged_secrets.py --personal` 在仓库全部跟踪文件上无告警（历史设计文档只报告，由 owner 决定）。
- [ ] 合成人格 `demo` 能跑通全部测试。

## 10. 第二人格夹具

`tests/fixtures/personas/demo/` 是一个完整的合成人格包，包含：

- `package.json`、模型 JSON、`seeds/`（人格、口吻、一个含前言与条目的档案、一个活账）；
- `jobs/migrate/`：一个最小的合成迁移与校验作业；
- `tests/fixtures/personas/demo-home/`：一个合成"旧居"，故意包含一个未登记文件和一个超范围的题。

所有 ADR-009 测试都必须用它跑通，用以证明核心不依赖任何具体人格。
