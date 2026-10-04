# 记忆方案：一个真相，文件只承载行为

> 回应 owner 的问题："我对记忆系统同时用 md 文件和 MongoDB 不满意。"

## 1. 现状到底是什么

从代码看（证据见 [REVIEW.md §4](REVIEW.md#4-记忆现状)），**运行时记忆已经只在 Mongo 里**。"两套"的感觉来自四个地方：

1. **人格正文三份并存**：核心配置里的 md、人格包里的 md、Mongo 头。md 只在头缺失时种一次，之后各自漂移，没有人知道哪份算数。
2. **人格的旧居全是 md**：人格文档、档案、日志、活账、心情 JSON。按原计划把这些"搬进来"，就会出现"md 一份、Mongo 一份"的双权威。
3. **原生会话 JSONL 是另一份转录**：DSH 自己保存会话日志，里面还反复嵌着上下文 JSON。它看起来像记忆，其实是执行日志。
4. **DSH 没有长期记忆包**：如果把 `AGENTS.md`、skills 这些 md 当作记忆，就会和 Mongo 抢角色。

## 2. 选项

| 选项 | 内容 | 结论 |
|---|---|---|
| A. md 为权威，Mongo 只做索引 | 人格状态写 md（git 可见），Mongo 存向量和元数据 | **拒绝**。CAS、并发、作用域隐私、审计、按节可见性都要在文件上重造；群回合与私聊回合同时写同一文件会冲突；个人数据进了工作树，容易被提交 |
| B. **Mongo 为权威，md 只作种子与导出** | 一切状态是 Mongo 修订记录；md 只在导入（种子、迁移）或导出（备份、阅读）时出现 | **采纳** |
| C. 双写同步 | md 和 Mongo 互相同步 | **拒绝**。永远有冲突窗口；"谁赢"无法定义 |

## 3. 决定：文件存行为，Mongo 存状态

| 数据 | 归属 | 载体 | 说明 |
|---|---|---|---|
| 核心 prompt（中性） | 行为 | 核心包文件 | 随核心发布 |
| 人格 prompt 片段、skills、集成、人格作业、解析器 | 行为 | 人格包文件 | 随 `development_publish` 发布 |
| 人格模型的**公开默认值** | 行为（默认值） | 人格包 JSON | 私有覆盖写进 `policy:<persona>` |
| 人格、口吻、档案、活账、工作文档、验收合约 | **状态** | `doc:<persona>:<slug>` | 包内 md 只作种子 |
| 情感 | **状态** | `affect_events` + 修订 + 提案 | — |
| 自我（Core/Self）、关系 | **状态** | 现有修订头 | 不变 |
| 情节记忆：聊天分块、独白、摘要、导入条目、晋升单元 | **状态** | `memory_units` | 新增字段见 §5 |
| 政策参数 | **状态** | `policy:<persona>` | "数字只在一处" |
| 原始消息、回合、任务、计划、回执、审计 | **状态（记录）** | 现有集合 | 不变 |
| 原生会话 JSONL | **执行日志** | DSH_HOME | **永远不是记忆权威**；只用于原生显示与恢复 |
| 导入源文件快照 | **证据** | `artifacts` + GridFS | 支撑 `source_window` 回读 |
| md 导出 | **派生物** | owner 本地指定目录 | 只读渲染，带修订 id；不回流 |

一句话：**角色学到的、感到的、记得的、答应的、决定的，都在 Mongo；告诉程序和模型"怎么做"的，才是文件。**

## 4. 状态分层与读取方式

| 层 | 内容 | 怎样进入上下文 |
|---|---|---|
| 文档层 | 人格、口吻、档案、活账、工作文档、合约 | **确定性注入**（按 `inject` 和可见性），或按需读取；**不靠检索** |
| 情感层 | 事件、修订、提案 | 确定性投影 |
| 自我/关系层 | Core、Self、关系头 | 现有注入 |
| 情节层 | `memory_units` | 检索（RRF + 显著度 + 证据判定） |
| 记录层 | 消息、回合、任务、审计 | 历史增量；工具查询（现有 `history_query`/`discussion_digest`） |

"我是谁、对方是谁、我现在什么心情"这类**必须召回**的东西不交给检索去碰运气，一律走确定性注入；检索只负责"被话题勾起来的往事"。

## 5. 情节层扩展（`memory_units` 新字段）

| 字段 | 含义 |
|---|---|
| `kind` 新值 `imported_entry` | 人格作业导入的条目；`entry_type` 由人格定义，例如日志条目、共同史条目 |
| `kind` 新值 `memory_unit` | 夜间沉淀晋升的三件套：`fact`、`appraisal`、`signal`（"下次怎么对这个人"） |
| `source_window` 扩展 | 对话来源保持现状；文件来源为 `{origin, path, file_sha256, line_from, line_to, heading}` |
| `invented` | `true` 表示人格自述编写、并非共同经历。注入时附固定标记，回答"我们一起……"类问题时不得当证据 |
| `salience` | `{pinned: bool, ref_count: int, last_ref_at: ts}`；`ref_count` 由 `retrieval.selected` 审计累加 |
| `scope_key` 新值 | `owner-private:<persona>` |
| `origin` | `asuna` 或源根 id |

### 5.1 检索排序

```text
score = RRF(向量, 词法)                               # 现状
      + w_pin  · pinned
      + w_heat · log(1 + ref_count)
      − w_age  · age_days / half_life_days
```

权重全部来自政策参数，核心缺省全为 0，排序与现状完全一致（有黄金测试保证）。

### 5.2 证据判定（coverage）

检索结果附 `coverage ∈ {sufficient, insufficient}`：最高分低于 `memory.coverage_floor`（缺省为 0，即永远 sufficient），或候选为空时，判为 `insufficient`。判为 `insufficient` 时，上下文明确告诉角色：**"证据不足，只能当灵感，不能当事实说。"**

### 5.3 淡忘与钉住

- **不删除**。淡忘只体现在排序。
- 角色可以在 DECIDE 中 `pin`/`unpin`（≤3，`owner_private` 回合）。
- 要让旧而重要的东西一直在场，应写进文档层（档案、人格、活账），由角色主动把它"钉进正文"，不靠系统硬留。

## 6. 权威与生命周期（导入、同居、切换、导出）

### 6.1 生命周期

```text
种子(seed) ──▶ 导入(import, 源根 cohabiting) ──▶ 切换(cutover) ──▶ 导出(export, 只读)
     │              │  源文件可继续变（旧居还活着）       │  源文件再变 = RED，不写
     │              │  按 sha256 增量、按 origin 幂等     │  宿主为唯一权威
     ▼              ▼                                    ▼
  头缺失时一次   新居写入另记 origin=asuna，不碰导入条目   人格可选择把导出写回她的备份仓
```

### 6.2 冲突规则

| 情形 | 处理 |
|---|---|
| `cohabiting`，源文件变了，宿主中对应实体自导入后**没动过** | 按源更新，生成新修订，`author=persona_job` |
| `cohabiting`，源文件变了，宿主中对应文档**已被角色改过**（头修订 ≠ `import_base`） | **不覆盖**；产生冲突报告（RED），列出双方差异；由人格决定 |
| `cohabiting`，只追加类数据（情感事件、日志条目、档案条目） | 按 `origin + source_identity` 求并集；新居事件 `origin=asuna`，互不覆盖 |
| `cutover` 后源文件变了 | RED（`SOURCE_CUTOVER`），一条不写 |
| 同一请求重复提交 | 按 `origin + source_identity + content_sha256` 幂等，第二次为空操作 |

权威状态由 owner 在本地配置中切换（见 [PERSONA_CONTRACT.md §6](PERSONA_CONTRACT.md#6-源根与权威状态)）。**"搬家日 ≠ 记忆冻结日"**：`cohabiting` 期间旧居照常生活，增量随时可以同步。

### 6.3 回读

导入时，把源文件快照按 `file_sha256` 存进 `artifacts`/GridFS（同一 sha 只存一份）。之后即使源文件移动或修改，`source_window` 仍能逐字节回读当时的原文。

## 7. 写入量与去重

| 问题 | 处理 |
|---|---|
| episode 存完整 `system` 与 `context`，一轮改写 6–8 次 | 改存 `system_ref`；`context` 只存块 id、修订 id 和选中的 id（D-4） |
| `state.commit` 审计复制整份文档 | 大文档改存内容 sha256 与大小；内容以集合中的修订为准，哈希链仍可检测篡改（D-4） |
| `lane_receipts`、`phase.output` 存全文 | 改存引用和 sha256（D-4） |
| 历史在原生会话中重复十余次 | 按会话与来源场景的高水位只注入增量；压缩代数变化时重置（D-3） |

## 8. 备份与导出

- 导出是**派生物**：把文档层渲染成 md，每节带修订 id 和可见性标注。**不导出**原始消息和回合。
- 导出目标路径只能来自 owner 本地配置，并且必须**位于本仓库工作树之外**，或者是被 `.gitignore` 忽略的路径（R-7）。
- 人格若想把导出写回自己的私有备份仓，用人格作业自己完成。核心只提供渲染。

## 9. 现有数据如何过渡

- 不改现有集合的既有字段；新增字段缺省为空或 0。
- `persona:<id>` 头转成 `doc:<persona>:persona`（见 [ARCHITECTURE.md §5.4](ARCHITECTURE.md#54-与现有自我状态的关系)）。
- 删除 `config/prompts/persona_local.md`；人格包 `persona/core.md` 改为 `seeds/persona.md`。
- 向量嵌入沿用现有 `MemoryIndexer`。首次大批导入会积压上千条待嵌入，**必须分批**（沿用 `index_pending(batch_size)`），并在作业报告中显示进度。

## 10. 不做的事

- 不引入第二个数据库或向量库。
- 不写 md 与 Mongo 的同步守护进程。
- 不把原生会话 JSONL 当记忆来源。
- 不把记忆写进 `AGENTS.md` 或 skills。
- 不自动摘要文档层内容。摘要只存在于情节层，并且必须带 `source_window`。
