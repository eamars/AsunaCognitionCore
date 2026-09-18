# 03 · 推荐实现与 Codex 执行计划

## 1. 语言决策

**默认：Python 负责认知控制/状态/检索/测试，TypeScript 仅负责 DSH 进程内扩展。**

DSH 的 Python SDK 已提供 subprocess JSON-RPC 驱动、显式 DSH_HOME、profile/patch 和事件通知；但 Python 客户端不是任意 Cordis 内部能力的自动映射。[S1]

因此先实现 `DshLane` adapter，业务代码不直接依赖 DSH 的事件细节。两个长寿命 runtime 分别绑定 qwen/gemma。每个 lane 一个 SDK worker，阻塞 SDK 调用放专用线程，不能阻塞 Python ingress 事件循环。异步调用支持与取消具体以实际 SDK 探针为准。

本地 TS bundle 提供：角色完整 prompt/工具白名单；所需动态上下文 hook；压缩策略；可靠事件采集；最小自定义控制 RPC（必要时）；受控工具定义。不把业务 MongoDB 写入搬到插件中形成第二个状态机。

若 SDK 不支持必要的 per-session lifecycle、显式模型路由或 custom operations，不反复 hack。先写 ADR-001，用 TypeScript 控制整个 V1 也可；数据库/协议/验收不变。选择单一路径实施，不同时建设两个后端。

推荐依赖类别：Python 数据校验、MongoDB 当前受支持 driver、HTTP/local RPC、pytest；TS 使用 DSH 匹配版本的依赖和 schema validation。Codex 固定具体版本并提交 lockfiles，不照抄旧项目依赖。安装环境隔离，不全局升级现有 DSH。Python SDK默认带同版本runtime wheel；必须明确使用其匹配runtime，或经兼容性探针验证的指定dsh_bin，不能假定它自动使用用户当前全局DSH。优先冻结用户已验证的revision；需要不同SDK/runtime版本时保留对照和ADR。

## 2. 阶段 0：本地能力核实（开发前置，不以文档代替）

输出 `reports/environment.json`、`reports/integration_probe.md`、`config/resolved.redacted.json`。

核实事项：

- 当前操作系统/容器边界、DSH 二进制与源码位置、版本/commit、profile、是否有本地修改。上传日志中 `/usr/local/lib/node_modules/@deepseek-ai/dsh/` 是历史线索，不是当前必然路径。
- Python SDK 和选用 runtime 能否精确对应；显式 DSH_HOME；不自动载入用户生产 `~/.dsh` 或旧工作区 AGENTS/skills。
- 两个真实 endpoint 的 provider/model id。日志里曾出现 `local-qwen38-flash` / `qwen38-next-uncensored-freetoken-vision` 与 `local-gemma4-4090-only` / `gemma4-26b-a4b-it-qat-vision-262144-qat-mtp`，只作为定位线索，不自动使用或宣称等同于官方原始权重。
- 对每个 endpoint 记录 served model、量化、MTP、tokenizer/chat-template hash、thinking mode、KV 格式、并发资源组、实际 context capacity、采样参数及未知字段。实际定制权重必须标 `deployment_variant`，不把测得行为归因于整个模型家族。
- 普通输出、reasoning-only、原生 tool call、错误后继续、stop/length 区别、中文 stop sequence、monologue→decision→speak 连续请求。
- provider 级实际请求是否可捕获；捕获必须覆盖主生成、摘要、重试及辅助调用。仅拿 prompt builder 的预期文本不足以通过。
- 新旧 session 恢复、下轮投递、进程重启、手动 compaction、压缩失败无破坏。DSH 的 followup 是投递不是任务完成句柄；由 adapter 建立对应回执。[S2]
- 向量 Mongo、embedding、索引/过滤、写关注和 CAS。
- 工具子进程沙箱证明：不能访问旧项目、凭据、审计库、publishing endpoint、宿主网段。禁止在真实设备上试攻击，使用本包的合成 canary 文件/伪密钥。

缺一项就明确 PASS/FAIL/BLOCKED，不以“理论支持”通过。0 阶段不允许破坏现有配置。Mongo 未就绪可继续 mock 开发，但 LOCAL_DEPLOYMENT 不能通过。

## 3. DSH 适配地图：真实接口与本项目接口分开

