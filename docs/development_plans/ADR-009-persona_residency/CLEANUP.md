# 清理：遗留代码、遗留访问、人格中立化与个人数据

## 1. 原则

- **沿调用链删除，不按文件名盲删。** 先确认没有运行时导入路径能到达，再删。运行时入口有三个：`asuna.native_worker`、`asuna.cli ui`、保留的 `--debug` 维护命令。
- 被删模块的专属测试一并删除。混合测试只裁掉涉及被删模块的部分，**不得因此降低不变量覆盖**（作用域、崩溃点、幂等、审计链）。
- 每删一处，在阶段报告中写清：删了什么、为什么无人调用、由什么替代、用了哪条 grep 验证。
- 本机工作树可能有他人未提交的改动。动手前 `git status`，不覆盖未提交内容。

## 2. 运行时资源搬出设计文档目录

**现状**：`config.py:10` 在未打包时把 `BUNDLE` 指向 `docs/development_plans/ADR-001-…`。运行时的 schema（`decision`、`reflection`、`mutation`、`task_result`）、`reflect.md`、世界夹具、默认 `prompts_dir` 都从那里来。`packages/cognition-core/runtime-manifest.json` 与 `tools/pack_plugins.py:34-51` 也从那里复制。核心 prompt 则从工作区的 `config/prompts/` 读取（`prompts_dir`），而不是从已发布的 worker 读取。

**目标**：

| 内容 | 新位置 | 说明 |
|---|---|---|
| 运行时 schema | `src/asuna/resources/schemas/*.json` | 源与打包同构 |
| 核心中性 prompt（`common`、`executor`、`stage_*`，以及新增的 `stage_write`、`stage_settlement`、`stage_presence`） | `src/asuna/resources/prompts/*.md` | **行为文件**，随 `development_publish` 发布 |
| `RUNTIME_API.md` 副本 | 打包时复制（不变） | — |
| 测试夹具 `world.json` 等 | `tests/fixtures/` | 不再由运行时读取 |
| 现有 `src/asuna/resources.py`（授权解析） | 改名 `src/asuna/grants.py` | 避免与 `resources/` 数据目录同名 |

- 删除 `config/prompts/` 目录和配置键 `prompts_dir`。`config.prompt_path` 只读包内资源。
- `cli.py` 不再自带 `BUNDLE` 副本；`seed` 子命令的夹具参数改为必填，且只在测试中使用。
- `runtime-manifest.json` 和 `pack_plugins.py` 只从 `src/asuna/resources/` 映射资源。

**完成判据**：`grep -rn "docs/development_plans" src packages tools/pack_plugins.py` 结果为 0（T0.2）。

## 3. 删除清单

