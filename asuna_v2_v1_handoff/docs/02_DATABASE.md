# 02 · MongoDB、聊天记录、记忆与检索

## 1. 复用实例，不复用旧业务集合

权威数据存储：用户已有、支持 vector search 的 MongoDB 实例。Asuna 正式库默认 `asuna_v2`，开发库 `asuna_v2_dev`，测试库 `asuna_v2_test_<run_id>`。这些是新命名方案，不代表当前已创建。

公开 Kazusa 配置确认了 `MONGODB_URI`、`MONGODB_DB_NAME` 与 `EMBEDDING_BASE_URL/API_KEY/MODEL`。HOWTO 的 URI 是 `mongodb://localhost:27017`，Compose 内部用 `mongodb://mongo:27017`；二者是部署示例，不是用户机器实际地址。[S6][S7]

Codex 本地发现顺序：

1. 操作者显式配置的 `ASUNA_MONGODB_URI` 与新库名。
2. 由 `KAZUSA_CONFIG_PATH` 明确指定的本地 `.env`，或已知本地 Kazusa checkout 的有效配置文件；只解析上述白名单 key，不执行旧 Python 模块。
3. 有权限读取的实际服务/Compose 环境，核实容器 DNS 与当前运行 namespace。
4. 仍未找到则标记 `BLOCKED_CONFIG`；不扫描内网、不尝试随机 IP、不假定 localhost。

输出只包含配置来源路径、key 名、脱敏 host/port 与 fingerprint。原 URI、口令不写报告、不进入模型、Git 或 artifact manifest。用户授权复用实例不是授权修改旧库；必须使用数据库级最小权限账户或应用 allowlist，禁止旧库写入。创建新库权限不足时提出明确 blocker，不自动改用 `roleplay_bot`。

### 首次探针

`ping`、`hello`/可用版本信息、可用读写权限、写关注能力、事务支持、搜索索引 API、带 scope filter 的真实向量查询、embedding 维度/返回顺序、索引就绪状态。版本号不替代功能测试。兼容 Mongo 的服务可能有不同向量语法，按实际探针选择 adapter。

不要求为了 V1 重建整个数据库。已有 server 支持向量，不代表新 Asuna collection 已有索引。默认创建独立索引；旧向量数据不自动搬迁。

## 2. 集合与所有权

正文允许 Markdown；Mongo 负责索引、scope、版本和引用。以下是 V1 完整逻辑模型，可用一个 StateStore 模块实现，不必拆微服务。

| 集合 | 用途与关键字段 | 索引/约束 |
|---|---|---|
| `identities` | `person_id, accounts[], display_names[], verified_by` | 唯一 `(platform, account_id)`；不以昵称唯一 |
| `scenes` | `scene_id, kind, members, scope_key, policy_epoch` | `_id`；授权成员变更推进 epoch |
| `messages` | 入站聊天、待发/已发角色话语，见下 | 去重、scene 顺序、publication key |
| `episodes` | 角色阶段状态、monologue/decision/response 引用、固定 revisions | 唯一 `(scene_id, source_event_id, episode_kind)` |
| `tasks` | 工具/提醒/反思任务；目标、授权、状态、结果与交接 outbox | unique request_key；状态+due_at；CAS version |
| `memory_units` | 可检索聊天片段、经历、monologue、事实/解释 | scope+kind+有效状态；source 去重；vector index |
| `state_heads` | 当前有效人格/关系/情绪 overlay 指针 | unique `(character_id, kind, subject_id, scope_key)` |
| `state_revisions` | 不可变状态候选/修订正文、parent/source/change reason | `_id`；entity+revision；mutation_id |
| `sessions` | scene/task→DSH binding，模型/preset/policy/compaction generations | unique binding key；checkpoint version |
| `audit_events` | 逐步事件、检索选择、LLM 调用、压缩、发布、错误 | unique `(stream_id, seq)`；trace/episode/task |
| `artifacts` | 大请求/输出/文件的 manifest、大小、hash、scope、GridFS id | `_id`；hash 非公开、scope 强制 |

