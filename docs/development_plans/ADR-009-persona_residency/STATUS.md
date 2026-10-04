# ADR-009 实施状态

> 实施者追加的进度记录（IMPLEMENTATION.md「文档更新」允许）。不含个人数据。
> owner 授权（2026-10-04）：ADR 仅作参考，与现实冲突时以实施者的专业判断为准，偏离逐条记在下面；测试库用后删除；真实库仅用于测试、不可清空。

## 总览

| 阶段 | 状态 |
|---|---|
| P0 卫生与地基 | 完成（见下方报告） |
| P1 人格契约 v2、人格模型、政策存储 | 完成（见下方报告） |
| P2 文档层、渲染、WRITE 阶段、人物档案 | 完成（见下方报告） |
| P3 情感引擎 | 完成（见下方报告） |
| P4 记忆扩展、人格数据 API、探针、人格作业、导出 | 完成（见下方报告） |
| P5 调度对齐、节律、心跳、沉淀、表达、显著度 | 完成（两部分报告见下方；人工检查见第二部分） |
| P6–P7 | 未开始 |

## 基线（`549beb4c`）

- DSH 固定版 `0.2.0-rc.2`；DSH_ALIGNMENT §2 各项在依赖树中逐项复核：`systemPrompt.section({complete})`、`context()`、`suppressRuntimeContext()`、`includeHarnessIdentity`、`MIN_EVERY_INTERVAL_SECONDS = 60`、`daily`/`weekly`/`cron` 与 `schedule_update`、`agent.inject`/`runMaintenance` 均存在，签名与 ADR 一致。
- 基线测试：pytest **34 failed / 137 passed**（隔离工作树 + 真 Mongo），JS **10/10**（publication 用例在隔离树里因 `.runtime` 缺失失败，与代码无关）。
- 基线失败的主要原因：固定名测试库在同一次运行内被多个用例复用，夹具行共用 `mutation_id: "seed"` 撞唯一索引；其余是陈旧用例（引用已不存在的 `ToolBroker.server`、`ContextBuilder(skill_catalog=…)`、CLI `run` 子命令、`declared_status` 等）。

## P0 报告

