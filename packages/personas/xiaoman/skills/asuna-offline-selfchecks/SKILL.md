---
name: asuna-offline-selfchecks
description: 沈小满在核心技能 asuna-self-improvement 的离线自检之上记的增量笔记：「挂错项目」红的读法（xiaoman 候选没有 tools/tests，No such file or directory 是选错项目不是产品坏）、单独跑某个用例文件、p3 用例删除后的现行跑法与 pytest 不收 *_cases.py 的盲区、p5b 退役后「文件不存在 + exit 2」怎么读、「没收录 ≠ 已退役」、适配器自检在 qq-napcat-adapter 技能里不在这套里。通用离线自检的命令清单、退出码读法、__pycache__ 清理、project 归属、发布与重启口径一律以 asuna-self-improvement（随认知核发布）为准，这里不再重复；两份不一致按核心技能办。候选根里的一次性脚本写到哪儿、发布前怎么按 `files` 白名单扫候选根、判「文件有没有进到装给 worker 的包里」只认 artifact 那串 sha256 与 `.tgz` 的文件清单（`changed_files` 不等于包内容），都记在「候选根」一节。**要哈希就在沙箱里 `hashlib` 本地算、别为了算 sha 出网**（现成一行命令＋公网哈希服务反例清单；没有沙箱那一格写「哈希未算」、别拿外部服务返回值当本机号），记在「判据补遗 (j)」。附零依赖离线自检 check_skill.py。
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
  从不跑 `tools/`」的结构，红了没人知道——但这一族今天不等于「没人跑」：`tests/test_offline_checks.py`
  把 `tools/` 下每个 `*_offline_check.py` 收成一条 pytest 用例（11-09 现场 `pytest --collect-only` 收出 5 条）。
  所以 `p2_summary_loop_cases.py`、`p5_proactive_cases.py`、`discussion_digest_cases.py`、
  `outbound_image_cases.py`、`integration_import_cases.py` 这五套是被那条 pytest 间接跑着的：`tests/test_*.py`
  里没有一个直接 import 它们，链条是 cases → `tools/` 入口 → pytest。判「这一套有没有人跑」去看那条
  pytest 收几条，别只看有没有哪个 `test_*.py` 提到它。
- 报「某套用例过没过」要同时写清**跑的是哪条入口、哪台解释器**，一条道的绿不代表这套用例绿——这条不过期，例子会过期：11-09 那天
  直接跑 `tests/discussion_digest_cases.py` 是 4/20 通过、rc 1，同一天 `tools/p1c_offline_check.py` 那条入口带着
  `sys.modules["asuna.people"] = None` 的隔离跑出 20/20、rc 0。那道隔离是**历史形状**，ADR-118 L2（main `436f25fc6abf`）
  之后文件里没有了，改成模块自己带一行明着的 `from asuna import people`：People 被挡就在 import 那一刻 ImportError——「缺席变绿」这一格从此在直跑这条入口上关掉。解释器那一格留着、形状换了：同一行直跑，在装不上 `httpx` 的解释器上是红（rc 1，`ModuleNotFoundError: No module named 'httpx'`），不再自动变 20/20。

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

**一条命令并进来（`pre_publish_scan.py`）**：发布前手敲的几条检查现在并成本目录一个只读脚本，在候选根跑（项目按 `development_*` 挂的那个）：

```sh
python3 skills/asuna-offline-selfchecks/pre_publish_scan.py --expect skills/<这次要动的技能> [--expect-entries <上一份报告的名单条数>] [--allow-missing <确实要删的路径>]
```

