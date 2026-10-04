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
| P6 DSH 对齐（其余） | 完成（报告见下方） |
| P7 协调器拆分与遗留收尾 | 完成（两部分报告见下方；D-8 按 D7-5 处理） |

ADR-009 于 2026-10-05 完成并合并到 main（见文末「完成与后续」）。

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

### 基线即失败的 17 条（已在 P5–P7 全部修复，见 P7 报告）

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

## P6 报告

```text
阶段：P6
提交：见本提交
完成：
  T6.1 PASS [Mongo] 历史增量：sessions 行记 history_hwm（按来源场景）、history_generation 与 compaction_generation；私聊连续两轮，第二轮 delivered_history 不再包含第一轮已给出的行、第一轮的输入与她自己的回复（上下文附 history_from_program 说明省略数）；未唤醒的行在下一次唤醒回合中恰好出现一次；阶段结果报告的压缩代数 +1 后下一回合重发完整 12 条窗口；新的原生会话（如 Web 新建对话）没有游标，得到完整窗口
  T6.2 PASS [Mongo] 大于 16 KB 的文档提交后 audit_events 只存 {collection, id, revision, content_sha256, bytes}；哈希链照旧（verify）；新增 audit.verify_documents 按每个文档最近一次提交比对集合（内联按值、引用按 sha），手工篡改大文档或小文档都报 AUDIT_DOCUMENT_TAMPERED；replay 对引用提交需要 trace 附带的内容（缺最终修订时报 REPLAY_CONTENT_MISSING），CLI trace 导出 {events, contents}；phase.output 只存 content_sha256/bytes（reasoning 同样）；原生 lane_receipts 只存 {content_sha256, bytes, native_ref, blank}，同一 operation 重复请求由 Host 从已保存的阶段结果回答（不重新生成）并校验 sha
  T6.3 PASS [JS] CognitionCore 配置 mountSchedule（缺省 true）：false 时 Asuna 不挂载 Schedule，worker 以 schedule=false 初始化、计划功能关闭；true 且 Host 未安装时恰好挂载一次；已安装时复用
  T6.4 PASS [JS] CONSULT 阶段在空闲的角色会话中运行，行动工具仍在等待；返回值是真实的原生助手事件；结束后角色会话不等待下一阶段（无 waiter），随即可以接纳新的人类输入
  T6.5 PASS [JS] native-loop、publication 等全部 JS 用例通过（18/18）
反证：T6.1/T6.2 用例在改动前失败（无 history_delta 模块、state.commit 内联全文）；T6.3 在改动前无 attachSchedule
删除：phase.output 与原生回执中的全文
偏离：D6-1…D6-4（见下）
未验证：真实 DSH 会话中 compaction/end 事件计数随压缩增加（固定版的 dsh-compaction-basic 写入该事件，已读源码核实；未在演示环境触发一次真实压缩）
人工检查：演示环境（合成人格 demo，Web 界面，同一原生会话）连续两轮：第一轮无游标，给出完整窗口 11 行；第二轮 given 0 / omitted 12，会话游标前移；两轮回复都切题。原生回执只含 content_sha256/bytes 与 native_ref（session:seq），真实 DSH 报告 compaction_generation=0
下一步：P7 — D-8 拆分 Coordinator.advance；CLEANUP 剩余删除；T7.3。
```

## P7 报告（第一部分）