大内容通过 GridFS（或经验证的同机 blob store）保存；V1 推荐 GridFS，使数据库备份可覆盖审计正文。禁止把整条 session 的全部聊天塞进一个无限增长的文档。Mongo 单 BSON 文档上限是 16 MiB；应用内普通文档先设 1 MiB 上限，超出切 artifact，而不是截断正文。[S11]

每个 collection 都有 schema_version。测试数据有 test_run_id，清理命令只允许 `asuna_v2_test_` 前缀且 manifest 匹配。不得执行宽泛 dropDatabase 或 dropIndexes。

## 3. 聊天记录：业务历史不是 DSH transcript

`messages` 是“现实交互”的权威投影；DSH transcript 是模型执行过程。两者不能混为一谈。

```json
{
  "_id": "msg-uuid",
  "schema_version": 1,
  "scene_id": "dm-a",
  "scope_key": "scene:dm-a",
  "policy_epoch": 1,
  "direction": "outbound",
  "author": {"kind": "character", "person_id": "xiaoman"},
  "platform_event_id": null,
  "reply_to": "msg-user-001",
  "occurred_at": "2026-09-19T00:00:00Z",
  "received_at": "2026-09-19T00:00:00Z",
  "content": [{"type": "text", "text": "查了。原件还在。"}],
  "episode_id": "ep-001",
  "monologue_refs": ["mem-monologue-001"],
  "task_refs": ["task-001"],
  "publication_key": "ep-001:speak:0",
  "delivery_state": "READY",
  "receipt": null,
  "revision": 1
}
```

入站 message 的 author/person_id 来自认证 adapter，不信正文 JSON。入站状态是 RECEIVED；出站状态为 DRAFT→READY→SENDING→DELIVERED/FAILED/UNKNOWN。只有 DELIVERED 才能进入“已经说出口”的对话投影；未送达内容可留在角色内部记忆但必须标明未送达。

公众读取 API 只返回公开 content、author、reply_to、送达状态和可见 artifact。monologue_refs 即使关联 messages 也仅操作者可读，不把 ID 作为向公众展开私密内容的凭证。按对象 ID 直接读取仍需 scope 检查。

必要索引：

- 入站部分唯一索引 `(adapter_id, scene_id, platform_event_id)`，仅在 platform_event_id 存在时；客户端不提供 ID 则 adapter 分配。
- `(scene_id, occurred_at, _id)` 读取时间线；另有严格 `scene_seq` 由程序分配，以处理相同时刻/乱序到达。
- 出站部分唯一索引 `publication_key`；重试不能生成新 key。
- `(episode_id)`、`task_refs` 查询关联。received_at/occurred_at 分开，不能让晚到消息改变已执行事件的真实顺序。

消息编辑/删除以原消息 ID 关联版本/墓碑，驱动对应 memory 与派生摘要失效。不可把编辑当全新独立事实继续叠加关系分数。

## 4. Monologue 和可检索记忆

```json
{
  "_id": "mem-monologue-001",
  "schema_version": 1,
  "kind": "monologue",
  "character_id": "xiaoman",
  "scope_key": "scene:dm-a",
  "subjects": ["person-a"],
  "source_event_ids": ["msg-user-001"],
  "episode_id": "ep-001",
  "body_markdown": "我还在意刚才的误会，但不想把猜测当作他的意思。",
  "epistemic_type": "character_interpretation",
  "status": "active",
  "valid_from": "2026-09-19T00:00:00Z",
  "supersedes": [],
  "depends_on": ["msg-user-001"],
  "embedding": [],
  "embedding_model": "DISCOVER_LOCALLY",
  "embedding_revision": "DISCOVER_LOCALLY",
  "embedding_dim": null,
  "embedding_status": "PENDING",
  "content_sha256": "computed",
  "policy_epoch": 1
}
```

分开保存事实 `observed_fact`、他人陈述 `reported_claim`、角色看法 `character_interpretation`、愿望 `intention`、真实被接受的承诺 `commitment`。承诺只有 task/message 状态支持时才建立，不能仅据 monologue 自动创建未来义务。

独白是角色生成的内部叙事，不宣称完整呈现模型 hidden computation。native reasoning 可审计但默认不入向量记忆，不用于生成“她真实为何这样想”的权威结论。

