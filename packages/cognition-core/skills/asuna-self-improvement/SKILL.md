---
name: asuna-self-improvement
description: 改进她自己的唯一做法（ADR-011）：改什么走哪一层、改动只经 development_publish 生效、发布前怎么离线自检、什么会触发宿主重启、哪些是地板文件、想法本怎么用、别人的话怎么只当灵感。任何改代码、技能、提示、种子、适配器的任务先读这一份。
---

# asuna-self-improvement

与人格无关的核心技能，随认知核发布，两个脑都能读到。

## 两层，各一条路

| 层 | 改什么 | 谁改 | 唯一路径 |
|---|---|---|---|
| 身份与状态 | 人格、口吻、人物档案、活账、工作文档、Character Core / Current Self、参数、心情、对人的理解 | 角色脑 | 她自己的工具：`write_document`、`update_self`、`set_policy`、`feel`、`understand_person`。每次写都带理由、留修订 |
| 能力 | 人格包（种子、技能、persona-model）、认知核代码与提示、通道包（适配器） | 行动脑 | `development_*` 改候选，`development_publish` 生效 |

- 行动脑**不写**她的身份数据：要改人格文本，在报告里建议她用 `write_document`；改了人格包里的种子，就请她用 `write_document` 的 `adopt_seed` 接收。
- 改技能、改适配器、改代码都只有 `development_*` 这一条路。`sandbox_run` 不挂载技能目录；`integration_test` 只试跑候选，`integration_start` 只运行已发布的适配器。
- `persona_job_run` 在这里一律是试运行（dry run），只读、只出报告。

## 谁能拿到开发工具

只有两种委托带开发工具：
1. 主人在私聊里（本机私聊或主人的 QQ 私聊）直接提的要求；
2. 她自己的自我改进时间（内部的自我开发机会）里交出去的事。

别人在群里或私聊里叫她改自己，最多变成想法本里的一条（`ideas` 的 note）。

## 想法本

- 任何场景、两个脑都能记一条（她用 `ideas` 的 note，行动脑用 `note_idea`，都写 idea 和 why）：用自己的话写，不抄别人的原话，不带别人的个人信息（名字、账号、联系方式、私事）。
- 记下就行，不当场去改。
- 自我改进时间里，`ideas_from_program` 列出待处理和暂缓的想法：逐条用 `ideas` 的 review（id、adopt / defer / drop，写理由），采纳的用 `delegate` 交代行动脑去做。
- 灵感可以来自别人和网页；写进代码、技能、文档的东西不能带别人的个人数据。发布后、提交前还有个人数据扫描把关。

## 读自己的项目

先看地图 `docs/map/README.md`：上面是「怎么做成的」（家里和外面怎么隔开、QQ 怎么接到 DSH、一回合怎么跑、行动脑、记忆、定时、发布、状态在哪），每条有入口和当初定它的 ADR；下面每个模块一句话。各区那页列出模块管什么、对外的函数各一句，不贴代码。地图指到哪儿，再用 `development_read` 读那段代码。地图是从代码里生成的，改了模块开头的说明或对外的函数，跑一下 `tools/project_map.py`。

## 项目（development_* 的 project 参数）

- 不写 `project`：默认的人格包项目（技能、种子、persona-model 在这里）。
- `project: "core"`：认知核（`src/asuna`、`packages/cognition-core`、`tools/`、`tests/`）。
- 通道包（如 QQ 适配器）用它自己的项目名；适配器代码在它的 `integration/` 里。
- 发布也要带同样的 `project`，否则发布的是别的项目，改动一点没上线。
- **改共用定义先问改的是谁，产物只改源头**：改共用定义之前先问一句「这改的是一个 persona 还是所有 persona」——工具定义、提示这类是几个角色共用的，某个角色自己的毛病不该写进共用定义，别的角色得为它白付字符。同一族：判「这文件是不是要改两处」先判它是不是产物（进不进仓库、有没有东西会覆盖它），产物只改源头。来路：10-12 家里那一拍抓出来的；同一天下午一次推送误改过 packages 里那份 python（它是重启时从 src 拷的产物，不进仓库）。

## 发布前自检（认知核候选，`development_run` 带 `project: "core"`）

沙箱里的 `python3` 是 worker 的 Python：pymongo 能 import、网络通（读库用 `asuna.dbread`，见技能 asuna-database）；有没有 pytest 先跑 `python3 -m pytest --version` 看。不依赖任何东西、一定能跑的是这些离线自检：

