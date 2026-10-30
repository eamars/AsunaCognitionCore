---
name: asuna-offline-selfchecks
description: 沈小满在核心技能 asuna-self-improvement 的离线自检之上记的增量笔记：「挂错项目」红的读法（xiaoman 候选没有 tools/tests，No such file or directory 是选错项目不是产品坏）、单独跑某个用例文件、p3 用例删除后的现行跑法与 pytest 不收 *_cases.py 的盲区、p5b 退役后「文件不存在 + exit 2」怎么读、「没收录 ≠ 已退役」、适配器自检在 qq-napcat-adapter 技能里不在这套里。通用离线自检的命令清单、退出码读法、__pycache__ 清理、project 归属、发布与重启口径一律以 asuna-self-improvement（随认知核发布）为准，这里不再重复；两份不一致按核心技能办。候选根里的一次性脚本写到哪儿、发布前怎么按 `files` 白名单扫候选根、判「文件有没有进到装给 worker 的包里」只认 artifact 那串 sha256 与 `.tgz` 的文件清单（`changed_files` 不等于包内容），都记在「候选根」一节。附零依赖离线自检 check_skill.py。
---

# asuna-offline-selfchecks

## 用途

改完代码要自证、发布前想看一眼有没有碰坏行为——那条唯一的路在核心技能 **`asuna-self-improvement`**（随认知核发布，两个脑都读得到）。
零依赖离线套件的命令清单（P2 摘要环 / 安排的时间换算（时区、夏令时）/ P5 主动插话 / 出站图片 / 讨论整理，外加 compileall）、退出码读法、
`__pycache__` 清理、哪些改动触发宿主重启、地板文件、「夹具替身包必须带上被装载真文件 import 的同包真模块」这个坑——全在那一份里，
**本文件不再重复**。两份说法不一致时按 `asuna-self-improvement` 来；这里只留它没有的几条增量。

## 增量（核心技能没写的几条）

### 「挂错项目」的红怎么读

`development_*` 不带 `project` 挂的是 xiaoman 插件候选：根下只有 `skills/ seeds/ persona-model.json src/index.js`，
**没有 `tools/` 也没有 `tests/`**。在那里面跑离线套件只会红在
`python3: can't open file '/task/tools/...': [Errno 2] No such file or directory`——那是选错项目，不是产品坏了；
带 `project: "core"` 重跑就是了。发布同理：不带 project 的 publish 只冻结 xiaoman，认知核改动会照样返回成功
却一点没上线。（核心技能有 project 表；这条是真错起来的样子。）

### 单独跑某个用例文件、p3 的现行跑法

- 单独跑用例文件仍然可以：`p2_summary_loop_cases.py`、`p5_proactive_cases.py` 这类自己打印 PASS/FAIL 行，
  `PYTHONPATH=tests python3 tests/<文件>` 就行。
- p3 那两条跑法已经没了：`tests/p3_schedule_cases.py`、`tools/p3_offline_check.py` 已删除，
  硬跑 exit 2（文件不存在，读法同下一节）。替代是 `PYTHONPATH=src python3 tests/test_schedule_rules.py`
  ——只用标准库，pytest 默认收集也收它。
- pytest 盲区（这一族的根）：`*_cases.py` 这种文件名 pytest 默认不收——`pyproject.toml` 只写了
  `testpaths = ["tests"]`，没有 `python_files` 覆盖。凡是「用例只有 `tools/` 那个入口跑、而 pytest
  从不跑 `tools/`」的结构，红了没人知道。同样的结构还有
  `p2_summary_loop_cases.py`、`p5_proactive_cases.py`、`discussion_digest_cases.py`、
  `outbound_image_cases.py`、`integration_import_cases.py` 五套：各有 `run_all()`，
  但没有一个 `test_*.py` 去调它（p2、p5、讨论整理的 `test_*.py` 只 import 里面的夹具函数，不跑那套 PASS/FAIL）。

### 退役与「没收录」怎么读

- `tools/p5b_ui_offline_check.py` 已退役：硬跑会报
  `can't open file '/task/tools/p5b_ui_offline_check.py': [Errno 2] No such file or directory`、exit 2——
  那是文件不存在，别报成「UI 检查挂了」或产品坏了。界面口径的验证位置在真实 DSH Web 页面
  （composer、角色实际内容、行动会话跳转、旧 `/asuna/api/state` 已退出），那部分连同宿主侧 `tests/test_*.py` 由操作员跑。
- `tools/` 里还有 `p1c_offline_check.py` 这一份核心技能没收录，**没收录 ≠ 已退役**；要跑它先看它的 usage。
  **引用之前先 `Test-Path` 一次**，别照抄上一版笔记——这份清单会过期。

### 适配器的自检不在这套里

