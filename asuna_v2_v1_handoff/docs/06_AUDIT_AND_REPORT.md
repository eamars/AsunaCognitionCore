# 06 · 逐步审计、重放与 Codex 回报

## 1. 必须能回答的问题

对任一公开 message：谁在什么场景输入了什么？加载哪版人格和关系？有哪些候选回忆、哪些被过滤、最后真正进模型的是哪些？Gemma 生成了什么 monologue/decision？Qwen 做了哪些工具调用？结果依据是什么？什么时候压缩？消息实际发给谁、有没有收到回执？重试是否重复影响记忆或副作用？

只保存最后答案、系统 prompt hash 或模型自述“我读到了”都不够。

## 2. 事件字段与因果链

```json
{
  "event_id": "audit-uuid",
  "stream_id": "ep-001",
  "seq": 7,
  "trace_id": "trace-001",
  "parent_event_id": "audit-parent",
  "episode_id": "ep-001",
  "task_id": null,
  "phase": "MONOLOGUE",
  "type": "llm.response_committed",
  "occurred_at": "2026-09-19T00:00:00Z",
  "scope_key": "scene:dm-a",
  "actor": "character",
  "request_artifact_id": "artifact-request",
  "response_artifact_id": "artifact-response",
  "source_refs": [],
  "status": "SUCCESS",
  "payload": {},
  "prev_hash": "...",
  "event_hash": "..."
}
```

hash 对 canonical JSON 计算，不含 event_hash 本身；每 stream 独立序列，由单 writer/CAS 保证。外部 manifest 保存 stream root，能发现意外修改。拥有 DB/宿主全部权限的人仍可改写整个链；不要宣传不可篡改。

最少事件：ingress.received/rejected/deduped、context.prepared/verified、retrieval.completed、llm.request/response/error、phase.started/completed/failed、task.accepted/claimed/result/stale/cancelled、tool.intent/result、memory.created、state.proposed/committed/conflict、compaction.start/summary/end/error、publication.ready/attempt/receipt/unknown、recovery.reconciled、policy.denied。

`trace_id`、`episode_id`、`task_id`、DSH session/turn/step/call ID 必须能双向查；不能只靠时间戳拼接。

## 3. Provider 实际请求证据

每次调用记录三层：

1. 业务上下文 manifest：persona/relationship/source IDs、scope、选取/排除与预算。
2. DSH 派生历史与工具列表：role/source/阶段对应、消息 ID、压缩代数。
3. 真正发往本地模型服务的请求 body：messages、tools、model、采样/思考/输出预算；tokenizer-rendered 字符串/IDs 可取得时额外保存。

连接 URI/token/header 等凭据不进入 export，保留受保护本地配置 fingerprint。请求正文保留实际语义内容，只能以明确 redaction 标记屏蔽隐私，不能修改角色措辞来美化样本。

模型服务负责最终 chat template 时，未取得 server render 必须标 `token_render_visibility=unavailable`，不能把 HTTP body 当最终 token 序列。依然可以通过 body 证明材料已送到服务，不能证明模型内部注意力。

所有辅助 LLM purpose 也登记，尤其 compaction、session title、评分、query rewrite。V1 禁用无用标题调用；发现意外云请求直接 FAIL。

native reasoning 的展示标题为“模型返回的 reasoning”，不是“真实心理过程”。monologue 标“角色持久独白”。audit 不要求获取服务端没有提供的 hidden state。

## 4. 操作界面最低要求

必须实现 CLI inspect 与不依赖公网的静态 HTML trace：

- 时间线按阶段/任务折叠；区分真人输入、内部控制、独白、工具、公开输出。
- 点击阶段查看实际 prompt、选中记忆、未选中原因、模型参数、耗时、tokens。
- before/after compaction 并排或文本 diff，保留引用和摘要原文。
- 显示人格/关系版本差异、原因与来源；显示 pending/committed/conflict。
- 显示消息 RECEIVED / READY / DELIVERED / UNKNOWN，不把生成等同发送。
- 错误与缺数据有明确标记，不以空白格掩饰。可导出机器 JSON。

HTML 必须转义用户/模型/工具文本，不能执行嵌入 script；不得加载 CDN。审计页面是操作者视图，不部署给群成员。以后外部 adapter 只能读取公开消息 API。

## 5. 重放和差分

`state-only replay` 只读事件、重建投影到新库，不调用模型、工具或发布；比较 persona head、关系 head、任务终态、送达集合和引用完整性。

`model-rerun` 从固定实际 request 重新生成，输出独立 attempt 和区别，默认不触发外部副作用。不能覆盖原 trace。用 fake tool ledger 时记录 `tool_mode=replay`。

`counterfactual` 明确指出修改了哪个因素：persona/model/memory/noise/compaction。只改一个因素的实验不应同时更换 sampling、重置关系或多塞回忆。

## 6. Codex 报告

使用 `reports/report.template.json` + `report.md`。每个测试 result 包括：test_id、status、mode、attempts、executed_at、environment_ref、fixture_hash、commands/exit_codes、metrics、assertions、evidence_paths/hash、failure_category、minimal_repro、limitations。

每项结论必须配：

- `what_works`：限定范围，引用 PASS tests。
- `what_fails`：已复现反例，不把原因猜测写成事实。
- `not_tested`：为什么没测，包括人工盲评缺失。
- `design_deviations`：Python→TS、不同压缩策略、降级检索、模型变更等。
- `next_smallest_experiment`：针对最大未知的一项最小验证，不建议一次重写全部系统。

失败分类：CONFIG、DSH_API、MODEL_PROTOCOL、PERSONA_ADHERENCE、MEMORY_RETRIEVAL、COMPACTION_LOSS、TOOL_EXECUTION、PRIVACY_POLICY、DURABILITY、CACHE_TEMPLATE、RESOURCE_CAPACITY、AUDIT_GAP、EVALUATION_INSUFFICIENT。

禁止将失败自动归为“模型弱”。例如人格未入请求是 CONTEXT/实现问题，不是 persona adherence 的有效反例。

## 7. 验收完成门槛

证据包至少含 environment/lockfiles、原始 fixture hashes、所有 case result、失败/重试全部 attempt、匿名角色输出、人工评分原表、prompt和压缩样本、真实 vector 证据、cache/latency 原始数据、脱敏数据库 schema/index、恢复重放结果、报告。

raw private traces 仅留操作者本地；给远端模型或本聊天回传报告前显式 redacted export。synthetic canary 在测试报告中可保留以验证断言，实际凭据和私密聊天必须移除。

报告模板初始全部 NOT_RUN。文档生成方仅验证本包结构与工具脚本，未连接用户本地 DSH/Mongo/模型；Codex 不得沿用本包检查结果冒充任何 live 验收。