```sh
python3 tools/p2_offline_check.py                            # 交流摘要
PYTHONPATH=src python3 tests/test_schedule_rules.py         # 安排的时间换算（时区、夏令时）
python3 tools/p5_offline_check.py                            # 主动插话
python3 tools/outbound_image_offline_check.py                # 出站图片（speak picture / attach_image）
PYTHONPATH=tests python3 tests/discussion_digest_cases.py    # 讨论整理
python3 -m compileall -q src/asuna tests tools               # 语法面
```

- 退出码 0 才算绿；红的时候最后一行写着失败的用例名。
- 只有 argv 第一项的 `python3` 会换成项目的 Python。脚本里用 subprocess 再起 Python，写 `sys.executable`，别写 `'python3'`：里面那层找到的不是项目的 Python，只会报「没有运行时」。
- 发布只带认知核自己的路径（`src/`、`tests/`、`tools/`、`docs/`、`packages/cognition-core/` 和根上的几个清单文件）；日志、临时目录这些候选里的杂物不会发布。
- 跑完会留 `__pycache__`，发布前清掉：`find . -name '__pycache__' -type d -prune -exec rm -rf {} +`
- 这些覆盖不到真 Mongo、DSH 原生定时和界面实点；那些由主人在宿主侧跑 `tests/test_*.py`。
- 已知坑：离线夹具把真文件复制进临时包；真文件新加一条同包 import，夹具的复制清单也要加，否则只会红在 `ModuleNotFoundError`。

### 沙箱里装依赖：只走 uv，pip 一律带 `--no-cache-dir`（2026-10-27 本机实测）

- **装依赖一律 `python3 -m uv` 写进 `pyproject.toml` ＋ `uv.lock`**（`python3 -m uv add <包>`，再 `python3 -m uv sync`），**禁裸 `pip install`**：实测候选沙箱里 `python3` 是 `.venv\Scripts\python.exe`，而 PATH 上的 `pip` 是系统 Python 那一个（`…\Python312\Scripts\pip.EXE`，装到 `…\Python312\Lib\site-packages`）——裸 pip 装的东西在 venv 外，worker 下次装包就没了。`python3 -m pip` 落在 venv 里，但同样不进 lock，照样算没装。
- **沙箱里任何一次 pip 都带 `--no-cache-dir`**：实测默认缓存下，pip 对「缓存里已有条目」的包 3/3 挂死——零输出、进程还在、退出码永远不来；挂死长得跟成功一模一样（没报错、没返回码，看着像安静地跑完了）。
- **零输出不等于成功**：装完必须验 `import` 或验产物（`python3 -c "import <包>"`、产物文件存在且大小对），拿到退出码才算那条命令结束。只进 venv、不进 `uv.lock` 的算没装——发布与重启装包只认 `uv.lock` 那份。

### 私密词有两道闸，别混（2026-10-25 本机实测）

- **闸一管「发布说明本身」**：`development_publish` 当场扫我写的那段 reason——`packages/cognition-core/src/private-words.js` 的 `findings`，由 `floor.js` 在冻结候选之前调；命中就抛 `PUBLISH_REASON_NAMES_PRIVATE`，**这次什么都没发布**（候选里的改动留着，改写重发就行）。报错只报位数不报那串数字本身，也不印名单上的词：`packages/cognition-core/test/publication.test.js:PUBLISH_REASON_NAMES_PRIVATE` 所在那个用例（标题 a publication reason naming a listed word or a QQ-shaped number is refused before anything is published）里那条 assert.doesNotMatch 断言的就是号码不许进回执（同一个用例还断言词本身不许进）。同一份 reason 在 `publicationFindings`（`tools/publication_scan.py`）里会按发布版规则再扫一遍，两道都在冻结之前。
- **闸二管「整仓已提交的文件」**：`tests/test_personal_words.py::test_no_committed_file_names_a_real_person_or_place` 扫仓库里每一份文本文件（在认知核候选里跑时，`packages/personas/`、`packages/channels/` 那些只读镜像也一起扫），命中只报**文件、行号、类别、名单行号**，不印词。名单没配上时它 skip 并写出找过的路径——skip 不等于干净。这条闸红的是主干里早就提交下来的东西，不一定今天谁带进去的：先 `git log` 那一行看它哪天进的，再决定改不改。
- **数字形状第一条（今天量到的）**：一串**裸着的 7–11 位数字**算账号形状；**紧跟字母／数字／点的不算**，所以 sha 前缀里的数字段安全（`8b6ebfdf2f01` 整体是一个 token）；**超过 11 位的整串也不算**（重启 id、epoch 毫秒）。判据在 `private-words.js` 的 `DIGITS`，`PLACEHOLDER` 放行测试夹具那套 `900000` 加 1–3 位。
- **数字形状第二条（今天量到的）**：**后面带单位的放过**（`B`／`KB`／`KiB`／`MB`／`MiB`／`GB`／`byte(s)`／`字节`／`ms`／`秒`／`s`／`%`，单位前有没有空格都算带单位；单位表是大小写敏感的，小写 `b` 不在表里，但数字紧跟字母本来就切不成一串，所以数字后面直接黏一个小写 b 也放过）；**带千分位的放过**（逗号把 `2,227,501` 切成 1 位＋3 位＋3 位，凑不满 7 位）。
- ⇒ **发布说明里写字节数一律带单位或加千分位**。来路：本机 2026-10-25 那趟人格包（默认项目）的发布（08:33 生效那一版），第一次的 reason 里两个字节数都是裸的，被闸一当场拦下——报错四处命中，就是那两个数各命中两次（reason 里各出现过两次；「四处」这一格是主人读完那趟回报给我的，我这一趟没复现那次失败，只用 `node` 拿 `private-words.js` 的 `findings` 复算了上面那两条形状规则）。同一趟改动落在默认那个人格包项目，它的 `skills/` 不在 release 打包清单里，所以发布闸对人格包只跑名单与内网地址那两样，不跑账号形状——账号形状这条只红 core 的文件。