```text
阶段：P0
提交：见本提交（单个提交）
完成：
  T0.1 PASS [离线] 无 docs/ 的副本中导入 coordinator/tasks/memory/native_worker；prepare_resources 不调 npm，产物含 decision.schema.json 与全部核心 prompt
  T0.2 PASS [离线] git grep docs/development_plans -- src packages tools/pack_plugins.py → 0
  T0.3 PASS [离线] 会话类真值表；群→本机场景链接被拒（LINK_PRIVACY_DOWNGRADE），本机↔owner 私聊链接保留；宿主启动路径调用该过滤并写审计
  T0.4 PASS [Mongo] 70 KB 合成人格：episodes 无 system，有 system_ref{persona_doc_revision, voice_doc_revision, common_sha256, render_sha256}，BSON ≤ 64 KB；带旧 system 字段的在途回合用原文续跑
  T0.5 PASS [JS] 角色系统提示与 worker 渲染逐字节相同；无 harness 身份句与运行时上下文；普通会话两者仍在
  T0.6 PASS [Mongo] 群场景任务的行动脑系统提示不含合成人格正文任何句子，只含显示名
  T0.7 PASS [离线] terminal/chat/prompt-toolkit 为 0；uv lock --check 通过；AGENTS.md 新条文在
  T0.8 PASS [离线] 扫描器用例 11/11；--all 跟踪文件 0 命中（只报告范围另计）；.gitignore 条目在
  T0.9 PASS [离线] 核心目录无人格名；核心 prompt 无指代人格的性别代词
  T0.10 PASS [离线] 未设时区 → UTC 且注明「未设置时区，以 UTC 显示」；无缺省时区常量；设了 timezone 时行为不变
  T0.11 PASS [离线] --profile asuna-demo --config 解析出演示 profile/配置/库名；不带参数与现行相同；环境变量同效
  T0.12 部分：pytest 17 failed / 153 passed（基线 34 failed）；剩余 17 条在基线上全部已失败（清单见下），无新增失败。JS 11/11。
反证：tests/adr009_p0_cases.py 全部 9 条与 JS T0.5 在基线 549beb4c 的隔离工作树上失败（缺 visibility 模块、runtime-manifest 引用设计文档、prompt-toolkit 仍在、harness 句仍在系统提示中等）。
删除（为何无人调用 → 验证）：
  - src/asuna/{experiments,reporting,review,review_material,review_scores,legacy_evidence,doctor,retrieval_trials}.py 与 CLI doctor/report/export/review-*：只服务 ADR-001 验收、依赖设计文档包；`git grep -nE "retrieval_trials|review_material|review_scores|legacy_evidence|from \.experiments|from \.reporting|from \.doctor" -- src tests tools` → 0
  - MemoryService.reflect/proposal 与 reflect.md、reflection/mutation schema：无运行时调用者（REFLECT 走 commit_understanding）；m4 的 E19 改为直接走同一 CAS 路径 Store.mutate，不变量保留
  - chat.terminal/chat/new_context/compact/trace 与 prompt-toolkit：R-2；test_chat 中 compact 专属用例删除，其余两条改为断言持久化记录（phase.output、episode.failure）
  - native_worker 的旧 lane 锁 runtime.lock 与 prompts_dir 覆盖：旧 lane 已退役、prompt 只读包内资源
  - tools/：ADR-001 证据/诊断脚本（assess_engineering、audit_finish_reasons、capture_paused_native、diagnose_*、finalize_*、probe_{cache,compaction_audit,effect_fence,evidence_export,export,git_bytes,isolation,native_atomicity.py,report_observations,review_scores,revision,rollback,scope,m0,retrieval,coordinator}、record_retrieval_correction、refresh_environment、run_checks）、一次性补丁工具（p2/p2b/p3/p5 make/apply、p2b_edge_probe、p2b_probe_loop、repair_asuna_event_envelopes.mjs）、人格专属/含个人标识工具（import_persona_resources、probe_embedding_host、以群号命名的检查脚本、discover_connections）
  - m9 的独立评审用例、m10 的 E07 provider_finish 用例：专属于已删模块
  - config/prompts/（含 persona_local.md）；config/ 下三个以群号命名的文件移出版本控制（git rm --cached）并忽略
偏离：见下方「决定与偏离」D0-1…D0-11
未验证：真实 QQ、真实人格 profile 未启动（不需要）；沙箱用例本阶段无
人工检查：演示环境（asuna-demo profile、asuna_v2_demo_main、无渠道）中经原生 composer 发言，角色回答；Trajectory 的 Initial System Prompt 以核心中性头「共同约束」开头、紧接合成人格段，无 harness 身份句。截图未入库。
下一步：P1 — registerPersona v2 校验与 persona_model.py / policy.py。
```

### 保留的 tools（均可导入或 `--help` 正常）

| 脚本 | 用途 |
|---|---|
| adr009_offline_check.py | ADR-009 离线检查入口 |
| check_staged_secrets.py | 提交前密钥扫描；`--personal` 个人数据告警 |
| make_demo_config.py | 生成被忽略的演示配置 |
| pack_plugins.py / setup_native_profile.py / asuna-launch.mjs | 打包、安装 profile、启动 |
| check_dsh_release.py、check_mongo_host.py | 维护诊断 |
| fingerprint_embedding.py、fingerprint_models.py | 模型/嵌入服务指纹（维护） |
| p1c/p2/p3/p5_offline_check.py、linked_scenes_offline_check.py、read_image_offline_check.py | 既有离线测试基建 |
| probe_blob.py、probe_host_seam.py、probe_integration_lifecycle.py、probe_integration_transport.py、probe_sandbox.py、read_search_deployment.py | `--debug` 级隔离探针 |
| probe_native_atomicity.mjs、probe_native_schedule.mjs、probe_plugin_install.mjs | 原生 Host 探针 |

### 基线即失败、仍失败的 17 条（未在 P0 修复）

test_consultation ×2（`task_status` 能力、`ToolBroker.server`）、test_engineering_m10 E05/E12_E13、m11 CLI `run`、m7 两个崩溃点、test_p2_summary_loop ×5（真库路径的陈旧断言）、test_p3_schedule reschedule、test_p5 topic_is_derived、test_skills（`skill_catalog` 参数）、test_workspace_tasks ×2（`declared_status`）。它们是 ADR-001/005 时代的陈旧用例，与本 ADR 改动无关；计划在 P7 收尾时连同夹具模式一并清理或改写。

## P1 报告