```text
阶段：P7（第一部分）
提交：见本提交
完成：
  T7.1 PASS [Mongo] 崩溃矩阵（crash_matrix_worker / crash_worker 与 m 系列）全部通过：m7 两个崩溃点的失败原因是子进程 worker 没有像 conftest 一样使用合成身份 character_id=demo，消息作者与恢复进程不一致（ONLY_CHARACTER_SPEAK_CAN_PUBLISH）；对齐后 7/7
  全套 Python 211 passed / 0 failed（基线 34 failed），JS 18/18，adr009 离线 37/37
  基线遗留失败全部处理：consultation ×2 与 workspace_tasks ×2 去掉已退役的 task_status 能力与 HTTP 工具代理；m10 E05 补 policy_epoch（与 m1 同名用例一致）、E12_E13 改为检查沙箱连不上本机 Mongo 端口；m11 去掉已退役的 `asuna run`，并以 UTF-8 读取帮助输出；skills 去掉已移交原生 DSH 的技能目录注入，保留挂载所有权断言；p5 topic 在测试内建群场景；p2_summary_loop ×5：audit_of 认真库、摘要事件在运行证据里、ep9 不能引用 ep1 的独白（守卫正确，用例数据陈旧）、samples 按 peer 间隔计
  CLEANUP 遗留配置键：删除 legacy_database（数据库仍受 allowed_databases 白名单保护）、transport_read_timeout_seconds、workdir、示例中的 local_only / publish_adapter
  T7.3（部分）：§10 的 6 项检查中 5 项为 0；剩余 task_mode/cli-fixture/runtime.lock 共 17 处（见「未做」）
未做（按专业判断留给 owner，理由见 D7-1…D7-3）：
  D-8 Coordinator.advance 事件驱动拆分与 T7.2
  夹具模式（task_mode 非 workspace 分支、cli-fixture、DECISION_SCHEMA 回退）的删除
  episodes.system 兼容与 persona:<id> 头读取路径的删除
反证：m7 两个崩溃点在对齐身份前失败（基线即失败）
删除：legacy_database 与上述无读取者的配置键；退役能力的陈旧断言
偏离：D7-1…D7-3（见下）
未验证：—
人工检查：未做（ACCEPTANCE §4 的整套人工检查待 D-8 之后一并进行）
下一步：owner 决定 D-8 的时机；生产库迁移（转换 persona 头、清理在途旧回合）之后删除 system 兼容与 persona 头读取
```

## P7 报告（第二部分，owner 裁决后）

```text
阶段：P7（第二部分）
依据：owner 裁决（2026-10-04 傍晚）——碍事的测试先删；不做数据迁移，旧兼容可直接删；人格包自检可以修
完成：
  夹具模式删除：task_mode 不再存在（工作区模式是唯一模式）；删除 tasks 的夹具 TOOLS/fixture_* 工具、RESULT_SCHEMA 与 TaskService.finish、task_status、inject_read_failures、非工作区执行分支；coordinator 的 DECISION_SCHEMA 回退；router 的 cli-fixture 标签、非渠道群的夹具安静路径与 Router.batch；task_result.schema.json
  旧兼容删除：episodes.system 读取兼容（阶段系统提示只从 system_ref 重渲）；persona:<id> 头的转换与 state 中 persona: 实体的变更/回滚入口（人格只是文档）；registerPersona.persona_file（契约 v2 必须有 kind=persona 的 seed，携带 persona_file 时明确拒绝）
  privacy：删除旧 lane 的 runtime.lock 租约；原生会话行没有 dsh_home，过去会在 delete_memory 处 KeyError——现在原生会话被置为 INVALIDATED（纪元提升已经使其失效），结果 limitations 写明原生 DSH 转录未从 DSH home 物理删除
  人格包 QQ 适配器自检 preview_readable：不再写死群号，改为检查预览里 allowed_group_ids 与群路由一一对应（WSL 下用合成预览验证：一致 → 通过，不一致或为空 → 失败）
  测试：夹具世界改由 tests/fixture_grant.py 给 dm-a/A 一条带工作区的渠道路由授权（场景仍为 public），并替换本机配置可能带入的真实路由；崩溃矩阵 after_tool_commit 改用 write_file；m 系列 CAS/作用域用例改以 overlay 头为目标；删除只验证已退役功能的用例（夹具执行器结果 JSON、旧 lane 租约、旧人格头转换）
  T7.3 PASS [离线] CLEANUP §10 六项检查全部为 0（--personal --all 只剩只报告范围）
  全套 Python 209 passed / 0 failed，JS 18/18，adr009 离线 37/37，case runner P2/P3/P5 全过，看图自检全过
  D-8 / T7.2 PASS [离线] native_worker 的分派改为 Dispatcher：宿主回复（result / host_result）在读取线程上直接完成等待中的 Future，可能等待宿主回复或长时间运行的调用（tool、persona.job_run）各用独立线程；分派池线程从不等待 Future.result()。线程池设为 1、两个场景的阶段请求交替到达时都能完成；反证：同一用例改回旧的全部入池路由会超时（死锁）
偏离：D7-4、D7-5（见下）
```