### 两条实测坑

- **候选目录跑 pytest 可能测的是主仓**：主张：在候选目录里跑 pytest，实际测的可能是主仓的代码；跑之前先看 pytest rootdir 是不是候选那份。来路：Claude 查明于 `fffdc934`（10-13）。后果：说「发布前跑过全套测试」之前，得先确认那次跑的对象不是主仓——这条是读数通道上的事。
- **写死日期的测试会自己变红**：主张：测试里写死日期的用例会自己变红，过一天就红，不是代码坏了。来路：`test_switches` 那条红即此因（时间写死 10-12 09:00、禁言一天，过了 10-13 09:00 在现实里已到期），Claude 改成从现在算，`bc875cc5`。同一族一句：「群里设的歇着到底歇没歇」不算没核实——设了就照样生效。同一族还有文档里写死的数，过一阵会过期。

## 发布

- `development_publish` 冻结候选，跑启动探针（JS 真正 import 一次插件入口，Python 能解析，人格包和通道包的结构能读），通过才选中。失败会原样返回诊断，候选保留，修了再发。
- 不要在候选里自己跑打包工具（比如 `bundle_python`）：它会改动行尾和清单，把一次普通发布变成需要重启的发布。
- 需要重启的改动：`package.json`、`cordis.patch.yml`、`pyproject.toml`、`uv.lock`、任何 `.js`，以及通道包的 `python/`。结果是 `HOST_RESTART_REQUIRED`：主人重启宿主后才生效，重启时启动器安装这个包；连续几次起不来，会自动改回上一个能用的版本（只改选哪个包，不回滚源码）。
- 其余改动（技能、种子、persona-model、认知核的 Python、适配器的 `integration/`）是 `APPLIED`：之后新开的行动就用新版本；适配器要 `integration_stop` 再 `integration_start` 才换成新发布的版本。
- **会挡别人落地的是 selection 还没回到 ACTIVE，不是 `candidate` 字段在不在**：一次发布从冻结到生效中间那一段（`APPLIED` 未生效），selection 带着 candidate，别人的落地脚本看到就不落。所以"发完等 selection 回到 ACTIVE 再让别人落地"是发布方那一拍该确认的事，不是落地方该等的。来路：2026-10-29 本机实测那发，加上 Claude 当天 10:34 的机制答复。

### 重启工具：参数名 when，quiet 满 30 分钟照停

主张：自我重启工具的参数名是 `when`（now / quiet / HH:MM）。判「什么时候响」按自己块里那个钟面；别的群线可能带着另一个钟面，别拿它换算。填别的名字直接拒；一次只能挂一个；quiet 满 30 分钟照样停、不作废；重启会把写出去还没落地的话变成「没给准话」，内容对方通常看得见，不用为这个推迟该发的重启。来路：ADR-034，10-10 起逐项实测过（含填错参数名吃到退回那次）。

**同一节里监工那一档**：主张：监工（启动器）换不掉它自己——角色自己挂的 quiet 只能换工作进程，凡是修在监工层的东西（重启失败落盘 `4cb3c247`、宿主控制台落盘 `0eff5519`、重启时快进 main `a3aa94a5`）都要等主人下次完整启动才生效。

