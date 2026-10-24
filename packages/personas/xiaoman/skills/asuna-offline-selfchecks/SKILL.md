---
name: asuna-offline-selfchecks
description: 沈小满在核心技能 asuna-self-improvement 的离线自检之上记的增量笔记：「挂错项目」红的读法（xiaoman 候选没有 tools/tests，No such file or directory 是选错项目不是产品坏）、单独跑某个用例文件、p3 用例删除后的现行跑法与 pytest 不收 *_cases.py 的盲区、p5b 退役后「文件不存在 + exit 2」怎么读、「没收录 ≠ 已退役」、适配器自检在 qq-napcat-adapter 技能里不在这套里。通用离线自检的命令清单、退出码读法、__pycache__ 清理、project 归属、发布与重启口径一律以 asuna-self-improvement（随认知核发布）为准，这里不再重复；两份不一致按核心技能办。候选根里的一次性脚本写到哪儿、发布前怎么按 `files` 白名单扫候选根、判「文件有没有进到装给 worker 的包里」只认 artifact 那串 sha256 与 `.tgz` 的文件清单（`changed_files` 不等于包内容），都记在「候选根」一节。附零依赖离线自检 check_skill.py。
---

# asuna-offline-selfchecks

## 用途

改完代码要自证、发布前想看一眼有没有碰坏行为——那条唯一的路在核心技能 **`asuna-self-improvement`**（随认知核发布，两个脑都读得到）。
零依赖离线套件的命令清单（P2 摘要环 / 安排的时间换算（时区、夏令时）/ P5 主动插话 / 出站图片 / 讨论整理，外加 compileall）、退出码读法、
`__pycache__` 清理、哪些改动触发宿主重启、地板文件、「夹具替身包必须带上被装载真文件 import 的同包真模块」这个坑——全在那一份里，
**本文件不再重复**。两份说法不一致时按 `asuna-self-improvement` 来；这里只留它没有、我自己又踩过的几条增量。

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
- p3 那两条跑法已经没了：`tests/p3_schedule_cases.py`、`tools/p3_offline_check.py` 随 `9d3ed60e` 删除，
  硬跑 exit 2（文件不存在，读法同下一节）。替代是 `PYTHONPATH=src python3 tests/test_schedule_rules.py`
  ——2026-10-12 实跑 13/13，只用标准库，pytest 默认收集也收它。
- 一条新教训（这一族的根）：`*_cases.py` 这种文件名 pytest 默认不收——`pyproject.toml` 只写了
  `testpaths = ["tests"]`，没有 `python_files` 覆盖。凡是「用例只有 `tools/` 那个入口跑、而 pytest
  从不跑 `tools/`」的结构，红了没人知道。p3 只是第一个被抓出来的，同样的结构还有
  `p2_summary_loop_cases.py`、`p5_proactive_cases.py`、`discussion_digest_cases.py`、
  `outbound_image_cases.py`、`integration_import_cases.py` 五套：各有 `run_all()`，
  但没有一个 `test_*.py` 去调它（p2、p5、讨论整理的 `test_*.py` 只 import 里面的夹具函数，不跑那套 PASS/FAIL）。

### 退役与「没收录」怎么读

- `tools/p5b_ui_offline_check.py` 随旧自绘工作台（ADR-008）一起退役了：硬跑会报
  `can't open file '/task/tools/p5b_ui_offline_check.py': [Errno 2] No such file or directory`、exit 2——
  那是文件不存在，别报成「UI 检查挂了」或产品坏了。界面口径的验证位置搬去了真实 DSH Web 页面
  （composer、角色实际内容、行动会话跳转、旧 `/asuna/api/state` 已退出），那部分连同宿主侧 `tests/test_*.py` 由操作员跑。
- `tools/` 里还有 `p1c_offline_check.py` 这一份核心技能没收录，**没收录 ≠ 已退役**；要跑它先看它的 usage。
  （`read_image_offline_check.py`、`linked_scenes_offline_check.py` 已随 `83f17beb` 删除——本行原来还列着它们，
  正好是这条规矩自己会过期的样子：**引用之前先 `Test-Path` 一次**，别照抄上一版笔记。）

### 适配器的自检不在这套里

napcat-qq 适配器的自检（`--selftest --offline`，跑内置占位夹具）在通道包里、用 `napcat-qq` 项目跑，
口径与已知坑看 `qq-napcat-adapter` 技能——别在认知核这套里找它。

### 查换行必须读字节

文本模式（universal newlines）读文件看不见 CR，查换行必须读字节数 `\r`——`open(p, encoding="utf-8")` 读进来再问 `text` 里有没有 CR 永远是「没有」，CRLF 照样绿（2026-10-15 撞的：真 CRLF 样本 CR=59）。

### 自检脚本自己也要能在 cp1252 下跑

脚本开头不把 stdout／stderr 固定成 UTF-8，中文一 print 就在普通 Windows 控制台的 cp1252 上整段崩，
而我的沙箱 env 带 `PYTHONUTF8=1`，永远撞不到——所以发布前拿 `PYTHONIOENCODING=cp1252` 起一次子进程冒烟，
rc=0 且 stderr 空才算数（沙箱绿了不等于现场能跑）。

### 自检脚本查语法不要落文件