## 合并 main 与测试收敛（owner 傍晚裁决之后）

```text
合并：ADR-009 分支起点早于 main 上最后两次 ADR-008 提交（c574e5be、5ee97fb5），左栏按 QQ／Local 分组与每段「角色脑／行动脑」标签都在其中；已合并（4b9c81de），在真实 profile 的 Web 页面上核对：左栏 QQ（群聊·…、私聊·…）／Local（<人格显示名>·本地私聊）／Ungrouped；本地私聊一轮委托中依次出现「角色脑」（DECIDE）、「行动脑」（list_files / write_file 与校验）与反馈轮的「角色脑」
合并取舍：原生回执保持完整结果（main 的不变式：完成的阶段不重开），审计只存哈希；记忆面板「人格基线」跟随人格文档；本地会话标题与会话提示取人格显示名；单 Host 锁保留并改名 host.lock
测试耗时：每个测试重建库（建集合与索引约 0.4 s、审计化种子约 0.27 s、删库约 0.08 s）占全套约 57%；改为整次运行只建一次夹具世界并复用重置后的测试库（会话结束全部删除），全套 217 s → 120 s
测试收敛（owner：去掉低价值测试）：只保留守护隐私/可见性、授权与纪元、恰好一次（入站/发布/不重开阶段）、崩溃恢复、审计完整性、沙箱隔离与页面上可见行为的用例；删除 136 个测试/离线用例与 16 个文件（措辞/常量/源码 grep、遗留行为、重复用例、假集合上的全量离线包装、黄金排序文件）。现为 Python 156、JS 22，全套约 70 s
保留：人格包技能 asuna-offline-selfchecks 在无 Mongo 的沙箱里运行 tools/p2/p3/p5/p1c 离线自检，这四套离线用例作为人格自开发的唯一自检保留（不再由 pytest 包装重复运行）
```

## 与 owner 逐项走查（2026-10-04 晚，真实页面）