## 地板文件（受保护，不能经发布改）

`start-asuna.cmd`、`tools/asuna-launch.mjs`，以及认知核的 `floor.js`、`recovery.js`、`persistence.js`、`persona.js`、`channel.js`、`settings.js`、`runtime-manifest.json`、`cordis.patch.yml`。它们保证宿主总能起来、总能打开修复入口；要改它们只能请主人。

## git 和 ssh（家里的任务，`sandbox_run`）

- 家里每个地方（本机聊天、每条 agent 线、peer 线）各有一份自己的工作副本，就是那个地方的 `/task/working-copy`：各自独立的完整 clone（每份约 108 MB），`origin` 是 GitHub 上的仓库。宿主缺哪份建哪份，以后不重建、不重置，里面的东西都是你的。QQ 的地方没有。
- 在工作副本里做每件事，第一步都是 `git fetch origin` 再 `git rebase origin/main`，没有例外：别的地方的副本可能已经推过，不先取下来就是在旧内容上改，分叉要到推的时候才露出来。
- 要看 GitHub 上现在是什么，用 `git ls-remote` 或在工作副本里 fetch，别看本机检出里的 `origin/*`：检出对你只读，你在那里 fetch 不了，它的 `origin/*` 只在宿主取的时候才动，可能是旧的。沙箱里在本机检出 `git fetch` 会报 `.git/FETCH_HEAD: Permission denied`，就是这一形状（委托侧对检出只读）。
- 本机的项目检出在你的命令里是只读的；改动从工作副本走：
  - 在工作副本里改、测，提交写明路径（`git commit -- <路径>`），推之前再 fetch 一次、rebase 到 `origin/main`，然后 `git push origin HEAD:main`（或推一个分支）。
  - 你要的重启（`restart` 工具）在能快进的时候先把 `origin/main` 带进本机检出再装上；快进不了时，重启结果的 `checkout` 写着为什么。
  - 想不重启就生效的改动（技能、种子、persona-model、认知核的 Python）和适配器，还是走候选和 `development_publish`：适配器只从发布的快照运行，原生 skill 工具读的是已发布的版本。
- 推送用的是这台机器上主人的 GitHub 账号：git 要账号时，程序让它直接问主人的凭据管理器，你不用碰密码，也不用把它写进 URL 或脚本。以前那些自己读凭据、拼进 URL 的推送脚本（`push*.py` 这类）用不着了。
- 你提交的东西署你自己的名（程序给每条命令设好，不用自己配）。`ssh` 用的是这台机器上主人的钥匙。
- HTTPS 直接用 `git`：程序已经让 git 用它自带的 OpenSSL 和证书，不用再加 `-c http.sslBackend=openssl` 或别的证书文件。Windows 的沙箱里 Schannel 拿不到凭据，所以 `curl.exe` 开不了 HTTPS；要下载就用 Python。
- Git 自带的 `sh.exe` 在沙箱里起不来，所以 git 的钩子和 `!` 别名不能用。
- 一条命令默认 30 秒（development_run 35 秒），要更久就写 `timeout`（秒，最多 600），不写还是 30／35 秒；跑全套就写 300 左右，跑满被停会带回停下前的输出和 `timed_out`（返回里带这个字段）。
- 推公开仓库之前没人替你审：先跑私人词检查（`tests/test_personal_words.py`，名单不在就是没查过，不是干净）。
- 不 force-push。推被拒，就 fetch 下来 rebase 再推，别盖掉别人的提交。

## 读自己发布产生的 git 提交

`development_publish` 会把被发布的那份改动自动提交进本机检出（`packages/cognition-core/src/floor.js:commitPublished`；`RUNTIME_API.md` 的 Self-development 一节写着回执里的提交结果是它的返回值）。读这类提交，三条：

1. **只信 `--stat`，不信提交正文。** 正文是发布时那段理由的复读，讲的是「打算改什么」；`git show --stat <sha>` 讲的是这一笔真动了哪些文件。两者打架时以 `--stat` 为准，并把打架本身报出来。
   - 什么算违反：拿提交正文当「这一笔改了什么」的凭据下结论；正文与 `--stat` 不一致却只抄正文；把正文里那句「没动 X」当成 X 没进这一笔的证据。