编译那一格在内存里查：`compile(源码, 路径, 'exec')`，不写 `.pyc`、不需要临时目录，沙箱里外都能真查；
语法不过照旧逐条 `compiles_<脚本>` 红并带 SyntaxError。分寸：`compile()` 只查语法，不查 import 和运行时
——这一格绿不等于脚本能跑。
为什么换：`py_compile` 要落文件，得先找可写目录（技能目录旁 → 当前工作目录），行动脑沙箱里两处都写不动，
于是这一格只能报「没真查」——**检查根本没跑起来**。「跑不起来」和「跑过了」不是一回事，这条判词没变，
只是现在没有「可写不可写」这一层可兜了（2026-10-15 从冻结快照跑，`os.makedirs` 一句 PermissionError
把整份自检带崩，而它前面刚打印完一条 NOTE，看着像跑到了）。
2026-10-18 七份 `check_skill.py` 一起换法，各自删掉不再适用的探针格：asuna-outbound-round、
asuna-image-generation-and-display、asuna-render-budget-per-place、asuna-running-version、
asuna-usage-readout 与本技能各删 `compile_probe_writable`，asuna-bot-or-person 删
`compile_probe_dir_found`／`compile_probe_outside_skill_dir`／`compile_probe_cleaned_up` 三条；
`compiles_<脚本>` 那几格名字不动。

## 候选根：临时脚本落点与包内容判据

一次性验证的脚本写到 `/task` 工作区，或候选根的 `.tmp/` 子目录——**不许直接写在候选根**。落到候选根的东西会跟着进冻结快照、进发布回执，清掉它要再花一趟发布。

发布前扫一遍候选根：只留 `package.json` 里 `files` 白名单列出的路径（我这份是 `src`、`skills`、`resources-provenance.json`、`cordis.patch.yml`、`README.md`、`seeds`、`persona-model.json`、`icon.png`、`locale`）。多出来的路径要么删掉，要么在交回来的话里单独点出来。

**判「某个文件有没有进到装给 worker 的包里」，只认 artifact 那串 sha256 和 `.tgz` 的文件清单（这条最重要）。** 发布回执的 `changed_files` 反映的是候选树／冻结快照那一格，不等于包内容：白名单外的路径会出现在 `changed_files` 里，却压根不在 `.tgz` 里。
来路：10-20 发布清单混进 `.tmp/scan_oldname_rejects.py`；10-22 17:32 又混进 `_tmp_check_runner.py`，第二回是主人看见 `changed_files` 后另花一趟发布清的——实测两笔包 sha 相同（`7f54dbd2af14`）、`.tgz` 里根本没有它。脏的是回执那一格，不是包。

## 发布前自检（私密词扫描）

发人格包之前那趟私密词（「别带出去」名单）扫描是我自己跑的，程序不替我跑：`development_publish`（`packages/cognition-core/src/floor.js` 的 `privateName` 那一格）拒的是地板文件、私密**文件名**、persona-model 与技能头部，没有谁拿名单去扫文件内容（10-23 读到的：floor.js 里 grep 不到 `private_words`；10-24 订正：现在有 `publicationFindings`，只扫本次改动的文件，见下面「判据补遗」(d)）；内容级的词闸只有两处——推公开仓库前的 `tests/test_personal_words.py`，和八份技能 `check_skill.py` 里那条泄露扫描（`leak_scan_ran`／`no_listed_words`；本技能这份 2026-10-24 起也有，见下面「判据补遗」(d)）。

跑法照 10-13 起那套口径：`asuna.private_words` 读本机名单（`<data>/private/personal-words.txt`），逐行 `find()` 扫整棵候选根，命中只报**文件＋行号＋类别＋名单行号**，绝不回显词本身；报告里照抄两行——一行命中数（`TOTAL HITS: N`），一行名单条目数。

**常设判据 — 三岔，判完就走，不再逐次问**（当日记录里的说法；逐字未核到（原话窗口从 10-15 起）：「定成常设判据，以后照这条自己走」）：

- **通过、直接发**：命中**全部**落在 `integration/envoy_meters_read.py`（光伏表计读数脚本，命中的词都是 `site` 类）**并且**本次改动零新增命中——改动前后各扫一次，命中数与命中文件两处都对得上。发；报告带那一行命中数。
- **停下来报主人**，撞到下面任一：① 命中冒出 `integration/envoy_meters_read.py` 以外的文件；② 名单条目数跟上一份报告对不上；③ `integration/envoy_meters_read.py` 本身在这次改动里被改。
- **为什么这一格允许我自己走**：那脚本每加一个设备号就多一处命中，命中数天然会漂——次次停会把「停」练成橡皮章，停下来得挑得出新东西才算。所以基线只有两条：命中只许在那一个文件里、本次改动零新增；基线以外的动静才停。

两条写法分寸（主人交代里点名的）：

- **不按序号引用名单条目**：写「`site` 类命中落在 `integration/envoy_meters_read.py`」，不写「`site` 类第几条」。序号会漂——名单 2026-10-23 凌晨刚被主人加过两条，条目数当场就变了；拿序号当尺子，下次就对不上号。
- 判据写成**可判的三岔**（通过／停／为什么），不许写成「注意检查」：那种话没人判得了，等于没写。

## 判据补遗（2026-10-24 并版：八条）