```text
阶段：P1
提交：见本提交
完成：
  T1.1 PASS [JS] 合成包 @asuna/demo 与已安装人格包都按契约 v2 注册；不装人格时 ready() 报「Select an installed Asuna persona」，Core 惰性。演示环境中 v2 demo 包经 worker 校验模型后完整跑通一个 Web 回合
  T1.2 PASS [JS]+[离线] 模型 persona.id 不符 → PERSONA_ID_MISMATCH；模型不合 schema → PERSONA_MODEL_INVALID（带路径）；不可读 → PERSONA_MODEL_UNREADABLE；Core 惰性、显示原因，其他已注册人格不受影响
  T1.3 PASS [Mongo] 政策写入带 what 并生成修订（理由、作者、父修订）；secret/counter → POLICY_CLASS_REFUSED；缺 what 被拒；未声明键、超范围值被拒；并发同基修订恰好一个成功、另一个 BASE_REVISION_STALE；同 mutation_id 重放幂等
  T1.4 PASS [离线] 生效值 政策 > 模型 > 核心缺省；包给私有键默认值或在 policy_keys 声明私有键/核心可写键 → 拒绝；时区 政策 > 全局配置 > UTC（明示）；自开发间隔 政策 > 本地 every_seconds > 模型 > 1440
  T1.5 部分 PASS [Mongo] 政策按人格 id 隔离（另一人格的键不可见、不可写）。文档/情感/记忆的隔离随 P2/P3/P4 各自的存储补测
  T1.6 PASS [JS] model、seeds、jobs、skills 相对已发布产物根解析；未发布时相对包根
反证：adr009_p1_cases 4 条与 persona.test.js 3 条在基线上全部失败（无 persona_model 模块、registerPersona 不校验、floor 写死 persona/core.md）。
删除：floor.js 写死的 persona/core.md 改写
偏离：D1-1、D1-2（见下）
未验证：已安装人格包在真实 profile 上的启动（未启动真实 profile）
人工检查：演示环境 v2 包回合成功（P1 无 ACCEPTANCE §4 条目）
下一步：P2 — DocumentStore 与 persona:<id> 头的转换。
```

## P2 报告

```text
阶段：P2
提交：见本提交
完成：
  T2.1 PASS [Mongo] 同基修订、同文档并发追加：恰好一个成功，另一个 BASE_REVISION_STALE，无丢失更新
  T2.2 PASS [离线] public 会话只含 public+always 节；owner_private 两类都含且 public 在前；on_demand/never 不出现；上下文块按 recall_protocol.order，缺省为核心顺序，不丢键
  T2.3 PASS [离线]+[Mongo] 让渲染变大且超预算的修改被拒（PERSONA_RENDER_OVER_BUDGET，带估算值），头不变；变小的修改被接受；已超预算时渲染完整（与无预算渲染逐字节相同）、回合照常完成、写 render.over_budget 审计，记忆右栏标红
  T2.4 PASS [Mongo] 档案注入：owner 私聊 = 前言 always 节 + 最近 N 条 injectable 条目 + 可注入条目标题索引；群聊无；行动脑无；未标 injectable 的条目从不自动注入
  T2.5 PASS [Mongo] 档案条目 replace_section → DOC_OP_NOT_ALLOWED；correction 追加引用原 sid 的节，原条目字节不变
  T2.6 PASS [Mongo] 伪 lane：DECIDE write_docs(append_section) → WRITE 阶段 → 提交，SPEAK 的「程序已提交的结果」含 write_docs 摘要与 rejections；set_tags 不产生 WRITE；无效意图进 rejections、回合照常 SPEAK；群回合 write_docs 全拒（DOC_WRITE_REQUIRES_OWNER_PRIVATE）
  T2.7 PASS [Mongo] next=recall + read：可读节原文进入 recall 上下文；public 会话读 owner_private 节被拒并记录
  T2.8 PASS [Mongo] 旧 persona:<id> 头 + 包内种子并存 → 转换而非种子，正文等于旧头；之后回合的 manifest 记录文档修订 id，system_ref 带 render_sha256
  T2.9 PASS [离线]+[Mongo] 种子只在头缺失时导入、重启不覆盖；sid 生成确定（同名加 -2，CJK 保留）；front-matter 覆盖生效、未知 sid 列出；adopt_seed 按 sid 合并，双方都改过的节列为冲突不覆盖
  T2.10 PASS [Mongo] 行动脑系统提示只含 public 且带 values 标签的节；owner_private 节与无标签 public 节都不出现
反证：adr009_p2_cases 与 test_adr009_p2 在基线上无法导入 documents 模块而全部失败；T2.6 前的基线决策 schema（additionalProperties:false）会把整条带 write_docs 的决策判为 BAD_DECISION_JSON。
删除：无
偏离：D2-1…D2-7（见下）
未验证：真实人格 profile 未启动
人工检查：演示环境中「文档」出现在记忆右栏，每节带可见性/注入/标签标注；在 owner 本机对话里请角色记下一件事，角色经 DECIDE write_docs → WRITE 追加了 dossier:demo-owner 的条目（owner_private、带 entry_date），右栏出现新修订
下一步：P3 — affect.py（事件、修订、提案、投影），先对齐参考实现。
```