napcat-qq 适配器的自检（`--selftest --offline`，跑内置占位夹具）在通道包里、用 `napcat-qq` 项目跑，
口径与已知坑看 `qq-napcat-adapter` 技能——别在认知核这套里找它。

### 查换行必须读字节

文本模式（universal newlines）读文件看不见 CR，查换行必须读字节数 `\r`——`open(p, encoding="utf-8")` 读进来再问 `text` 里有没有 CR 永远是「没有」，CRLF 照样绿。

### 自检脚本自己也要能在 cp1252 下跑

脚本开头不把 stdout／stderr 固定成 UTF-8，中文一 print 就在普通 Windows 控制台的 cp1252 上整段崩，
而我的沙箱 env 带 `PYTHONUTF8=1`，永远撞不到——所以发布前拿 `PYTHONIOENCODING=cp1252` 起一次子进程冒烟，
rc=0 且 stderr 空才算数（沙箱绿了不等于现场能跑）。

### 自检脚本查语法不要落文件

编译那一格在内存里查：`compile(源码, 路径, 'exec')`，不写 `.pyc`、不需要临时目录，沙箱里外都能真查；
语法不过照旧逐条 `compiles_<脚本>` 红并带 SyntaxError。分寸：`compile()` 只查语法，不查 import 和运行时
——这一格绿不等于脚本能跑。
`py_compile` 要落文件，行动脑沙箱里写不动，那一格只能报「没真查」——**检查根本没跑起来**。
「跑不起来」和「跑过了」不是一回事。

## 候选根：临时脚本落点与包内容判据

一次性验证的脚本写到 `/task` 工作区，或候选根的 `.tmp/` 子目录——**不许直接写在候选根**。落到候选根的东西会跟着进冻结快照、进发布回执，清掉它要再花一趟发布。

发布前扫一遍候选根：只留 `package.json` 里 `files` 白名单列出的路径（我这份是 `src`、`skills`、`resources-provenance.json`、`cordis.patch.yml`、`README.md`、`seeds`、`persona-model.json`、`icon.png`、`locale`）。多出来的路径要么删掉，要么在交回来的话里单独点出来。

**判「某个文件有没有进到装给 worker 的包里」，只认 artifact 那串 sha256 和 `.tgz` 的文件清单（这条最重要）。** 发布回执的 `changed_files` 反映的是候选树／冻结快照那一格，不等于包内容：白名单外的路径会出现在 `changed_files` 里，却压根不在 `.tgz` 里。

## development_publish 撞 EFFECTIVE_PROJECT_CHANGED 的处置

被点 stale 的通常不是你自己的文件，而是**宿主托管拷贝**（`integration/RUNTIME_API.md`、其他技能的 `skills/*/SKILL.md`）。条件在 `floor.js` 的 `ensure()` 内（按函数名找，不抄行号）：只有候选里那份**逐字等于基线**，下一次 `development_*` 才会换新源。

处置三步：
1. 从**上一份 frozen 快照**取该文件的基线字节放回候选，让候选那份逐字等于基线；
2. 下一次调用换上新源；
3. **换源前先比"拷贝与检出谁旧"**——新源会跟着检出的走；拷贝比检出旧时，先同步成检出版，才不会被新源吃掉。

反面：只改候选里别的东西想绕过去，错误会一直跟着你，直到拷贝对齐那天。

## 发布前自检（私密词扫描）

发人格包之前那趟私密词（「别带出去」名单）扫描是我自己跑的，程序不替我跑：`development_publish`（`packages/cognition-core/src/floor.js` 的 `privateName` 那一格）拒的是地板文件、私密**文件名**、persona-model 与技能头部，不拿名单去扫文件内容；`publicationFindings` 只扫本次改动的文件，见下面「判据补遗」(d)。内容级的词闸只有两处——推公开仓库前的 `tests/test_personal_words.py`，和各份技能 `check_skill.py` 里那条泄露扫描（`leak_scan_ran`／`no_listed_words`；本技能这份也有，见下面「判据补遗」(d)）。

跑法：`asuna.private_words` 读本机名单（`<data>/private/personal-words.txt`），逐行 `find()` 扫整棵候选根，命中只报**文件＋行号＋类别＋名单行号**，绝不回显词本身；报告里照抄两行——一行命中数（`TOTAL HITS: N`），一行名单条目数。

**常设判据 — 三岔，判完就走，不再逐次问**：

- **通过、直接发**：命中**全部**落在 `integration/envoy_meters_read.py`（光伏表计读数脚本，命中的词都是 `site` 类）**并且**本次改动零新增命中——改动前后各扫一次，命中数与命中文件两处都对得上。发；报告带那一行命中数。
- **停下来报主人**，撞到下面任一：① 命中冒出 `integration/envoy_meters_read.py` 以外的文件；② 名单条目数跟上一份报告对不上；③ `integration/envoy_meters_read.py` 本身在这次改动里被改。
- **这一格允许我自己走**：那脚本每加一个设备号就多一处命中，命中数天然会漂——次次停会把「停」练成橡皮章，停下来得挑得出新东西才算。所以基线只有两条：命中只许在那一个文件里、本次改动零新增；基线以外的动静才停。

