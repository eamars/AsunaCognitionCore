# 目标架构

> 本文定义**核心**要提供什么。凡写"人格模型参数"处，取值属于人格包或人格私有数据，不进核心。示例只用合成人格 `demo`。

## 0. "像真人"的可观察判据

不评"像不像"，只看下面这些能力是否真实存在、可审计：

| 判据 | 可观察证据 |
|---|---|
| 有情绪，情绪有来由、会过去、没解决的会挂着 | 情感账本条目带 `ref`；投影随时间按参数衰减；`open` 事件不衰减 |
| 情绪改变行为，但不替她说台词 | 投影给出档位、倾向和行为档位；SPEAK 输入里没有任何情感模块写的句子 |
| 记得人，而且越处越厚 | 人物档案只追加；最近条目被注入；可按需读取全文 |
| 会忘，也会钉住 | 检索排序含显著度；角色可钉住；证据不足时明确标出 |
| 会主动，也会沉默 | 心跳/沉淀回合存在；大多数心跳以 `silent` 结束也算正常 |
| 有作息，作息是理由不是开关 | 上下文有节律块；普通回复不因睡眠窗被程序拦截 |
| 会成长，且成长有版本 | 人格/口吻/档案/政策的每次修改都有修订、理由、来源 |
| 能做事 | 委托行动脑、自开发、人格作业都可用 |

## 1. 原则与执行点