## P3 报告

```text
阶段：P3
提交：见本提交
完成：
  T3.1 PASS [离线] 黄金夹具 affect-events.example.json 全部期望点误差 < 1e-6；自建 36 条合成事件（种类半衰期、事件自带半衰期、缺省、挂账、已关闭、作废、fix_ts/fix_kind、钳位、活跃度半衰期、5 种时区偏移含 Z）在两种 close_mode × 60 个时刻（共 120 点）上与参考实现逐点一致，贡献明细顺序与 describe() 输出也一致
  T3.2 PASS [离线] 同一已关闭挂账事件 from_close 与 retroactive 给出各自定义的值；ts > t 不计入；负半衰期被拒；kind_floor 过滤 top_kinds；无偏移时间被拒
  T3.3 PASS [Mongo] DECIDE affect 合法条目提交：宿主时间戳、origin=asuna、source_scope 按会话类；ref 不在 ref_index / require_cost 下缺 cost / 超 max_delta / 未知 kind 各自被拒，回合照常完成
  T3.4 PASS [Mongo] owner 私聊提交的事件，其 why/ref/who/cost 与 owner_private 倾向在随后群回合的上下文、群回合系统提示、行动脑提示中都搜不到；群回合只见 label、public 倾向与 public 档位
  T3.5 PASS [离线]+[Mongo] affect.py 无 delete/replace/update/find_one_and_* 与 Store.put 写入；Store.put 对 affect_* 拒绝；void 缺 why 被拒；operator 擦除写 by=operator 的 void 修订，投影随之归零
  T3.6 PASS [Mongo] 伪评估路由阻塞至放行：回合在提案返回前已 COMMITTED；放行后提案入库，带 source_scope 与 ref_index 快照，下一回合上下文出现 affect_proposals_from_program；提案字段集合不含任何台词字段；accept 以快照通过 ref 闸门；过期提案明示 expired 并写入决定记录
  T3.7 PASS [Mongo] affect.import 同批两次第二次新增 0；同 source_identity 内容变 → EVENT_IMMUTABLE；源中新增 void → 恰好 1 条修订（重放为已存在）；fix_kind 缺 value 被拒；导入保留自带半衰期与原始时间串
  T3.8 PASS [离线] bands/policy 首个命中，覆盖等号两侧边界
反证：adr009_p3_cases 与 test_adr009_p3 在基线上无 affect 模块；基线决策 schema 把带 affect 的决策整体判为 BAD_DECISION_JSON。
删除：无
偏离：D3-1…D3-4（见下）
未验证：评估路由的 JS 原生会话（asuna-appraiser-<persona>）未在真实模型上运行——演示环境未配置 appraiser 路由；Python 侧异步路径由 T3.6 覆盖
人工检查：演示环境中角色在一次致谢后经 DECIDE affect 提交了一条 gratitude 事件（source_scope=owner-private:demo）；记忆右栏「情感」显示当前投影（label/val/arl/挂账数）与最近事件。此前一轮缺 cost 的提交被 require_cost 闸门逐条拒绝、回合照常。群场景 Trajectory 只见档位一项由 T3.4 覆盖（演示环境无渠道）
下一步：P4 — memory_units 新字段、owner-private 检索、persona_data.py 与探针。
```

## P4 报告

