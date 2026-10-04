# 分阶段实施与测试

## 0. 通用约定

### 0.1 测试形态

| 标签 | 含义 | 运行方式 |
|---|---|---|
| **[离线]** | 不需要 Mongo、模型或沙箱。用伪集合，沿用 `tests/*_cases.py` + `tools/*_offline_check.py` 的形式 | `python tools/adr009_offline_check.py [--phase Pn]`（新增，按阶段汇总 PASS/FAIL） |
| **[Mongo]** | 需要 Mongo，数据库名 `asuna_v2_test_*`，测试结束**删除自己创建的库**。现有夹具不清理，P0 一并修正 | `pytest tests/test_adr009_<phase>.py` |
| **[JS]** | 需要先 `npm ci` | `npm run test:native` |
| **[沙箱]** | 需要 WSL 与 bubblewrap（`integration.py`、`sandbox.py` 的现有沙箱）。不可用时 **SKIP 并写明原因**，同时必须跑对应的 [离线] 协议替身测试 | `pytest -m sandbox tests/test_adr009_p4.py` |
| **[人工]** | 在 Web UI 中用 `demo` 演示环境（§0.3）看到的结果；截图存本地被忽略的 `reports/` | [ACCEPTANCE.md §4](ACCEPTANCE.md#4-人工-web-检查) |

- 所有测试使用合成人格 `demo`（`tests/fixtures/personas/demo/`）。`tests/conftest.py` 中的 `character_id='xiaoman'` 改为 `'demo'`，夹具数据同步改为合成数据。
- 真实模型、真实 QQ、真实人格数据、真实库**都不是**任何测试的前提。

### 0.2 反证（每阶段至少一条）

测试必须证明它确实在测这次改动：至少一条新测试在改动前的基线上失败，改动后通过。

- [离线]：沿用 `p2_offline_check.py --baseline` 的做法。
- [Mongo]/[JS]：`git worktree add ../asuna-base <阶段起点提交>`，把新测试文件复制过去运行，记录失败输出，然后删除这个工作树。
- 报告中写明哪条测试、在哪个基线、以什么断言失败。

### 0.3 `demo` 演示环境（人工检查与本地冒烟）

- 启动器接受 `--profile <name>` 与 `--config <path>`（或环境变量 `ASUNA_PROFILE`、`ASUNA_CONFIG`）。缺省值仍是现行的 `asuna-native` 与 `config/local.json`。在 P0 中实现。
- 演示配置 `config/demo.local.json`（被忽略）由 `config/demo.example.json`（跟踪的模板）生成：
  - 数据库 `asuna_v2_demo_*`；
  - `chat.persona=demo`；
  - **不配置任何渠道、集成或 QQ 路由**；
  - 模型路由指向 owner 自己的本机模型。
- 演示 profile 只装核心与 `demo` 人格包。**任何人工检查都不得使用真实 profile 或真实库**，除非 owner 事先明确同意。

### 0.4 每阶段交付

每个阶段交付一个或多个提交，加一份阶段报告（格式见 [AGENT_START.md](AGENT_START.md#汇报格式)）。阶段之间可以停下来交付；下一阶段不得以"上一阶段没做完"为由扩大范围。

---

## P0 卫生与地基

**目标**：在不改变可见行为的前提下完成以下几件事：
- 运行时脱离设计文档目录；
- 堵上已知的隐私缺口；
- 删除终端适配器；
- 核心做到人格中立，清理跟踪文件中的个人数据；
- 在核心中建立 `owner_private` 判定；
- 提供演示环境。

**范围（文件）**：
- `src/asuna/resources/**`（新）；`src/asuna/grants.py`（由 `resources.py` 改名）。
- `config.py`、`cli.py`、`packages/cognition-core/runtime-manifest.json`、`tools/pack_plugins.py`（把"准备资源目录"拆成不调用 npm 的函数）。
- `tests/fixtures/**`、`tests/conftest.py`。
- `chat.py`（删终端）、`pyproject.toml`、`uv.lock`、`AGENTS.md`。
- 会话类判定与 `owner-private` scope 过滤：`context.py`、`retrieval.py`、`state.py`、`native_api.py`。此阶段只建判定与过滤，还没有 owner-private 数据。
- `scene_links.py` 与宿主启动：拒绝隐私降级链接（`LINK_PRIVACY_DOWNGRADE`）。
- `coordinator.py`：`system_ref`，以及旧 `system` 字段的读取兼容。
- `index.js`（D-1）、`tasks.py`（D-2，P0 只给人格显示名）。
- 新增 `src/asuna/render.py`：此阶段只渲染现有人格头，不做文档层。
- `schedule_rules.py`：删除核心默认时区。未设置时以 UTC 明示；现有本地配置的 `timezone` 键照常生效。
- 核心 prompt 审读：去掉人格名，去掉指代人格的性别代词（例如 `executor.md` 中的"她"）。
- `tools/check_staged_secrets.py`（`--personal`），以及 `tools/personal_scan_allow.txt`。
- 个人数据与人格名清理（[CLEANUP.md §8–9](CLEANUP.md#8-人格中立化)），包括 `config/group-*` 三个跟踪文件。
- `tools/asuna-launch.mjs`：增加 `--profile`/`--config`；`start-asuna.cmd`/`start-asuna-ui.cmd` 原样转发参数（`%*`）；新增 `config/demo.example.json`。

**不做**：文档层、情感、任何新的 DECIDE 字段。

**测试**：

| 编号 | 形态 | 判定 |
|---|---|---|
| T0.1 | [离线] | 把 `docs/development_plans` 临时改名后，`import asuna.coordinator, asuna.tasks, asuna.memory, asuna.native_worker` 成功；调用 `pack_plugins` 的资源准备函数（不调用 npm），产物目录含 `python/asuna/resources/schemas/decision.schema.json` 与全部核心 prompt |
| T0.2 | [离线] | `git grep -n "docs/development_plans" -- src packages tools/pack_plugins.py` 为 0 |
| T0.3 | [离线] | 会话类真值表：owner 本机场景 → `owner_private`；owner 渠道私聊（规范人物 = owner）→ `owner_private`；owner 在群里发言 → `public`；非 owner 私聊 → `public`。另外：配置一条"群 → owner 本机场景"的链接，启动时被拒（`LINK_PRIVACY_DOWNGRADE`）；"本机场景 ↔ owner 私聊"的链接被接受 |
| T0.4 | [Mongo] | 用 70 KB 合成人格跑一个回合后：`episodes` 文档没有 `system` 全文字段，有 `system_ref{persona_doc_revision, common_sha256, render_sha256}`，文档 BSON ≤ 64 KB；同时，带旧 `system` 字段的在途回合仍能续跑 |
| T0.5 | [JS] | 角色作用域组装出的系统提示与 worker 渲染结果逐字节相同；不含 harness 身份句（断言用固定版中该句的实际文本）；普通非 Asuna 会话的系统提示不变（沿用现有隔离测试） |
| T0.6 | [Mongo] | 群场景任务的行动脑系统提示中，不出现合成人格正文中的任何句子（逐句子串检查）；P0 中只包含人格显示名 |
| T0.7 | [离线] | `git grep -nE "def terminal\|def chat\\(\|prompt_toolkit\|prompt-toolkit" -- src pyproject.toml` 为 0；`uv lock --check` 通过；`AGENTS.md` 含 [CLEANUP.md §7](CLEANUP.md#7-agentsmd-修改) 的新条文 |
| T0.8 | [离线] | ① 用 `--paths` 扫描临时文件，能命中合成的 ≥7 位 id、私有网段地址、拒绝清单条目；输出只有"文件:行:类别"和汇总行，不含命中值；退出码 0。② 带 `personal-scan: ok` 的行和白名单常量不命中。③ `--all` 在跟踪文件上（"只报告"范围除外，本 ADR 文件夹包括在内）为 0 命中。④ `.gitignore` 含 `config/personal-denylist.local.txt` 与 `config/group-*.json` |
| T0.9 | [离线] | `git grep -niE "xiaoman\|小满" -- src/asuna packages/cognition-core config tools` 为 0；核心 prompt 审读清单（报告中逐文件列出）确认没有人格名，也没有指代人格的性别代词 |
| T0.10 | [离线] | 未设置任何时区时，上下文时钟注明"未设置时区，以 UTC 显示"；`schedule_rules.py` 中没有缺省时区常量；设置了现有本地配置 `timezone` 时，行为与改动前相同 |
| T0.11 | [离线] | 启动器以 `--profile asuna-demo --config config/demo.local.json` 解析出的 profile、配置路径和数据库名就是演示值；不带参数时与现行相同 |
| T0.12 | [Mongo]+[JS] | 现有测试套件全部通过。只允许按 CLEANUP 规则删改被删模块的专属测试，并在报告中列出 |

**停止条件**：D-1 所需的 DSH 接口名与 [DSH_ALIGNMENT.md §2](DSH_ALIGNMENT.md#2-已核实的-dsh-02-事实) 不符 → 停下来报告。

---

## P1 人格契约 v2、人格模型、政策存储

**目标**：把人格参数从核心中剥离成数据，并能安装第二个人格。

**范围**：
- `packages/cognition-core/src/index.js`：`registerPersona` v2，校验并转交 `model`/`seeds`/`jobs`，校验 `PERSONA_ID_MISMATCH`。
- `floor.js`：`persona()`/`skillPaths()` 相对已发布产物根解析 `model`、`seeds`、`jobs`、skills，删除写死的 `persona/core.md`（[PERSONA_CONTRACT.md §2.3](PERSONA_CONTRACT.md#23-相对已发布产物解析)）。
- `native_worker.py`：`initialize` 接收模型。
- 新增 `src/asuna/persona_model.py`（schema 校验、生效值解析）、`src/asuna/policy.py`（`PolicyStore`）。
- `tests/fixtures/personas/demo/**`。
- `packages/xiaoman`：改用 v2 字段；模型只放中性默认值，**不写入任何人格私有值或个人数据**；把 `peerDependencies` 改为核心 `0.2.x`。

**测试**：

| 编号 | 形态 | 判定 |
|---|---|---|
| T1.1 | [JS] | 安装 `demo` → Core 就绪；安装 `@asuna/xiaoman` → Core 就绪；不装人格 → Core 惰性并显示原因，Web 外壳正常 |
| T1.2 | [JS]+[离线] | 模型不合 schema、或 `model.persona.id` 与注册 id 不一致 → 注册被拒，错误可读，Core 惰性，其他 DSH 会话不受影响 |
| T1.3 | [Mongo] | 政策存储：写入带 `what` 的 `param` 成功，并生成修订；`secret`/`counter` 被拒（`POLICY_CLASS_REFUSED`）；缺 `what` 被拒；并发写同一键，一个成功，另一个 `BASE_REVISION_STALE` |
| T1.4 | [离线] | 生效值优先级：政策 > 模型默认 > 核心缺省；模型给私有键默认值，或在 `policy_keys` 中声明私有键，注册被拒；时区与自开发间隔对现有本地配置的优先级符合 [PERSONA_CONTRACT.md §3](PERSONA_CONTRACT.md#3-人格模型persona-model) |
| T1.5 | [Mongo] | 装两个人格、选中其一：文档、政策、情感、记忆的读写都带人格 id 过滤，另一个人格的数据不可见 |
| T1.6 | [离线] | 已发布产物根解析：在候选与已发布产物中放两份不同的模型文件，worker 拿到的是已发布那份；`seeds`/`jobs` 路径同理 |

---

## P2 文档层、渲染、WRITE 阶段、人物档案

**目标**：人格、口吻、档案、活账成为可修订的整篇文档，按可见性与预算确定性注入；角色能自己写。

**范围**：
- 新增 `src/asuna/documents.py`（`DocumentStore`，含 `sid` 生成与种子 front-matter）。
- `render.py`（完整渲染、预算、超预算状态）。
- `context.py`（`dossier_from_program`、`ledgers_from_program`、`ref_index`，按召回协议排序）。
- `coordinator.py`（`write_docs`、`read`、`policy_set`、`pin`、`rejections`、WRITE 阶段）。
- 新增 `resources/prompts/stage_write.md`（中性）。
- `resources/schemas/decision.schema.json`（增量见 [examples/decision-delta.schema.json](examples/decision-delta.schema.json)）。
- `tasks.py`（public 价值段）。
- `native_api.py`（记忆右栏显示文档、可见性标签、超预算状态）。
- `persona:<id>` 头的转换（先于种子）。

**测试**：

| 编号 | 形态 | 判定 |
|---|---|---|
| T2.1 | [Mongo] | 两个写入以同一基修订、同一节并发提交：恰好一个成功，另一个 `BASE_REVISION_STALE`，没有丢失更新 |
| T2.2 | [离线] | 渲染：`public` 会话只含 `public`+`always` 的节；`owner_private` 会话两类都含，`public` 节在前；`on_demand`/`never` 节不出现；上下文块顺序符合人格模型的 `recall_protocol.order`，缺省时符合核心缺省顺序 |
| T2.3 | [离线]+[Mongo] | 使 `owner_private` 渲染变大并超预算的修改被拒（`PERSONA_RENDER_OVER_BUDGET`，带估算值），头不变；使渲染变小的修改总被接受；已经超预算时渲染仍然完整（与无预算时逐字节相同）、回合照常完成，状态为红并有审计 |
| T2.4 | [Mongo] | 档案注入：owner 私聊 → 前言 `always` 节 + 最近 N 条 `injectable` 条目（N 取自模型或政策）+ 标题索引；群聊 → 无（除非节被标 `public`+`always`）；行动脑 → 无；未打 `injectable` 的条目在任何会话中都不自动注入 |
| T2.5 | [Mongo] | 档案条目不可 `replace_section`（`DOC_OP_NOT_ALLOWED`）；`correction` 追加一节并引用原 `sid`，原条目字节不变 |
| T2.6 | [Mongo] | 用伪 lane：DECIDE 给出 `write_docs`（`append_section`）→ WRITE 阶段输出正文 → 提交成功，SPEAK 的"程序已提交的结果"含提交摘要；`set_tags`/`adopt_seed` 不产生 WRITE 阶段；无效意图记入 `rejections`，回合照常 SPEAK；群回合的 `write_docs` 全部被拒（`DOC_WRITE_REQUIRES_OWNER_PRIVATE`） |
| T2.7 | [Mongo] | `next=recall` 加 `read`：可读节的原文进入 recall 上下文；`public` 会话读取 `owner_private` 节被拒并记录 |
| T2.8 | [Mongo] | 已有 `persona:<id>` 头、文档缺失、包里也有种子：结果是**转换**，不是种子（文档正文等于旧头正文），且不受预算阻挡；渲染与转换前语义等价；之后回合的 manifest 记录文档修订 id 与 `render_sha256` |
| T2.9 | [Mongo] | 种子只在头与旧头都缺失时导入；包内种子变更后，重启不覆盖；`sid` 生成是确定的（同一文件两次生成结果相同，同名标题加 `-2`）；`adopt_seed` 按 `sid` 合并，冲突节列入报告且不覆盖；front-matter 覆盖生效 |
| T2.10 | [Mongo] | 行动脑系统提示只含 `values` 标签的 `public` 节；`owner_private` 节以及不带 `values` 的 `public` 节都不出现 |

---

## P3 情感引擎

**目标**：通用情感账本、投影与提交路径；可选的评估路由。

**范围**：
- 新增 `src/asuna/affect.py`（事件、修订、提案、纯函数投影）。
- `state.py`：`COLLECTIONS` 增加 `affect_events`、`affect_amendments`、`affect_proposals`，提供专用的只插入写方法，不经 `Store.put` 的替换路径。
- 新迁移 `migrations/003_affect.py` 与索引：
  - `affect_events`：`(persona, ts)`，以及 `(persona, origin, source_identity)` 唯一（部分索引）；
  - `affect_amendments`：`(target)`，以及 `(persona, origin, source_identity)` 唯一（部分索引）；
  - `affect_proposals`：`(persona, status, created_at)`。
- `context.py`：`affect_from_program`、`affect_proposals_from_program`。
- `coordinator.py`：`affect`、`affect_ops`、`affect_adopt` 闸门。
- 评估路由：JS `Config.routes.appraiser`（可选）、原生会话 `asuna-appraiser-<persona>`、`phase=APPRAISE`、`episode_finished` 后异步运行。
- worker 方法 `affect.import`（P4 再经数据 API 暴露）。
- `native_api.py`：右栏显示当前投影与最近事件。

**测试**：

| 编号 | 形态 | 判定 |
|---|---|---|
| T3.1 | [离线] | 用 [examples/affect-events.example.json](examples/affect-events.example.json) 加自建的合成夹具（≥30 条事件，覆盖：类型半衰期、事件自带半衰期、缺省半衰期、挂账、已关闭、作废、钳位、活跃度半衰期、不同时区偏移），在 ≥100 个时刻上，实现与 [examples/affect_reference.py](examples/affect_reference.py) 的结果误差 < 1e-6 |
| T3.2 | [离线] | `close_mode=from_close` 与 `retroactive` 对同一个已关闭的挂账事件给出不同且符合定义的值；`ts > t` 的事件不计入；负半衰期被拒；`kind_floor` 过滤 `top_kinds` |
| T3.3 | [Mongo] | DECIDE `affect` 合法条目被提交，带宿主时间戳、`origin=asuna`、按 §2.2 规则取的 `source_scope`。以下各被拒、且不打断回合：`ref` 不在 `ref_index`；`require_cost` 下 `cost` 为空；超 `max_delta`；未知 `kind` |
| T3.4 | [Mongo] | 泄漏测试：owner 私聊中提交的事件，其 `why`/`ref`/`who` 字符串在随后的群回合上下文 JSON、群回合系统提示、行动脑提示中都搜不到；群回合只看到 `label`、`public` 倾向与 `public` 档位 |
| T3.5 | [离线]+[Mongo] | 静态检查：对 `affect_*` 集合不存在 `delete_*`、`replace_*`、`update_*`、`find_one_and_*` 或经 `Store.put` 的写入；`void` 缺 `why` 被拒；operator 擦除生成 `by=operator` 的 `void` 修订 |
| T3.6 | [Mongo] | 评估路由（伪路由，人为阻塞直到测试放行）：回合在提案返回**之前**就已到达 `COMMITTED`；放行后提案入库，带 `source_scope` 与 `ref_index` 快照，并在下一次回合上下文中按可见性出现；提案 schema 中没有面向台词的字段（schema 断言）；用提案的 `ref` 执行 `accept` 能通过闸门；过期提案标为 `expired`，并在下一次上下文中明示 |
| T3.7 | [Mongo] | `affect.import` 同一批导入两次，第二次新增 0 条；同一 `source_identity` 内容改变 → `EVENT_IMMUTABLE`；源中某事件新增 `void` → 恰好生成 1 条修订；`fix_kind` 不带 `value` 被拒 |
| T3.8 | [离线] | `bands`/`policy` 规则首个命中生效，覆盖等号两侧的边界值 |

---

## P4 记忆扩展、人格数据 API、探针、人格作业、权威状态、导出

**目标**：人格能够**自己**完成迁移，以及今后任何新数据源的接入。核心只证明能力，用合成人格端到端走通。

**范围**：
- `memory_units` 新字段：文件形态的 `source_window`、`invented`、`salience`、`origin`、`persona`、`owner-private` scope，以及唯一部分索引 `(scope_key, origin, source_identity)`。
- `retrieval.py`：`owner-private` 过滤；显著度此阶段只累计 `ref_count`，排序在 P5；`coverage_score`。
- `blobs.py`：支持 `owner-private:<persona>` scope。
- 新增 `src/asuna/persona_data.py`（数据 API 与探针）。
- 新增 `src/asuna/persona_jobs.py`（`IntegrationRunner` 的 run-to-completion 形态与 stdio 传输）。
- 新工具 `persona_job_run`：只授予带 `development_grant` 的任务，返回值按 [PERSONA_CONTRACT.md §7.4](PERSONA_CONTRACT.md#74-触发)。
- 本地配置 `persona_sources` 与 `persona_runtime` 的校验。
- 设置卡：源根与状态、运行按钮、导出按钮、报告链接。
- 导出渲染：worker 方法 `persona.export`。
- `tests/fixtures/personas/demo/jobs/migrate/**`、`tests/fixtures/personas/demo-home/**`。

**测试**：

| 编号 | 形态 | 判定 |
|---|---|---|
| T4.1 | [Mongo] | 导入条目带文件 `source_window` 与快照；源文件随后被修改或删除，回读仍逐字节等于导入时那一段；快照 artifact 的 scope 为 `owner-private:<persona>`，非 operator 读取被拒 |
| T4.2 | [Mongo] | `owner-private` 记忆单元在 `public` 会话的检索中出现 0 次。词法候选必测；向量过滤在嵌入服务不可用时 SKIP 并注明 |
| T4.3 | [Mongo] | 同一写请求提交两次，第二次为空操作；`dry_run` 后各集合（审计除外）计数不变，返回的计划与随后真实执行的结果一致 |
| T4.4 | [Mongo] | `cohabiting`：源变而宿主未改 → 更新；源变而宿主已被角色改（头 ≠ `import_base`）→ 冲突报告，不覆盖；只追加类按并集，新居条目不受影响。`cutover`：任何写入返回 `SOURCE_CUTOVER`，计数不变 |
| T4.5 | [沙箱] | 作业沙箱：读未授权路径失败；网络访问失败；对另一人格的请求返回 `PERSONA_SCOPE_DENIED`；超时被强杀并报 `error`；`/out` 超限被截止并报 `error`。**[离线]替身**：用一个不加沙箱的"直连运行器"跑同一份 stdio 协议用例（请求/响应、报告、退出码），只验证协议，不验证隔离 |
| T4.6 | [沙箱]（不可用时 SKIP，并以 [离线] 替身跑协议部分） | **端到端合成自迁移**：`demo` 的作业在 `demo-home` 上——① 试运行报告未登记文件为红，退出码 1；② 补全清单后正式导入；③ 按 `demo` 的私有题库校验：可回答的题，其锚点都出现在 `probe.retrieve(as=owner_private)` 的前 6 中，锚点文件未登记的题判红，超范围的题记为 `NOT_RUN(scope)`、不计入通过；④ 重跑为空操作 |
| T4.7 | [离线] | 导出：目标路径位于仓库工作树内且未被忽略时，拒绝；位于工作树外，或位于被忽略路径时，接受；导出内容不含 `messages`/`episodes`；每节带修订 id 与可见性标注 |
| T4.8 | [Mongo] | `invented=true` 的条目在检索结果和探针摘录中总是带固定标记 |
| T4.9 | [Mongo] | `persona_job_run` 只出现在带 `development_grant` 的任务工具清单中，群任务、普通私聊任务都没有；它的返回值不含任何摘录字段（对报告中合成摘录文本做子串检查） |
| T4.10 | [Mongo] | `coverage_score`：有向量时取最大相似度，只有词法时取覆盖比例；低于 `coverage_floor` 判 `insufficient`；RRF 分数不参与判定 |
| T4.11 | [Mongo] | 链接与派生数据：owner 私聊中产生的独白、分块和摘要，在任何 `public` 会话（包括配置了合法链接的群）的上下文与检索中出现 0 次 |
| T4.12 | [Mongo] | CONSULT 隐私：群场景任务的 CONSULT 上下文与答复中，没有 owner 私密文档、档案、情感原因或 `owner-private` 记忆的任何片段 |

---

## P5 调度对齐、节律、心跳、夜间沉淀、表达质感、显著度

**范围**：
- **先做 D-5**：60 秒下限、原生 `daily`/`weekly`，以及 `schedule.js` 的 `/schedule/update` 与日志（[DSH_ALIGNMENT.md D-5](DSH_ALIGNMENT.md#d-5-调度60-秒下限与原生规则p5先于心跳)）。
- `context.py`：`rhythm_from_program`、`recent_phrasing_from_program`、`coverage_from_program`。
- `schedule.py`：`presence`/`settlement` 计划、`schedule_update`；自开发间隔的优先级。
- `chat.py`/`coordinator.py`：新的回合种类、预闸门、`promote`、`pin`。
- `publish.py`/`channels.py`：多段发布、`not_before`、崩溃恢复。
- `retrieval.py`：显著度排序。
- 新增 `resources/prompts/stage_presence.md` 与 `stage_settlement.md`（中性）。

**测试**：

| 编号 | 形态 | 判定 |
|---|---|---|
| T5.1 | [离线] | 节律块按 IANA 时区与睡眠窗算出 `in_sleep_window`（含跨午夜窗口）；睡眠窗内的普通私聊输入照常进入 DECIDE，没有程序拦截；`public` 会话缺省不含节律块，`rhythm.public_clock=true` 时只含 `local_time` |
| T5.2 | [Mongo] | 心跳：目标场景忙，或在最小间隔内 → 不建回合、lane 调用次数为 0、记一条跳过审计；否则建 `presence` 回合，`silent` 结局合法；`policy_set heartbeat.every_min` 触发 `/schedule/update`（伪 schedule 记录调用），不删建；目标场景不是 `owner_private` 时拒绝创建计划 |
| T5.3 | [Mongo] | 沉淀：同一本地日期只执行一次；回合在 `internal_scene` 中进行；没有时区时不建计划；`promote` 超出配额的部分被拒；来源不满足 ≥ `min_roots` 个回合、≥ `min_dates` 个日期的被拒；通过的生成 `memory_unit` 三件套，`visibility` 映射到正确的 scope |
| T5.4 | [Mongo] | 多段：`max_messages=3` 时 SPEAK 切出 3 段 → 出站 `:speak:0..2`；渠道场景的 `not_before` 间隔落在 `[min_gap_s, max_gap_s]`；`claim` 不返回未到时刻的段；第 1 段 `FAILED` 后，第 2、3 段为 `CANCELLED_AFTER_FAILURE`。`max_messages=1` 时，对同一伪 lane 输出，出站行集合（文本、`publication_key`、投递状态序列）与改动前相同 |
| T5.5 | [离线] | `recent_phrasing` 对给定的出站序列给出确定的 4-gram 列表；没有重复时为空 |
| T5.6 | [Mongo] | **先在阶段起点**，对固定的合成语料与查询集，记录检索排序的黄金文件（`tests/fixtures/retrieval_golden.json`）。改动后：权重全 0 时排序与黄金文件完全一致；加上 `pinned` 权重后，被钉单元在相关查询中进入前 6 |
| T5.7 | [离线] | 自开发间隔按"政策 > 现有本地配置 > 人格模型 > 1440 分钟"取值；`schedule.py` 中不再有写死的缺省间隔（其他模块的时间换算常量不在此列） |
| T5.8 | [离线]+[JS] | `every_seconds=60` 通过、59 被拒，三处一致（常量只有一个来源）；IANA 时区的 `clock` 规则映射为原生 `daily`/`weekly`，星期 0→1、6→7；固定偏移时区走一次性重挂；`schedule.js` 的 update 写入日志后，对账不会把它误判为删除再创建 |
| T5.9 | [Mongo] | 多段崩溃恢复：在第 1 段发布后注入崩溃，恢复后第 2、3 段按序继续；第 1 段处于 `SENDING` 时，按 `SENDING→UNKNOWN` 处理，后续段被取消 |

---

## P6 DSH 对齐（其余）

**范围**：D-3、D-4（`system_ref` 之外的部分）、D-6，以及 CONSULT 的 JS 测试（[DSH_ALIGNMENT.md](DSH_ALIGNMENT.md)）。

**测试**：

| 编号 | 形态 | 判定 |
|---|---|---|
| T6.1 | [Mongo] | 历史增量：私聊连续两轮，第二轮 `history` 块不再包含第一轮已给出的行；群里未唤醒的行在下一次唤醒回合中恰好出现一次；压缩代数 +1 后重发完整窗口 |
| T6.2 | [Mongo] | 大于 16 KB 的文档提交后，`audit_events` 中不含其全文，只含 sha 与大小；手工篡改集合中的该文档后，`audit.verify` 报告篡改；`lane_receipts`/`phase.output` 不含全文 |
| T6.3 | [JS] | `mount_schedule=false` 时 Asuna 不挂载 Schedule；为 `true` 且 Host 未安装时恰好挂载一次 |
| T6.4 | [JS] | CONSULT：行动工具等待期间，角色会话不持有共享锁；返回值是真实的角色结果 |
| T6.5 | [JS] | 现有 `native-loop.test.js` 与 `publication.test.js` 全部通过 |

---

## P7 协调器拆分与遗留收尾

**范围**：D-8；[CLEANUP.md](CLEANUP.md) 中剩余的删除和条件删除；`system` 字段兼容的删除（确认没有在途旧回合后）；`persona_file` 与 `persona:<id>` 头读取路径的删除。

**测试**：

| 编号 | 形态 | 判定 |
|---|---|---|
| T7.1 | [Mongo] | 现有崩溃矩阵（`crash_matrix_worker.py`、`crash_worker.py` 及 m 系列）全部通过 |
| T7.2 | [Mongo] | worker 线程池设为 1 时，两个场景的阶段请求交替到达，两边都能完成，不死锁；任何代码路径都不在 worker 线程上等待 `Future.result()` |
| T7.3 | [离线] | [CLEANUP.md §10](CLEANUP.md#10-完成判据p7-末尾一次性检查) 的全部检查为 0 |
| T7.4 | [Mongo]+[JS]+[人工] | 全套测试通过；用演示环境（§0.3）完成 [ACCEPTANCE.md §4](ACCEPTANCE.md#4-人工-web-检查) 的人工检查 |

---

## 文档更新（每阶段随代码一起）

- `README.md`、`RUN_ASUNA.md`、`RUNTIME_API.md`、`NATIVE_PLUGIN.md`：只写**现在怎么用**，例如新的设置项、源根、人格作业、导出、演示环境；不写开发日记。
- `docs/development_plans/**` 不改（本文件夹除外）。实施者可以在本文件夹追加 `STATUS.md`，记录各阶段的完成情况。