它一次做五件事：① 候选对 ACTIVE 冻结快照逐文件比 sha256，列 changed／added／missing（缺失＝防吞），`--expect` 给了就要求改动全落在预期前缀内，缺失默认算停；② 按候选 `package.json` 的 `files` 白名单扫候选根，白名单外的路径一律只报 NOTE（不进包；既有的、新冒出来的、空目录都是）11-12 起。第③件事里，白名单外、ACTIVE 快照里没有的文件命中差与「被改」单列成「比对不到」NOTE，不当新增、不停，但也不是干净的证据；命中落在 envoy 脚本以外的文件照样停），另报 `__pycache__` 残留；③ 私密词扫描，候选与 ACTIVE 各扫一次整棵根，按下面「三岔」判（① 命中落在 `integration/envoy_meters_read.py` 以外的文件；② 名单条数和 `--expect-entries` 对不上，不给就是“②没判”、最后一行明说；③ envoy 那个文件本身被改；另候选与 ACTIVE 逐文件命中数对不上也停），名单读不到或 0 条算“没真查”；④ 对有改动的技能目录跑它自己的 `check_skill.py`；⑤ 候选根下每份 `SKILL.md` 的头拿**真 YAML 解析器**解析一遍（`yaml.safe_load`，同 DSH 装载侧 dsh-skill-filesystem 的 `parseFrontmatter`：取第一个 `---` 到下一个 `---` 之间那一段）。红＝装载侧收不下＝整本从行动侧清单里静默消失。退出码语义照自检的原样：0 = 通过、可发；1 = 停（最后一行列是哪几条）；2 = 没法判（名单、ACTIVE、候选根找不到，**或这台机没有可用的 YAML 库**——这一格不退化成正则，宁可判不了）。拿当前 ACTIVE 当候选对拍用 `--candidate <ACTIVE 的 packageRoot>`（应 changed／added／missing 全 0）。它不替代下面“常设判据”的判断，只是把需要手数的那几步程序化；核心技能 asuna-self-improvement 的发布前自检命令清单（core 候选用）不在这个脚本的范围里，照那一份办。

第⑤件事护的是「两侧尺子不同」（11-17 查明）：装载侧 DSH 用真 YAML 解析器读头，`description` 是 plain scalar，值里出现 ASCII「冒号＋空格」就抛 `YAMLParseError`（Nested mappings are not allowed in compact mappings），`parseSkillFile` 返回 undefined、`discoverRoot` 只 warn 一行就 `continue`；我这侧 `src/asuna/skills.py` 的 `header()` 是宽容正则，整行当值收下，所以发布探针照报 `Skill headers valid.`——我一路绿、行动侧一路空。两道静默都要逮：① 解析抛错（尺子必须是真解析器，不许拿宽容正则替它）；② 值里「空格＋#」被 YAML 当注释、后半截丢掉——这种**解析器不抛错**，所以那一格只能拿原文与解析结果成对判（只对 plain scalar 判，引号／块标量／流式放过）。口径三条：这一格不看 `--expect`（一本装载不上的技能不该因为「这次没改它」就跟着发出去）；`--skill-heads <根>`（可重复）只跑这一格，用来现扫 ACTIVE 那几根——技能散在人格包／core／通道包三个 `skills/` 下，份数现读，11-17 实测三根 19 份、全绿；`name` 与 `description` 也照装载侧的硬要求判（非空字符串、`name` 合 `SKILL_NAME`、废弃与非布尔的 invocation 字段），它们红了同样是整本消失。**未核实**：两侧解析器不是同一枚（装载侧 npm `yaml`、我这侧 PyYAML），我只在「冒号＋空格抛错」「空格＋# 截断」两种形状上对拍过，别的 YAML 怪形状谁更严没测。

**第⑤件事有自己的自检针**（11-17 补，之前它裸着）：本目录 `check_skill.py` 里 `skill_head_probe_*` 三发——import 同目录那份 `pre_publish_scan.py`，喂一发**坏头**（`description` 值里带 ASCII「冒号＋空格」）进它的 `check_skill_head`，断言**红**；再喂一发**好头**（同一个值改成＝号）断言绿；再用它真读一遍本技能自己的 `SKILL.md`，断言绿。三发的结果都印进输出（`PROBE` 开头，含尺子的 `__file__` 与 YAML 库版本），关口加载不了、或这台机没有可用的 YAML 库，一律红——「没真查」不许长得像「过了」。反证口径：把第⑤件事那段换成宽容正则或整段删掉，红的是 `skill_head_probe_bad_head_red` 这一族（实测过），不是只剩「行动侧清单少一本」那种静默。

**名单条目数那一格**（11-17 改）：`check_skill.py` 不再钉死它——**这个数会随我加词长大**，钉死一个会长大的数等于每加一个词白响一次；响多了这条就成噪音，等它真响（名单被人改了）也没人看。现在每次现读、按类别打印（好和 `private_words summary` 一眼对照），差值只在带 `--expect-entries N`（N 抄上一份报告那一行，和上面第③件事同一口径）时才算，**只报差、不算失败**。`--expect-entries` 的处置写死在下面「三岔」第②条那句里。