| 需要 | 上游已核对的概念 | Asuna 必须实现/验证 |
|---|---|---|
| Python 长寿命调用 | `DeepSeekHarness`、profile/patch、独立 DSH_HOME | lane 生命周期、session ownership、超时和取消 |
| 角色无默认 assistant prompt | `PromptSection.complete` | 角色显式 composition；禁止继承 coding instructions/skill catalog |
| 状态更新追加 | `PromptContext` | scope-aware snapshot、版本冻结、实际投递证据 |
| 逐步投递 | `followup / inject / steer / send` | stable message IDs、phase/task receipts、去重/reconciliation |
| 角色压缩 | `BasicCompactionEngine.summarize()`、compaction interface | 角色模板、episode-balanced range、审计、失败回滚 |
| 固定 presets | agent-presets composition | character/executor 两个独立 preset，不在已有对话中切换 |
| 实际模型调用审计 | provider/LLM streaming 扩展与持久 events | 捕获 prepared request、compaction 辅助调用和原始返回 |

上表只声明上游存在这些概念，不给出未经运行验证的插件注册代码。Codex 要在 pinned checkout 中找到对应类型，编译小探针，并把文件/符号/行号写入 integration report。不得伪造 `agent.onMessage`、`session.compact()` 等便利 API。

注意：`agent/request` 不能任意突变消息；模型可见内容要走已记录的输入渠道。[S2] `complete` prompt 只覆盖 prompt sections，不自动撤销动态贡献与工具。[S3] 默认压缩的辅助 LLM 请求不一定经过普通 request hook。[S4]

## 4. 仓库建议

```text
asuna-ai-cognition-core/
  pyproject.toml / uv.lock (或等价锁文件)
  src/asuna/
    coordinator.py        # 事件/episode 状态机，唯一 owner
    dsh_lane.py           # SDK 与本地插件适配
    state.py              # Mongo 读写/CAS/恢复
    context.py            # 注入/预算/快照/权限
    retrieval.py          # embedding + vector/lexical
    publish.py            # outbox 与幂等模拟通道
    audit.py              # 调用/事件/导出/回放
    cli.py                # 下文的命令
  dsh-plugin/
    package.json / pnpm-lock.yaml
    src/character-preset.ts
    src/executor-preset.ts
    src/compaction.ts
    src/audit-bridge.ts
    src/tools.ts
  config/ prompts/ schemas/ fixtures/
  tests/unit/ tests/integration/ tests/live/ tests/adversarial/
  reports/<run_id>/
```

这是职责结构，不要求制造一个类或进程对应每个文件。一个协调器、一个数据库实例、两个 DSH lane 足够。

## 5. 协议

### ExternalEvent（可信 envelope）

`event_id, adapter_id, scene_id, person_id, event_type, text, reply_to, mentions[], occurred_at, received_at, scope_key, policy_epoch`。

外部 text 可以包含伪 system、JSON 或 agent 名称，不能覆盖 envelope。V1 CLI 场景身份由 fixture manifest 注入，公开 HTTP 将来必须认证。

### Decision（Gemma 输出）

只让模型填 `next`、自然语言 `goal`、`constraints`、`recall_query`、`speak_before_action`。其余一律程序补齐。对应 schema 在 `schemas/decision.schema.json`。

控制协议和人格指令分开。stage STOP ≠ episode end。最多一次语法修复；修复后的内容同样保存，失败就 `FAILED_PROTOCOL`。修复不能悄悄把 delegate 改成 speak 来获得通过。

### TaskRequest（程序生成）

`task_id, request_key, episode_id, scene_id, requester_id, intent_revision, goal, constraints, raw_input_refs, allowed_capabilities, resource_scope, reply_route, persona_revision, policy_epoch`。

只能附必要原始输入和事实，不能只给角色转述；也不能附整个私聊/群历史。若 Qwen 需要额外事实，通过 scope-limited retrieval 工具，不得直接访问 Mongo。

### TaskResult（Qwen + 运行时证据）

`task_id, intent_revision, status, facts[], uncertainties[], unmet_items[], artifact_refs[], effect_receipts[], needs_decision`。模型返回报告不自动代表验证通过，程序把执行回执/验收结果作为独立字段。native stop 但无合法结果时最多一次提醒补交，仍失败则 FAILED_PROTOCOL，不无限继续。

### MutationProposal（角色可写）

`entity_key, base_revision_id, scope_key, change_class, changes, reason, source_ids`。模型不填授权凭据、审核结果或 policy_epoch。程序拒绝未知路径、scope 扩张、基础版本过时与非 global-safe 来源的全局提升。反思外层使用 `schemas/reflection.schema.json`，明确区分 no_change 与 propose；不能把合法不修改当作坏JSON或强制模型修改人格。

## 6. 工具与资源

第一版提供两类工具：

**可确定验证的 fixture 工具**：`fixture.lookup`、`fixture.read_resource`、`fixture.run_checks`、`fixture.stage_copy`、`fixture.commit_copy`。允许 schema error、超时、失败、重复结果、延迟等预设故障。所有工具记录输入/输出/receipt，禁止返回标准角色答案。

