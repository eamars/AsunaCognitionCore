---
name: asuna-offline-selfchecks
description: 在没有 pytest、没有 pymongo、不联网的隔离沙箱里验证 Asuna 项目改动：跑仓库自带的零依赖离线用例与自检（P2 摘要环 / P3 自然语言安排 / P5 主动插话 / 讨论整理），外加 compileall；含各条命令、覆盖范围、退出码读法与已知坑（夹具替身包必须带上被装载真文件 import 的同包真模块）。development_* 默认绑定 xiaoman 插件项目，跑这套与发布认知核都要显式 project="core"。
---

# asuna-offline-selfchecks

## 用途

`development_run` 给的沙箱里只有标准库：`pytest`、`pymongo` 都 import 不到（`jsonschema` 有，`zoneinfo` 带真 DST 规则）。
仓库里 `tests/test_*.py` 大多要 Mongo，跑不动。能跑的是这套**零依赖离线自检**——它们用假集合 + 假 lane
把真文件装进临时包真算，不需要 Mongo、不需要 pytest、不碰网络，也不需要先起宿主。

改完代码要自证、或者发布前想看一眼有没有碰坏行为，跑这一套；全绿再 `development_publish`。

## 项目归属（ADR-008：跑之前先认准 project）

`development_*` 工具不写 `project` 时绑定的是**默认的 xiaoman 角色插件**项目（本技能文件就存在这个候选里）。
那个候选根目录只有 `skills/ seeds/ persona-model.json src/index.js`，**没有 `tools/` 也没有 `tests/`**，
下面这套命令在里面跑只会红在 `No such file or directory`——那是挂错项目，不是产品坏了。

- 跑这套离线套件：`development_run` 显式带 `project: "core"`（认知核候选里才有 `tools/` 和 `tests/`）。
- 发布：`development_publish` 默认也只冻结并发布 **xiaoman 插件**；改的是认知核（`src/asuna`、`tools/`、
  `tests/`）必须显式 `project: "core"`，否则 publish 会照样成功返回，但核改动一点没上线。
- 反过来也成立：只动插件（`skills/*/SKILL.md`）就不必带 project，而这套用例也不覆盖插件文件。
- QQ 适配器和它的技能在 **napcat-qq** 通道包里（`project: "napcat-qq"`，候选里是 `integration/ skills/ python/`）；
  `integration_*` 工具改的就是这个候选的 `integration/`，发布要带 `project: "napcat-qq"`，自测用 `qqadapter/selftest.py`。

## 入口（在认知核候选根目录 /task 里跑，`development_run` 带 `project="core"`）

```sh
python3 tools/p2_offline_check.py          # 摘要触发/归属/更正/闭环：P2
python3 tools/p5_offline_check.py          # 主动插话闸门与再核：P5
python3 tools/p3_offline_check.py          # 自然语言安排：编译面 + 只用标准库 + 38 条用例 + 基线反证
PYTHONPATH=tests python3 tests/discussion_digest_cases.py   # 讨论整理（按需整理）
python3 -m compileall -q src/asuna tests tools              # 语法面
```

- 退出码 0 = 全绿；非 0 时最后一行会写出「N/M 通过，失败：<用例名>」，`p3_offline_check` 红的时候打印
  `P3 自检：1 项不合格`，绿的时候打印 `P3 自检：可以出补丁`。
- 单独跑用例文件也行：`PYTHONPATH=tests python3 tests/p3_schedule_cases.py`（`p2_summary_loop_cases.py`、
  `p5_proactive_cases.py` 同理），它们自己打印 PASS/FAIL 行。
- `p3_offline_check.py [基线目录]` 的第二参是「改动前」副本，用来做反证；默认 `/task/p3-baseline`，
  找不到就跳过反证并说明——跳过不算失败。

## ADR-008 之后不再跑：`tools/p5b_ui_offline_check.py`

自绘三栏旧工作台随 ADR-008 退役（ADR-008 UI_SPEC：本方案替代旧
"自绘 Asuna 三栏工作台"；`CODEX_START.md` 验收口径写明"旧工作台不再是默认入口"；`IMPLEMENTATION.md` P4
"接回 QQ/定时/发布并退出旧工作台"）。随它一起退役的还有 `tools/p5b_ui_offline_check.py`——现在 `tools/`
里已经没有这个文件，硬跑只会 `python3: can't open file '/task/tools/p5b_ui_offline_check.py': [Errno 2]
No such file or directory`、exit 2。那是文件不存在，别当成"UI 检查挂了"或者产品坏了。

界面口径的验证位置也跟着搬了：UI_SPEC §6 要求在真实 DSH Web 页面上看 composer、角色实际内容、行动会话跳转、
记忆标签点开才取详情，并确认旧 `/asuna/api/state`、`/asuna/api/stream` 已退出；这部分连同宿主侧
`tests/test_*.py` 由操作员跑——本来这套离线件就覆盖不到 UI 实点，退役只是把那份假 lane 自检整个拿掉了。

顺带一句免得误读：`tools/` 里还有 `p1c_offline_check.py`、`read_image_offline_check.py`、
`linked_scenes_offline_check.py` 这几份，本技能一直没收录，**没收录 ≠ 已退役**；要跑它们先看各自 usage。

## 权限与边界

- 全部只读产品代码 + 只往 `/tmp` 写临时包；不写 Mongo、不发 QQ、不调模型。
- 跑完会留 `__pycache__`，发布前清掉：`find . -name '__pycache__' -type d -prune -exec rm -rf {} +`
- 这套覆盖不到真 Mongo 的 CAS、真 DSH 原生定时与 UI 实点：那些仍要宿主侧 `tests/test_*.py`（操作员跑）。

## 已知坑

夹具把**真文件**复制进临时包（`p3pkg` / `p3coord`），外面垫替身。真文件新加一条同包 import，
复制清单就得同步加一个文件，否则用例只会红在 `ModuleNotFoundError: No module named 'p3xxx.<name>'`，
看不出是夹具少带了文件。2026-09-24 就踩过一次：真 `context.prepare` 会 `from .self_state import SelfState`，
`p3coord` 没带 `self_state.py`，`context_projection_runs_end_to_end` 长期红。

## 版本

v1（2026-09-24）：首次记录，命令与结论都来自本次实跑。

v1.1（2026-10-02）：补 ADR-008 项目归属一节——`development_publish` 默认发布 xiaoman 插件，
认知核改动与这套离线套件都要显式 `project="core"`；入口标题同步标注。命令本身与判定口径没改。

v1.2（2026-10-02）：按 ADR-008 的退役变化对齐清单——摘掉 `p5b_ui_offline_check.py`（文件已不在 `tools/`，
frontmatter 描述与入口同步去掉 P5-b），新增退役一节写清"文件不存在"这种红怎么读、以及 UI 口径的新验证位置；
P3 用例数按实跑写成 38 条。旧工作台 / P5-b 的历史记录留在试用记录里，不删。

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
按"只跑与本次改动必要、且当前仍保留的件"选，带 `project="core"` 实跑：

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