| 项 | 位置 | 为什么 | 替代 |
|---|---|---|---|
| 终端适配器 | `chat.py:578 terminal()`、`chat.py:623 chat()` | owner 裁定 R-2 | Web |
| 只为终端存在的方法 | `Chat.new_context`（`chat.py:154`）、`Chat.compact`/`_compact`（`chat.py:158`、`:345-355`，调用不存在的 `NativeLane.compact`） | 无 Web 调用者 | 原生压缩 |
| 读旧绑定格式的追踪 | `Chat.trace`（`chat.py:453-544`） | 读的字段已不再写入 | 原生 Trajectory + 记忆右栏 |
| 终端依赖 | `pyproject.toml` 中的 `prompt-toolkit`（以及 `uv.lock` 中只被它引入的条目，用 `uv lock` 重新生成） | 随终端删除 | — |
| ADR-001 夹具模式 | `tasks.py` 的夹具 `TOOLS`、`RESULT_SCHEMA`/`TaskService.finish`、非工作区执行分支、`inject_read_failures`、`task_status` 分支；`coordinator.py` 的 `DECISION_SCHEMA` 回退；`router.py:54` 的 `cli-fixture` 标签与夹具群路径；`host.py:147` 与 `native_worker.py:143` 的 `task_mode` 强制 | `task_mode` 恒为 `workspace`，这些路径不可达 | 工作区模式（唯一模式） |
| 死方法 | `Router.batch`（`router.py:79`）、`Coordinator.recover`（`coordinator.py:361`）、`MemoryService.reflect`/`proposal`（`memory.py:171-209`，使用 ADR-001 的 `persona:P1` 与 `reflect.md`） | 无运行时调用者 | REFLECT 阶段（`commit_understanding`） |
| 死模块 | `retrieval_trials.py` | 无人导入 | — |
| ADR-001 验收与评分工具链 | `review.py`、`review_material.py`、`review_scores.py`、`experiments.py`、`reporting.py`、`legacy_evidence.py`、`doctor.py`，以及 CLI 子命令 `doctor`、`report`、`export`、`review-pack`、`review-import`、`review-aggregate` | 服务于 ADR-001 验收与旧证据目录；`doctor` 写死了已不存在的启动路径 | 原生 profile 启动器；`tools/check_dsh_release.py`、`tools/check_mongo_host.py` |
| 测试替身留在运行时包 | `lanes.py` 的 `FakeLane` | 只有测试使用 | 移到 `tests/fakes.py`；`LaneResult` 若仍被运行时使用则保留 |
| 旧 UI 设置函数 | `model_settings.py` 中只被测试或工具使用的 `native_thinking` 兼容、`edited_models`、`public_models`、`persist`、`revision`；`tokens.py` 的 `TokenMeter`（若只被它们使用） | 旧设置界面已退役 | 原生设置卡 |
| 遗留配置键 | `config.py` 的 `legacy_database`（`:83`、`:103`）；运行时不读的 `workdir`、`transport_read_timeout_seconds`、`publish_adapter`、`local_only`；角色/行动路由的 `base_url` 必须是本机地址的校验（模型调用已归 DSH；**嵌入端点的校验保留**） | 无读取者或语义已转移 | — |
| 旧 lane 锁 | `native_worker.py:146` 的 `RuntimeLease(.../character/runtime.lock)` | 旧 lane 已退役 | 原生单 Host |
| 导入兼容垫片 | `context.py`、`schedule.py`、`proactive.py`、`summary_trigger.py` 的扁平离线加载 `try/except`；`chat.py`、`host.py`、`memory.py` 中永远不会走到的 `scene_links = None` 分支 | 打包后路径固定 | 正常相对导入；离线检查脚本改为设置 `PYTHONPATH` |
| 隐藏 CLI 开关 | `cli.py` 的 `--native`、`--read-only` 与"legacy UI switches are retired"分支 | 已退役 | — |
| 过时排除表 | `floor.js:252` 排除列表中已删除的模块名 | 指向不存在的文件 | 按实际模块更新 |
| 一次性 ADR-005 补丁工具 | `tools/p2_make_patch.py`、`p2_apply_patch.py`、`p2b_make_patch.py`、`p3_*_patch.py`、`p5_*_patch.py`、`p2b_edge_probe.py`、`p2b_probe_loop.py` | 针对 `/task` 快照的一次性补丁 | — |
| 引用被删模块的工具 | `tools/` 下导入了上表模块的脚本（例如 `run_checks.py`、`assess_engineering.py`、`audit_finish_reasons.py`、`diagnose_*.py`、`finalize_*.py`、`refresh_environment.py`、`probe_review_scores.py`、`probe_report_observations.py`、`probe_evidence_export.py`、`probe_export.py`） | 依赖被删模块 | 若仍有用途，改写为不依赖被删模块，并在 `RUN_ASUNA.md` 记录用途；否则删除 |
| 一次性修复脚本 | `tools/repair_asuna_event_envelopes.mjs` | 已完成使命 | — |
| 人格专属导出工具 | `tools/import_persona_resources.py` | 核心工具不得为某个人格服务（R-5） | 人格作者在自己的包内维护 |
| 含个人标识的工具 | 文件名含群号的检查脚本；`tools/probe_embedding_host.py` | 个人数据（R-6） | 删除；需要时以本地未跟踪脚本存在 |

`tools/` 的最终去留以一张表交付：保留的每个脚本必须**能导入**（`python -c "import runpy; runpy.run_path(...)"` 或 `--help` 正常），并且服务于当前运行、维护或测试。

**保留** `tools/*_offline_check.py` 与 `tests/*_cases.py`：它们是离线测试基建，P0–P7 的离线测试沿用这种形式。

## 4. 修复清单

| 项 | 位置 | 修复 |
|---|---|---|
| 擦除命令 `KeyError` | `privacy.py:25,48` 读取原生会话行没有的 `dsh_home` | 改为按原生会话 id 定位：DSH 会话文件只报告位置，不由 Asuna 删除原生日志（原生日志归 DSH 管）；Mongo 侧擦除照常 |
| 擦除覆盖新数据 | `privacy.py` | 擦除扩展到 `owner-private` 记忆单元、文档节（写墓碑修订）、情感事件（写 `void` 修订，`by=operator`，理由必填） |
| 行动脑人格泄漏 | `tasks.py:414` | D-2 |
| harness 身份句 | `index.js` | D-1 |

## 5. 条件删除

| 项 | 条件 |
|---|---|
| `schedule.py:45-83` 一次性计划迁移（字段 `legacy_schedule_binding`） | 在本机库上执行只读检查：`plans` 中没有任何未迁移的行。检查结果写进阶段报告后才删除；否则保留并报告行数 |
| `persona:<id>` 头的读取路径 | P2 完成文档化转换且 T2.8 通过后，于 P7 删除 |
| `registerPersona.persona_file` | P7 删除（P1 起已由 `seeds` 取代） |

## 6. 保留清单（明确不删）