```text
阶段：P4
提交：见本提交
完成：
  T4.1 PASS [Mongo] 导入条目带文件 source_window；源文件改动并删除后，快照回读逐字节等于导入时内容；快照 scope=owner-private:<persona>，非 operator 读取被拒；同 sha 去重
  T4.2 PASS [Mongo] owner-private 记忆单元在 public 检索中出现 0 次，连词法候选都不是；本机向量检索可用，向量路径也一并覆盖；owner-private scope 不能作为普通或联动 scope 传入
  T4.3 PASS [Mongo] 同一写请求两次第二次为空操作；dry_run 前后各集合计数不变，计划数与随后真实执行一致
  T4.4 PASS [Mongo] cohabiting：宿主未改 → 按源更新；角色改过（头 ≠ import_base）→ conflict 不覆盖；只追加类按 origin+source_identity 并集；cutover → SOURCE_CUTOVER、计数不变；跨人格 → PERSONA_SCOPE_DENIED
  T4.5 PASS [沙箱] WSL bubblewrap 中：看不到 /mnt/c、只见授权源根、网络不可达、/out 超 64 MB 判 error；跨人格请求得 PERSONA_SCOPE_DENIED；超时强杀判 error（直连启动器跑协议部分）
  T4.6 PASS [沙箱]+[离线替身] 合成自迁移：试运行未登记文件为红、退出码 1、零写入；补全清单后正式导入；按私有题库探针校验：可答题的锚点出现在 probe.retrieve(as=owner_private) 前 6，超范围题记 NOT_RUN(scope)；重跑为空操作。沙箱与直连两种启动器各跑一遍
  T4.7 PASS [Mongo] 导出：工作树内未忽略路径被拒；工作树外或被忽略路径接受；内容只有文档层，每节带修订 id 与可见性
  T4.8 PASS [Mongo] invented=true 的条目在探针摘录与回合上下文中总带固定标记
  T4.9 PASS [Mongo] persona_job_run 只随开发授权授予；工具返回值只含 run_id/job/status/exit_code/dry_run/counts/report_artifact_ids/reason，报告中的合成摘录不出现
  T4.10 PASS [Mongo] coverage：向量时取最大相似度、仅词法时取覆盖比例；低于 coverage_floor 或无结果判 insufficient；RRF 不参与
  T4.11 PASS [Mongo] owner 私聊产生的独白在配置了（被拒的）链接的群回合上下文中出现 0 次
  T4.12 PASS [Mongo] 群场景任务的 CONSULT 系统提示与上下文中没有 owner_private 人格节
反证：adr009_p4 全部依赖新模块 persona_data/persona_jobs，基线上无法导入；基线 retrieval 没有 private_scope 与 coverage。
删除：无
偏离：D4-1…D4-6（见下）
未验证：真实人格的旧居与题库（属于人格本人，按 ADR 不在本阶段）
人工检查：演示环境设置卡显示源根（cohabiting，路径遮蔽）、作业与渲染预算状态；「试运行」与「运行」都经 WSL bubblewrap 执行并因未登记文件判红、退出码 1；记忆右栏「作业报告」可读红项；导入条目出现在右栏，展开后显示 source_window 与导入时快照的逐行回读
下一步：P5 — 先做 D-5（60 秒下限、原生 daily/weekly、schedule_update）。
```

## P5 报告（第一部分）

```text
阶段：P5（第一部分）
提交：见本提交
完成：
  T5.1 PASS [离线] 节律块按 IANA 时区与睡眠窗计算 in_sleep_window（含跨午夜）；since_owner_message_min 只在 owner_private；public 缺省无节律块，rhythm.public_clock=true 时只有 local_time；协调器与 chat 中无睡眠窗拦截路径
  T5.5 PASS [离线] recent_phrasing 对给定出站序列给出确定的 4-gram 列表（CJK 按字、其他按词，≥3 次、≤5 条）；无重复时为空
  T5.6 PASS [Mongo] 阶段起点先录制 tests/fixtures/retrieval_golden.json（固定合成语料与查询、词法路径）；权重全 0 时排序与黄金文件完全一致；加 pinned 权重后被钉单元在相关查询中排第一
  T5.7 PASS [离线] 自开发间隔 政策 > 本地 every_seconds > 人格模型 > 1440 分钟（T1.4 覆盖优先级函数）；schedule.py 中无写死的缺省间隔
  T5.8 PASS [离线]+[JS] every_seconds=60 通过、59 被拒，常量只在 schedule_rules 一处，DECIDE schema 与提示词从它取值；IANA 时区的 clock 规则映射为原生 daily/weekly（星期 0→1、6→7）；固定偏移时区仍走一次性重挂（原有驱动用例改在固定偏移下运行，期望的 UTC 时刻不变）；schedule.js 的 /schedule/update 调原生 schedule_update 并写 update 日志，对账不当成删除再创建
  T5.2 / T5.3 / T5.4 / T5.9 未做：心跳、夜间沉淀、多段发言与其崩溃恢复
反证：adr009_p5_cases 在基线上失败（无 rhythm 模块、下限为 300）；T5.6 的黄金文件在加入显著度之前录制
删除：schedule_rules 中 300 秒下限；schedule.py 的写死 86400
偏离：D5-1、D5-2（见下）
未验证：原生 daily/weekly 与 schedule_update 在真实 Host 上的到期派发（演示环境未建计划）
人工检查：未做（P5 的人工项依赖心跳与多段发言）
下一步：心跳（presence）计划与预闸门，然后夜间沉淀与多段发言。
```