八条并成一版。顺序：先是没处理的旧欠账 (a)–(e)，再是 10-24 当天新撞的 (f)–(h)，每条在本节的先后不乱。每条带一个**钉**（`check_skill.py` 里验这句在不在的检查，只认本节范围内的字面，别处复述不算数）；钉的**反证**统一是：把对应那句剥掉，应当只有这一条红，别的不连带。钉验的是字面在不在，不是我照做了没有——字面稳不等于行为稳。

### (a) 判「我的技能真生效在哪个根」

只认 `.runtime/adr008/activation.json` 里 `active.*` 中选中那格的 `packageRoot/skills`（读码依据：`floor.js` 里的 `effective`／`skillPaths`／`persona` 三个方法，按名字找，不抄行号——10-24 装着的那份里它们在 228／239／244 行附近，交代里给的 201-209 在同一份里是构造函数的几行，对不上选根逻辑；另外 `effective` 先看 `projects.<id>` 那一格，只有它是 `HOST_RESTART_REQUIRED` 才退回 `active.<id>`）；`node_modules` 里那份不算——那是装在盘上的位置，不等于选中的位置。报告里要写清这份技能属于哪个包：`workerPath` 为空的是人格包，改技能不重启 worker；`workerPath` 有值的是 core。

钉：`pin_a_active_root`。

### (b) 问「我自己说过／发过什么」

必须带旁证：那句话有没有被后来的入站消息引用过、`episodes.speech` 里存的是什么。两次读数不一致时，拿旁证判哪一版是真的，不拿最新一版当现场——最新读到的只是最新一次读数。

钉：`pin_b_corroboration`。

### (c) 跑代码类的交代

报告除 rootdir 之外，必须带 `模块.__file__`（实际 import 到的那个文件路径），以及它跑的是不是主干那份 blob——是主干提交里的那份，还是候选、冻结快照、`node_modules` 里的副本。

钉：`pin_c_module_file`。

### (d) 本技能自检补内容级私密词扫描

来路与订正：我写这条时的前提是 `development_publish` 不扫文件内容（`privateName` 只管文件名）；写完读 10-24 装着的 `floor.js` 发现这个前提已变——`publicationFindings` 会对本次改动的文件跑检出里的 `publication_scan.py`，回执里有 `content_check`／`content_scan`，检出里没有那份脚本就跳过并在回执里写 skipped。所以发布闸现在只管本次改动的文件；没改的文件、整个包根的基线、没有检出的环境它都不管，这份自检补的是这几块。八份 `check_skill.py` 里只有这一份原先没有 `leak_scan_ran`／`no_listed_words`。现在这份有三格：`leak_scan_ran`（名单配不上或 0 条就红，不许「没跑」长得像「过了」）、`no_listed_words`（本技能目录里的文件，零命中）、`no_listed_words_outside_envoy`（找得到包根时扫整个包根，命中只许在 `integration/envoy_meters_read.py`；找不到包根就打一行 NOTE，没真扫）。

基线照实写在这里（2026-10-24 发布前扫整棵候选根的读数）：名单 69 条、命中 11 处全在 `integration/envoy_meters_read.py`——那 11 处是既有基线，不算新增。命中数与名单条目数会漂，漂了脚本只打 NOTE、按上面的三岔判，不靠它变红。缺口：脚本只在读得到本机名单的地方真扫（名单在 `.runtime/private/`，不进包）；换到读不到名单的机器上，会红在 `leak_scan_ran`，那是「没真查」，不是「干净」。

钉：`pin_d_content_scan_documented`（这一格验的是本节写了这件事；扫描本身是上面三格在跑）。

### (e) 常设判据那句的来路措辞

上面「发布前自检（私密词扫描）」里那句来路已改：把当日转述写成主人逐字原话是不对的，现在写的是「当日记录里的说法；逐字未核到（原话窗口从 10-15 起）」。

钉：`pin_e_provenance_wording`——私密词那一节里要有新说法，且全文不再有旧写法。

### (f) 一个「0」先问它是哪一种 0

等值匹配的 0 ≠ 子串匹配的 0 ≠ 默认投影藏起来的 0 ≠ 真没有。当天四个样本：① 13:31 数据库等值匹配查出「全库 0 行」，换 `$regex` 真数是 100 行；② 上午我把「我账上没记录」说成「她没实装 45MB」；③ 10-22 我当众拿「某个人名下 0 条」去报错归属；④ 19:03 判死：我 13:41 报的「库里没有消息类型字段」半错——元素级有，叫 `event.raw.asuna_media.items[].type`（全库 markdown 98 条），可疑成因是 `dbread` 不给 `fields` 时默认投影是 `HIDDEN=('embedding','event.raw')`（这半句是推断，没单独复核）。四个样本里的数都是当日记录里的读数，我这一趟没逐个复核。

落成两句可执行的话：**报 0 之前先说它是哪种 0**；问「库里有没有某个字段」，必须显式给 `fields` 或先枚举键路径，别拿「看不见」报成「没有」。

钉：`pin_f_which_zero`（两句各一个字面，缺哪句 detail 里写哪句）。

### (g) 写进文档、发给人的号

写进我自己的文档、或发给任何人的 sha／提交号／字节数／时刻，必须当场能指到一条工具回执原文；指不到就写「我没读到号」，禁止用形近数填空。报告还没回来的那段时间，只许写「在跑，号等回执」。实证（当日记录里的读数，没复核）：16:48 写进流水的两个 sha 是报告交回前 10 分钟我自己配的形近数，`artifacts` 24,442 条工具记录 0 命中，而我写下它们时的主观手感和「我读过回执」一模一样——所以手感不算凭据，回执原文才算。