- `audit.py` 的 `verify`、`replay`、`projection`：审计链完整性工具，m 系列测试依赖。
- `persistence.js`：DSH 0.2 补丁（D-9）。
- ADR-007 地板与恢复 preset。
- `IntegrationRunner` 沙箱：人格作业复用它。
- `--debug` 维护命令：`db-init`、`inspect`、`rollback`、`index`、`delete`、`cancel`、`replay`。`seed` 只供测试。

## 7. `AGENTS.md` 修改

替换第 4 条（关于 `chat()`/`terminal()`）为：

```text
- `chat.py`'s `Chat` class is the Web-reused queue and action controller. There is no terminal chat adapter; all interaction goes through the Web UI.
```

追加两条：

```text
- The core is persona-agnostic. Persona names, persona text, and persona-specific parameters live only in persona packages, persona-private data, or test fixtures; core code, core prompts, core tools, and example configs must not contain them.
- Personal data stays local. Real account IDs, addresses, host names, user names, time zones, and private content belong in ignored local config, MongoDB, or private source roots, never in tracked files. Examples use documentation-reserved placeholders.
```

## 8. 人格中立化

| 项 | 修改 |
|---|---|
| `config/prompts/persona_local.md` | 删除（随 `config/prompts/` 整体删除） |
| `packages/xiaoman/persona/core.md` | 改为 `seeds/persona.md`，经 `seeds` 声明 |
| `config/local.example.json` | 删除 `persona_file`；`chat.persona` 用占位值 `<persona-id>` |
| `tools/setup_native_profile.py` | `--persona` 必填，无缺省；不出现任何人格名 |
| `tools/pack_plugins.py` | 只打包核心，以及作为参数传入的人格包目录；不写死人格目录 |
| 核心 prompt | 审读 `common.md`、`stage_*.md`、`executor.md`，去掉任何人格口吻或人格专属规则（T0.9） |
| `character_id` 缺省 | `config.character_id()` 的回退值保持中性（现为 `'character'`），不得出现人格名 |
| 测试 | 默认用合成人格 `demo`；`packages/xiaoman` 只作为"第二个真实包能被安装"的冒烟用例 |

## 9. 个人数据清理

### 9.1 类别与检测（写成可执行规则，不写具体值）

| 类别 | 检测模式（`check_staged_secrets.py --personal`） | 替换为 |
|---|---|---|
| 平台账号、群号 | 文件名或内容中 ≥7 位的连续数字（白名单：哈希、时间戳字段、测试中明确合成的 id 前缀 `demo-`） | `demo-user-1`、`demo-group-1` |
| 局域网与私有地址 | RFC 1918 三段私有网段（`10/8`、`172.16/12`、`192.168/16`） | `192.0.2.x`（RFC 5737）或 `127.0.0.1` |
| 主机名、用户名 | 本地拒绝清单中的条目（见 9.2） | `example.invalid`、`<user>` |
| 时区与地点 | 核心代码与示例中的具体 IANA 时区字面量（测试夹具中的 `UTC` 和明确合成的时区除外） | 政策键 `rhythm.timezone` |
| 人格名 | 核心目录中的人格显示名与 id（人格包与测试夹具除外） | `<persona-id>` |
| 私密内容 | 由拒绝清单覆盖 | — |

### 9.2 本地拒绝清单

- 位置：`config/personal-denylist.local.txt`，加入 `.gitignore`，每行一个字面量或正则。
- 内容：owner 自己的账号、昵称、主机名、用户名、地址片段等。**由 owner 在本机填写，仓库只提供空模板** `config/personal-denylist.example.txt`。
- `tools/check_staged_secrets.py --personal [--all]` 扫描暂存文件（或 `--all` 扫描全部跟踪文件），命中时打印"文件:行:类别"，**不打印命中值本身**，退出码为 0（告警级软规则，R-7）。

### 9.3 范围

- **必须清理**：`src/`、`packages/`、`tools/`、`tests/`、`config/*.example.*`、根目录手册。
- **只报告不改**：`docs/development_plans/**`（设计史）。是否清理，由 owner 决定。
- **不做**：重写 git 历史。公开前是否需要清理历史（或另起公开仓库），是 owner 的独立决定；本 ADR 只在最终报告中提醒。

## 10. 完成判据（P7 末尾一次性检查）

```text
grep -rnE "def terminal|def chat\(|prompt_toolkit|prompt-toolkit"   src pyproject.toml          → 0
grep -rn  "docs/development_plans"                                  src packages tools/pack_plugins.py → 0
grep -rnE "retrieval_trials|review_material|review_scores|legacy_evidence|from \.experiments|from \.reporting|from \.doctor" src tests tools → 0
grep -rnE "task_mode|cli-fixture|legacy_database|runtime\.lock"     src                         → 0
grep -rniE "xiaoman|小满"                                            src/asuna packages/cognition-core config tools → 0
python tools/check_staged_secrets.py --personal --all               → 跟踪文件中（除 docs/development_plans）无命中
```