下面是它第③件事对着的判据原文和手工跑法。

跑法：`asuna.private_words` 读本机名单（`<data>/private/personal-words.txt`），逐行 `find()` 扫整棵候选根，命中只报**文件＋行号＋类别＋名单行号**，绝不回显词本身；报告里照抄两行——一行命中数（`TOTAL HITS: N`），一行名单条目数。

**常设判据 — 三岔，判完就走，不再逐次问**：

- **通过、直接发**：命中**全部**落在 `integration/envoy_meters_read.py`（光伏表计读数脚本，命中的词都是 `site`／`host` 类）**并且**本次改动零新增命中——改动前后各扫一次，命中数与命中文件两处都对得上。发；报告带那一行命中数。
- **停下来报主人**，撞到下面任一：① 命中冒出 `integration/envoy_meters_read.py` 以外的文件；② 名单条目数跟上一份报告对不上；③ `integration/envoy_meters_read.py` 本身在这次改动里被改。

②这一条 11-17 把处置写死（它响的频次＝我加词的频次，不写处置就会被读成噪音）：对不上先跑一次 `private_words summary` 对一次——脚本数到＝工具数到，就是我在加词，**只更那个数（报告那一行与 `--expect-entries`／基线），不要开查道链**；只有两边数对不上、或命中位置冒出 envoy 以外，才当「名单被人改了」来查。停仍然要停（这是一步确认，不是一场调查）。
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

基线（钉的是命中位置，不是条目数）：命中 12 处全在 `integration/envoy_meters_read.py`（host×1、site×11）——那 12 处是既有基线，不算新增。**名单条目数不是基线**：这个数随我加词长大，钉死它等于每加一个词白响一次，响多了我就不看这条，真出事前它已经是噪音了。11-17 起 `check_skill.py` 里那个 `BASELINE_LIST_ENTRIES = 125` 常量删掉：改成每次现读＋按类别打印（差值只在带 `--expect-entries N` 时算，只报差、不算失败，口径同上「三岔」第②条），并加一格 `private_list_categories_known`（名单里出现工具与 `pre_publish_scan.py` 不认的类别就红——那条目会被脚本数进去、被那两把尺数在外，三把尺悄悄数出两个数）。对不上的处置照第②条那句：先和 `private_words summary` 对一次，对得上就只更数，**不要开查道链**。
条目数读数史（每次现读、都带来源）：69 是 10-24 发布前，11-02 现量 90 条（本机名单自己长出来的，主人判过不是串词），11-03 20:35 发布趟 103 条（增长是我自判、已向金主报备），11-05 实量 106 条，11-12 现量 125 条，11-16 那次发布回执自述现量 130 条，11-17 现量 129 条（`private_words summary`：entries 129，person 59／host 30／group 17／account 10／other 5／email 3／site 5，文件非空 131 行含 2 行注释；`check_skill.py` 现读同一份文件也是 129 条、命中仍 12 处）。命中数会漂，漂了脚本只打 NOTE、按上面的三岔判，不靠它变红。缺口：脚本只在读得到本机名单的地方真扫（名单在 `.runtime/private/`，不进包）；换到读不到名单的机器上，会红在 `leak_scan_ran`，那是「没真查」，不是「干净」。

钉：`pin_d_content_scan_documented`（这一格验的是本节写了这件事；扫描本身是上面三格在跑）。11-17 起钉四处字面：「内容级私密词扫描」「命中 12 处全在 `integration/envoy_meters_read.py`」「名单条目数不是基线」「不要开查道链」——把条目数又当基线写回来，或把那条处置删掉，钉就红。

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


### (i) 派活交代里写死中间产物落点

派活交代必须带这一句硬话：**`TEMP`／`TMP`／`TMPDIR` 只活一条命令——命令一结束那一格就被回收（`sandbox_run`、`development_run`
都一样），跨命令要留的东西一律写 `/task`（或候选里），别拿 TEMP 当中间存储。**

丢的形状要说清：脚本往 TEMP 写、下一条命令再读，读不到时那条写文件的命令早就 rc=0 交回过了——**静默丢，还丢在回执之后**，
我看见的是一串绿。所以落点要在交代里写死，别留给「他大概会放对」。