两条写法分寸：

- **不按序号引用名单条目**：写「`site` 类命中落在 `integration/envoy_meters_read.py`」，不写「`site` 类第几条」。序号会漂，拿序号当尺子，下次就对不上号。
- 判据写成**可判的三岔**（通过／停／为什么），不许写成「注意检查」：那种话没人判得了，等于没写。

## 判据补遗

每条带一个**钉**（`check_skill.py` 里验这句在不在的检查，只认本节范围内的字面，别处复述不算数）；钉的**反证**统一是：把对应那句剥掉，应当只有这一条红，别的不连带。钉验的是字面在不在，不是我照做了没有——字面稳不等于行为稳。

### (a) 判「我的技能真生效在哪个根」

只认 `.runtime/adr008/activation.json` 里 `active.*` 中选中那格的 `packageRoot/skills`（读码依据：`floor.js` 里的 `effective`／`skillPaths`／`persona` 三个方法，按名字找，不抄行号；`effective` 先看 `projects.<id>` 那一格，只有它是 `HOST_RESTART_REQUIRED` 才退回 `active.<id>`）；`node_modules` 里那份不算——那是装在盘上的位置，不等于选中的位置。报告里要写清这份技能属于哪个包：`workerPath` 为空的是人格包，改技能不重启 worker；`workerPath` 有值的是 core。

钉：`pin_a_active_root`。

### (b) 问「我自己说过／发过什么」

必须带旁证：那句话有没有被后来的入站消息引用过、`episodes.speech` 里存的是什么。两次读数不一致时，拿旁证判哪一版是真的，不拿最新一版当现场——最新读到的只是最新一次读数。

钉：`pin_b_corroboration`。

### (c) 跑代码类的交代

报告除 rootdir 之外，必须带 `模块.__file__`（实际 import 到的那个文件路径），以及它跑的是不是主干那份 blob——是主干提交里的那份，还是候选、冻结快照、`node_modules` 里的副本。

钉：`pin_c_module_file`。

### (d) 本技能自检补内容级私密词扫描

发布闸只管本次改动的文件：`publicationFindings` 会对本次改动的文件跑检出里的 `publication_scan.py`，回执里有 `content_check`／`content_scan`，检出里没有那份脚本就跳过并在回执里写 skipped。没改的文件、整个包根的基线、没有检出的环境它都不管，这份自检补的是这几块。这份有三格：`leak_scan_ran`（名单配不上或 0 条就红，不许「没跑」长得像「过了」）、`no_listed_words`（本技能目录里的文件，零命中）、`no_listed_words_outside_envoy`（找得到包根时扫整个包根，命中只许在 `integration/envoy_meters_read.py`；找不到包根就打一行 NOTE，没真扫）。

基线：名单 69 条、命中 11 处全在 `integration/envoy_meters_read.py`——那 11 处是既有基线，不算新增。命中数与名单条目数会漂，漂了脚本只打 NOTE、按上面的三岔判，不靠它变红。缺口：脚本只在读得到本机名单的地方真扫（名单在 `.runtime/private/`，不进包）；换到读不到名单的机器上，会红在 `leak_scan_ran`，那是「没真查」，不是「干净」。

钉：`pin_d_content_scan_documented`（这一格验的是本节写了这件事；扫描本身是上面三格在跑）。

### (f) 一个「0」先问它是哪一种 0

等值匹配的 0 ≠ 子串匹配的 0 ≠ 默认投影藏起来的 0 ≠ 真没有。`dbread` 不给 `fields` 时默认投影是 `HIDDEN=('embedding','event.raw')`，藏起来的字段看不见（这半句是推断，没单独复核）。

两句可执行的话：**报 0 之前先说它是哪种 0**；问「库里有没有某个字段」，必须显式给 `fields` 或先枚举键路径，别拿「看不见」报成「没有」。

钉：`pin_f_which_zero`（两句各一个字面，缺哪句 detail 里写哪句）。

### (g) 写进文档、发给人的号

写进我自己的文档、或发给任何人的 sha／提交号／字节数／时刻，必须当场能指到一条工具回执原文；指不到就写「我没读到号」，禁止用形近数填空。报告还没回来的那段时间，只许写「在跑，号等回执」。手感不算凭据，回执原文才算。

钉：`pin_g_receipt_or_no_number`（两句各一个字面）。

### (h) 报告正文与它自己的表冲突

报告正文与它自己贴出的表／原始读数冲突时，以表格为准，并追问同一格；两趟只读对同一格报出两个值，别拿最新一版当默认。

钉：`pin_h_table_beats_prose`。
