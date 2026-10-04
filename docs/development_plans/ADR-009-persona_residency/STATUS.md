# ADR-009 实施状态

> 实施者追加的进度记录（IMPLEMENTATION.md「文档更新」允许）。不含个人数据。
> owner 授权（2026-10-04）：ADR 仅作参考，与现实冲突时以实施者的专业判断为准，偏离逐条记在下面；测试库用后删除；真实库仅用于测试、不可清空。

## 总览

| 阶段 | 状态 |
|---|---|
| P0 卫生与地基 | 完成（见下方报告） |
| P1 人格契约 v2、人格模型、政策存储 | 完成（见下方报告） |
| P2–P7 | 未开始 |

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

## 给 owner 的待决事项

1. 人格包 QQ 适配器自检 `preview_readable` 现在期望占位群号；对着真实部署的预览文件会失败，需要改成从预览/配置读取期望值（属于人格包行为改动，未擅改）。
2. 公开前是否清理 git 历史与历史设计文档中的个人标识（扫描器对 `docs/development_plans/**` 其他 ADR 报告 78 处，只报告不改）。
| D1-1 | 完整 schema 校验在 worker `initialize` 中进行（Python jsonschema）；JS `registerPersona` 只做契约形状、路径不越界与 `PERSONA_ID_MISMATCH` 的同步校验 | DSH 侧没有 JSON Schema 校验依赖；两处任一失败都使 Core 惰性并显示原因 |
| D1-2 | 人格包里的路径（model、seeds、jobs、skills、persona_file）一律存为相对 `resource_root` 的路径，由 floor 按已发布产物根或包根解析为绝对路径 | 满足 PERSONA_CONTRACT §2.3；也让同一份贡献可在候选与已发布产物间切换 |
| D1-3 | 已安装人格包的人格正文原样从 `persona/core.md` 移到 `seeds/persona.md`（未改一字），模型只含 id 与显示名；核心与该包版本升到 0.2.0 / 对等依赖 0.2.x | CLEANUP §8 与契约 v2；不替人格取参数或标注可见性 |