**真实本地代码任务工具**：独立 task workspace 内 read/write/edit/grep + sandboxed command。用固定小 Python 工程修复错误并跑测试。不能把模型绑定到一个理想固定工具序列；只验证最终正确产物、必要约束与证据。

文件路径、命令与工具参数由程序权限检查。代码执行环境可用容器/合格沙箱，网络默认关闭，环境变量白名单。不要直接给 Qwen unrestricted host bash，然后声称它看不到 Mongo URI。

发布不作为 Qwen 的工具。角色模型也不直接调用 platform SDK；只有 SPEAK 验证通过后的程序路径发送。

## 7. 执行阶段

### M0：发现与锁定

完成上述探针；建立干净 test profile。输出能力表与阻塞项。确认两个模型各至少一次真实调用，向量库至少一次 scope-filtered 真查询。尚未满足也可继续写 mock，但不能跳过状态标记。

### M1：确定性骨架

Mongo schemas/indexes、身份/场景、消息去重、episode/task CAS、publish outbox、审计记录、fake clock、fake lane。通过所有 ENGINEERING unit/integration 后提交。恢复测试至少在任意阶段 kill/restart 一次。

### M2：真实角色回路

Gemma 无通用工具、人设自动注入、独立 monologue、微协议 decision、speak、静默。保存每次 prepared request。不能先用 Qwen 把 Gemma 意图解成 JSON 才跑起来。

### M3：真实工具融合

Qwen 执行 lookup、文件副本与代码修复任务；Gemma 先形成意图后行动、结果返回后表达。完成 cancellation、partial/blocked、结果重投、多场景公平调度。

### M4：记忆、关系、演化

chat chunks、真实 embedding/vector、scope 再校验、monologue 召回、关系比较、全局/私域修订、冲突/回滚、删除失效；执行一次 fake-day reflection。保持测试 fixture seed 不被 agent 改动。

### M5：压缩与故障

两侧实际 DSH compaction，不同周期/不同次数、摘要失败、资源冷切、Mongo/endpoint 不可用、crash/replay。未运行的 native summary 不允许伪造事件补齐。

### M6：模型归因与压力矩阵

冻结 config，运行所有 formal suites，导出匿名角色对照给人工评分；记录未通过/待人工项，不先调人设到某一条输出漂亮。每次变更另建实验。

每一阶段给 `what_works / what_fails / not_run / deviation`。最终不以“实现文件齐了”替代验收。

## 8. 必须实现的 CLI（本包不提供这些命令）

```bash
asuna doctor --config config/local.yaml --out reports/env
asuna db-init --config config/local.yaml --database asuna_v2_dev
asuna seed --fixture fixtures/world.json --database asuna_v2_test_RUN
asuna run --scenario fixtures/scenarios.jsonl --case P01 --mode live --out reports/RUN
asuna inspect episode EP_ID --format html --out reports/EP_ID.html
asuna inspect request CALL_ID --view provider
asuna compact --lane character --scene dm-a --reason acceptance
asuna reflect --scope global-safe --clock 2026-09-20T00:00:00Z
asuna replay TRACE_ID --mode state-only --deny-model-and-tools
asuna evaluate --suite engineering --manifest fixtures/acceptance_cases.json --out reports/RUN
asuna evaluate --suite live --manifest fixtures/acceptance_cases.json --out reports/RUN
asuna evaluate --suite attribution --config config/experiments.yaml --out reports/RUN
asuna evaluate --suite long-context --config config/experiments.yaml --out reports/RUN
asuna report --run RUN --out reports/RUN/report.json
asuna export --run RUN --redacted --out reports/RUN/evidence.zip
```

`--mode mock` 必须与 live 输出目录和结果标签分离；命令必须输出 test_id、attempt、evidence path、结果和 exit code。doctor 不能输出原凭据；inspect 默认操作者权限。不存在的 case/test id 应失败，不应静默运行默认样本。

## 9. 停止/降级原则

缺核心 persona、ACL 不确定、无法审计真实请求、数据库写入失败、协议不可解析：暂停对应 episode，不让通用助手替代角色答复。可在操作台显示系统错误，但必须标 `system_notice`，不得冒充小满。

向量服务暂时失败：可用有标记的近期精确回忆降级；正式 RAG 验收不通过。模型 OOM：记录容量/配置与最小失败请求；不静默缩短到 32k 然后报告 262k 正常。

任何 cloud fallback、隐藏 summarizer、未授权 native tools、真实发送 side effect 都视为验收阻断。不要绕过失败的沙箱检查。