聊天向量采用 `kind=chat_chunk`，引用 2–6 条同 scene、同 scope 的相邻消息；每 chunk 最多 1,024 embedding-model tokens，overlap 最多 128。不能跨私聊/群边界组块。角色运行时原文尾部与 retrieved chunk 用 source ID 去重。不能把全部日志、工具错误栈和 stdout 自动索引成角色经历。

重要长期记忆由受控 reflect 提议；新事实与 monologue 即时落盘，embedding 索引可异步。对近期未索引记录走 scope 内精确回读，不能用索引可见延迟造成“刚说完就忘”。

## 5. 版本提交与崩溃恢复

V1 不假定 standalone Mongo 支持多文档事务。优先用单文档 CAS + 稳定 ID + 可恢复写入顺序；可用事务时只在必须的边界采用，不把外部副作用塞进数据库事务。

### 状态修订

1. 生成稳定 mutation_id 并写 audit.intent。
2. 插入不可变 revision 候选，记录 parent_revision_id、source IDs、完整正文及 hash。
3. `state_heads` 用 `_id + expected_revision_id` 条件原子切换到新指针；失败标 CONFLICT，不覆盖。
4. 写 audit.commit；若此时崩溃，恢复时按当前 head 的 parent 链和 mutation_id 补齐已接受事实。
5. 下一个 episode 读取新 head；已开始的 episode 保持原 version vector。

只有在 active head 祖先链上的 revision 属于已生效历史；孤立候选不算曾经接受。不能用最大 revision 数自动挑新版本。删除/回滚是新的版本或授权删除操作，不能靠改 history 消除旧行为。

Mongo 的单文档条件更新可用于此 CAS；不会自动实现多文档事务或语义合并。[S8]

### Task 与消息 outbox

`tasks` 插入 READY 即为持久委托事实，协调器按状态领取；不要求另写一份 outbox 才知道它存在。领取用 version/lease_owner/fencing_token，重启和过期 worker 不能双写。

出站 messages 的 READY 即为发布 outbox。发布前核验 episode version、task intent_revision、policy_epoch、scope、撤销状态；发送时固定 publication_key。模拟接收器实现幂等落地。普通不支持幂等的外部通道发送后崩溃应 UNKNOWN，而不是盲重试。

跨 DSH/Mongo 无法原子提交：预写 operation intent，向 DSH 使用稳定 message/request ID 投递，回收 DSH durable receipt/事件序号，标记 delivered-to-lane。重启先 reconciliation，再决定重投。DSH 没有确认去重保障时不能凭名称假定幂等；标 UNKNOWN 或用插件 durable inbox 查验。

## 6. 向量与混合检索

### Embedding 契约

复用用户已有本地 embedding endpoint，必须记录 model ID、revision/权重 fingerprint、dimensions、query/document 前缀、归一化与 cosine/dotProduct 约定。不能只因为维度相同就混用两种 embedding。

Kazusa 当前 `_client.py` 对部分 embedding 模型区分 query/document 前缀；仅用它定位已有部署需要，不搬进 Asuna 的历史业务层。[S12]

生成 embedding 失败时保留 PENDING/ERROR 状态和原因。正常聊天可降级为 scope 内近期+精确检索，但真实向量验收必须 FAIL/BLOCKED，不得用关键词成功冒充 vector pass。

### 管线

1. 在任何检索前构建授权 predicate：character_id、scope_key、policy_epoch、status、tombstone/expiry。
2. 固定载入 persona/scene continuity 与有效承诺，不参与相似度淘汰。
3. 向量召回 top 24；精确实体/关键词候选 top 24。operator 配置若启用 reranker，候选先做权限过滤后才进入本地 reranker。
4. 使用明确的 reciprocal-rank 融合 `sum(1/(60+rank))`；并列按稳定 ID。该公式是 V1 实验选择，不是最优声明。
5. 选最多 6 个相关记忆，按 token 预算截取完整语义单元；优先保证 source/epistemic_type。已在 recent tail 的来源不重复。
6. 取回每个候选的**当前权威正文**，再次验证 tombstone/scope/revision。vector index 可能过期；不能直接相信旧索引投影。
7. 选中更正记录时，沿 supersedes 在同一授权域内有限回读原判断，并保留“历史/已更正”标记。正常相似度召回不把superseded当现行事实，但它不是删除：回答“你以前怎么想”时仍可通过来源链回忆。该补读不计新的vector top-k命中，也不能复活tombstone。
8. 保存候选 ID/排名/得分/选择原因/排除原因与请求 fingerprint。对未授权候选只写脱敏拒绝计数，不在普通审计索引泄露内容。