## P5 报告（第二部分）

```text
阶段：P5（第二部分）
提交：见本提交
完成：
  T5.2 PASS [Mongo]+[离线] 心跳是 kind=presence 的原生 every 计划，只投递到 owner_private 目标（非 owner_private → PRESENCE_TARGET_NOT_OWNER_PRIVATE）；预闸门只有 BUSY（场景队列有待处理）、MIN_GAP（距上次心跳不足 heartbeat.min_gap_min）与 REST_WINDOW（仅当人格自选 heartbeat.skip_in_sleep 且处于睡眠窗），每次跳过都写 presence.skipped 审计；政策改 heartbeat.every_min 后经 schedule_update 原地改期，不删不建
  T5.3 PASS [Mongo] 夜间沉淀是 kind=settlement 的原生 daily 计划（rhythm.settle_at + IANA 时区；未设时区不建计划），同一本地日期只运行一次（SKIPPED:ALREADY_SETTLED）；沉淀回合的上下文带 settlement_from_program（未结情感事件、晋升候选、配额）；promote 只在沉淀回合可用（否则 PROMOTE_ONLY_IN_SETTLEMENT），检查每日配额（PROMOTION_QUOTA）与来源 ≥ min_roots 个不同回合且 ≥ min_dates 个本地日期（PROMOTION_SOURCES_INSUFFICIENT）；public 声明进 global-safe，其余进 owner-private
  T5.4 PASS [Mongo] speak.max_messages=3 时 SPEAK 按独占一行的 split_marker 切成 3 段，出站 <ep>:speak:0..2；渠道场景每段带 not_before，相邻间隔 = clamp(上一段字数 / chars_per_second, min_gap_s, max_gap_s)；claim 不返回未到时刻的段，也不越过尚未送达的前段（且不让后来的消息插队）；第 1 段回执 failed 后第 2、3 段为 CANCELLED_AFTER_FAILURE；max_messages=1 时出站行（键、文本、投递状态、无分段字段）与改动前相同；本地场景不排时
  T5.9 PASS [Mongo] 第 1 段发布后注入崩溃，recover 后按原键继续第 2、3 段、不生成新行；第 1 段处于 SENDING 时 recover_sending 按 SENDING→UNKNOWN 处理并取消后续段
反证：adr009_p5_cases 的 t5_2 在本部分之前失败（无 heartbeat_rest_gate）；T5.4/T5.9 用例在改动前无分段行
删除：decide_delta 中 promote 的 NOT_YET 拒绝
偏离：D5-3…D5-5（见下）
未验证：心跳/沉淀计划在真实 Host 上的到期派发（演示环境未配置 heartbeat_target 与 settle_at）
人工检查：未做（演示环境只有行动模型可用，且人工项依赖真实到期派发）
下一步：P6 — D-3 历史增量、D-4 审计/回执去重、D-6 mount_schedule、CONSULT 的 JS 测试。
```

## 决定与偏离