钉：`pin_g_receipt_or_no_number`（两句各一个字面）。

### (h) 报告正文与它自己的表冲突

报告正文与它自己贴出的表／原始读数冲突时，以表格为准，并追问同一格；两趟只读对同一格报出两个值，别拿最新一版当默认。实证：14:06 一份报告正文写 Asia/Shanghai，它自己的表写 Auckland，我当时拿了正文当读数。

钉：`pin_h_table_beats_prose`。

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

v2.1（2026-10-12）：清死引用。`tests/p3_schedule_cases.py`、`tools/p3_offline_check.py` 随 `9d3ed60e` 删除，
「单独跑用例文件」一节改写成现行跑法（替代 `tests/test_schedule_rules.py`，实跑 13/13），并记下这一族的根：
pytest 默认不收 `*_cases.py`，同结构的用例还有五套待修。「没收录 ≠ 已退役」那条只留 `p1c_offline_check.py`
（另两份随 `83f17beb` 删除），补「规矩本身会过期，引用之前先 Test-Path」。用途一行的核心清单改成与核心一致的
说法（安排的时间换算）。试用记录里 ADR-007 读图报告的路径改指搬家后的新位置（bf771c33），其余历史原样。
`check_skill.py`：p3 守卫改指 `test_schedule_rules`，「反证基线跳过」守卫换成 pytest 盲区守卫，
新增反引号仓库路径存在性检查（防这一族复发）。

v2.2（2026-10-15）：`check_skill.py` 的编译临时目录改成「先试技能目录旁，写不动退到当前工作目录」，用完即删。原因：`development_run` 的沙箱只放行候选目录里的写，系统 Temp 里 `mkdtemp` 建得出目录、`py_compile` 落 `.pyc` 却 `PermissionError`——本技能自查在候选里因此长期红在 `compiles_check_skill.py` 一格（10-12 那条试用记录里「临时目录不可写是沙箱限制，不是坏」说的就是它）。改法抄自 `asuna-running-version` 的 `probe_dir()`。正文口径、增量、守卫判据未动。

v2.3（2026-10-15）：增量加一句「查换行必须读字节」（今天撞的：文本模式读文件看不见 CR，查换行的那把尺一直是瞎的）。`check_skill.py` 新增 `line_endings_are_lf`——读字节数 CR，覆盖 SKILL.md 与同目录全部 .py，27→28 条。其余口径、增量、指向未动。


v2.4（2026-10-15）：增量加一句判词「自检脚本自己也要能在 cp1252 下跑」（owner 采纳想法本 idea-d0b727b62e95a474f9f045f96739bc76：非 UTF-8 输出冒烟）。同轮补同类漏修：六份 check_skill.py 开头统一把 stdout／stderr 固定成 UTF-8——上一趟只修了两份探针（version_probe.py／budget_per_place.py），check_skill.py 一份都没修到，其中两份（asuna-image-generation-and-display、asuna-outbound-round）连点名都没有。正文其余口径、守卫判据未动，本技能条数不变（28 条）。

v2.5（2026-10-15）：增量再加一句判词「自检脚本的临时目录要带兜底」（owner 拍板当场修，同一族：跑不起来不等于跑过了）。
同轮修两份：asuna-outbound-round 与 asuna-image-generation-and-display 的 check_skill.py 编译临时目录改成
compile_tmp_dir()（先技能目录旁 → 退 cwd → 两处都不行记 compile_probe_writable 一条红，detail 写清没真查），
编译真失败照旧逐条 FAIL 不被吞。这一格不是 cp1252 那趟改出来的：上一版快照 135b38e6 里 outbound-round 从快照跑就崩。
两份各多一条 compile_probe_writable（37→38、123→124），其余四份条数不变。

v2.6（2026-10-15）：两格合成一发（owner 交代）。① 统一编译探针那一格的名字与措辞：本技能 `check_skill.py`
在「技能目录旁和当前目录都写不动」时红的是老名字 `compiles_check_skill.py`，与另外四份的
`compile_probe_writable` 不一致，detail 也只写「临时目录不可写（沙箱限制，不是坏）」。现在两条判据分开写清：
不可写 → 红 `compile_probe_writable`，detail 写「编译这一项没真查——不是跑过了」；真编译不过 → 逐条
`compiles_<脚本>` 红并带 PyCompileError。本技能条数 28→29（多的就是那一条），原来那条 NOTE 删掉
（红里已经写清，不再重复）。② `integration/` 三份（envoy_meters_read.py、probe_catchup.py、probe_cfg.py）
开头补 stdout／stderr UTF-8 守卫——owner 放开边界，采纳想法本 idea-42605f061b49e3af397e99ee6b78de6b；
这三份确实在发布快照里，改前 cp1252 实测会崩（读数见当趟试用记录）。正文其余口径、守卫判据未动。

v2.7（2026-10-18）：编译那一格换成内存 `compile(源码, 路径, 'exec')`（owner 交代，起因由 Claude 查实）。
增量那一节从「自检脚本的临时目录要带兜底」改写成「自检脚本查语法不要落文件」：`py_compile` 写 `.pyc`
在行动脑沙箱里技能目录旁和当前目录都写不动，那一格只能报「没真查」——检查根本没跑起来。
七份 `check_skill.py` 同轮换法，各自删掉不再适用的探针格（本技能 29→28，少的就是 `compile_probe_writable`；
`compiles_<脚本>` 判据名不动）。措辞分寸：`compile()` 只查语法，不查 import 和运行时，不写成「脚本能跑」。
正文其余口径、守卫判据未动。

