---
name: asuna-offline-selfchecks
description: 沈小满在核心技能 asuna-self-improvement 的离线自检之上记的增量笔记：「挂错项目」红的读法（xiaoman 候选没有 tools/tests，No such file or directory 是选错项目不是产品坏）、单独跑某个用例文件与 p3 的反证基线参数、p5b 退役后「文件不存在 + exit 2」怎么读、「没收录 ≠ 已退役」、适配器自检在 qq-napcat-adapter 技能里不在这套里。通用离线自检的命令清单、退出码读法、__pycache__ 清理、project 归属、发布与重启口径一律以 asuna-self-improvement（随认知核发布）为准，这里不再重复；两份不一致按核心技能办。附零依赖离线自检 check_skill.py。
---

# asuna-offline-selfchecks

## 用途

改完代码要自证、发布前想看一眼有没有碰坏行为——那条唯一的路在核心技能 **`asuna-self-improvement`**（随认知核发布，两个脑都读得到）。
零依赖离线套件的命令清单（P2 摘要环 / P3 自然语言安排 / P5 主动插话 / 出站图片 / 讨论整理，外加 compileall）、退出码读法、
`__pycache__` 清理、哪些改动触发宿主重启、地板文件、「夹具替身包必须带上被装载真文件 import 的同包真模块」这个坑——全在那一份里，
**本文件不再重复**。两份说法不一致时按 `asuna-self-improvement` 来；这里只留它没有、我自己又踩过的几条增量。

## 增量（核心技能没写的几条）

### 「挂错项目」的红怎么读

`development_*` 不带 `project` 挂的是 xiaoman 插件候选：根下只有 `skills/ seeds/ persona-model.json src/index.js`，
**没有 `tools/` 也没有 `tests/`**。在那里面跑离线套件只会红在
`python3: can't open file '/task/tools/...': [Errno 2] No such file or directory`——那是选错项目，不是产品坏了；
带 `project: "core"` 重跑就是了。发布同理：不带 project 的 publish 只冻结 xiaoman，认知核改动会照样返回成功
却一点没上线。（核心技能有 project 表；这条是真错起来的样子。）

### 单独跑某个用例文件、p3 的反证基线

- 单独跑用例文件也行：`PYTHONPATH=tests python3 tests/p3_schedule_cases.py`
  （`p2_summary_loop_cases.py`、`p5_proactive_cases.py` 同理），它们自己打印 PASS/FAIL 行。
- `p3_offline_check.py [基线目录]` 的第二参是「改动前」副本，用来做反证；默认 `/task/p3-baseline`，
  找不到就跳过反证并说明——跳过不算失败。

### 退役与「没收录」怎么读

- `tools/p5b_ui_offline_check.py` 随旧自绘工作台（ADR-008）一起退役了：硬跑会报
  `can't open file '/task/tools/p5b_ui_offline_check.py': [Errno 2] No such file or directory`、exit 2——
  那是文件不存在，别报成「UI 检查挂了」或产品坏了。界面口径的验证位置搬去了真实 DSH Web 页面
  （composer、角色实际内容、行动会话跳转、旧 `/asuna/api/state` 已退出），那部分连同宿主侧 `tests/test_*.py` 由操作员跑。
- `tools/` 里还有 `p1c_offline_check.py`、`read_image_offline_check.py`、`linked_scenes_offline_check.py` 这几份，
  核心技能一直没收录，**没收录 ≠ 已退役**；要跑它们先看各自 usage。

### 适配器的自检不在这套里

napcat-qq 适配器的自检（`--selftest --offline`，跑内置占位夹具）在通道包里、用 `napcat-qq` 项目跑，
口径与已知坑看 `qq-napcat-adapter` 技能——别在认知核这套里找它。

## 版本

v1（2026-09-24）：首次记录，命令与结论都来自本次实跑。

v1.1（2026-10-02）：补 ADR-008 项目归属一节——`development_publish` 默认发布 xiaoman 插件，
认知核改动与这套离线套件都要显式 `project="core"`；入口标题同步标注。命令本身与判定口径没改。

v1.2（2026-10-02）：按 ADR-008 的退役变化对齐清单——摘掉 `p5b_ui_offline_check.py`（文件已不在 `tools/`，
frontmatter 描述与入口同步去掉 P5-b），新增退役一节写清「文件不存在」这种红怎么读、以及 UI 口径的新验证位置；
P3 用例数按实跑写成 38 条。旧工作台 / P5-b 的历史记录留在试用记录里，不删。

v2（2026-10-05）：压缩。通用离线自检规则（命令清单、退出码读法、`__pycache__` 清理、权限与边界、
夹具坑、project 归属表）与核心技能 `asuna-self-improvement`（ADR-011，随核发布）重复，删掉并指向它；
只留增量：挂错项目的红怎么读、单个用例文件与 p3 反证基线、p5b 退役读法、没收录 ≠ 已退役、适配器自检的去处。
试用记录按历史保留不删。新增零依赖自检 `check_skill.py`：查本文件的指向、增量与「通用清单没有回潮」。

## 试用记录

2026-09-24，在可发布候选（Asuna 认知核）里实跑：

- 改前 `python3 tools/p3_offline_check.py` → `FAIL 离线用例全绿（36/37） → ['context_projection_runs_end_to_end']`，
  用例侧报 `ModuleNotFoundError: No module named 'p3coord.self_state'`；