| 编号 | 决定 | 理由 |
|---|---|---|
| D0-1 | D-1 未使用 `section({complete:true})`；在角色作用域的 assemble 瀑布里把渲染结果设为唯一段，并 `suppressRuntimeContext()` | 固定版在瀑布**之前**求值 complete 段的文本（`assemble()` 源码），而 Web 输入的首个阶段（及其系统提示）只在瀑布内由 worker 接纳后才知道；complete 段会恢复为过期文本。效果与 ADR 要求相同，T0.5 覆盖 |
| D0-2 | CLEANUP §3 中依赖设计文档包的部分提前到 P0 删除 | 运行时脱离设计文档后它们无法导入。任务夹具模式（`TOOLS`/`RESULT_SCHEMA`/`finish`、`Coordinator.recover`、`Router.batch`）仍被大量用例使用，保留到 P7；`task_result.schema.json` 随之迁入资源目录 |
| D0-3 | 非缺省 profile 拥有独立 DSH_HOME、activation 与候选目录（`.runtime/adr008/profiles/<name>/`），floor 新增 `stateDir` 配置 | 共用会让演示环境的自开发发布选中 owner 的 core 产物 |
| D0-4 | `asuna-channel.local.json`/`integration.local.json` 只对 `config/local.json` 隐式加载；其他配置须用 `channel_config`/`integration_config` 显式指定 | 否则同目录的演示配置会继承真实 QQ 路由 |
| D0-5 | owner 的被忽略配置 `config/local.json` 补上原先由核心缺省提供的 `timezone` | 删除核心缺省时区后保持真实部署行为不变（T0.10 的后半） |
| D0-6 | 所有用例改为每例独立库并在结束时删除；固定名库加随机后缀 | owner 要求删除测试库；也修复了基线的串库失败 |
| D0-7 | `sessions` 绑定只存 `system_sha256`，不再存系统提示全文 | D-4 的同一目的；JS 侧从阶段请求取全文 |
| D0-8 | 技能工作区白名单放宽为 `.runtime/**/self-development/**` | 非缺省 profile 的候选目录在其 stateDir 下 |
| D0-9 | 人格包（含合成 `demo`）作为参数传给 `pack_plugins.py --persona` 与 `setup_native_profile.py --persona-package`；项目 id、preset 从包自身读取 | CLEANUP §8：核心工具不写死人格 |
| D0-10 | 演示环境的人工检查用 `--shared-action-model`（两条路由都指向行动模型） | 当时角色模型端点不可用；路由名不推断模型，不影响验证点 |
| D0-11 | `dsh plugin add` 需要 PATH 上有 pnpm；本机用 corepack 缓存的 pnpm 通过临时 shim 安装 | 环境事实，记录以便复现 |