```text
签收标准（owner）：看得懂才保留，看不懂就删。设计变更先提方案、讲清取舍与 DSH 插件边界，再动手。
第 1 步 文档：记忆面板去掉内部标签、重复字样与 [object Object]；QQ 会话标题与发言人用群名/昵称；摘要与原始来源
  不再把核心通知（行动结果、计划到期）当成本人的话（已作废 833 条摘要、111 条记忆块，均为审计化写入）。
第 2 步 自我与对人的认识：删除无人写入的「场景自我补充」（overlay）和三条已过时的「未实现」占位；空条目说明何时写入；
  对人的认识带上当前对象的人物档案；子会话标题用任务目标。
上下文与压缩（owner 决定：缓存命中优先、尽量减少注入与压缩摘要之间的重复）：
  实测（本地会话 30 轮）：每轮注入均 35K 字，其中任务结果约 14.5K、历史约 6.3K、召回约 3.9K；17 次压缩失败 10 次
  （5 次摘要被 8,192 上限截断——角色路由先推理；3 次合并前无压缩引擎时上下文溢出；2 次 DSH 以 chars/4 估中文，
  压缩后仍判超限而再压）。
  角色脑压缩：DSH BasicCompactionEngine 子类，只覆盖文档化的 summarize()；同一重放前缀（缓存复用），中文角色扮演检查点，
  不转抄程序资料；摘要上限 24,576、保留尾 16%、预留 32,768。行动脑沿用 DSH 工程模板。
  每轮注入改由插件在通知入会话时组装：与最新 32K 估算 token 内（每次压缩都会保留的尾部）完全相同的块、历史行与记忆不重复；
  更早的（含被压缩吸收的）重新给出。取代 D-3 的 history_hwm/compaction_generation。实测下一轮 6.6K 字。
  逐块上限并标注截断：历史行 1,500、记忆 1,200、任务报告 6,000、最后 4 条工具观察各 600。
遗忘（owner 决定：时间 + 信息量）：分数 × 0.5^(距上次真实使用天数/30) × 0.5^(此后该对话消息数/1500)；只有角色轮次算使用；
  钉住不衰减；淡到 0.1 以下且已被摘要覆盖的原始聊天块退出自动召回（显式 recall 仍可读）；不删除。
  记忆单元记录 formed_at（662 条独白回填为审计化修订）；钉住限 owner_private 轮。
行动脑人格（owner 试行）：persona 模型 render.action_persona=persona 时给出「她是谁」（按任务来源会话的类别），不含任何记忆与状态。
两个上下文圈（owner 批准的设计）：DSH 原生计量染紫色代表角色脑，旁边一枚蓝色圈代表最近的行动会话。
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
| D6-1 | 历史游标在 prepare 时按「本回合将进入的角色会话」计算：Web 输入用其原生会话 id，渠道与计划输入用与原生绑定相同的解析规则（在 ingest 时解析一次并写入 episode）；无原生会话的 lane（测试）用 `history:<binding>` 行 | 上下文快照（context.prepared）与实际给出的历史一致、可审计；会话变了（新建对话）自然得到完整窗口 |
| D6-2 | 压缩代数 = 会话中无 error 的 `compaction/end` 事件数，随每个阶段结果回传；在角色阶段前比较「游标设置时的代数」与「最近观测的代数」 | 固定版有可观测的持久事件，按 D-3 不用启发式；压缩发生在本回合内时下一回合重发 |
| D6-3 | `scenes.sequence` 与 `memory_units.salience` 是 `$inc` 计数器，不进入文档摘要（COUNTER_FIELDS）；隐私删除对审计的既有改写不在篡改检测范围内 | 这些字段本来就不产生修订；否则任何一次发言都会被判为篡改 |
| D6-4 | FakeLane（测试替身）的回执仍保存全文；配置项名为 `mountSchedule`（JS 配置的驼峰命名），即 ADR 中的 `mount_schedule` | 测试替身没有原生转录可回读；命名与同一对象的其他配置项一致 |
| D7-1 | D-8（advance 拆分为事件驱动续接）本次不做 | 计划自述「风险高」；它改变每个阶段的线程模型，门槛是崩溃矩阵（本次刚修复成绿）。在 owner 不在场时推送这种改动收益小于风险；建议在 owner 可以同步做人工 Web 检查的时段进行 |
| D7-2 | （已由 owner 裁决撤销，见 P7 第二部分）`episodes.system` 兼容与 `persona:<id>` 头转换不删 | 只读核查生产库：仍有 2 个未转换的 `persona:` 头、52 个带 `system` 全文的非终态回合（WAITING_TASK/INTERRUPTED）。ADR 的删除条件「确认没有在途旧回合后」尚不满足；现在删除会让正式迁移前的真实部署无法启动或续接 |
| D7-3 | （已在 P7 第二部分完成删除）夹具模式本次不删，`privacy.py` 的 DSH home `runtime.lock` 租约保留 | 夹具模式仍被大量 m 系列用例当作驱动（D0-2）；删除要逐个改写为工作区模式，适合与 D-8 同批。租约是隐私删除时防止并发写 DSH home 的守卫，CLEANUP 所指的旧 lane 锁（native_worker）已不存在 |
| D7-4 | 隐私删除对原生会话只作废、不物理删除其 DSH 转录 | 原生转录由 DSH 会话持久化管理，位置与格式属于固定版；纪元提升已使会话不可再用（NATIVE_SESSION_EPOCH_CHANGED）。物理删除需要走 DSH 的会话删除接口，列为后续 |
| D7-5 | D-8 不把 `Coordinator.advance` 改写为续接式，而是修正分派路由 | 实际风险是宿主回复与等待它的调用共用有界分派池（池满即死锁，T7.2 的情形）；角色与行动阶段本来就在各自专用线程（asuna-chat / asuna-actions）上顺序等待，按场景次序推进正是它们的职责。续接式改写会触动全部阶段语义与崩溃点而不带来功能收益；路由修正消除了死锁类别，崩溃矩阵与阶段语义不变 |
| D8-1 | 每轮上下文的去重从 Python 游标（D-3）移到插件，在通知入会话时按可见尾部组装 | 压缩通常发生在新一轮第一个 pre-step，Python 侧判断总晚一轮；而新压缩提示不转抄程序资料，晚一轮就会两头都没有。以「每次压缩都会保留的尾部」为准，无论何时压缩都安全；会话日志是唯一状态 |
| D8-2 | 人格模型 `memory.salience`（全为 0、从未启用）由 `memory.forgetting` 取代，衰减改为乘性半衰（时间 × 信息量） | ADR 的线性扣分与 RRF 量级不匹配（0.016–0.033），owner 要求信息量也参与遗忘 |
| D8-3 | 行动脑可接收人格「她是谁」（`render.action_persona=persona`），ADR §8.3 原只许公开 values 段 | owner 试行；不含记忆、关系、情感或其他状态，按任务来源会话的类别取段落，行动规则优先 |
| D8-4 | 删除 overlay（场景自我补充）实体 | 全库无写入路径，却出现在页面与每轮上下文中 |
| D8-5 | 情感对模型只用词（静态投影）：她读到档位、指示句、倾向与来由（强度/起伏/时间都用词），记账也只用词（强度、起伏、好坏），由人格模型的 scale 映射为数值；公开会话另有「心情可能来自别的对话，不解释、不编理由」 | owner 与 Kazusa 的经验：模型对原始数值的理解不稳定；心情全局共享（跨会话的不确定性是人的样子），关于某个人的状态才按人隔离。规则已写入 AGENTS.md |
| D8-6 | 人按账号认，不按名字：每个场景里每人一个固定标签 `[名字 #n]`（`scene_people`），名字去掉换行、不可见字符与标签字符；消息正文缩进在标签行下；程序注明群主/管理员、同名/名字相近、名字里带 owner 称呼或她的名字、24 小时内改名；owner 由账号认定并以人格的 `people.owner_label` 开头；上下文、摘要与压缩都用同一套标签，QQ 号不再给模型 | owner 判定昵称注入是最严重的风险；参考 Kazusa 适配器（模型不见平台 ID）与小满自己的 QQ 实现（认号不认名片、owner 设计的身份括号与缩进正文）；真实数据里已有两人同名片 |
| D8-7 | 未决项收尾：canonical 映射只读配置（删掉别名立即撤销 owner 私聊）；入站 raw 只存核验过的发言人资料、媒体块与群名；自动接入的人一律 `qq:<账号>`；她的上下文用会话名代替场景 id／scope／epoch／平台消息号。owner 定的开发期规则：旧数据不转换，不合新设计就删——QQ 侧整体重置（消息、记忆、关系、标签、会话绑定与 16 段 QQ 原生转录），删除前导出到本机 `.runtime/backups/` | owner：「pre-date data is wrong then you should remove them」；QQ 旧摘要九成写着 QQ 号、三成消息来自哈希 id 的人，逐行删会留下空洞 |
| D8-8 | QQ 平台代码移出核心与人格包：新通道包 `packages/napcat-qq`（`@asuna/napcat-qq`）带适配器（`integration/`，原人格包 `integrations/qq-napcat-adapter`，git 历史保留）、适配器技能，以及平台种类模块 `python/napcat_qq`（`qq:` 的人与场景 id、适配器的 @ 写法、默认图片主机、适配器派生设置）。核心只留 `channel_kinds` 登记：按 id 前缀问已装平台；JS 侧 `registerChannel`，Core 等部署里配置的通道插件登记后才起 worker。适配器的开发候选归通道包自己的项目 `napcat-qq`（她的 `integration_*` 工具仍可用；发布 `python/` 改动下次重启生效）。设置键 `qqAdmission` 改名 `channelAdmission`。安装：`pack_plugins --channel`、`setup_native_profile --channel-package`。 | owner：「can the QQ specific code be moved to its own napcat_qq, so in the future we can package into a separate DSH plugin」；直接装成第三个 DSH 插件（安装只多一个 `dsh plugin add`），比先打进核心包再拆更省 |
| D8-9 | 熟悉程度用话说：familiarity.py 只从记录算（owner 账号、她写过的理解、她回过对方几轮、对方说过几句），按人（canonical）跨场景；relationship 块给 familiarity、人格的 stance 与 understanding。不再预置关系占位记录：没有就写「你还没写过对这个人的理解」，她第一次反思的理解直接建记录；生产库 2191 条占位删除（先导出）。小满的 stance：生人只闲聊、不替人干活，熟人帮、主人尽力，主人开口可放开；心情槽「帮忙」 | owner：「Stranger should not fallen to 帮忙 category, perhaps just 闲聊. Friendly, but not helpful」「everyone starts with neutral, or no data」 |
| D8-10 | 接话判断（relevance gate）：@ 与回她的话照旧；她参与过的线里的接话、点名不 @（新唤醒原因 name_called）、开了主动的群的主动机会，先在每群一个小的子会话里问一句 接话／不理（角色路由、低思考、约 5% 窗口就压缩）；只读文字：为什么问、说话人标签与熟悉程度、她上次说话后的这些话（10–60 分钟、≤40 行）、心情。不理就在召回前结束；接话才准备完整上下文。群里一轮的历史用同一窗口。deployment.reasoning_effort：attend 默认 low，本部署 group 设为 medium | owner 选「Per group」「Gate low, group turns medium」「Only the 2 opted-in groups」；放在她群会话之外：研究数据显示一轮的第一请求多半没命中缓存（QQ 会话中位 9.2 万未缓存 token），会话内判断不轻 |
| D8-11 | 群里的位置与管理：适配器查本号在各群的身份放进 raw.asuna_self；她的上下文有 your_place_from_program；是群主或管理员时可在 DECIDE 用 group_action（mute/unmute/recall/kick，按标签选人），程序先查：她是管理、对象唯一、不是主人/自己/群主/别的管理、禁言时长固定档、撤回只撤这条或对方十分钟内的最后一条、每群每小时 6 次；动作走 outbox 先于消息、适配器只调 set_group_ban/delete_msg/set_group_kick，平台 retcode 即回执，中断记 UNKNOWN 不重试。她自己的群笔记 group_notes（write_docs，doc 写 group_notes，公开给该群）。默认开启，路由可 admin_actions: false 关 | owner：「If I'm to build them today, I'd enable all features … on by default」 |
| D8-12 | 她还没在某个会话里有过一轮时，平台消息不进会话正文（DSH 要求第一条可见内容是她第一步写的系统头，否则这轮之后日志载不回来，曾经因此停过 worker），而是排在该会话的 DSH inbox（next-step，留最新 40 条，更早的在 Memory）；她第一轮的第一步把它们按到达顺序认领在系统头之后、阶段通知之前，通知的历史不再重复这些行；第一轮正在开始时到的行等系统头写好再进正文。认领时这些平台行不算本机输入。原先挡在外面的 125 行（14 个会话）删回执后由启动投影重新排入。DSH 侧栏从一个会话的第一轮起才列出它 | owner：「Can you bring up the web so I can see the full trace and thinking process?」「Yeah I want you to fix the inbox issue」；用 DSH 自己的 inbox（splice 事件、认领顺序、Web 的待处理显示）而不是自写系统头 |
| D8-13 | 行动脑在主会话里的记录与角色脑用同一套原生渲染：片段改为取来源会话的分组条目（与主 Chat 同一 grouped view），交给主 Chat 自己的列表组件，去掉 `individualRecords`（它关掉了原生的整轮折叠，行动脑因此显示成一串 Think/Tool call 行，而角色脑是「Completed in …」折叠加 Analysis）；片段种类加上 `turn-process`，行动那一轮有自己的原生折叠头。安装器把两个原生渲染包随插件一起装（以前只装一次，改了补丁也不会更新） | owner：「both brain should share the same widget and the same to render, and no custom widget or call」；修订案本来写的是「原生思考与工具折叠行为继续适用」 |
| D8-14 | 需要模型答案才能继续的地方都做确定性检查并如实回告（answers.py）：角色各阶段、接话判断、情感评估、行动脑报告、对话摘要。检查：正常停下、有正文（只有思考不算；只有行动脑的工具调用算）、符合该处格式（DECIDE 的 JSON 与 schema、SELF 两个字段、接话判断第一行、评估的 JSON 数组）。不合格就在同一会话里用一条程序检查说明哪里不对、这一步要什么，再问，最多两次修正；仍不合格按该处的失败处理（阶段失败、接话判断按不理放过、跳过评估、行动 BLOCKED、摘要下次再来）。传输错误与完全空的回复先由 DSH 自己的重试处理；被打断的回合不修。修正用同一会话（`:fix-N` 操作，原生 lane 按去掉后缀的基本操作解析），DECIDE 原有的一次修正并入这里 | 小满在群里的独白只写进了思考，正文为空，回合直接失败、Web 上看不到；owner：「Thinking without output seems an erratic behavior … should apply to ALL model output … deterministic」「the classifier should return honest mistake to the model」；选 option 2（需要确定输出才能继续的地方），反馈方式与 DSH 把失败的工具调用回给模型一致 |

## 给 owner 的待决事项

已裁决（2026-10-04 傍晚）：1 自检已修（改为一致性检查）；2 git 历史不清理（软性指引）；4 不迁移，旧兼容已删；3 D-8 在 owner 可以一起看 Web 界面时进行。

剩余：原生会话转录的物理删除（D7-4）。

## 完成与后续

```text
完成判据：P0–P7 全部报告；owner 逐项走查（真实页面）之后的修正（D8-1…D8-14）已部署；
  全套 Python 201 passed、JS 28/28、离线自检 p1c/p2/p3/p5 全过。
合并：owner 授权（2026-10-05 夜）由实施者在测试全过后以 --no-ff 合并到 main 并推送。
后续（不阻塞完成，另行处理）：
  D7-4 原生会话转录的物理删除（走 DSH 会话删除接口）。
  新会话的第一轮：触发这一轮的那条平台消息有时排在她第一步（MONOLOGUE）之后才进会话正文，
    页面上显示为独白在前、消息在后，那一轮的阶段也不再折叠。只影响一个会话的第一轮；待复现后修。
  她决定不说话（委托且不先说、或沉默）时，那一轮最后一步是 DECIDE 的 JSON，DSH 把它当作这一轮的回答显示。
    DSH 原生的做法是把委托做成工具调用（参数由 schema 校验），方案见 ADR-010/PROPOSAL-DECISION-DISPLAY.md。
  旧的子会话标题（行动脑 · task-ep-…、交流摘要 · local-dm）是改用任务目标与会话名之前建的，新会话已是可读标题。
```