钉：`pin_i_temp_one_command`（这一节的字面）＋ `temp_rule_present_when_temp_mentioned`（正文一提到临时目录／TEMP 就必须带上
上面那句落点，缺了就红；判本技能正文，读得到核心技能 `asuna-self-improvement` 的正文时一起判，读不到打 NOTE 说没真查）。

### (j) 要哈希就在沙箱里 hashlib 本地算，别为了算 sha 出网

算 sha256／sha1／字节数一律在沙箱里本地算（`sandbox_run`、`development_run` 里起 `python3`，读字节 → 算 → 打印），**不许把要量的字面送进公网哈希服务换结果**。现成一行：

```sh
python3 -c "import hashlib,sys;print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())"
```

反例（真发生过，写死在这儿）：11-05 09:32 那趟只读活，要为一条私网守卫的拒话算 sha256，本回合工具表里没有 `sandbox_run` 也没有 `development_run`，于是把整行拒话按 UTF-8 百分号编码送进 `md5calc.com` 的 GET 哈希 API 算，还得借它的 base64 往返和已知向量倒推「送出去的字节就是我看到的字节」；那趟记下来的域名清单里还有 `api.hashify.net`、`api.sha256.com`、`api.allorigins.win`、`api.codetabs.com`（这四个只在 idea 字面里读到，那趟 `audit_events` 里核到的是 `md5calc.com` 一个域名 13 处，另外四个没核到）。代价是两头的：慢；而且把被测内容（要测的 URL、拒话正文）交给第三方算——**尺子和被测物不同源，那一格就不许写成「本机核实过」**。

**没有沙箱那一格怎么落**：只读／无开发授权的回合里（那趟现场量过：`allowed_capabilities` 18 项，`sandbox_run` 与 `development_run` 都不在里面，本地确实没手），哈希那一格写「**哈希未算**（本回合没有沙箱）」，字面与字节数照抄，别出网、也别拿外部服务返回值当本机号。真要那个号：把字面原样写进报告或 `/task`（跨命令要留的东西一律写 `/task`，别拿 TEMP 当中间存储），下一趟带沙箱的活现算。

钉：`pin_j_local_hash_offline`（只认这一节的字面）。

### (k) 主检出 .git 写不了时，用任务目录里的工作仓取对象、推 main

沙箱写不了主检出的 `.git`（`git fetch` 报 `.git/FETCH_HEAD: Permission denied`，`update-ref` 同样），又要对已有提交做 amend／merge 或取远端对象时，在任务目录里立一个工作仓：`git init` → `.git/objects/info/alternates` 里写主检出 `.git/objects` 的路径 → `update-ref` 把要的号立成 ref → 要对象就对象、要检出就 `reset --hard`（只动工作仓，不碰主检出）→ `git push origin <sha>:refs/heads/main` 走普通快进、不 force。三条字面坑，每条是一次失败换来的报错原文：

- **alternates 文件必须 LF 行尾**：写成 CRLF 会报 `object directory …objects? does not exist`（行尾那个 CR 被当成路径的一部分）。写完按字节数一遍 CR。
- **路径写相对路径**：Windows 盘符路径（`C:/…`）里的冒号会被当成多目录分隔符；从工作仓 `.git/objects/info/` 往上数到主检出 `.git/objects` 写 `../` 串。
- **远端只用 https**：本地路径的 clone／fetch 要起 msys 的 `sh.exe`，沙箱里起不来（报 `STATUS_ACCESS_DENIED`）；对象走 alternates，远端走 https。

推前远端尖只认 `git ls-remote origin refs/heads/main`，推后再读回，两个号都报；推前闸照常 `check_staged_secrets.py --personal --paths <要推的文件>`（临时工作仓绕开仓里的推送闸，走它就当没过闸）。主检出 porcelain 前后各数一次 0 行，才能说没在别人的工作树里留东西。来路：2026-11-10 主检出一次 amend 那趟，第二次靠这套真把 merge 推了上去；「默认就这么取对象」那一条是同批想法里的另一枚，与本节同族。

钉：`pin_k_alternates_notes`（只认这一节的字面）。

### (l) 分叉根因：主检出 main 从不被推送腿推进

推送腿都在任务目录的工作仓里推，主检出的 `main` 因此不会被推进；下一次 `development_publish` 的自动提交就落在旧基上，和远端分叉（11-09、11-10 各一回，同型：merge-base 是旧提交、本地独 1 枚、远端独 2 枚、`--dry-run` 新旧提交都 non-ff；不是消息格式问题，是基座旧）。我这一侧照做的三句：