| D1-1 | 完整 schema 校验在 worker `initialize` 中进行（Python jsonschema）；JS `registerPersona` 只做契约形状、路径不越界与 `PERSONA_ID_MISMATCH` 的同步校验 | DSH 侧没有 JSON Schema 校验依赖；两处任一失败都使 Core 惰性并显示原因 |
| D1-2 | 人格包里的路径（model、seeds、jobs、skills、persona_file）一律存为相对 `resource_root` 的路径，由 floor 按已发布产物根或包根解析为绝对路径 | 满足 PERSONA_CONTRACT §2.3；也让同一份贡献可在候选与已发布产物间切换 |
| D1-3 | 已安装人格包的人格正文原样从 `persona/core.md` 移到 `seeds/persona.md`（未改一字），模型只含 id 与显示名；核心与该包版本升到 0.2.0 / 对等依赖 0.2.x | CLEANUP §8 与契约 v2；不替人格取参数或标注可见性 |
| D2-1 | 运行时 decision-delta schema 的 `doc_ref` 放宽为 `^[A-Za-z0-9][A-Za-z0-9:_.-]{0,127}$` | `dossier:<规范人物 id>` 中的人物 id 不保证小写（测试夹具即为大写） |
| D2-2 | 档案 512 KB 滚动分卷未实现；单个修订仍受 1 MB 上限（DOC_REVISION_TOO_LARGE） | 当前没有接近该规模的档案；分卷不影响任何已定义测试，留作后续 |
| D2-3 | 角色 WRITE 未声明 visibility 的新节按 owner_private 保存，并在结果中可见 | 与数据 API 的缺省一致（§2.2），宁私勿泄 |
| D2-4 | 上下文头部加 `session_class` | 演示中角色在 DECIDE 里明确表示无法判断本回合能否写文档；这是程序事实，应当明示 |
| D2-5 | `affect*`、`promote` 在其引擎上线前被逐条拒绝（FIELD_NOT_AVAILABLE），不静默丢弃 | 失败语义：单项失败只记 rejections |
| D2-6 | `pin` 在 P2 先落地为记忆单元的 `pinned` 标记（须在本回合 ref_index 内且可读）；排序权重在 P5 | 协调器范围已列出 pin |
| D2-7 | 人物档案种子的缺省可见性为 owner_private（其他种子仍为 public） | §2.2「人物档案 缺省 owner_private」 |
| D3-1 | 提案的决定（accept/decline/edit/expired）以 `decision:<proposal_id>` 新文档插入 `affect_proposals`，而不是改写提案行的 status | 满足「affect_* 只插入、不更新」的静态检查（T3.5）；唯一 _id 保证一个提案只被决定一次。索引改为 `(persona, kind_row, created_at)` |
| D3-2 | 情感块附带 `commit_rules`（require_cost、max_delta、kinds、allow_untyped） | 演示中角色因不知道 require_cost 而提交被拒；这些是人格模型参数，不是私密内容 |
| D3-3 | 导入事件未声明可见性时 source_scope=`owner-private:<persona>`；声明 public 时为 `global-safe` | §2.2「导入：按写入方声明」；缺省从严 |
| D3-4 | 评估路由的设置项未加入设置卡；在 profile 的 `asuna-cognition-core.routes.appraiser` 中配置（与 character/action 同形，未配置即关闭） | 时间所限；行为与 §6.7 一致 |
| D4-1 | 人格作业用新的 `SandboxLauncher`（同一 WSL bubblewrap 环境，Popen 双向 stdio）而不是直接复用 `IntegrationRunner` | IntegrationRunner 管理常驻集成进程；作业需要双向管道与 run-to-completion。隔离参数一致：--unshare-all、只读代码与源根、仅 /out 可写、prlimit |
| D4-2 | 试运行时宿主对所有写方法强制 dry_run，不依赖作业自觉 | 「试运行不写」是宿主的保证 |
| D4-3 | `probe.retrieve(as=public)` 以一个不存在的场景 scope 检索，只看得到 global-safe | 契约只给 `as: owner_private|public`，没有场景参数；这是最保守的 public 视图 |
| D4-4 | `salience.ref_count` 与 `last_ref_at` 用计数器式 `$inc` 写入，不生成修订 | 计数不是状态修订；排序权重在 P5 |
| D4-5 | 设置卡新增「人格数据」：源根与状态、作业试运行/运行、导出、渲染预算；报告在记忆右栏「作业报告」 | ACCEPTANCE §4 P4；未做设置卡上编辑源根（源根只在本机配置中改，§6） |
| D4-6 | 演示环境的迁移清单文档由实施者写入演示库 | 合成人格 `demo` 没有自己写清单的历史；真实人格的清单由她自己写 |
| D5-1 | 原生 daily/weekly 的计划标 `native_recurring`，到期后不重挂，只前移 `next_fire_at` 并计 `fire_count`；改节奏时若新旧都是原生重复规则则用 schedule_update 原地修改，否则仍「先建后删」 | 与 D-5 一致，同时保留固定偏移时区与一次性计划的既有路径 |
| D5-2 | 生产库中已存在的一次性重挂式 clock 计划不迁移，继续按旧路径运行直到被改期 | 不改动在途计划；改期时自然切到原生规则 |
| D5-3 | 心跳与沉淀计划只在本机配置 `persona_runtime.<persona>.heartbeat_target` 指向 owner_private 场景、或人格模型有 `rhythm.settle_at` 且时区为 IANA 时才建立；建立失败写审计 `rhythm.plan_refused`，不影响启动 | 不替人格选目标或时刻；目标场景属于本机部署事实（§6） |
| D5-4 | 晋升的来源回合从 `context.prepared` 审计的 manifest 中计（记忆单元被选入的回合），本地日期按人格时区 | 「被 ≥2 个回合引用」需要一个确定、可审计的事实来源 |
| D5-5 | 分段的 not_before 只用于渠道场景；分段的后续段在前段未送达前不可被 claim，且排在队首时整条渠道等待 | 保证同一场景的出站次序；本地场景没有平台节奏需要模拟 |

## 给 owner 的待决事项

1. 人格包 QQ 适配器自检 `preview_readable` 现在期望占位群号；对着真实部署的预览文件会失败，需要改成从预览/配置读取期望值（属于人格包行为改动，未擅改）。
2. 公开前是否清理 git 历史与历史设计文档中的个人标识（扫描器对 `docs/development_plans/**` 其他 ADR 报告 78 处，只报告不改）。