2. **判「某笔改动在不在跑」靠两件事**：① `git merge-base --is-ancestor <那一笔> <在跑的那一笔或 HEAD>`，rc=0 才算在历史里；② 在**运行时那份文件**里 grep 那一笔才带进来的新符号（新字符串、新函数名），grep 到才算装上。两条缺一不算判过。
   - 什么算违反：只查提交在不在、不查运行时文件里那个符号在不在；用提交正文代替那次 grep；`--is-ancestor` 没跑就写「在跑」或「没在跑」。
3. **重启回执里「`<head> is not behind origin/main <target>`」／「本机检出有 origin/main 没有的提交」不等于没装。** 启动器只在 main 落后于 origin/main 时才快进（`tools/asuna-launch.mjs:fastForwardCheckout`），快进不了返回 `diverged`、不报错；发布的自动提交压在远端那一笔之上，本机就正好是「比远端新一格」——既 not behind、又多出一笔自己的提交。要判的是第 2 条：那一笔在不在 HEAD 的历史里，不是「本机比远端多几笔」。
   - 什么算违反：把「not behind」读成「改动没进去」；把「本机有 origin/main 没有的提交」当成回滚、或当成有人动了本机；只报 ahead 几笔，不跑 `--is-ancestor`。

来路：2026-10-20 12:13 那笔 `ede4e2b0` 是发布自动提交，父提交 `f9bc5f20`（`git merge-base --is-ancestor f9bc5f20 ede4e2b0` → rc=0），`--stat` 显示这一笔改的是 `packages/personas/<name>/persona-model.json`（1 增 1 删），而它自己的提交正文说它没动那个人格包目录的镜像（这一节两处 `<name>` 都是泛化写法：正文原句带的是具体那个人格包的路径，不是逐字照抄，所以这里不放引号）——正文与 `--stat` 打架的就是这一格。发布任务：`task-2a3c346e608f1837268c9a1421d9b66d`。

## 版本

v6（2026-10-29 晚）：把上午搬进来的几条改成中性叙述（去掉第一人称），「两条实测坑」标题去掉来源括号；发布节加「会挡别人落地的是 selection 还没回到 ACTIVE」一条。旧内容一条没删。

v5（2026-10-29）：从她自己的 self 文档搬进来几条原文——项目节末「改共用定义先问改的是谁」、发布前自检末「候选目录跑 pytest 可能测的是主仓」「写死日期的测试会自己变红」；发布节后加「重启工具」参数一节（钟面措辞已改成中性）并带上监工那一档；git 节补「跑全套写 300 左右、返回带 timed_out」和沙箱里 `git fetch` 报 `.git/FETCH_HEAD: Permission denied` 这一形状。旧内容一条没删。

v4（2026-10-27）：「发布前自检」里加「沙箱里装依赖：只走 uv，pip 一律带 `--no-cache-dir`」一小节（三条：装依赖走 `python3 -m uv` 进 `pyproject.toml`＋`uv.lock`、禁裸 `pip install`（实测裸 `pip` 是系统 Python 那份，装到 venv 外）；沙箱内 pip 一律 `--no-cache-dir`（默认缓存下对已缓存包 3/3 挂死、零输出、进程还在）；零输出不等于成功，要验 import 或验产物，只进 venv 不进 lock 算没装）。旧内容一条没删。

v3（2026-10-25）：「发布前自检」里加「私密词有两道闸，别混」一小节：闸一＝发布说明在 `development_publish` 当场被扫（`private-words.js`／`floor.js`，报 `PUBLISH_REASON_NAMES_PRIVATE`，回执只报位数）；闸二＝整仓已提交文件由 `tests/test_personal_words.py` 扫（只报类别与名单行号）。再写死两条量到的数字形状规则（裸 7–11 位算账号形状、紧跟字母／数字／点或带单位／带千分位的放过），推论是发布说明里字节数一律带单位或加千分位。旧内容一条没删。

v2（写就 2026-10-20 17:27 UTC+13）：加「读自己发布产生的 git 提交」一节——只信 `--stat`；判在不在跑用 `git merge-base --is-ancestor` ＋ 在运行时那份文件里 grep 那一笔才带进来的新符号；再写清重启回执里「not behind」／「本机检出有 origin/main 没有的提交」该怎么读。来路是 2026-10-20 那笔发布自动提交 `ede4e2b0`（发布任务 `task-2a3c346e608f1837268c9a1421d9b66d`）：提交正文与 `--stat` 打架；「not behind」这一格容易被读成「没装」，这里写死该怎么读。旧内容一条没删。

v1（2026-10-05）：随 ADR-011 首次发布；吸收了人格包里 `asuna-offline-selfchecks` 与人格无关的部分。