- **发布前先读「主检出落后」读数**：主检出 `git rev-parse HEAD` 对 `git ls-remote origin refs/heads/main` 的号；对不上就先停下报，**不许 merge／rebase／reset 硬挪**主检出去凑齐（这格防的就是这个）。对齐是有写权限那条线的事。
- **推送腿回执固定带一格**「主检出落后远端 N 枚」（读数，N 取不到就写取不到，不写 0）。
- **同一趟既要改仓又要发布**：先发布，再把自动提交和自己那笔按顺序排好，一次快进推上去；先 push 再发布会让两笔成兄弟（11-09 实测，两笔 tree 相同、内容零差，push 被 non-fast-forward 拒）。

两个机制方向还没定、不自己拍：发布流程在自动提交前先把主检出对齐远端，或推送腿回执强制带落后读数；与有写权限的那条线并谈。

钉：`pin_l_fork_root_cause`（只认这一节的字面）。

### (m) 交件类文件里的日期字段：脚本读钟面实算，不手打

交件类文件（章稿／合包／报告）里的日期字段，一律由脚本读钟面（`dbread.now()`／系统时钟）实算后写入；brief 里和写手正文里都不手打日期。手打的日期从没对过钟；文件自称「本机钟面」的那一格尤其危险，它给假数盖了一枚「已核」的章；合包脚本拿两章头注释当日期源，错了就整链传染。做法：① 日期字段留空或写占位，落盘的脚本读钟面填；② 合包脚本自己读钟面，不从上游文件头注释里抄；③ 交件时把文件里的日期和落盘那一刻的钟面对一眼，对不上就是假数，不进账。来路：一次合包腿实测，包内的日期与拼装行的实测日期差了三天同框，靠腿抓包才没端出去；“假数不躺账”同一族。

钉：`pin_m_dates_by_script`（只认这一节的字面）。

### (n) 提交号缩写一律由命令给，写出去前验类型

提交号的缩写一律由命令给（`git rev-parse --short=12 <全号>`），不用眼睛从一个 40 位串里截前 12 位；往线上、往文档、往回执里写缩写之前，先跑一次 `git cat-file -t <那串缩写>`，确认它解析得动。写「某枚提交在不在历史里」这类断言时，判的那条命令必须用全号，缩写只当给人看的记号。对我自己的回执同样生效。回执里「提交号」和「发布候选 sha」分开标名，不并成「发布 sha」一个词。来路：一次我把一枚提交自己截出的缩写第 12 位截错，`cat-file -t` 报 Not a valid object name，还据此讨论了一轮「为什么缩写读不到」；同族毛病：把抄来的字符当现场。

钉：`pin_n_short_sha_by_command`（只认这一节的字面）。

### (o) 提交说明纪律：第一段只一句

发布说明（即提交说明）的第一段只写一句、不超过 80 字；空一行后细节进 body。整段理由堵成一行会让 `git log --oneline` 和回执里的一行读数变成一堵墙。

钉：`pin_o_commit_subject_one_line`（只认这一节的字面）。

### (p) `check_staged_secrets.py` 在非 git 候选上的真实可用写法

11-18 现场在 core 候选上跑出来的三格，按现读记：

- `--strict` 这把工具不认：带上它退出码 2。
- `--personal --all` 在非 git 候选上一个文件都没读到，退出码 3，输出 `UNCHECKED: no file was read`，不算过闸。
- 能跑的是 `--personal --paths <文件...>`（候选里的文件可以写绝对路径），同时把 `ASUNA_PRIVATE_WORDS` 指到本机名单；实测 15 个文件退出码 0、命中 0。`denylist` 那一格仍是 `UNCHECKED`（没有那份可选名单），不影响退出码，报告里照写 `UNCHECKED`。
- 我账上那串命令行字面（带 `--strict`、写 `--all`）是 11-17 现场看到后当规格抄给执行腿的，不通用：以现读为准。实测 `--help` 不打帮助，打一行 `SECRET_SCAN_TAKES_NO_OPTIONS: for files, write --personal --paths FILE...`，退出码 2。核心技能「推 GitHub」那节写的是 `--paths` 用法，不一致按核心技能办。

钉：`pin_p_secrets_real_usage`（只认这一节的字面）。