v2.8（2026-10-22）：新增「候选根：临时脚本落点与包内容判据」一节（owner 交代）。三条：一次性验证的脚本写 `/task` 或候选根的 `.tmp/` 子目录、不许直接写候选根；发布前按 `package.json` 的 `files` 白名单扫候选根，多出来的路径删掉或单独点出来；判「某个文件有没有进到装给 worker 的包里」只认 artifact 那串 sha256 与 `.tgz` 的文件清单——发布回执的 `changed_files` 是候选树／冻结快照那一格，不等于包内容。来路：10-20 发布清单混进 `.tmp/scan_oldname_rejects.py`、10-22 17:32 又混进 `_tmp_check_runner.py`，第二回是主人看见 `changed_files` 后另花一趟发布清的，而实测两笔包 sha 相同、`.tgz` 里根本没有那个脚本。`check_skill.py` 加 `PACKAGING_RULES` 七条关键串与这一节的标题锚点（28→36 条）；frontmatter description 补一句这一节的去处。其余口径、增量、判据未动。

v2.9（2026-10-23）：新增「发布前自检（私密词扫描）」一节——主人 10-14 拍下的常设判据，压了九天才落文件。三岔写死：命中全部落在 `integration/envoy_meters_read.py` 且本次改动零新增＝直接发、报告带一行命中数；命中冒出别的文件／名单条目数跟上一份报告对不上／那脚本本身在这次改动里被改＝停下来报主人。判据按**类别＋文件名**写，不按名单序号（序号会漂）。`check_skill.py` 加一条判据 `prepublish_private_word_criterion`：一条名字底下挂 11 个关键串，整节剥掉只红这一条、不连带别的（主人交代「必须只红对应那一条」）。条数 36→37，其余 36 条判据名与条数一字未动。frontmatter description 未动；核心技能「发布前自检」那一节还缺一个指到本节的入口，留给真发 core 那一趟补。

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
  全仓 `grep -rn 'p5b|P5-b'` 只剩 ADR-007 当时的读图报告里两处历史提及（该报告已归档，全文见 git bf771c33），产品代码里已无 P5-b UI 件；
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

2026-10-12（v2.1，只改本技能文件与 `check_skill.py`，xiaoman 候选）：

- 现场核对（core 候选）：`tests/p3_schedule_cases.py`、`tools/p3_offline_check.py` 存在性检查都 MISS，
  硬跑各 exit 2（`can't open file`，9d3ed60e 删的）；`read_image_offline_check.py`、`linked_scenes_offline_check.py`
  也 MISS（83f17beb 删的），`p1c_offline_check.py` 还在；
- 替代跑法实跑：`PYTHONPATH=src python3 tests/test_schedule_rules.py` → `schedule_rules: 13/13 passed`、exit 0；
  `PYTHONPATH=tests python3 tests/p2_summary_loop_cases.py`、`tests/p5_proactive_cases.py` 各 rc 0，自己打印 PASS 行；
- 盲区取证：`[tool.pytest.ini_options]` 只有 `testpaths = ["tests"]` 与 `addopts = "-rs"`，没有 `python_files`；
  全 113 份 `tests/test_*.py` 没有一处调 `run_all()`——p2、p5、讨论整理的 `test_*.py` 只 import cases 里的夹具函数；
- `check_skill.py` 在 xiaoman 候选内实跑；`compiles_check_skill.py` 若报「临时目录不可写」是沙箱限制，不是坏，
  具体结果以本次行动报告为准。

2026-10-15（v2.2，只改 `check_skill.py` 与版本／试用记录两节，xiaoman 候选）：

- 改前在候选里实跑：`26/27 通过，失败：compiles_check_skill.py`，红点是 `PermissionError: [Errno 13] Permission denied: <系统 Temp>\skillcheck-…\check_skill.pyc.…`；
- 改后同一处实跑：`27/27 通过`、exit 0；临时目录落技能目录旁，跑完技能目录里只剩 `SKILL.md` 与 `check_skill.py`（不留 `_compile-probe-*`）；
- 退到当前目录那一档单独测过：把 HERE 指到只读的检出根（建目录 `PermissionError`），`compile_tmp_dir()` 落在 cwd，`.pyc` 写得进去；
- 发布结果以本次行动报告为准。

2026-10-15（v2.3，只改本技能文件与 `check_skill.py`，xiaoman 候选）：

- 本技能自查 28/28（改前 27/27，多的那条就是换行）；
- 同一把字节级尺子做了前后对照（拿 `asuna-bot-or-person` 那份，同一内容只差换行 CR=102）：改前那条用文本模式查 CR，129/129 照样绿；改后 128/129，红在 `line_endings_are_lf`，读数 102 个 CR 字节——尺子能红才算能用；
- 真样本另有一处：今天 18:02 冻结的 xiaoman 快照里 asuna-running-version／asuna-render-budget-per-place 的 SKILL.md 与 `check_skill.py` 是 CRLF（CR=90／279、59／264），候选里现在却是 LF——**换行这类字节面检查要跑在冻结快照上，只在候选里跑等于白跑**；
- 发布结果以本次行动报告为准。