六条原则见 [README.md](README.md#六条原则贯穿全部文档)。每条都必须落到可测试的执行点：

| 原则 | 执行点 |
|---|---|
| 文件存行为、Mongo 存状态 | 核心不从 md 读取任何人格状态；人格包 md 只在头缺失时作种子；导出是只读渲染 |
| 人格是插件 | 核心代码与核心 prompt 中不出现人格名；合成人格 `demo` 跑通全部测试 |
| 判断归角色、记账归程序 | 情感数值、衰减、配额、幂等全部是纯函数或带 CAS 的写入；模型只提交语义选择 |
| 隐私分层 | §2 的谓词在每个读路径生效；有专门的泄漏测试 |
| 个人数据留本地 | 示例只用占位符；提交前告警检查 |
| DSH 原生优先 | 见 [DSH_ALIGNMENT.md](DSH_ALIGNMENT.md) |

## 2. 隐私与可见性模型

### 2.1 会话可见类（session class）

每个回合（episode）在建立时由程序算出 `session_class ∈ {owner_private, public}`，并写入 manifest：

```text
owner_private  ⇔  (scene_id == chat.scene_id  且  person_id == chat.person_id)        # owner 本机场景
              或  (scene.kind == 'dm'  且  canonical(person_id) == chat.person_id)    # owner 的渠道私聊
public         ⇔  其他一切（群聊——包括 owner 在群里发言——以及非 owner 的私聊、行动脑）
```

- `canonical()` 使用现有规范人物映射（`scene_links`），映射本身属于 owner 的本地配置。
- **跨场景链接（`context_links`/`read_scenes`）永远不提升会话类**。即使配置错误，把某个群链接到本机场景，群回合仍是 `public`。
- **行动脑的系统提示恒为 `public` 渲染**（§8.3）：任何任务都不注入 `owner_private` 的文档、档案、情感或记忆块。**任务载荷**（目标、约束、原始输入、CONSULT 答复）继承来源回合的类：
  - 来自 `owner_private` 回合的任务，载荷可以含 owner 自己交代的私密信息（现状如此，也是做事所必需）；
  - 来自 `public` 回合的任务，其 CONSULT 在该场景的角色会话中进行，而该会话只有 `public` 渲染与本场景数据，因此答复不含私密内容（泄漏测试 T4.12）。
  - owner 任务若需要更多私有数据，只能通过已授权的工具读取（例如现有 `development_database_read`），不能经由提示注入。
- **内部回合**（心跳、夜间沉淀、自开发机会）的类由其目标场景决定。目标必须是 `owner_private` 场景，否则拒绝创建。

### 2.2 数据可见性

| 数据 | 可见性如何表达 | 缺省值 |
|---|---|---|
| 文档的节 | `visibility ∈ {public, owner_private}` | 包种子：`public`（种子是可公开的包内容，可用 front-matter 逐节覆盖）；经数据 API 写入而未声明：`owner_private`，并在结果中提示 |
| 记忆单元 | `scope_key`：新增 `owner-private:<persona>`；原有 `scene:*`、`global-safe` 不变。写入方声明的 `visibility` 映射为：`public` → `global-safe`，`owner_private` → `owner-private:<persona>` | 未声明：`owner-private:<persona>`，并提示 |
| 情感事件 | 事件本身全局，一个人格只有一颗心；**原因字段**（`ref`/`why`/`cost`/`who`）按 `source_scope` 判定可读性 | 在 `owner_private` 会话中提交：`source_scope = owner-private:<persona>`；在其他会话中提交：本场景 `scene:*`；导入：按写入方声明 |
| 产物（artifact） | `scope_key` | 源文件快照、作业报告：`owner-private:<persona>`。`BlobStore` 需支持该 scope，读取仍只允许 operator 视图 |
| 情感倾向文本 | 人格模型中每种倾向标 `public` 或 `owner_private` | `owner_private` |
| 人物档案 | 按节；注入规则见 §7 | `owner_private` |
| 政策参数 | 不注入正文；程序按键使用 | — |

### 2.3 读取规则

`可读(数据, 会话) ⇔ 数据.visibility == public  或  会话.session_class == owner_private`，再叠加现有的场景作用域规则：`scene:*` 只在本场景和已授权的链接中可读；`owner-private:<persona>` 只按会话类判定，**与链接无关**。

**链接降级在配置加载时就拒绝。** 若 `context_links`/`read_scenes` 中的读方场景属于 `public` 类，而被读场景属于 `owner_private` 类（owner 本机场景或 owner 私聊），宿主启动时报 `LINK_PRIVACY_DOWNGRADE` 并拒绝该条链接。原因是 owner 私密场景里已有的独白、分块、摘要和关系头仍沿用 `scene:*` 作用域（不迁移既有数据），只有禁止这类链接，才能保证它们不会被公开场景读到。`owner_private` 场景之间的链接（例如本机场景 ↔ owner 渠道私聊）照常允许。

### 2.4 必须改造的读路径（缺一处即为泄漏）

1. `retrieval.py`：向量 `filter` 与词法候选查询。
2. `Store.get`（`state.py:119`）以及 `mutate` 的可读 scope 集合。
3. `context.py` 的所有块，包括链接历史合并。
4. 新增的 `DocumentStore.read/render`、情感投影渲染、档案注入。
5. 探针 API（见 [PERSONA_CONTRACT.md](PERSONA_CONTRACT.md)），按调用时声明的 `as_scene` 计算会话类。
6. 行动脑系统提示，见 §8.3。
7. 记忆右栏（`native_api.py`）：这是 operator 视图（owner 本机），显示全部内容，但每条带可见性标签。
8. CONSULT：答复只回到发起任务的那个行动会话；`public` 场景任务的 CONSULT 上下文只含 `public` 内容（T4.12）。
9. `BlobStore`（`blobs.py`）：支持 `owner-private:<persona>` scope，读取仍需 operator 视图。
10. `persona_job_run` 的返回值只含状态、计数和报告 artifact id，不含任何摘录（[PERSONA_CONTRACT.md §7.4](PERSONA_CONTRACT.md#74-触发)）。
11. 导出：只在 owner 操作下，写到本地配置指定的目录（[MEMORY.md §8](MEMORY.md#8-备份与导出)）。

## 3. 组件总图

```text
@asuna/<persona>（人格包：只含可公开的默认值与代码）
  ├─ persona model JSON（情感模型、政策键声明与默认值、召回顺序、注入预算、节律/心跳/表达参数）
  ├─ seeds/*.md（文档种子：只在头缺失时导入）
  ├─ jobs/*（人格作业：人格自己写的导入器、校验器……）
  └─ skills/、integrations/（不变）
                │ registerPersona v2
                ▼
@asuna/cognition-core（JS） ─stdio─▶ Python worker
  ├─ 角色作用域：人格段（完整替换 + 抑制 harness 身份句）
  ├─ 行动作用域：public 价值段
  ├─ 原生 schedule：用户计划 / presence 心跳 / settlement 夜间沉淀
  └─ 设置卡：源根与权威状态、心跳目标、情感评估路由
                                   ├─ DocumentStore            doc:<persona>:<slug>
                                   ├─ AffectLedger + Projection affect_events / affect_amendments / affect_proposals
                                   ├─ PolicyStore              policy:<persona>
                                   ├─ Memory（扩展）           memory_units + salience + source_window + invented
                                   ├─ ContextBuilder（扩展）   按召回协议组装；history delta
                                   ├─ Coordinator（扩展）      DECIDE 增量、WRITE 阶段、失败隔离
                                   ├─ PersonaDataAPI / Probe   ChannelServer 上的受控端点
                                   └─ PersonaJobs              IntegrationRunner 的 run-to-completion 形态
                                                  │
                                                  ▼
                                         Mongo（单库，唯一状态真相）
```

## 4. 人格包与人格模型

契约、模型 schema、人格数据 API、作业与公开就绪规则见 [PERSONA_CONTRACT.md](PERSONA_CONTRACT.md)。本节只强调两点：

- **人格模型是数据。** 核心为每个参数提供中性的缺省值，缺省行为等于"该功能关闭"或"沿用现状"，例如显著度权重为 0、心跳关闭、没有情感种类表。人格包提供公开默认值；owner/人格的私有覆盖写进 `policy:<persona>`。
- **核心 prompt 中性化。** `common.md`、`stage_*.md`、`executor.md` 不得出现人格名、人格口吻或人格专属规则。人格的一切表达来自人格文档。

## 5. 文档层（DocumentStore）

### 5.1 存储

- 实体键：`doc:<persona>:<slug>`，作用域固定为 `global-safe`。可见性在节上表达，不靠 scope。`<persona>` 一律指人格 id（见 [PERSONA_CONTRACT.md §2.1](PERSONA_CONTRACT.md#21-标识口径)）。
- 节 id（`sid`）按标题确定性生成：GitHub 风格 slug（小写、去标点、空格转连字符），同名依次加 `-2`、`-3`；第一个 `##` 之前的内容取 `sid=_preamble`。角色在 WRITE 中新建的节按同一规则生成。`sid` 生成后不随标题修改而改变。复用 `state_heads`/`state_revisions`，但走**独立的 `DocumentStore` 类**：`Store.mutate` 的实体白名单、字段白名单和"必须有记忆来源"规则不适用于文档。
- 修订内容：

```json
{
  "kind": "persona | voice | dossier | ledger | working | contract | index | <persona-defined>",
  "title": "string",
  "subject": "canonical person id（仅 dossier）",
  "sections": [
    {"sid": "稳定 id", "heading": "string", "body": "markdown 原文",
     "visibility": "public | owner_private", "inject": "always | on_demand | never",
     "tags": ["preamble | entry | injectable | invented | …"], "entry_date": "YYYY-MM-DD（dossier 条目必填）",
     "body_sha256": "hex"}
  ],
  "source": {"origin": "seed | asuna | <source-root-id>", "path": "相对源根的路径", "sha256": "导入时源文件哈希", "import_base": "导入时的修订 id"}
}
```

- 每个修订附带：`reason`（1–2000 字）、`source_ids`、`author ∈ {character, persona_job:<id>, seed, operator}`、`mutation_id`（幂等键）、`parent_revision_id`。
- 单个修订不超过 1 MB。`dossier` 超过 512 KB 时滚动卷：`doc:<persona>:dossier:<person>:v<n>`。前言留在第 0 卷，注入时跨卷取最近条目。

### 5.2 操作与约束

| 操作 | 允许的文档种类 | 约束 |
|---|---|---|
| `seed` | 全部 | 只在头缺失时执行；包升级不覆盖 |
| `replace_section` | persona、voice、ledger、working、index、dossier 前言 | 必须带 `reason`；CAS 条件为基修订加该节 `body_sha256` |
| `append_section` | 全部（contract 除外） | dossier 条目必须带 `entry_date` |
| `correction` | dossier 条目、ledger | 追加一个引用原 `sid` 的更正节，**原文不改** |
| `set_tags` | 全部 | 修改 `visibility`/`inject`/`tags`；必须带理由 |
| `adopt_seed` | 全部 | 由人格（`write_docs` 的 `adopt_seed` 操作，不经 WRITE 阶段）或 operator（设置卡）显式执行：把包内新种子按 `sid` 并入现有文档，双方都改过的节列为冲突，不覆盖 |
| 删除 | — | **不提供**。只能由 operator 的隐私擦除写墓碑（审计） |

`contract` 种类导入后只读。

### 5.3 谁能写

| 写入方 | 条件 |
|---|---|
| 角色 | 经 WRITE 阶段（§9.2），且只在 `owner_private` 回合中。**群回合不能写任何文档**，这样陌生人的输入无法驱动人格修改自我 |
| 人格作业 | 经人格数据 API，受源根权威状态约束 |
| operator | 回滚、擦除（审计） |

### 5.4 与现有自我状态的关系

- `character_core:`/`current_self:` 保持原语义（ADR-007），不并入文档层。
- **转换先于种子。** 启动时，若 `doc:<persona>:persona` 缺失而旧的 `persona:<persona>` 头存在，就先把旧正文转成单节文档（`sid=_preamble`，`public`，`always`）。只有两者都不存在时，才用包种子初始化。转换**不受预算阻挡**（超预算时的状态见 §8.1）。转换后上下文只读文档；旧头的读取路径在 P7 删除。
- 文档 CAS 冲突沿用现有错误码 `BASE_REVISION_STALE`。

## 6. 情感引擎

### 6.1 数据

- `affect_events`：只追加，不可修改。

```json
{"_id": "sha256(persona, origin, source_identity) 或 sha256(episode_id, index)",
 "persona": "id", "origin": "asuna | <source-root-id>", "source_identity": "导入时由作业给出",
 "ts": "UTC ISO-8601（事件时刻，宿主写入时取现取时刻）", "ts_original": "导入时的原始字符串",
 "ref": "可指认的事实 id", "ref_kind": "message | episode | memory | doc_section | task | external",
 "why": "≤500 字", "cost": "≤200 字", "val": 0.0, "arl": 0.0,
 "kind": "人格模型中的种类或空", "who": "规范人物 id 或自由标签（≤64）",
 "open": false, "half": null, "half_arl": null,
 "source_scope": "scene:* | owner-private:<persona>", "episode_id": "id 或 null", "created_at": "UTC"}
```

- **事件不可变。** 导入时，同一 `origin + source_identity` 已存在而内容不同，就拒绝（`EVENT_IMMUTABLE`）；变化只能以修订表达。`source_scope` 的取值规则见 §2.2。
- `affect_amendments`：只追加。`{target, op: close | void | fix_ts | fix_kind, value?, at, why, by: character | persona_job:<id> | operator, origin, source_identity?}`。`fix_ts`/`fix_kind` 必须带 `value`；`void` 必须带 `why`。投影把修订折叠进事件后再计算。
- `affect_proposals`：情感评估路由的提案。字段包括事件字段（不含 `ts`）、`source_scope`（取所评估回合的会话类）、`episode_id`、提案时的 `ref_index` 快照、状态 `pending | accepted | declined | expired`，以及决定理由。

### 6.2 投影（纯函数，时刻 t）

模型参数 `M`：`default_half_h`、`arl_half_h`、`kinds{k:{half_h, tendency, tendency_visibility}}`、`clamp{val:[lo,hi], arl:[lo,hi]}`、`close_mode ∈ {from_close, retroactive}`。

对每个满足 `ts ≤ t` 的事件 e：

```text
若 e 被 void（任意时刻）                       → 贡献 0（void 表示"前提不成立"，视为从未计入）
half_v = e.half      若 e.half > 0     否则 M.kinds[e.kind].half_h  若 kind 在表中  否则 M.default_half_h
half_a = e.half_arl  若 e.half_arl > 0 否则 M.arl_half_h
Δa = (t − e.ts) 小时
val 衰减：
  close_mode = from_close ：
      若 e.open 且 (未 close 或 t < closed_at) → decay_v = 1
      否则若 e.open                          → decay_v = 0.5^((t − closed_at)/half_v)
      否则                                   → decay_v = 0.5^(Δa/half_v)
  close_mode = retroactive ：
      若 e.open 且 从未 close                → decay_v = 1
      否则                                   → decay_v = 0.5^(Δa/half_v)       # 关闭后按事件时刻回算
arl 衰减：decay_a = 0.5^(Δa/half_a)                                            # 活跃度不受挂账影响
val(t) = clamp(Σ e.val·decay_v),  arl(t) = clamp(Σ e.arl·decay_a)               # 先求和再钳
```

- `fix_ts`、`fix_kind` 修订会替换事件中对应的字段后再计算。
- 贡献明细：`|e.val·decay_v| ≥ 0.5` 或 `|e.arl·decay_a| ≥ 0.5` 的事件，供审计和 owner 私密注入使用。
- 参考实现：[examples/affect_reference.py](examples/affect_reference.py)。实现必须与它在合成夹具上逐点一致（误差 < 1e-6）。
- **导入一致性由人格自己负责。** 导入旧账本时，用 `close_mode` 和每条事件自带的 `half` 复现旧算法：常见的"关闭后按事件时刻回算"对应 `retroactive`，"从关闭时刻起衰减"对应 `from_close`，选哪个由人格裁定。与旧脚本逐点对账是人格自己的验收，不是本 ADR 的验收。
- 事件自带的 `half`/`half_arl` 为 `null` 或 0 表示未设置；负数一律拒绝。

### 6.3 投影输出

```json
{"val": 12.3, "arl": 41.0,
 "label": "由 M.bands 首个命中规则给出",
 "top_kinds": [{"kind": "k", "share": 0.42, "tendency": "（按可见性过滤）"}],
 "policy": [{"slot": "话量", "text": "…", "visibility": "public"}],
 "open_count": 2,
 "contributions": [{"event_id": "…", "kind": "k", "val": 3.1, "arl": 0.0, "age_h": 5.2, "held": true, "why": "…（仅 owner_private）"}]}
```

`M.bands` 和 `M.policy` 是有序规则表，条件只能比较 `val`/`arl` 与常数（`gte/gt/lte/lt`），首个命中生效。表达能力足以覆盖"两轴分档 → 名称、表情提示、行为档位"这一类模型。

### 6.4 提交（只有角色能提交）

DECIDE 新增可选字段（完整 schema 见 [examples/decision-delta.schema.json](examples/decision-delta.schema.json)）：

- `affect`：≤3 条 `{kind?, val, arl, who?, ref, why, cost?, open?, half?, half_arl?}`。`ts` 由宿主在提交时取现取时刻，**模型不填时间**。
- `affect_ops`：≤3 条 `{op: close | void, event_id, why}`。`void` 必须写 `why`。
- `affect_adopt`：对评估路由提案的决定 `{proposal_id, decision: accept | decline | edit, why, edit?}`。

程序闸门（任何一项不过只拒该条，并记入 `episode.rejections`，**不打断回合**）：

1. `ref` 必须出现在本回合 manifest 的 `ref_index` 中。`ref_index` 收录当前输入、已选记忆、已注入文档节、任务、本回合 id。
2. `M.require_cost=true` 时 `cost` 不能为空。
3. `|val| ≤ M.max_delta.val`，`|arl| ≤ M.max_delta.arl`。
4. `kind` 必须在 `M.kinds` 中，或者 `M.allow_untyped=true` 且为空。

`affect_adopt` 的 `accept`/`edit` 用提案自带的 `ref_index` 快照来校验 `ref`。

**缺省值**：人格模型 `affect.enabled=true` 时，`default_half_h`、`arl_half_h`、`clamp` 必须给出（schema 强制）；其余参数缺省为 `close_mode=from_close`、`require_cost=false`、`allow_untyped=true`、`max_delta={val:100, arl:100}`、`proposal_ttl_h=24`、`kind_floor=0`。
5. `affect_ops` 的目标事件，其 `source_scope` 必须对本会话可读。

### 6.5 注入

| 会话类 | 注入内容 |
|---|---|
| `owner_private` | 完整投影（含 `contributions` 的原因、全部倾向、全部行为档位） |
| `public` | `label`，以及 `visibility=public` 的倾向和行为档位。**不含任何原因、`who`、事件 id 或数值** |
| 行动脑 | 不注入情感 |

**SPEAK 阶段只收到行为档位，不收到原因和提案文本。**

### 6.6 对称条款（写死在代码里）

- 情感评估路由与投影**不产生任何可直接发出的句子**：提案 schema 中没有面向台词的字段，投影只输出档位。
- **没有任何 API 删除情感事件**。只能逐条 `void` 并写理由，或由 operator 隐私擦除（写墓碑并审计）。不提供批量重置。
- 情感只能由角色提交。评估路由只能提案，人格作业只能在 `cohabiting` 源根下按 origin 导入。
- 角色可以决定说或不说，但说不说不影响账本。

### 6.7 情感评估路由（可选，对应"情感核"）

- 新职责路由 `appraiser`。JS `Config.routes` 增加可选项 `appraiser`（与 `character`/`action` 同形），**不从名字推断模型**；未配置时整个功能关闭。
- 模型调用由 Core 在 Host 内的原生会话 `asuna-appraiser-<persona>` 中执行（无工具 preset，与 summary preset 同类）。worker 以 `stage` 事件、`phase=APPRAISE` 发出请求，结果经 `result` 回传。
- 时机：`episode_finished` 之后**异步**运行，绝不在回合内阻塞。输入只取本回合可见的材料（输入、独白、发言）。
- 输出：≤3 条提案，字段同 `affect` 去掉 `ts`，`why ≤ 200` 字。超时或失败只记审计。
- 提案在下一次同人格回合的上下文中以 `affect_proposals_from_program` 出现，按可见性过滤。过了 `M.proposal_ttl_h` 仍未决定的标为 `expired`，**明示而不静默**。

### 6.8 夜间消化与可选阈值

- 默认**没有数值睡眠恢复**。夜间沉淀回合（§10.3）列出挂着的事件和待决提案，由角色决定 `close`/`void`/保留。
- 人格模型可以设一个无状态下限 `kind_floor`：累计 |val 贡献| 低于它的情绪种类不在 `top_kinds` 中列出，数值本身不变。不提供带滞回的阈值三态，因为那需要额外的状态。

## 7. 人物档案（dossier）

- 键 `doc:<persona>:dossier:<canonical_person>`。内容由**前言节**（`tags` 含 `preamble`，写法规矩、长期结论）和**条目节**（`tags` 含 `entry`，必须有 `entry_date`，按时间追加）组成。
- **只追加、不改写、不摘要**：条目不支持 `replace_section`，修正用 `correction` 追加；前言可以 `replace_section`，但必须写理由。
- 注入（MONOLOGUE 上下文的 `dossier` 块）：

| 会话类 | 对当前对话人的档案注入 |
|---|---|
| `owner_private` | `inject=always` 的前言节 + 最近 N 条带 `injectable` 标签的条目（`N = dossier.inject_last`，由人格模型或政策给出；核心缺省 0，即只注入前言）+ 最近 30 条可注入条目的标题索引 |
| `public` | 只注入 `visibility=public` 且 `inject=always` 的节（缺省为无） |
| 行动脑 | 不注入 |

- **未打 `injectable` 标签的条目永不自动注入**，只能按需读取（§9.3），且只在 `owner_private` 会话中。
- 与关系头分工：档案是积累式正文，关系头（`relationship:*`）是场景内的活账。REFLECT 仍然写关系头；档案的追加走 WRITE。

## 8. 角色系统提示渲染与上下文组装

### 8.1 系统提示（角色作用域，每会话）

```text
[核心中性头]  common.md（中性规则：阶段协议、认知类型、来源规则、隐私规则）
[人格段]      persona 文档中对本会话可读、inject=always 的节，public 节在前、owner_private 节在后
[口吻段]      voice 文档中对本会话可读、inject=always 的节
```

- 以角色作用域的 `systemPrompt.section({complete: true})` 注册，渲染结果就是完整的系统提示，并调用抑制运行时上下文的接口，**去掉 harness 身份句**（见 [DSH_ALIGNMENT.md D-1](DSH_ALIGNMENT.md#d-1-角色系统提示人格段与-harness-身份句)）。
- public 节在前，可以让同一人格在不同会话之间共享前缀缓存。
- **预算**：上限 = min(`render.budget_tokens`, 所解析角色路由的 `context_window` × `render.max_window_share`)。`render.budget_tokens` 来自人格模型或政策，核心缺省为空（不设绝对上限）；`render.max_window_share` 缺省 0.25。估算用保守的字节/字数上界，与现有分块预算口径一致。**以 `owner_private` 渲染（最大的那份）为准。**
  - 提交时校验：会让渲染变大的文档修改，若超预算就**拒绝提交**（`PERSONA_RENDER_OVER_BUDGET`，附估算值）；让渲染变小的修改总是允许。
  - 渲染时若已经超预算（例如换了窗口更小的路由，或转换来的旧人格本身就超），**照常完整渲染，不截断，也不让回合失败**；同时在设置卡与记忆右栏显示红色状态并写审计，直到人格或 owner 调整内容或预算。`render.budget_tokens` 是核心可写键。
  - **从不静默截断。**
- episode 只存 `system_ref = {persona_doc_revision, voice_doc_revision, common_sha256, render_sha256}`，**不再存系统提示全文**（见 D-4）。
  - `system_ref` 在回合准备时固定所用修订；同一回合内 WRITE 产生的新修订，从下一个回合才生效。
  - 各阶段需要系统提示时，按 `system_ref` 重渲染，结果按 `render_sha256` 缓存。
  - 升级前已在途的回合仍带旧的 `system` 字段，读取时兼容；P7 在确认没有在途旧回合后删除兼容代码。

### 8.2 阶段上下文（MONOLOGUE 前置的 JSON）

块按人格模型 `recall_protocol.order` 排列，这对应人格"醒来先看什么"的习惯。该顺序必须是核心已知块 id 的排列；缺失的块按核心缺省顺序补在末尾：

| 块 id | 上下文键 | 内容 | 可见性 |
|---|---|---|---|
| `self_state` | `self_state_from_program` | Character Core / Current Self（现有） | 现有规则 |
| `dossier` | `dossier_from_program`（新） | §7 | 按 §7 |
| `affect` | `affect_from_program`（新） | §6.5 | 按 §6.5 |
| `affect_proposals` | `affect_proposals_from_program`（新） | §6.7 | 按提案的 `source_scope` |
| `relationship` | `relationship`、`overlay`、`relationship_shared_from_program` | 现有 | 现有规则 |
| `ledgers` | `ledgers_from_program`（新） | `kind=ledger` 文档中 `inject=always` 的可读节 | 按节 |
| `rhythm` | `rhythm_from_program`（新） | §10.1 | 按 §10.1 |
| `memories` | `memories`、`memory_source_rules`、`coverage_from_program`（新） | 检索结果与证据判定（[MEMORY.md §5](MEMORY.md#5-情节层扩展memory_units-新字段)） | §2.3 |
| `history` | `delivered_history`、`undelivered_outbound_not_public`、`linked_scenes_from_program` | **增量**历史（D-3） | 现有规则 |
| `tasks_plans` | `task_state_from_program`、`plans_from_program`、`schedule_control_from_program`、`scheduled_plan_from_program` | 现有 | 现有规则 |
| `recent_phrasing` | `recent_phrasing_from_program`（新） | §11.2 | 本场景 |
| `media` | `media_from_program` | 现有 | 现有 |
| `group_continuity` | `group_continuity_from_program` | 现有 | 现有 |
| `sender_identity` | `sender_identity` | 现有 | 现有 |

- **核心缺省顺序**就是上表从上到下的顺序。
- 不参与排序、位置固定的键：开头是 `scene_id`、`scope_key`、`policy_epoch`、`person_id`；随后是排序块；最后依次为 `understanding_update_from_program`、`action_capabilities_from_program`、`proactive_from_program`、`recent_experience_from_program`、诊断键（`*_from_host`）、`ref_index`（新，本回合可引用的 id 列表，见 §6.4）和 `event`。
- JSON 对象的键序就是注入顺序：序列化时不得排序键。

### 8.3 行动脑系统提示

`executor.md` 加上 **public 价值段**：只取 persona 文档中 `visibility=public` 且带 `values` 标签的节。若没有任何这样的节，就只给人格显示名。这一改动关闭了 `tasks.py:414` 的泄漏。

## 9. 回合变化

### 9.1 DECIDE 处理顺序（全部可选，单项失败只记录）

```text
cancel_task → affect_ops → affect_adopt → affect → policy_set → pin → write_docs（set_tags、adopt_seed 直接执行；其余 → WRITE）
→ reflect_understanding → reflect_self → promote（仅沉淀回合）→ schedule/plan → 分支(next；read 在 recall 分支中处理)
```

每个被拒绝的子项写入 `episode.rejections[] = {field, index, code, detail}`，并在 SPEAK 的"程序已提交的结果"里如实告诉角色，沿用 `_plan_rejected` 的语义。**`BAD_DECISION_JSON` 只用于整体 JSON 无法解析或必需字段缺失。**

### 9.2 WRITE 阶段

- DECIDE 的 `write_docs`：≤2 条 `{doc, op, sid?, heading?, entry_date?, tags?, visibility?, inject?, reason}`，只表达意图，不放正文。`set_tags` 和 `adopt_seed` 由程序直接执行，不经 WRITE 阶段；`replace_section`、`append_section`、`correction` 进入 WRITE 阶段。
- 对每条意图，程序在同一个角色会话里推进一个 WRITE 阶段（`stage_write.md`，中性提示）。阶段输入包括目标节的当前全文（或空）、该文档种类的操作约束和预算剩余；**输出只是正文本身**。
- 程序以 DECIDE 时看到的基修订为 CAS 基准提交。冲突、超预算、种类约束不符都只拒这一条。
- 群回合（`public`）的 `write_docs` 一律拒绝：`DOC_WRITE_REQUIRES_OWNER_PRIVATE`。

### 9.3 按需读取

`next=recall` 时可以带 `read: [{doc, sid}]`（≤3）。可读的节原文附进 recall 上下文；不可读的节记拒绝原因。`recall_query` 与 `read` 可以同时出现，仍受"至多 2 轮"的限制。

### 9.4 政策设置

`policy_set: [{key, value, reason}]`（≤3），只在 `owner_private` 回合可用。`key` 必须是人格模型声明过的键，或核心私有键（`rhythm.timezone`、`rhythm.sleep_window`、`rhythm.public_clock`），或核心可写键（`render.budget_tokens`）。值按声明的类型和范围校验，见 [PERSONA_CONTRACT.md §3](PERSONA_CONTRACT.md#3-人格模型persona-model)。

## 10. 节律、心跳与夜间沉淀

### 10.1 节律块

由政策参数 `rhythm.timezone`（**必须是 IANA 名称**；未设置时明确写"未设置时区，以 UTC 显示"）和 `rhythm.sleep_window`（`HH:MM-HH:MM`，可空）计算：

```json
{"local_time": "…", "timezone": "…", "in_sleep_window": true, "since_owner_message_min": 37}
```

- 时区优先级：场景级配置 `timezone`（现有；只用于该场景计划的计时）> 政策 `rhythm.timezone` > 现有 owner 本地配置的全局 `timezone` > UTC（明示）。
- `since_owner_message_min` 只在 `owner_private` 会话中出现。
- `public` 会话**默认不注入节律块**，因为本地时刻和作息会暴露 owner 的时区与生活规律。只有 `rhythm.public_clock=true`（核心私有键，缺省 false）时，才给出 `local_time`。

**节律是 DECIDE 的输入，不是闸门**：普通回复绝不因睡眠窗被程序拦截。现有群聊主动闸门的静默时段保持不变，它管的是"程序别主动插话"。

### 10.2 心跳（presence）

- 前提：人格模型 `heartbeat.enabled=true`，**并且** owner 在本地配置中设置了 `persona_runtime.<persona>.heartbeat_target`（场景 id，必须是 `owner_private` 场景）。
- 由原生 schedule 的 `every_seconds = 60 × heartbeat.every_min` 触发，作为 `plans` 行（`kind=presence`）管理。
- **确定性预闸门**（满足任一条就跳过，不调模型，只记一条计数审计）：
  1. 目标场景队列非空或有活动回合；
  2. 距上次 presence 回合不足 `heartbeat.min_gap_min`，且此后没有新事件；
  3. `heartbeat.skip_in_sleep=true` 且处于睡眠窗。该项缺省为 false，开不开由人格自己选。
- 回合：内部 `presence` 回合，类由目标场景决定。上下文含节律、情感、活账、最近活动。DECIDE 可以 `silent`（常态）、`speak`（发到目标场景）、`delegate`（自主项目）、写文档或改计划。
- 节奏：人格经 `policy_set` 修改 `heartbeat.every_min` 后，核心调用原生 `schedule_update`，不删建。

### 10.3 夜间沉淀（settlement）

- 原生 schedule，`daily` 于 `rhythm.settle_at`（本地时刻，IANA 时区），`plans.kind=settlement`，按本地日期幂等，每天最多一次。
- 回合在 `persona_runtime.<persona>.internal_scene` 中进行（缺省为 owner 本机场景 `chat.scene_id`，必须是 `owner_private` 场景）。没有设置 IANA 时区或 `settle_at` 时，不建沉淀计划，设置卡显示原因。
- 上下文：挂着的情感事件、待决与将过期的提案、活账中 `inject=always` 的节，以及**晋升候选**。候选由确定性规则生成：近 `promotion.window_days` 天内，被 ≥2 个不同回合引用过的记忆单元或独白，引用记录来自现有 `retrieval.selected` 审计。
- DECIDE 新增 `promote: [{fact, appraisal, signal, source_ids, visibility}]`（≤ `promotion.daily_quota`；核心缺省 0，即不晋升，由人格开启）。程序检查 `source_ids` 至少覆盖 `promotion.min_roots` 个不同回合、`promotion.min_dates` 个不同本地日期（缺省各为 2），通过的生成 `memory_units` kind `memory_unit`。
- 现有"每日自开发机会"的间隔改由 `self_development.every_min` 决定，优先级为：政策 > 现有本地配置 `self_development.every_seconds`（P7 前兼容读取）> 人格模型默认 > 1440 分钟。`schedule.py` 中不再有写死的缺省间隔。

## 11. 表达质感

### 11.1 多条发言与节奏

- SPEAK 可以用一行单独的分隔标记（`speak.split_marker`，核心缺省 `---split---`）切出 ≤ `speak.max_messages` 段（核心缺省 1，即沿用现状）。
- 出站键 `<ep>:speak:<i>`，按序发布。渠道场景每段带 `not_before`：上一段的 `not_before` + clamp(段长 / `speak.chars_per_second`, `speak.min_gap_s`, `speak.max_gap_s`)；`channels.claim` 不返回未到时刻的段。Web 本地场景按序立即投递。
- 第 i 段进入 `FAILED`/`UNKNOWN` 后，其后各段标为 `CANCELLED_AFTER_FAILURE`，不再发出。
- 崩溃恢复：恢复时，未发布的段按原顺序继续；处于 `SENDING` 的段沿用现有 `SENDING→UNKNOWN` 规则，其后各段同样取消。

### 11.2 近期措辞提示

确定性计算：本场景最近 `phrasing.window`（缺省 20）条本人出站中，出现 ≥3 次的 4-gram（CJK 按字，其他按词），取 ≤5 条作为 `recent_phrasing` 块。**只提示，不禁止。**

## 12. 自我成长与扩展点

人格不改核心就能做到的事：

| 想做的事 | 用什么 |
|---|---|
| 修订人格、口吻、档案、活账、工作文档 | WRITE 阶段（owner 私密回合） |
| 调整自己的情感半衰期、档位、心跳节奏、注入数量等 | `policy_set`（声明过的键） |
| 增加新技能、新集成 | 现有自开发 → 人格包 `skills/`、`integrations/` |
| **接入新的数据源**（例如本次超范围的外部日记） | owner 在本地配置新增一个源根；人格在自己的包里写一个人格作业（解析、导入、校验），经自开发发布后运行 |
| 写自己的迁移器、校验器、召回题库 | 人格作业 + 人格数据 API + 探针（题库放在人格私有数据里，不进包） |
| 新增文档种类 | `kind` 可以是人格自定义字符串（注入语义与 `working` 相同） |
| 需要核心能力 | 现有 `project=core` 自开发路径（ADR-007 地板不变） |

治理：每次写入都有修订、理由和来源，可由 operator 回滚。**不默认引入独立复审 LLM**；需要复审时，人格可以自己写成作业。

## 13. 不做的事

- 不做 Kazusa 式的多轴评估、门控情绪公式、RAG 规划器、多 LLM 巩固链。
- 不做数值关系分。
- 不默认做数值睡眠恢复。
- 不建第二个数据库、向量库或 md 同步守护进程。
- 不让行动脑、群聊或跨场景链接接触 `owner_private` 内容。
- 不替人格标注可见性、取参数值、写题库或导入真实数据。