标准 `$vectorSearch` 支持 pre-filter；当前用户实例的具体兼容性由探针确认。[S13] 若它无法在服务端对 scope 预过滤，允许在**已授权且有硬上限的子集**内做精确向量计算作为开发降级，必须标记 `scoped_exact_fallback`。不允许检索全库后仅在应用端过滤，也不能把此降级算成兼容 server-side-vector 验收。

### 建议索引定义（仅适用于探针验证为标准 Mongo Vector Search 的后端）

```json
{
  "name": "asuna_memory_v1",
  "type": "vectorSearch",
  "definition": {
    "fields": [
      {"type": "vector", "path": "embedding", "numDimensions": "REPLACE_WITH_PROBED_INTEGER", "similarity": "cosine"},
      {"type": "filter", "path": "scope_key"},
      {"type": "filter", "path": "character_id"},
      {"type": "filter", "path": "status"},
      {"type": "filter", "path": "policy_epoch"},
      {"type": "filter", "path": "embedding_revision"}
    ]
  }
}
```

此 JSON 是结构示意，维度占位符不是可执行配置。实际启用的每一个服务端predicate字段（例如额外expiry字段）都必须进入filter索引并通过探针；不支持的谓词不能悄悄去掉，尤其不能取消scope。expiry/tombstone/当前revision仍在权威回读再次检查。Codex 应按实际 server/driver 生成且等待索引 READY；需保存真实 query plan/索引定义和测试响应。`numCandidates` 按实际后端能力和受控语料调优，记录值，不在文档里伪装已验证最优。

## 7. 最小权限和隐私传播

`scope_key` 初版只支持 `global-safe` 和 `scene:<id>`。一个场景检索条件是全局安全资料或本场景资料，不能把 `person_id=A` 作为读取 A 所有私聊的通行证。group 成员变化推进 epoch，必要时重建受影响上下文。

模型提出的 source_refs 不足以证明输出没有使用未列出的上下文。默认输出继承本次完整输入的最严格 scope；角色全局人格更新只能在 global-safe 的独立反思 session 内处理，不允许把私域反思结果洗白。

非操作者不能提交 persona.base 修改或 policy 更新；人物在自己的范围内自我修订仍可自动接受。IDOR 测试必须覆盖 memory、message、artifact、audit、replay，不能只测向量查询。

## 8. 更正、删除、保留与备份

默认 V1 全量本地审计开启，使用合成资料。若用户请求不记录某次实际对话，V1 必须明确报告当前模式不支持“既完整审计又不留原文”，不能嘴上承诺不记、底层继续保存。生产接入前另做 no-store 全链路方案。

删除管线：先写 tombstone 并使 runtime 拒绝检索 → 标记所有 depends_on 派生记录/快照失效 → 删除向量可检索正文 → 清理/重建当前 DSH session → 清理对应 blobs 与可导出审计正文。元数据只保留删除事件，不保留可恢复敏感内容。备份不可能假定立即物理擦除；报告备份保留期限、访问控制及 crypto-erasure 能力，不能标“已经所有介质彻底清除”。

V1 必须通过活动库、索引、memory cache、摘要、session 和 audit export 的删除回归；历史备份擦除单列限制。删除之后已下载到外部的文件不在系统可撤回范围。

备份至少包括 MongoDB 新库与 GridFS、独立 DSH_HOME、锁文件、有效配置（凭据单独保护）以及版本 manifest。恢复验收在新测试库/目录执行，不覆盖原实例。审计 payload 和模型输入属于私密资料，即使没有 API key 也不能公开上传。