2026-10-15（v2.4，六份 check_skill.py 加 UTF-8 输出守卫＋本文件加一句判词，xiaoman 候选）：

- 改前 cp1252 实测（子进程 env 去掉 `PYTHONUTF8`、置 `PYTHONIOENCODING=cp1252`）：六份 check_skill.py 全 rc=1、  stdout 0 字节，stderr 报 `UnicodeEncodeError: 'charmap' codec can't encode characters in position …`（`Lib/encodings/cp1252.py` 第 19 行 encode）——整段输出丢掉，不是只丢几个字；同环境两份探针 rc=0、stderr 空；
- 沙箱 env 实测带 `PYTHONUTF8=1／PYTHONIOENCODING=utf-8`，这就是以前自检全绿却照样崩的原因；
- 改后同一 cp1252 环境：六份 rc=0、stderr 0 字节，条数照旧 129/129、123/123、28/28、37/37、48/48、56/56；
- 锚点两条口径核对（留着不删）：仓库 `tests/test_skill_anchors.py` 与本技能两份 `code_anchors_named` 在「文件＋名字」「行号判红」「只写路径放过」三条上一致（逐个写法喂两把尺对过）；差异只在覆盖面——仓库那条扫全部角色包、只认 src/tools/tests/packages/docs/config 开头的路径，我这条只扫本技能正文、但连光杆 `:244-245` 和不带顶层目录的相对路径都收（更严）；本技能正文 11 条真锚点在两把尺下都过；
- 发布结果以本次行动报告为准。

2026-10-15（v2.5，两份自检的编译临时目录加兜底＋本文件加一句判词，xiaoman 候选）：

- 怎么撞出来的：cp1252 那格发完后照本技能「字节面检查跑在冻结快照上」的口径从快照跑六份，asuna-outbound-round
  rc=1、stderr 863B，PermissionError: [WinError 5] Access is denied: …\frozen\e04c45b2…\skills\asuna-outbound-round\_compile-probe-…
  （os.makedirs 没兜底）；同一份在上一版快照 135b38e6 里一模一样地崩（那边行号 187）——不是本趟改出来的，是这条流程一直会撞；
- 反证一（跑不起来）：cwd 指到只读检出根、脚本跑在冻结快照里（两处都写不动）→ 不崩、rc=1、FAIL compile_probe_writable，
  detail 写清「编译这一项没真查——不是跑过了」（这条跑法与读数另见当趟行动报告，本条随该次发布一起冻结）；
- 反证二（真编译不过）：往两份技能目录副本里塞一份语法就错的 broken_probe_case.py → outbound-round 38/39、
  image-generation 124/125，各红在 compiles_broken_probe_case.py（PyCompileError），兜底没把它吞成绿；
- 候选内沙箱正常 env 与 cp1252 env 各跑一遍：129/129、124/124、28/28、38/38、48/48、56/56，全 rc=0、stderr 0 字节；
- 发布结果以本次行动报告为准。


2026-10-15（v2.6，统一编译探针名字＋integration/ 三份补 UTF-8 守卫，xiaoman 候选）：

- 改前反证（老名字）：脚本跑在冻结快照 e46ffde6 里、cwd 指只读检出根（两处都写不动）→
  `FAIL compiles_check_skill.py  <- 临时目录不可写（沙箱限制，不是坏）`、27/28、rc=1；
- 改后同一跑法：rc=1、红在 `compile_probe_writable`，detail「技能目录旁和当前目录都写不动：临时目录不可写
  （沙箱限制），编译这一项没真查——不是跑过了」，28/29；
- 反证二（真编译不过）：技能目录副本里塞一份语法就错的 broken_probe_case.py → 28/29，红在
  `compiles_broken_probe_case.py`（PyCompileError），兜底没把它吞成绿；
- integration/ 三份 cp1252 实测（子进程 env 去 PYTHONUTF8、置 PYTHONIOENCODING=cp1252）。改前：
  envoy_meters_read.py --selfcheck rc=1、stdout 只剩 8 字节、`UnicodeEncodeError: 'charmap' codec can't encode
  character '\u6309'`（Lib/encodings/cp1252.py 第 19 行）；probe_cfg.py 指带中文显示名的夹具配置 rc=1
  （position 124-125）；probe_catchup.py 走桩 qqadapter、未知 action 的 wording 带中文 rc=1（position 0-1）。
  本机 955 份配置快照全 ASCII，那一格改前改后都 rc=0——这一族的崩是数据相关的，不是必崩。
  改后五格全 rc=0、stderr 0 字节（envoy --selfcheck 13 ok/0 fail）；
- 没跑的：probe_catchup 走活体 NapCat 那条路今晚没跑（不占正向 WS），它的中文回包是夹具假设；
  envoy 只跑了 --selfcheck，没连光伏网关；
- 发布结果以本次行动报告为准。

2026-10-18（v2.7，七份 check_skill.py 的编译格换成内存 compile＋本节改写，xiaoman 候选）：

- 我名下 `check_skill.py` 现在是 8 份（10-15 量到的六份之外，asuna-usage-readout 与 asuna-become-human
  各自后来补了一份）：带 py_compile／临时目录写法的是 7 份，全改了；asuna-become-human 那份没这种写法，没动；