- 只改 `tests/p3_schedule_cases.py`（复制清单 + `sys.modules` 清理清单各加 `self_state`）后重跑 →
  `PASS 离线用例全绿（37/37）`、`P3 自检：可以出补丁`、exit 0；
- 同期回归：P2 `24/24`、P5 `19/19`、P5-b `24/24`、讨论整理 `18/18`、`compileall` exit 0；
- `development_publish` 的启动探针返回 `core=started / database=reachable / publish_path=reachable`，
  `changed_files` 只有那一个测试文件。

2026-10-02（第一次记录），只改本技能文件（xiaoman 插件候选）。按上面新口径带 `project="core"` 跑整套，认知核候选当时的真实结果：

- 绿：P2 `24/24`、P5-b `24/24`、讨论整理 `18/18`、`compileall` exit 0；
- 红：P5 `14/19`（`one_unanswered_attempt_per_topic`、`scene_cooldown_and_hourly_cap`、
  `one_message_does_not_clear_another_request`、`recheck_holds_when_the_gate_closed`、
  `topic_is_derived_for_every_group_row` ← `AttributeError: 'SimpleNamespace' has no attribute 'config'`）；
  P3 `33/38`，五条全红在同一句 `ImportError: cannot import name 'character_id' from 'p3coord.config'`；
- 这些红点都在夹具替身（`p3coord/config.py` 缺 `character_id`、P5 的 `SimpleNamespace` 缺 `config` 与 topic 字段），
  像产品代码加了新字段而夹具没跟上（推测，未逐行核对）；本次一个核文件都没动，红与本次改动无关，留在 core 侧待修；
- 插件侧本文件自查：两份 `SKILL.md` 的 frontmatter 都能解析、`name` 与目录名一致；
- 发布：`development_publish`（不带 project，即 xiaoman）连跑两次都停在 `PACK_FAILED`、`activated=false`——
  冻结与只读校验过了，卡在宿主 `packages/cognition-core/src/floor.js` 的
  `cmd.exe /d /s /c "npm.cmd pack … --pack-destination "<目标目录>""`：那对引号被 cmd 吞成字面量，
  npm 把目标当成相对路径，报 ENOENT。是发布器自身的 bug，需要操作员在 checkout 侧修（`floor.js` 受开发层保护，
  我改不动，也不该由这个 bug 决定发布结果）；因此 v1.1 仍未上线，改动留在候选里等发布器修好。

2026-10-02（同一 UTC 日内的第二次，沙箱 UTC 钟 23:57），仍只改本技能文件（v1.2：与 ADR-008 退役对齐）。
按「只跑与本次改动必要、且当前仍保留的件」选，带 `project="core"` 实跑：

- 退役核对：`tools/` 清单（63 个文件）里没有 `p5b_ui_offline_check.py`；硬跑 → exit 2 +
  `can't open file '/task/tools/p5b_ui_offline_check.py': [Errno 2] No such file or directory`，与本节口径一致；
  全仓 `grep -rn 'p5b|P5-b'` 只剩 `docs/ADR007-READ-IMAGE-REPORT.md` 两处历史提及，产品代码里已无 P5-b UI 件；
- P3：`PASS 全部源文件能编译` + `PASS schedule_rules 只用标准库` + `PASS 离线用例全绿（38/38）` +
  `PASS 基线反证跳过` → `P3 自检：可以出补丁`、exit 0。上面第一次记录那 5 条红（`p3coord.config` 缺
  `character_id`）不复现了——夹具已修好，那条红到此变成历史；
- P5：`P5 离线自检：19/19 通过`、exit 0；第一次记的 5 条红同样不复现；
- `python3 -m compileall -q src/asuna tests tools` exit 0（退役后全树没有悬空引用），`__pycache__` 已清；
- P2 与讨论整理本轮**没重跑**：它们在本核候选上第一次记录时就是绿的，这次核候选一个文件没动
  （`development_files` 里 `tools/` `tests/` 全部 `changed=false`），与退役改动无关，属于可省掉的重复；
- 发布：本轮是操作员在宿主侧修好那对引号（v1.1 记的 `PACK_FAILED`）之后的首次尝试；具体结果以本次行动的
  `development_publish` 回执为准——这条记录能随新版本被发现，就说明打包过了、v1.1+v1.2 一起上线。

2026-10-05（v2 压缩这一轮，只改本技能文件并新增 `check_skill.py`，xiaoman 候选，**未发布**）：

- 压缩依据：核心技能 v1 的「发布前自检」一节已含五条命令、退出码读法、`__pycache__` 清理与夹具坑，
  「发布」一节已含重启清单与地板文件，「项目」一节已含 project 参数表——本文件原来的「入口」「权限与边界」
  「已知坑」和「项目归属」大半是重复，删掉改成指向；不一致时以核心技能为准。
- 保留的增量就是「增量」一节那四条。三条旧试用记录（2026-09-24、2026-10-02 两次）按历史保留：
  里面的 P5-b `24/24`、P3 `33/38` 是当时的实跑事实，别按它们跑现在这套。
- `check_skill.py` 为本轮新增：查 frontmatter、`name` 与目录一致、指向核心技能、四条增量在、
  通用命令清单没有回潮散文（`tools/p2_offline_check.py` 这类字面量在反引号里按引用放过）、脚本能编译。
  实跑与反证结果见行动报告。
