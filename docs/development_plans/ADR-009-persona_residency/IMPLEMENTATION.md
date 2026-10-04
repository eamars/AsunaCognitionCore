# 分阶段实施与测试

## 0. 通用约定

### 0.1 测试形态

| 标签 | 含义 | 运行方式 |
|---|---|---|
| **[离线]** | 不需要 Mongo，不需要模型。用伪集合，沿用 `tests/*_cases.py` + `tools/*_offline_check.py` 的形式 | `python tools/adr009_offline_check.py [--phase Pn]`（新增，按阶段汇总 PASS/FAIL） |
| **[Mongo]** | 需要 `config/local.json` 指向的 Mongo；数据库名 `asuna_v2_test_*`，测试结束**删除自己创建的库**（现有夹具不清理，P0 一并修正） | `pytest tests/test_adr009_<phase>.py` |
| **[JS]** | 需要先 `npm ci` | `npm run test:native` |
| **[人工]** | 在 Web UI（优先用应用内浏览器）里看到的结果；截图存本地被忽略的 `reports/` | 见 [ACCEPTANCE.md §4](ACCEPTANCE.md#4-人工-web-检查) |

- 所有测试使用合成人格 `demo`（`tests/fixtures/personas/demo/`）。`tests/conftest.py` 中的 `character_id='xiaoman'` 改为 `'demo'`，夹具数据同步改为合成数据。
- 每个阶段**必须带反证**：至少一条测试在改动前的基线上失败、改动后通过，以证明测试确实在测这次改动。做法沿用 `p2_offline_check.py --baseline`。
- 真实模型、真实 QQ、真实人格数据**都不是**任何测试的前提。

### 0.2 每阶段交付

一个或多个提交，加一份阶段报告（格式见 [AGENT_START.md](AGENT_START.md#汇报格式)）。阶段之间可以停下交付，下一阶段不得以"上一阶段没做完"为由扩大范围。

---

## P0 卫生与地基

**目标**：不改变可见行为的前提下，把运行时从设计文档目录里解脱出来，堵上隐私缺口，去掉终端，让核心人格中立，并在核心中建立 `owner_private` 判定。

**范围（文件）**：
- `src/asuna/resources/**`（新）
- `src/asuna/grants.py`（由 `resources.py` 改名）
- `config.py`、`cli.py`
- `packages/cognition-core/runtime-manifest.json`、`tools/pack_plugins.py`
- `tests/fixtures/**`、`tests/conftest.py`
- `chat.py`（删终端）、`pyproject.toml`、`uv.lock`、`AGENTS.md`
- `context.py` / `retrieval.py` / `state.py` / `native_api.py`（会话类与 `owner-private` scope 判定，**此阶段只建判定与过滤，尚无 owner-private 数据**）
- `coordinator.py`（`system_ref`）
- `index.js`（D-1）、`tasks.py`（D-2）
- 新增 `src/asuna/render.py`（此阶段只渲染现有人格头，不做文档层）
- `tools/check_staged_secrets.py`（`--personal`）
- 个人数据与人格名清理（[CLEANUP.md §8–9](CLEANUP.md#8-人格中立化)）

**不做**：文档层、情感、任何新 DECIDE 字段。

**测试**：

| 编号 | 形态 | 判定 |
|---|---|---|
| T0.1 | [离线] | 把 `docs/development_plans` 临时改名后，`import asuna.coordinator, asuna.tasks, asuna.memory, asuna.native_worker` 成功；`pack_plugins.py` 产物中含 `python/asuna/resources/schemas/decision.schema.json` 与全部核心 prompt |
| T0.2 | [离线] | `grep -rn "docs/development_plans" src packages tools/pack_plugins.py` 为 0 |
| T0.3 | [离线] | 会话类真值表：owner 本机场景 → `owner_private`；owner 渠道私聊（规范人物 = owner）→ `owner_private`；owner 在群里发言 → `public`；非 owner 私聊 → `public`；把某个群经 `context_links` 链接到本机场景后，该群回合仍是 `public`；行动脑恒为 `public` |
| T0.4 | [Mongo] | 用 70 KB 合成人格跑一个回合后，`episodes` 文档没有 `system` 全文字段，有 `system_ref{persona_doc_revision, common_sha256, render_sha256}`；文档 BSON ≤ 64 KB |
| T0.5 | [JS] | 角色作用域组装出的系统提示与 worker 渲染结果逐字节相同；不含 harness 身份句（用固定版中该句的实际文本作断言）；普通非 Asuna 会话的系统提示不变（沿用现有隔离测试） |
| T0.6 | [Mongo] | 群场景任务的行动脑系统提示中，不出现合成人格正文中任何一句非 `values` 文本（逐句子串检查）；P2 之前只包含人格显示名 |
| T0.7 | [离线] | 下列三项都满足：① `grep -rnE "def terminal\|def chat\\(\|prompt_toolkit\|prompt-toolkit" src pyproject.toml` 为 0；② `uv lock --check` 通过；③ `AGENTS.md` 含 [CLEANUP.md §7](CLEANUP.md#7-agentsmd-修改) 的新条文 |
| T0.8 | [离线] | 下列三项都满足：① `check_staged_secrets.py --personal` 能在临时文件中命中合成的 ≥7 位 id、`192.168.x.x` 地址和拒绝清单条目，输出只有"文件:行:类别"、不含命中值，退出码 0；② `--all` 在跟踪文件（除 `docs/development_plans`）上无命中；③ `.gitignore` 含 `config/personal-denylist.local.txt` |
| T0.9 | [离线] | `grep -rniE "xiaoman\|小满" src/asuna packages/cognition-core config tools` 为 0；核心 prompt 中不含人格名 |
| T0.10 | [Mongo]+[JS] | 现有测试套件全部通过（只允许按 CLEANUP 规则删改被删模块的专属测试，并在报告中列出） |

**停止条件**：D-1 所需的 DSH 接口名与 [DSH_ALIGNMENT.md §2](DSH_ALIGNMENT.md#2-已核实的-dsh-02-事实) 不符 → 停下来报告。

---

## P1 人格契约 v2、人格模型、政策存储

**目标**：把人格参数从核心中剥离成数据；可以装第二个人格。

**范围**：
- `packages/cognition-core/src/index.js`（`registerPersona` v2：校验并转交 `model`/`seeds`/`jobs`）
- `native_worker.py`（`initialize` 接收模型）
- 新增 `src/asuna/persona_model.py`（schema 校验、生效值解析）、`src/asuna/policy.py`（`PolicyStore`）
- `schedule_rules.py`（删除核心默认时区）
- `tests/fixtures/personas/demo/**`
- `packages/xiaoman/src/index.js`（改用 v2 字段，模型只放中性默认值，**不写入任何人格私有值**）

**测试**：

| 编号 | 形态 | 判定 |
|---|---|---|
| T1.1 | [JS] | 安装 `demo` → Core 就绪；安装 `@asuna/xiaoman` → Core 就绪；不装人格 → Core 惰性并显示原因，Web 外壳正常 |
| T1.2 | [JS]+[离线] | 模型不合 schema → 注册被拒，错误可读，Core 惰性，其他 DSH 会话不受影响 |
| T1.3 | [Mongo] | 政策存储：写入带 `what` 的 `param` 成功并生成修订；`secret`/`counter` 被拒（`POLICY_CLASS_REFUSED`）；缺 `what` 被拒；并发写同一键，一个成功、一个 `STALE` |
| T1.4 | [离线] | 生效值优先级：政策 > 模型默认 > 核心缺省；模型若为 `rhythm.timezone`/`rhythm.sleep_window` 给出默认值，注册被拒 |
| T1.5 | [Mongo] | 装两个人格、选中其一：文档、政策、情感、记忆的读写都带人格 id 过滤，另一人格的数据不可见 |
| T1.6 | [离线] | 未设置 `rhythm.timezone` 时，上下文时钟注明"未设置时区，以 UTC 显示"；`schedule_rules.py` 中不存在缺省时区常量 |

---

## P2 文档层、渲染、WRITE 阶段、人物档案

**目标**：人格、口吻、档案、活账成为可修订的整篇文档，按可见性与预算确定性注入；角色能自己写。

**范围**：
- 新增 `src/asuna/documents.py`（`DocumentStore`）
- `render.py`（完整渲染与预算）
- `context.py`（`dossier`、`ledgers` 块，`ref_index`）
- `coordinator.py`（`write_docs`、`read`、`policy_set`、`rejections`、WRITE 阶段）
- 新增 `resources/prompts/stage_write.md`（中性）
- `resources/schemas/decision.schema.json`（增量见 [examples/decision-delta.schema.json](examples/decision-delta.schema.json)）
- `native_api.py`（记忆右栏显示文档与可见性标签）
- `persona:<id>` 头的转换

**测试**：

| 编号 | 形态 | 判定 |
|---|---|---|
| T2.1 | [Mongo] | 两个写入以同一基修订、同一节并发提交：恰好一个成功，另一个 `STALE`，没有丢失更新 |
| T2.2 | [离线] | 渲染：`public` 会话只含 `public`+`always` 的节；`owner_private` 会话含两类，`public` 节在前；`on_demand`/`never` 节不出现 |
| T2.3 | [离线] | 使渲染超出预算的修改被拒（`PERSONA_RENDER_OVER_BUDGET`，带估算值），头不变；渲染函数在任何输入下都不截断（输入超限时抛错，不返回半截） |
| T2.4 | [Mongo] | 档案注入：owner 私聊 → 前言 `always` 节 + 最近 N 条 `injectable` 条目 + 标题索引；群聊 → 无（除非节被标 `public`+`always`）；行动脑 → 无；未打 `injectable` 的条目在任何会话都不自动注入 |
| T2.5 | [Mongo] | 档案条目不可 `replace_section`（`DOC_OP_NOT_ALLOWED`）；`correction` 追加一节并引用原 `sid`，原条目字节不变 |
| T2.6 | [Mongo] | 用伪 lane：DECIDE 给出 `write_docs` → WRITE 阶段输出正文 → 提交成功，SPEAK 的"程序已提交的结果"含提交摘要；无效意图记入 `rejections`，回合照常 SPEAK；群回合的 `write_docs` 全部被拒（`DOC_WRITE_REQUIRES_OWNER_PRIVATE`） |
| T2.7 | [Mongo] | `next=recall` 加 `read`：可读节原文进入 recall 上下文；`public` 会话读取 `owner_private` 节被拒并记录 |
| T2.8 | [Mongo] | 已有 `persona:<id>` 头、文档缺失时，转换为单节文档（`public`、`always`），渲染与转换前语义等价；之后回合的 manifest 记录文档修订 id 与 `render_sha256` |
| T2.9 | [Mongo] | 种子只在头缺失时导入；包内种子变更后，重启不覆盖；`adopt_seed` 按节合并，冲突节列入报告且不覆盖 |

---

## P3 情感引擎

**目标**：通用情感账本、投影与提交路径，可选的评估路由。

**范围**：
- 新增 `src/asuna/affect.py`（事件、修订、提案、纯函数投影）
- `state.py`（`COLLECTIONS` 增加 `affect_events`、`affect_amendments`、`affect_proposals`，以及索引）
- `context.py`（`affect`、`affect_proposals` 块）
- `coordinator.py`（`affect`、`affect_ops`、`affect_adopt` 闸门）
- 评估路由（`Config.routes.appraiser`、`episode_finished` 后异步）
- worker 方法 `affect.import`（P4 再经数据 API 暴露）
- `native_api.py`（右栏显示当前投影与最近事件）

**测试**：

| 编号 | 形态 | 判定 |
|---|---|---|
| T3.1 | [离线] | 合成夹具（≥30 条事件，覆盖：类型半衰期、事件自带半衰期、缺省半衰期、`open` 挂账、已 `close`、`void`、钳位、活跃度半衰期、带不同时区偏移的时间戳）在 ≥100 个时刻（从最后一条事件起到其后 7 天）上，实现与 [examples/affect_reference.py](examples/affect_reference.py) 的结果误差 < 1e-6 |
| T3.2 | [离线] | `close_mode=from_close` 与 `retroactive` 对同一个已关闭的挂账事件给出不同且符合定义的值；`ts > t` 的事件不计入 |
| T3.3 | [Mongo] | DECIDE `affect` 合法条目被提交，带宿主时间戳、`origin=asuna`、`source_scope`；`ref` 不在 `ref_index` → 拒；`require_cost` 下 `cost` 为空 → 拒；超 `max_delta` → 拒；未知 `kind` → 拒；每种拒绝都不打断回合 |
| T3.4 | [Mongo] | 泄漏测试：在 owner 私聊中提交的事件，其 `why`/`ref`/`who` 字符串在随后的群回合上下文 JSON、群回合系统提示、行动脑提示中都搜不到；群回合只看到 `label` 和 `public` 档位 |
| T3.5 | [离线]+[Mongo] | 代码中没有删除 `affect_events` 的路径（静态检查：对该集合只有 `insert_one`/`find`）；`void` 缺 `why` 被拒；operator 擦除生成 `by=operator` 的 `void` 修订 |
| T3.6 | [Mongo] | 评估路由：用伪路由返回提案 → 提案入库，下一次回合上下文可见；提案 schema 中没有面向台词的字段（schema 断言）；路由超时不影响回合完成时间；过期提案标为 `expired` 并在下一次上下文中明示 |
| T3.7 | [Mongo] | `affect.import` 同一批导入两次，第二次新增 0 条；源中某事件新增 `void` → 生成恰好 1 条修订 |
| T3.8 | [离线] | `bands`/`policy` 规则首个命中生效，并覆盖边界值（等号两侧） |

---

## P4 记忆扩展、人格数据 API、探针、人格作业、权威状态、导出

**目标**：人格能够**自己**完成迁移，以及今后任何新数据源的接入。核心只证明能力，用合成人格端到端走通。

**范围**：
- `memory_units` 新字段（`source_window` 文件形态、`invented`、`salience`、`origin`、`owner-private` scope）
- `retrieval.py`（`owner-private` 过滤；显著度此阶段只记 `ref_count`，排序在 P5）
- 新增 `src/asuna/persona_data.py`（数据 API 与探针）、`src/asuna/persona_jobs.py`（`IntegrationRunner` 的 run-to-completion 形态与 stdio 传输）
- 新工具 `persona_job_run`（只授予带 `development_grant` 的任务）
- 本地配置 `persona_sources` 校验
- 设置卡（源根与状态、运行按钮、报告链接）
- 导出渲染
- `tests/fixtures/personas/demo/jobs/migrate/**`、`tests/fixtures/personas/demo-home/**`

**测试**：

| 编号 | 形态 | 判定 |
|---|---|---|
| T4.1 | [Mongo] | 导入条目带文件 `source_window` 与快照；源文件随后被修改或删除，回读仍逐字节等于导入时那一段 |
| T4.2 | [Mongo] | `owner-private` 记忆单元在 `public` 会话的检索中出现 0 次（向量过滤与词法候选都要测；向量测试在嵌入服务不可用时跳过并注明） |
| T4.3 | [Mongo] | 同一写请求提交两次，第二次为空操作；`dry_run` 后各集合（审计除外）计数不变，返回的计划与随后真实执行的结果一致 |
| T4.4 | [Mongo] | `cohabiting`：源变 + 宿主未改 → 更新；源变 + 宿主已被角色改（头 ≠ `import_base`）→ 冲突报告，不覆盖；只追加类按并集，新居条目不受影响。`cutover`：任何写入返回 `SOURCE_CUTOVER`，计数不变 |
| T4.5 | [离线]+[Mongo] | 作业沙箱：读未授权路径失败；网络访问失败；对另一人格的请求返回 `PERSONA_SCOPE_DENIED`；超时被强杀并报 `error`；`/out` 超限被截止并报 `error` |
| T4.6 | [Mongo] | **端到端合成自迁移**：`demo` 的作业在 `demo-home` 上——① 试运行时报告未登记文件为红，退出码 1；② 补全清单后正式导入；③ 按 `demo` 的私有题库校验：可回答的题，其锚点都出现在 `probe.retrieve(as=owner_private)` 的前 6 中；锚点文件未登记的题判红；超范围的题记为 `NOT_RUN(scope)`，不计入通过；④ 重跑为空操作 |
| T4.7 | [离线] | 导出：目标路径不在仓库工作树内、也未被忽略时，拒绝导出；导出内容不含 `messages`/`episodes`；每节带修订 id 与可见性标注 |
| T4.8 | [Mongo] | `invented=true` 的条目注入时带固定标记；在"共同经历"类问题的检索中出现时，上下文明确标注它不是共同经历 |
| T4.9 | [Mongo] | `persona_job_run` 只出现在带 `development_grant` 的任务工具清单中；群任务、普通私聊任务都没有 |

---

## P5 节律、心跳、夜间沉淀、表达质感、显著度

**范围**：
- `context.py`（`rhythm`、`recent_phrasing`、`coverage`）
- `schedule.py`（`presence`/`settlement` 计划、`schedule_update`）
- `chat.py`/`coordinator.py`（新回合种类与预闸门，`promote`、`pin`）
- `publish.py`/`channels.py`（多段与 `not_before`）
- `retrieval.py`（显著度排序）
- 自开发机会的间隔改由政策提供
- 新增 `resources/prompts/stage_presence.md` 与 `stage_settlement.md`（中性）

**测试**：

| 编号 | 形态 | 判定 |
|---|---|---|
| T5.1 | [离线] | 节律块按 IANA 时区和睡眠窗算出 `in_sleep_window`（含跨午夜窗口）；睡眠窗内普通私聊输入照常进入 DECIDE（没有程序拦截） |
| T5.2 | [Mongo] | 心跳：目标场景忙或在最小间隔内 → 不建回合、lane 调用次数为 0、记一条跳过审计；否则建 `presence` 回合，`silent` 结局合法；`policy_set heartbeat.every_min` 触发 `schedule_update`（伪 schedule 记录调用），不删建；目标场景不是 `owner_private` 时拒绝创建计划 |
| T5.3 | [Mongo] | 沉淀：同一本地日期只执行一次；`promote` 超配额的部分被拒；来源不满足 ≥2 个回合、≥2 个日期的被拒；通过的生成 `memory_unit` 三件套 |
| T5.4 | [Mongo] | 多段：`max_messages=3` 时 SPEAK 切出 3 段 → 出站 `:speak:0..2`；渠道场景的 `not_before` 间隔落在 `[min_gap_s, max_gap_s]`；`claim` 不返回未到时刻的段；第 1 段 `FAILED` 后，第 2、3 段为 `CANCELLED_AFTER_FAILURE`；`max_messages=1` 时行为与改动前逐字节相同 |
| T5.5 | [离线] | `recent_phrasing` 对给定的出站序列给出确定的 4-gram 列表；没有重复时为空 |
| T5.6 | [Mongo] | 权重全 0 时检索排序与改动前的黄金结果完全一致；`pinned` 加权后，被钉单元在相关查询中进入前 6；`coverage_floor` 以上判 `sufficient`，以下判 `insufficient` 且上下文含"证据不足"标注 |
| T5.7 | [离线] | 自开发机会间隔来自政策 `self_development.every_min`；代码中不再有 86400 常量 |

---

## P6 DSH 对齐

**范围**：D-3、D-4、D-5、D-6 与 CONSULT 的 JS 测试（[DSH_ALIGNMENT.md](DSH_ALIGNMENT.md)）。

**测试**：

| 编号 | 形态 | 判定 |
|---|---|---|
| T6.1 | [Mongo] | 历史增量：私聊连续两轮，第二轮 `history` 块不再包含第一轮已给出的行；群里未唤醒的行在下一次唤醒回合中恰好出现一次；压缩代数 +1 后重发完整窗口 |
| T6.2 | [Mongo] | 大于 16 KB 的文档提交后，`audit_events` 中不含其全文，只含 sha 与大小；手工篡改集合中的该文档后，`audit.verify` 报告篡改；`lane_receipts`/`phase.output` 不含全文 |
| T6.3 | [离线] | `every_seconds=60` 通过、59 被拒，三处一致（常量单一来源）；IANA 时区的 `clock` 规则映射为原生 `daily`/`weekly`，星期 0→1、6→7；固定偏移时区走一次性重挂 |
| T6.4 | [JS] | `mount_schedule=false` 时 Asuna 不挂载 Schedule；为 `true` 且 Host 未安装时恰好挂载一次 |
| T6.5 | [JS] | CONSULT：行动工具等待期间，角色会话不持有共享锁；返回值是真实的角色结果 |
| T6.6 | [JS] | 现有 `native-loop.test.js` 与 `publication.test.js` 全部通过 |

---

## P7 协调器拆分与遗留收尾

**范围**：D-8，以及 [CLEANUP.md](CLEANUP.md) 中剩余的删除和条件删除。

**测试**：

| 编号 | 形态 | 判定 |
|---|---|---|
| T7.1 | [Mongo] | 现有崩溃矩阵（`crash_matrix_worker.py`、`crash_worker.py` 及 m 系列）全部通过 |
| T7.2 | [Mongo] | worker 线程池设为 1 时，两个场景的阶段请求交替到达，两边都能完成（不死锁）；任何代码路径都不在 worker 线程上等待 `Future.result()` |
| T7.3 | [离线] | [CLEANUP.md §10](CLEANUP.md#10-完成判据p7-末尾一次性检查) 的全部 grep 为 0；`check_staged_secrets.py --personal --all` 在跟踪文件中（除 `docs/development_plans`）无命中 |
| T7.4 | [Mongo]+[JS]+[人工] | 全套测试通过；`start-asuna.cmd` 启动后完成 [ACCEPTANCE.md §4](ACCEPTANCE.md#4-人工-web-检查) 的人工检查 |

---

## 文档更新（每阶段随代码一起）

- `README.md`、`RUN_ASUNA.md`、`RUNTIME_API.md`、`NATIVE_PLUGIN.md`：只写**现在怎么用**（新的设置项、源根、人格作业、导出），不写开发日记。
- `docs/development_plans/**` 不改（本 ADR 文件夹除外，实施者可以在本文件夹追加 `STATUS.md` 记录各阶段完成情况）。