- 改前现场取证（跑已发布快照 3dbba8a2 里那几份、cwd 指只读检出根）：outbound-round 37/38、
  本技能 27/28、image-generation 154/155、running-version 53/54、render-budget 45/46、usage-readout 248/249
  全 rc=1、红在 `compile_probe_writable`（detail 写「没真查」）；bot-or-person 139/139 绿——
  它多一档兜底退到候选根目录，那一趟恰好写得动；
- 改后：候选内 8 份全 rc=0（34、136、155、28、38、47、55、250），cwd 指只读检出根同样全 rc=0；
  冻结快照里的复跑见当趟行动报告；
- 反证：临时副本（系统 Temp，用完即删）里添一份语法错的 `broken_probe_case.py` → outbound-round 38/39、
  bot-or-person 136/137、本技能 28/29，各红在 `compiles_broken_probe_case.py`
  （`SyntaxError: invalid syntax (broken_probe_case.py, line 1)`）——内存 compile 真在查，不是永远绿；
- 条数变化（逐份）：本技能 29→28、outbound-round 39→38、image-generation 156→155、render-budget 48→47、
  running-version 56→55、usage-readout 251→250、bot-or-person 139→136。删掉的全是「找不到可写落点」那一族
  探针格（内存 compile 不需要落点，留着就是永远绿的空判据）；`compiles_<脚本>` 那几格名字与条数不动。

2026-10-22（v2.8，只改本技能 `SKILL.md` 与 `check_skill.py`，xiaoman 候选）：

- 这一节的来路自己核过：在跑那两笔快照的包同名同 sha256（`asuna-xiaoman-0.2.0-7f54dbd2af14.tgz`，`7f54dbd2af14fbd05c59da9c99e2413cf43646ff0996f2f01d7d37169ca9d5ca`），`.tgz` 成员 29 条，`_tmp_check_runner.py` 一条都不在——而 17:32 那笔发布回执的 `changed_files` 里有它。包是干净的，脏的是回执那一格；
- 发布前扫候选根（脚本写在 `/task`，没落候选根）：`files` 白名单 9 项；根上白名单外的目录 5 个（`.tmp`、`_tmpcheck`、`cp_test`、`integration`、`journey`）、文件 3 个（`claude-ref-v1.png`、`package.json`、`xiaoman-official-ref-v2.png`）。前三个是空的临时目录，`integration/`、`journey/` 与两张 png 被 `files` 挡在包外；都不是本趟建的，按「单独点出来」处理（只删自己建的文件，所以没动它们）；
- 与动手前的候选清单比：35 份文件里只有这一份技能的两份变了——`SKILL.md` 改前 `93cc41fabaab`、`check_skill.py` `5c129efe6723` → `e560d36fe233`；`SKILL.md` 是分两趟写的（先新节与 description 那一句，中间态 `3f57d2f97c56`，再补版本条目与下面这条试用记录），写完的最终 sha 以发布回执为准（写进文件的 sha 会被自己改动，不在此自指）；其余 7 份技能一个字节没动，逐份 `check_skill.py` 重跑全 rc=0（34、136、157、36、38、47、61、294）；
- 本技能自查 28→36 条（一条节标题锚点＋7 条关键串）：候选内 36/36、rc=0；反证——把新节整段剥掉再跑同一份自检 → 28/36，红的正是节标题与那 7 条关键串（尺子能红才算能用）；cp1252 子进程冒烟 rc=0、stderr 0 字节；`python3 -m asuna.skills skills` → `Skill headers valid.`、rc=0；
- 换行：本趟写的两份在候选里 CR=0；字节面复看要跑在冻结快照上（快照可能带 CRLF，见 v2.3 那条），发布后另测。

2026-10-23（v2.9，只改本技能 `SKILL.md` 与 `check_skill.py`，xiaoman 候选）：

- 生效根照 `activation.json` 现读：`projects.xiaoman` 选中 candidate `b81724e561373a5a6f34c50e164510d8ab030b27212156dbaa0098c19e3469f0`、`state=ACTIVE`、包 `asuna-xiaoman-0.2.0-714b8b04b523.tgz`（sha256 `714b8b04b523178de13f63044a91aeee59f5b40becc3aab8ea430728fc9c3321`），`packageRoot` = `.runtime/adr008/development/xiaoman/frozen/b81724e5…`。那份 SKILL.md 与候选里同一份 sha256 一致（`cb51cc4f5692f7972674b917ab15009c651681671e3fc5145cd72611bac021d4`，31219 B，CR=0），整棵候选树 35 份与该快照逐文件比内容不同 0 处、新增 0、缺失 0 → 工作树里没有本次之外的未提交改动。
- 发布前私密词扫描（脚本 `/task/pw_scan_1023.py`，口径照 10-13 的 `envoy_shell_skip_words_1013.py`；词闸从在跑的 core `workerPath` import `asuna.private_words`）：名单条目数 67（site=3），扫 35 份（3 份 png 不是 UTF-8 文本，跳过），命中文件 1 个 = `integration/envoy_meters_read.py`，`TOTAL HITS: 11`（11 处＝行×条目对，都是 `site` 类，当天名单行号 34／43——这两个数只是今天的读数，判据本身不引用它们）。
- 自查：改前候选内 36/36、rc=0；改后 37/37、rc=0（多的就是 `prepublish_private_word_criterion`）；追加这条试用记录后再跑一次仍 37/37、rc=0。发布闸 `python3 -m asuna.skills skills` → `Skill headers valid.`、rc=0（同一趟另打一行「只在家里可用」点名两份头里没写 `scene_kinds` 的既有读数，与本趟无关）。
- 反证（副本跑在 `/task/pw1023_neg/`，不落候选根）：① 原样副本 37/37、rc=0；② 整节剥掉（从本节标题到「## 版本」）→ 36/37、rc=1，红的**只有** `prepublish_private_word_criterion`，detail 列出缺的关键串；③ 只抹掉「把「停」练成橡皮章」一处→ 同样 36/37、也只红同一条。cp1252 子进程冒烟 rc=0、stderr 0 字节。
- 反证那一趟的限度（照实记）：整节剥掉时 11 个关键串只缺 7 个——「停下来报主人」「命中冒出」「名单条目数跟上一份报告对不上」「本身在这次改动里被改」这四个在下面的 v2.9 版本条目里被复述了一遍，它们不单独承重；真承重的是节标题加「零新增命中」「不按序号引用名单条目」「可判的三岔」「把「停」练成橡皮章」「定成常设判据，以后照这条自己走」。判据名仍然只红那一条，没连带别的。
- 判据 ②（名单条目数对不上）今晚没有基线可比：这条判据第一次落文件，此前没有一份带命中数的发布报告。我能指到的上一个条目数是 45（10-16 记在 `asuna-bot-or-person` 的试用记录），今晚 67——差 22 条我逐条归不了因（名单不带历史），主人交代里点名的是10-23 凌晨他自己加进去的两条。今晚按「上一份报告不存在」处理：照发，两个数照抄进报告，不静悄悄。
- 来路核到此：「定成常设判据，以后照这条自己走」这句原话我在可及的原话库里没翻到（本机场景原话窗口从 10-15 起，10-13～10-15 逐字搜「常设判据」零命中），字面以 10-23 夜间这份交代为准。
- 边界：一次性脚本写在 `/task`（`pw_scan_1023.py` 等），候选根只多过 `.tmp/pw1023_patch.py` 一份（本趟建的，跑完就删，发布前候选树回到 35 份）；`__pycache__` 0 个；根上白名单外的东西（`.tmp`、`_tmpcheck`、`cp_test` 三个空目录，`integration`、`journey` 两个目录，两张 png）都不是本趟建的，只点出来不删。不碰 core、不碰别的技能、不动 `files` 白名单、不推 git、不重启 worker。
- 换行：本趟写的两份在候选里 CR=0；字节面复看跑在冻结快照上（见 v2.3 那条），发布后另测。

2026-10-24（八条并版，不抬版本号；只改本技能 `SKILL.md` 与 `check_skill.py`，xiaoman 候选）：

- 生效根现读 `activation.json`：`active.xiaoman` 的 `packageRoot` 在 `.runtime/adr008/development/xiaoman/frozen/` 下（候选哈希目录），`workerPath` 为 null → 这是人格包，不是 core；候选与那份冻结的 `SKILL.md`、`check_skill.py` 动手前逐字节相同。
- 动手前扫整棵候选根：名单 69 条、命中 11 处全在 `integration/envoy_meters_read.py`、UTF-8 文本扫 32 份（3 张 png 不是文本，跳过）。
- 新节「判据补遗」八条 (a)–(h)；(e) 同时改了私密词那一节里的一句来路。自检 37→48：多的是一条节标题、八个钉、两格泄露扫描（`no_listed_words`、`no_listed_words_outside_envoy`；`leak_scan_ran` 只在红时出现）。改前 37 条是 v2.9 的记录，这趟没重跑改前。
- 反证（副本在工作区 `neg8/`，不落候选根，用完即删）：每个钉的每个字面单独剥掉（该字面在补遗一节里恰好出现 1 次）都只红对应那一条，共 13 例；(e) 改回旧写法只红 `pin_e_provenance_wording`；整节剥掉红节标题加 7 个钉（`pin_e` 不在里面，它查的是私密词那一节）；本技能目录里塞一个名单词只红 `no_listed_words`，整包副本里别的文件塞一个只红 `no_listed_words_outside_envoy`；名单配不上、名单 0 条各只红 `leak_scan_ran`（这两例是把 `private_list` 换成桩验的，不是真拿走名单）；整包副本不塞词跑满格全绿。
- 没做成或没验的：「名单读不到」的真实环境没造出来（TEMP 下的副本照样找到了名单，那一例没红，所以只验了桩）；钉只验字面在不在，不验我后来照做没有。
- 订正两处前提：① 写 (d) 时以为发布闸不扫内容，读 `floor.js` 发现 `publicationFindings` 已会扫本次改动的文件，(d) 与私密词那一节的旧话都已订正；② 交代里的 `floor.js:201-209` 在 10-24 装着的那份里是构造函数几行，选根逻辑在 `effective`／`skillPaths`／`persona`，(a) 改按名字写。
- 两格只读核：`skill` 工具报 unknown 不会列清单（`packages/skill/tool-skill/src/index.ts` 的 138、145 行抛的是不带清单的一句，实测同样）；缺 `scene_kinds` 不会让发布闸停下（`python/asuna/skills.py` 114–122 行：只有头不合法才 `sys.exit`，缺的只打一行「只在家里可用」，exit 0）。
