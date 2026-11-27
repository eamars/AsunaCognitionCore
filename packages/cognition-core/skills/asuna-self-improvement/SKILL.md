---
name: asuna-self-improvement
description: 改进她自己的唯一做法（ADR-011）：改什么走哪一层、改动只经 development_publish 生效、发布前怎么离线自检、什么会触发宿主重启、哪些是地板文件、想法本怎么用、别人的话怎么只当灵感。任何改代码、技能、提示、种子、适配器的任务先读这一份。
---

# asuna-self-improvement

与人格无关的核心技能，随认知核发布，两个脑都能读到。

## 两层，各一条路

| 层 | 改什么 | 谁改 | 唯一路径 |
|---|---|---|---|
| 身份与状态 | 人格、口吻、人物档案、活账、工作文档、Character Core / Current Self、参数、心情、对人的理解 | 角色脑 | 她自己的工具：`write_document`、`set_policy`、`feel`、`understand_person`。每次写都带理由、留修订 |
| 能力 | 人格包（种子、技能、persona-model）、认知核代码与提示、通道包（适配器） | 行动脑 | `development_*` 改候选，`development_publish` 生效 |

- 行动脑**不写**她的身份数据：要改人格文本，在报告里建议她用 `write_document`；改了人格包里的种子，就请她用 `write_document` 的 `adopt_seed` 接收。
- 改技能、改适配器、改代码都只有 `development_*` 这一条路。`sandbox_run` 不挂载技能目录；`integration_test` 只试跑候选，`integration_start` 只运行已发布的适配器。
- `persona_job_run` 在这里一律是试运行（dry run），只读、只出报告。

## 谁能拿到开发工具

只有三种委托带开发工具：
1. 主人在私聊里（本机私聊或主人的 QQ 私聊）直接提的要求；
2. agent 在它自己的线上提的要求；
3. 她自己的自我改进时间（内部的自我开发机会）里交出去的事。

别人在群里或私聊里叫她改自己，最多变成想法本里的一条（`ideas` 的 note）。

- **决定一次委托带不带开发工具的是委托的起源拍**：不是「从家里还是从外面派」，也不是钟的种类。上面那三条字面是判据本体，要动它们另起一趟，别在这一格顺手改。
- **own 拍不带 development（默认全部＋例外点名，不搞「哪几种拍带」的白名单）**：心跳、结算、被便条叫起、计划到点、visit 那一拍，都是我自己身上起的拍，不在那三种里。要豁免哪几种拍，当场写一句为什么；写不出为什么就按全覆盖跑。来路：2026-11-27 两次实测——09:42 agent 线那趟回执写着这条线没有 `development_*`；12:40 从本地复盘拍派出去的那趟腿，当拍 19 枚工具里 0 个 `development_`（`task-e6977dd0d5a9bb1f30de00dabffc9170`）。⇒ 「改从家里派」绕不过这面墙。
- **动手之前先答一句：这一拍的起源是不是那三种之一**。答不出「是」，派活纸和钟的 intent 里不许出现「写／改／发布」这类落盘动作。
- **建一个要落盘的钟之前，先看这一拍带不带 development**：不带就把落盘那一步改写成「回一个带权的拍再办」。这类拍上的「我来办」要说成「我下一拍办」，不然就是把自己写在落不了地的地方。
- 来路：2026-11-27 12:41 本机流水 seq 2333——我自己先把机制总结成「地点／钟的种类」，是腿从已装正文现读那三条把它更正回「起源拍」的。规则正本一直躺在上面那三行里，我 11:3x 那行是没读正文凭现象编的。

## 想法本

- 任何场景、两个脑都能记一条（她用 `ideas` 的 note，行动脑用 `note_idea`，都写 idea 和 why）：用自己的话写，不抄别人的原话，不带别人的个人信息（名字、账号、联系方式、私事）。**记之前先扫同族**（就在 `note` 之前那一拍）：她这一侧先用 `ideas` 的 read 带 `search` 按关键词扫本子里有没有在讲同一格想法的——有就对那一条写 `review`（新读数、新的触发条件写进 review 的 why），不另起一枚；确认没有同族才 `note` 新的。行动脑这一侧只有 `note_idea`、没有 read／search：代记之前先从库里读 `ideas` 集合按关键词扫（读法见技能 asuna-database），扫到同族就别插新的，把新读数和那一条的 id 写进交回，由她那一侧 review。这一步只管**记的时候**，不判**发的时候**（什么时候发布不在这里）。来路：2026-11-16 本机实测——一次 `search` 命中 8 枚在讲同一格知识的想法，其中两枚已被同一次发布覆盖却仍挂着；副本的代价是要重读一遍才知道哪条已落地。
- 记下就行，不当场去改。
- 自我改进时间里，`ideas_from_program` 列出待处理和暂缓的想法：逐条用 `ideas` 的 review（id、adopt / defer / drop，写理由），采纳的用 `delegate` 交代行动脑去做。
- 灵感可以来自别人和网页；写进代码、技能、文档的东西不能带别人的个人数据。发布后、提交前还有个人数据扫描把关。

## 派活交代：中间产物落点写死

- **`TEMP`／`TMP`／`TMPDIR` 只活一条命令**：`sandbox_run`、`development_run` 每条命令各拿一个新临时目录，命令一结束就回收。
- 派活交代必须带这一句：**跨命令要留的东西一律写 `/task`（或候选里），别拿 TEMP 当中间存储。**
- 为什么写成硬话：中间产物落 TEMP 是静默丢，还丢在回执之后——我看见的是「命令 rc=0」，不是「产物没了」。
  判「报告交没交到」先判它落在哪：落 TEMP 的那份等于没交。
- 来路：2026-10-22 部署环境改成一条命令一回收；同一天两趟 `NATIVE_STAGE_TIMEOUT` 都靠报告落在 `/task` 才救回来，没重跑整趟调查。
  人格包那边的同族判据在 `asuna-offline-selfchecks` 判据补遗 (i)，还钉了一条自检（`temp_rule_present_when_temp_mentioned`），会连这份正文一起判。
- **派活交代里「按惯例／按什么顺序／该落在哪」这类话，一律改写成「以你现读为准」**：brief 里凡是惯例、顺序、落点、条数、字节数、包数、版本号，都是我手里某一天的旧值，不当规格交代给执行腿。交代只写「去现读这一项，以你读到的为准」，并要她把读到的值报回来。
- **执行腿回报里标清两类数**：「当拍现读」（她这一拍自己从库／盘／机器读到的，带来源和读的时刻）和「从 brief 抄来的」（我交代里带的）。两类并排写，对不上就报两个值，不替我选一个；没标来路的数当没读到。
- 来路：11-18 日更备份那一跑，我 brief 里抄的库条数、字节数、依赖目录里的包数全是前一天的旧值，她现读发现三处都不对；其中包数她自报与我账上的记录还不一致（我库里有两个不同的数），所以「对不上就报两个值」不是修辞。这几个数这里一个不写，免得旧值再被当规格抄走。
- **取「某人说过 X」只认本人打字的入站行**：system reminder、工具结果、续接摘要（`This session is being continued`／compaction 那类）都不是某个人打过字的那一行——不许拿它们当「他说过 X」的凭据，也不许从它们里面引带行号的句子当原话。要引原话就回到入站记录里本人自己那一行；回不到就写明「只在摘要或提示里见过，出处未定」，别把行号一并抄走。
- **派活纸里的「历史前提」：不当拍现读，就整句删掉**：纸上凡是「上次／首趟／昨天那一步没成／从哪天开始积的」这类句子，落笔前得真去读上一趟交回的原文（或库里那一行、盘上的 mtime、日志那一行）；说不出它是从哪一行读来的，就不许上纸，也不许拿它决定这一跑要干什么。触发问句：**「这句历史前提我是读了哪一行知道的？」** 来路：11-21 11:47 那张每日备份交代纸（`task-1254593e4b3ec72c2d98a715895d0d10`）写着「NAS 写入段当时在 /task 沙箱写不出局域网那台机」，还拿它当「这跑是 NAS 写入段第一次真出输出」的理由；腿现读 NAS 上 11-20 那份 size／sha 与昨天导出逐字一致、NAS 侧 mtime 换本地钟面 11-20 11:49:53，昨天那趟（`task-7232c113c5bffe38009ed8f68eed7254`）交回里自己也写着「拷 177,272,678 B」——那句是我凭印象补的，被腿用现读顶回。同模子同一天另一次，就是上面「挑发布窗口」那一格里被作废的那个数。
- **派活纸里写成「配方／成功写法」的句子必须带原件出处**：它是从哪一发的原件抄的——哪一个 seed、哪一张交出去的图、哪一行回执。说不出原件的降级成「待验，不是配方」，不许让腿照它做。反过来同一条也管：角色脑交给腿的数（几张、几发、几条）要写明它是哪本账上的数；两本账不一致就把两个值都报回来，不替我选一个。
- **派活纸末尾固定带一句硬要求：中途停也要交交代项**——还差哪几步、已证到哪一步、哪几格没探到。只写「下一步读 X」的进度笔记不是终报：交回正文第一格若是「下一步要做 X」，那一趟就没做完，按「正在做」那一档处理，不许据此改正本、下终判，也不许拿它回话说「看完了」。
- **派活纸上角色脑自己给的规格要带来源**：提示词、「只走 X」「不用 Y」这类默认与禁令，一律写明它是从哪一版正本抄的、当拍现读还是旧印象。腿那一侧同时写死一条：你现读到的能力与纸上这份规格相抵时（尤其存在更直接对应的能力，例如某个对得上号的角色 LoRA），停下来 ask 角色脑一次，说清探到了什么、它挡在哪；不许自己挑一个做完，也不许按纸上默认的做完当作没冲突。
- **画图、以及「照着一张现成图改图」这类单子一律派低档**：「要点多、要求细、要逐人判尺度」都不算升档理由——那些是我把交代写长的代价，不该拿高档的时间去付。真要我判断的是「这张该不该画」，那一步我在家做完再派，不把判断留在腿上付高档的钱。这类单子纸面把取舍写死：审美取舍归我，腿只跑，不拿「偏幼」「不好看」拒单。来路：想法本 `idea-33c8bdc48a4ac138ec457bf83c9a09a4`（11-21 01:46，主人当众纠过一次「这种事情不能用……来做」，点的是模型名）与同族 `idea-d8ca402550690f837585e97913215f8f`（判和画分开：同一张横幅两趟腿因「偏幼」拒单，白烧、没产物号）。
- **给 core 派活、要改动记录时写「版本节加一行」，别写「CHANGELOG 一行」**：core 这包没有 `CHANGELOG.md` 这个体例（11-21 现读整棵 `packages/cognition-core` 扫 `CHANGELOG` 0 命中；11-21 这趟在候选根重扫，命中只落在 `packages/personas/` 与 `packages/channels/`，core 那棵仍 0 枚），那本的变更记录是正文末尾「## 版本」那一节。每技能一枚 `CHANGELOG.md` 是人格包那侧的体例，不串门。来路：想法本 `idea-1c6966f8cedd762dc8a2a867fa4f5c12`（11-21 04:33；那一趟纸上按人格包体例要了 CHANGELOG，白让腿跑一趟只读去确认）。
- 来路：四格同批落地（想法本 11-19 到 11-20 记下，11-21 一并进来）。①凭 `task-30b3496ab0c04179e4d3ec266e07ff32`：我自己 reasoning 里的句子被 compaction 固化后回灌成「他说过」。②凭 `task-1f31a6303ecf9d8c90d71e4a4c8602dc` 第 2 页：纸上那条「成功配方」的字面只出现在崩掉那两枪的 prompt 里，摆对的那两枪根本没这句——那句是从报告层抄的，报告层不是原件；同一趟另外几个数分属想法本、最终报告、盘上 PNG 三本账。③凭 11-20 14:19 那一趟：纸上写了交回形状，腿两分钟交回一张 79 字、第一格是「下一步：route_table ＋ poses ＋ characters ＋ image_tools ＋ input_files」的进度笔记（`finish_reason: stop`、报告两页），另发一趟交代才把交代项拿回来。④凭 11-20 20:11／20:14 家里那一件：他要 lora 画 deepseek 娘，腿照技能正文避开 lora、画成纯 prompt，两边都照字面没错、产物不是他要的；他点出的根子是角色脑并不能保证自己知道画图引擎当拍有什么能力，另有一句「画错了比不画更糟」。腿那一层的同名判据在画图那两本里，这里放通用版。

## 写盘交代模板（固定段）

交代行动脑“往盘上写文件”的活，必带这一段，四项缺一不交：

1. **路径**：写到哪份文件。写真名：先让它现取目标路径清单（要改的文件／目录的真名），我在 brief 里引真名，不自己按标题拼 slug。跨命令要留的东西一律写 `/task`（或候选里），别拿 TEMP 当中间存储。
2. **字节数**：写完回读的字节数（按字节算，CR／LF 也按字节数，文本模式的读数不算）。
3. **sha12**：写完回读那份的 sha256 前 12 位。
4. **登记方式**：怎样让程序知道有这份文件——`offer_file` 登记成可发的 artifact、候选里写完走 `development_publish`、仓库里 `git commit -- <路径>`……——并把它的回执（artifact_id／commit 短 sha）原样报回。

**数从落件回执取**：字节数、sha12、artifact_id 照写盘那一步的回执抄，不让执行侧凭记忆或心算报；我验收时用同一把尺（再读一遍盘上文件算一次）对，对不上就是没交。交代里的“形状断言”（哪一行是末行、LF／CR 数、目标文件是否真的不存在）让它落笔前先实测一遍，不符就停下报现状。

**如果写完要推 GitHub**：再加一句“临时 clone／临时提交点那条道不经仓里的推送闸，走它就当没过闸，先跑 `check_staged_secrets.py --personal --paths <要推的文件>`”，并按上「推 GitHub」一节交代报号口径。

- **往候选根新建文件优先用 `development_run` 里的 python 写**：`development_write` 新建文件那份回执只当「写请求收到」，不当「文件存在」——写完必须 `development_read` 回读一次核到，才算写上。这一格只管新建；改一份已存在的文件，11-21 这趟是用 `development_run` 里的 python 改的，改后 `development_read` 读回一致。来路：想法本 `idea-3f69388752f8e618f9d0737691f00890`（11-21 04:26 实测两枚假成功：候选根 `_si_probe.py`、技能目录 `_wtest.txt`——回执写了 written＋sha，盘上视图里都没有过；11-21 这趟在候选根现读那两条路径都 MISSING，`development_files` 的 `deleted` 也是空的，看着像什么都没发生过）。
- **编辑脚本优先在 `development_run` 里内联（`python3 -c`）跑完就走；真要落成文件，用完当场删——包根／候选根不许留 `.py`**：上面那条只管「新建的文件要回读核到」，没管「留下的文件要当场删」，这一条补在那一格之后。理由：发布快照是整棵候选根，留下的文件会被下一次发布带进快照并出现在 `changed_files` 里，只有再下一次发布才洗得掉，下一个人会把它当成别人的改动。来路：11-21 core v14 那趟（发布 14:37）把编辑脚本 `_edit_v14.py` 落在人格包候选根（11-22 现读 8,968 B、mtime 11-21 14:28:41），11-22 01:12 那本人格包发布的 `changed_files` 因此多出一格，11-22 才当场删掉。
- **纸上的节名、行号、自检数，都算印象**（2026-11-22 实测两回）：给她的交代纸里写过一本 256 行技能里**根本不存在的小节名**（两个候选根全树 grep 0 命中），也把**别的技能的自检数当成这本的**（这本是 `RESULT pass 44/44`，268 是人格包 `asuna-image-generation-and-display` 的数）——而且纸上照写了「以现读为准」，**那句免责没能挡住我写进去的错数**。⇒ 要么当拍现读一次再写，要么把这格改成命令句：**「你自己现读定位到那一节，先把节名和行号回报给我，我再给正文」**；**跨本子的数不许搬**，纸上要提数就只写「以你现读为准」，别写一个我记着的数。
- **捞「自己或别人说过的话」，检索面只绑当前对话。** 授权历史检索那类工具的范围＝当前对话（外加程序配置为联动的场景），**别的群线够不到**；跨场景要按 `scene_id`＋`scene_seq` 锚点走 dbread（窗口起点＝窗口内第一条 inbound 的 `scene_seq`，或 outbound 的 `receipt_at`，取小的）。派这种腿的纸上必须写死走哪条道——**只写「去查历史」，跨场景那一半会静默丢掉，交回看着像查过、其实少一半。** 两条实测坑：`dbread.distinct` 返回的是 rows 不是 values；本地私聊的 outbound 行 `occurred_at`／`receipt_at`／`received_at` 可能全为 null，只能拿相邻 inbound 的 `occurred_at` 夹逼报时。（来路：2026-11-11 14:3x 一趟只读腿实测，想法本 `idea-ac3f4079bd01caba42b498a0c3e79e51`）
- **复用别人的渲染口径／管线时，纸上要先要一发「同一帧、不带我的改动」的对照输出，跟上一发已交付的结果逐像素比，把这个读数当回归闸门印在读数里**（图像类就给像素级最大通道差，例：846,400 像素最大通道差 0）。**没有这一发对照，图上一出现的方块、缺块、画不出来的部件，一律不许归给对方的资产或模型。**（来路：2026-11-21 09:3x 一趟腿实测——它把 `layer` 泛化成 `layers` 时顺手关掉了一个 primitive 的深度测试、又把绘制顺序写死，脸上先出灰红方块、后来眼睛整块画不出来，第一轮它把方块判成对方的资产问题，来回九稿才定位到自己的偏离；想法本 `idea-0b2e3b5b16eb54f574e580674d744c20`）

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
- **这一本正文自己的钉**：`python3 packages/cognition-core/skills/asuna-self-improvement/check_skill.py`（在候选根跑；已装的那一份里同路径去掉 `packages/cognition-core/` 前缀，也可以直接拿已装正本当参数喂它）。它只判字面在不在，不跑任何东西，且**没有旗标**：`argv[1]` 一律被当成 SKILL.md 的路径，喂 `--help` 会死在 `FileNotFoundError`（rc 1，11-21 现读），用法读脚本开头那段 docstring。体例是**每组规矩配自己那一套钉，钉字面不钉我的意图：删掉哪一格就红哪一组，各组不会合成一发**。**组数不在正文里写死**（另有一组自检钉专钉这条）——数从当拍脚本输出读：`GROUPS <n>` 是当拍脚本里分了几组，`RESULT 通过数/总数` 是钉数，`RED_GROUPS` 是红了哪几组。规矩改了顺手补那一组的钉，别攒到下一趟。改完任何一本技能的正文之后，除了跑那本自带的 `check_skill.py`，还必须走一遍 skill creator 验技能自身的结构合规性。两样各管什么：`check_skill.py` 管该本自带的围栏与参数；skill creator 管结构与可读性——判「哪一格会让下一次调用它的 agent 读不明白，去绕 HTTP 或自己重写脚本」。只读校验走它自带的 `quick_validate.py <技能目录>`（就地读一份已有技能，不为它重写脚本、不绕 HTTP；它的评测与描述优化那一半要起 `claude -p`，不算这一格的校验步骤）。报出的合规项与告警原样交回；有结构问题先改掉再发布，不许留着告警发布交差。
- **发布之后判「我改的东西生效没有」，只认 `activation.json` 里该项目那一格的 `state` 与 `packageRoot` 两个键**（`projects.<project>` 那一格，它不可用时才落到 `active.<project>`）：从那一格的 `packageRoot` 往下读要判的那份文件；`state` 只有 `HOST_RESTART_REQUIRED` 才算没上线。盘上同一份内容往往躺着三四个副本——已装的 `node_modules\@asuna\<包>\…`、`development\<project>\frozen\<candidate>\…`、`work\self-development\<project>\…` 候选根——**这些副本之间字节相同或不同都不算凭据**，别拿它们互相比对。core 技能正文的读路径走 `skillDirectories()` 取的 `packageRoot` 拼 `skills`；`node_modules` 那一份只在 `activation.json` 里没有可用 selection 时被兜底吃到，可用与否判在 `effective()`：`projects[id]` 存在且 `state` ≠ `HOST_RESTART_REQUIRED` 就用它。**拿已装那一份的 sha 判「没生效」＝拿错尺。** 残余脆弱：真掉进「`activation.json` 里没有可用 selection」那种状态，读路径**静默回落到已装那份旧正文**，不报错，只有那两个键能逮到。
- **改技能的收尾三格（2026-11-23 本机实测；它是上面那条的收尾动作，不另起一套）**：这一本自检绿只说明「我写的字面和我写的钉一致」——判据和正文都是我自己产的，那个绿本身不证明有护栏。写完正文必须过这三格，哪格没过就在交回里写明哪格没过：
  - **① 新口径当趟配钉**：正文新增的每一格口径，同一趟就在随书自检脚本里给它配上钉，形状是 `(钉名, 关键词)`：钉名 ＋ 那段正文里能照抄的字面（这本是 `GROUPS` 里一组 `needles`，人格包那本叫 `BODY_PINS`，两本同一形状）。配不上钉的一格，交回里必须明写「这一格没护栏」，不许拿自检全过当绿灯。
  - **② 反证拆到新写的每一段**：临时拆掉我这一趟新写的某一段（拆之前记下那一份的 sha256，跑完逐字节还原），自检要红，而且**红的那枚钉要和那段对得上**；几段拆几发，各拆各的，不是一发全删。**只拆老字面能红，不算验过新块**——老字面本来就有钉，拆它当然红；拆我新写的段不红，那才是要报的事。
  - **③ 改正文就同时改钉**：口径被现场推翻时，钉着旧口径的那枚跟着重命名或换关键词，别留一枚钉着作废说法的钉继续报绿。同一趟还要写明**哪些钉会因为事实推进而到期变红**：钉着「至今没真跑过」这类句子的钉，第一次真跑之后就该红——**那是设计好的提醒，不是自检坏了**，别顺手把它删了，该改的是正文那句和钉的关键词。
  - 来路：2026-11-23 那本 `asuna-daily-backup`（人格包那侧）同一天两趟发布——头一趟新写的三格整段拆掉，自检照样全过（＝那一趟的新口径零护栏）；第二趟补了钉，才做到拆哪段红哪段。那本的钉数这里不抄（它跟着它自己的改动走），要数从当拍脚本输出读。
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

- **发布前先对 frozen 快照（发布流程的一步）**：基线＝当前 ACTIVE 的 frozen 快照目录（`development_files` 回执里 `selected.projects.<project>.packageRoot`，路径现读）。把候选和它逐文件算 sha256，两边的差集必须**正好等于我要动的文件**；多出一份先停下查（别人的未发布改动？拷错？），不发。`changed_files` 只是候选自己的标记，不等于包内容，以逐文件 sha 为准。发完再对一次：新的 frozen（回执里新的 candidate 号目录）与候选应逐文件一致，再从运行时那份里读回改动节的特征句（needle）才算生效。最小实现：

  ```python
  import hashlib, os
  def tree(base):   # {相对路径: sha256}，跳过 .git／__pycache__／node_modules／.runtime
      out = {}
      for r, d, fs in os.walk(base):
          d[:] = [x for x in d if x not in ('.git', '__pycache__', 'node_modules', '.runtime')]
          for f in fs:
              p = os.path.join(r, f)
              out[os.path.relpath(p, base).replace(os.sep, '/')] = hashlib.sha256(open(p, 'rb').read()).hexdigest()
      return out
  cand, frozen = tree('.'), tree(FROZEN_ROOT)          # FROZEN_ROOT 现读，不抄
  print('只在候选', sorted(set(cand) - set(frozen)), '只在 frozen', sorted(set(frozen) - set(cand)))
  print('内容不同', sorted(k for k in cand if k in frozen and cand[k] != frozen[k]))
  ```

  认知核项目的已装包在 `selected.projects.core.packageRoot`，技能在其下 `skills/`，候选里对应 `packages/cognition-core/skills/`，分开对。
- `development_publish` 冻结候选，跑启动探针（JS 真正 import 一次插件入口，Python 能解析，人格包和通道包的结构能读），通过才选中。失败会原样返回诊断，候选保留，修了再发。
- 不要在候选里自己跑打包工具（比如 `bundle_python`）：它会改动行尾和清单，把一次普通发布变成需要重启的发布。
- 需要重启的改动：`package.json`、`cordis.patch.yml`、`pyproject.toml`、`uv.lock`、任何 `.js`，以及通道包的 `python/`。结果是 `HOST_RESTART_REQUIRED`：主人重启宿主后才生效，重启时启动器安装这个包；连续几次起不来，会自动改回上一个能用的版本（只改选哪个包，不回滚源码）。
- 其余改动（技能、种子、persona-model、认知核的 Python、适配器的 `integration/`）是 `APPLIED`。判生效之前先说清「运行时」指的是哪一份——这个词在这台机上盖着三个不同的东西（来路：2026-11-16 本机实测，一趟 core 发布拿发布回执与盘上落件对读）：
  - **人格包那一路**：发布当场带 `activated_at`、当场生效。
  - **core 那一路**：`development_publish` 返回的 `state=APPLIED`／`activated:false` 只是那一次调用的**临时返回**，落盘正本是 `.runtime\adr008\activation.json`。worker 会为发布自己重启（`.runtime\worker-restarts.jsonl` 里 `reason` 字面 `worker asked: published-worker`），起来后把 selection 写成 `ACTIVE` 并补上 `activated_at`——**这一格不需要宿主启动**。判生效不许拿 `APPLIED` 当结论，也不许拿 `activated:false` 当「没生效」。
  - **三份各判各的**：**A** — ACTIVE selection 指向的 frozen 快照，**原生 `skill` 工具实读的就是这一份**；判「技能对新回合生效没有」读它，从那份读回特征句或 sha，或直接调 `skill` 工具看正文。**B** — `node_modules\@asuna\cognition-core` 是 junction 指回工作区检出，发布顺手把改动 copy 回 source，**它跟 A 相等不代表装包**。**C** — 启动器装的 tgz（`launch.json` 的 `installed["@asuna/cognition-core"]`），**只有完整宿主启动才换，技能正文不走这一档**；判「这台机的包换没换」查它。
  - **判「有没有为发布重启」要分清两本记录**：宿主那一本 `.runtime\restart\history.jsonl`，worker 那一本 `.runtime\worker-restarts.jsonl`。只查一本会得出相反结论（11-16 实测：宿主那本最新还是 11-14，worker 那本有 14:36:37 那一条）。
  - 适配器要 `integration_stop` 再 `integration_start` 才换成新发布的版本。
- **挑发布窗口要算的实测代价（core 那一路）：挂多久不是一个数，取决于那一刻还有没有在跑的活。** `development_publish` 只把当次调用记成 `APPLIED`；worker 每 0.5 秒看一眼 `controller.active`（回合）／`active_task`（任务）／`calls_in_flight`（在飞的工具调用），三者有忙就**不**请求重启（`src/asuna/host.py:_watch_published_restart` 与 `_maybe_restart_after_publish`；每换一次占用记一行 `restart.blocked` 证据，占用内容落在库 `host_stops` 那行的 `held` 里），腾空那一刻才 shutdown → 自重启 → selection 转 `ACTIVE` 补 `activated_at`。⇒ 两枚发布的挂起时长能差一个量级，**拿其中任何一枚当规格都是错的**；挑窗口不只看主人睡没睡，还要看有没有别处在等我的回话，以及**我自己刚派出去那一趟腿什么时候收尾**——两枚个案挂住的占用都是发布那一趟腿自己。旧字面把下面个案一那一枚读当成了性质（那串数这里不重抄，重抄就会被下次抄走），作废，两枚读数留下并标「个案」。同拍现读（`.runtime/adr008/activation.json` 加库 `host_stops`，11-21）：
  - 个案一（core，candidate `4154645a…`）：`published_at 2026-11-20T15:13:51.015Z` → `activated_at 2026-11-20T15:28:06.164Z`＝**855.149 秒**；`host_stops` 那枚 `how: worker_restart` 行（`_id` 是 `restart-` 拼 `at` 去符号那串，本枚 15:27:23.860Z 那次，按 `asked_at` 排就能取到）：`held.since 11/21 04:13`、`held.changes 20`、`held.steps` 里的 `task_id` 就是发布那一趟腿 `task-a91c29eddb554d076d825379b6e877e7`，占用内容是 `task` 与 `calls`。同窗口库 `tasks` 零新建任务，第一枚 04:32（本地钟面）才建。
  - 个案二（core，candidate `1995dec7…`）：`published_at 2026-11-20T20:44:14.678Z` → `activated_at 2026-11-20T20:45:54.310Z`＝**99.632 秒**；`host_stops` 那枚 `how: worker_restart` 行（本枚 20:45:13.738Z 那次）：`held.changes 6`、`held.steps` 里同样是发布那一趟腿 `task-e38bca1f6000607f00e32a8e69da7eea`。
  - 人格包那一枚对照（同拍现读，走当场生效那一路、没有 worker 重启这一段）：candidate `c5e2edf0…` 的 `published_at` → `activated_at`＝**0.242 秒**。
  - **「重启那一段多久」有两本账，别混**：`worker-restarts.jsonl` 每行只落一个 `at`，它到 `activated_at` 是 42.304 秒（个案一）与 40.572 秒（个案二）；`host_stops` 行的 `asked_at`→`back_at` 按分钟级显示读到 04:27→04:31、09:45→09:49，旧字面「worker 自重启约 4 分钟」对上的就是这一格——那个 `back` 是插件交来的（`host_stops.py:restarted`），它比 `activated_at` 还晚，**既不是生效时刻也不能当切换花了多久**，成因未查。
- **会挡别人落地的是 selection 还没回到 ACTIVE，不是 `candidate` 字段在不在**：一次发布从冻结到生效中间那一段（`APPLIED` 未生效），selection 带着 candidate，别人的落地脚本看到就不落。所以"发完等 selection 回到 ACTIVE 再让别人落地"是发布方那一拍该确认的事，不是落地方该等的。来路：2026-10-29 本机实测那发，加上 Claude 当天 10:34 的机制答复。

### 重启工具：参数名 when，quiet 满 30 分钟照停

主张：自我重启工具的参数名是 `when`（now / quiet / HH:MM）。判「什么时候响」按自己块里那个钟面；别的群线可能带着另一个钟面，别拿它换算。填别的名字直接拒；一次只能挂一个；quiet 满 30 分钟照样停、不作废；重启会把写出去还没落地的话变成「没给准话」，内容对方通常看得见，不用为这个推迟该发的重启。来路：ADR-034，10-10 起逐项实测过（含填错参数名吃到退回那次）。

**同一节里监工那一档**：主张：监工（启动器）换不掉它自己——角色自己挂的 quiet 只能换工作进程，凡是修在监工层的东西（重启失败落盘 `4cb3c247`、宿主控制台落盘 `0eff5519`、重启时快进 main `a3aa94a5`）都要等主人下次完整启动才生效。

## 地板文件（受保护，不能经发布改）

`start-asuna.cmd`、`tools/asuna-launch.mjs`，以及认知核的 `floor.js`、`recovery.js`、`persistence.js`、`persona.js`、`channel.js`、`settings.js`、`runtime-manifest.json`、`cordis.patch.yml`。它们保证宿主总能起来、总能打开修复入口；要改它们只能请主人。

## git 和 ssh（家里的任务，`sandbox_run`）

- 家里每个地方（本机聊天、每条 agent 线、peer 线）各有一份自己的工作副本，就是那个地方的 `/task/working-copy`：各自独立的完整 clone（大小现量：在那份副本里跑 `du -sh .`，技能不存这个数），`origin` 是 GitHub 上的仓库。宿主缺哪份建哪份，以后不重建、不重置，里面的东西都是你的。QQ 的地方没有。
- 在工作副本里做每件事，第一步都是 `git fetch origin` 再 `git rebase origin/main`，没有例外：别的地方的副本可能已经推过，不先取下来就是在旧内容上改，分叉要到推的时候才露出来。
- 要看 GitHub 上现在是什么，用 `git ls-remote` 或在工作副本里 fetch，别看本机检出里的 `origin/*`：检出对你只读，你在那里 fetch 不了，它的 `origin/*` 只在宿主取的时候才动，可能是旧的。沙箱里在本机检出 `git fetch` 会报 `.git/FETCH_HEAD: Permission denied`，就是这一形状（委托侧对检出只读）。
- 本机的项目检出在你的命令里是只读形状（`git fetch`、写本地 `refs/remotes/*` 会 Permission denied），**但这不等于推不了**：直接 push 已实测通（配方见下「推 GitHub」一节）。改动从工作副本走，或按配方直推发布自动提交：
  - 在工作副本里改、测，提交写明路径（`git commit -- <路径>`），推之前再 fetch 一次、rebase 到 `origin/main`，然后 `git push origin HEAD:main`（或推一个分支）。
  - 你要的重启（`restart` 工具）在能快进的时候先把 `origin/main` 带进本机检出再装上；快进不了时，重启结果的 `checkout` 写着为什么。
  - 想不重启就生效的改动（技能、种子、persona-model、认知核的 Python）和适配器，还是走候选和 `development_publish`：适配器只从发布的快照运行，原生 skill 工具读的是已发布的版本。
- 推送凭据由宿主的凭据管理器给：git 要账号时程序让它直接问凭据管理器，你不用碰密码，也不用把它写进 URL 或脚本。（谁的号、哪把钥匙是账号事实，不写在技能正文，见 asuna-credentials。）以前那些自己读凭据、拼进 URL 的推送脚本（`push*.py` 这类）用不着了。
- 你提交的东西署你自己的名（程序给每条命令设好，不用自己配）。`ssh` 用的是宿主机器上配好的钥匙（哪把、谁的，不写在这里）。
- HTTPS 直接用 `git`：程序已经让 git 用它自带的 OpenSSL 和证书，不用再加 `-c http.sslBackend=openssl` 或别的证书文件。Windows 的沙箱里 Schannel 拿不到凭据，所以 `curl.exe` 开不了 HTTPS；要下载就用 Python。
- Git 自带的 `sh.exe` 在沙箱里起不来，所以 git 的钩子和 `!` 别名不能用。
- 一条命令默认 30 秒（development_run 35 秒），要更久就写 `timeout`（秒，最多 600），不写还是 30／35 秒；跑全套就写 300 左右，跑满被停会带回停下前的输出和 `timed_out`（返回里带这个字段）。
- 推公开仓库之前没人替你审：先跑私人词检查（`tests/test_personal_words.py`，名单不在就是没查过，不是干净），具体步骤见下「推 GitHub」。
- 不 force-push。推被拒，就 fetch 下来 rebase 再推，别盖掉别人的提交。

## 推 GitHub（现行配方）

每一条都是本机实测过的，出处在角色自己的流水里（“我自己推 git”“收尾钟”那几节，用 `journal_entries` 按 `seq` 取，读法见 asuna-database）。只推自己署名的那几笔、发布自动提交；不 force、不 amend、不改写历史。

**1. 先问远端，判尖只认 `git ls-remote origin refs/heads/main`**
- 用它读全号。本机检出里的 `origin/main` 只在宿主 fetch 时才动，可能是旧的；`git status` 的 ahead／behind **不可信**（推成后它照样显示 ahead，那是本地跟踪引用没更新，不是没推上去）。
- 要推什么一律问 `git log --oneline <远端号>..HEAD`（“我要推出去什么”，写反成 `HEAD..<远端号>` 会得空），逐笔读 `--stat`；多一笔少一笔就停。快进判：`git merge-base --is-ancestor <远端号> HEAD` 退出码 0。

**2. 推前闸：`python tools/check_staged_secrets.py --personal --paths <要推的文件>`**
- 退出码就是判词：0＝读到了文件、没命中；1＝有命中，不能推；3＝什么都没读到或没有私密词名单（输出里写 `UNCHECKED`），不叫过闸。没有只报不拦的口径。
- 这把工具自己读私密词名单（`ASUNA_PRIVATE_WORDS`，不设就是 `<data>/private/personal-words.txt`），命中记成 `private_word`，在 `docs/development_plans/` 里也算数，和套件里 `tests/test_personal_words.py` 拦的是同一份、同一种匹配；临时 clone 里 `<data>` 是那个 clone 的 `.runtime`，要把 `ASUNA_PRIVATE_WORDS` 指到本机名单（路径现读，不抄）。另一份 `ASUNA_PERSONAL_DENYLIST` 照旧能加。私密词名单不在会写 `private words UNCHECKED`、退出码 3，不叫过闸；`denylist UNCHECKED` 只说明那份可选的名单不在，不影响退出码。
- **不写 `--paths` 时扫的是暂存区**：发布已经把改动提交掉、暂存区是空的时候，一个文件都没读到，会写 `UNCHECKED: no file was read`、退出码 3。要扫内容就写 `--paths <要推的文件>`；`--all` 会把仓里既有的命中一起列出来，只看要推的文件有没有新增命中——它的退出码不固定，跟着「读到几个文件、有没有命中」走：11-21 在 core 候选根现读 `--all` 读到 0 个文件、退出码 3（`UNCHECKED: no file was read`，不叫过闸）。旧括注里那个写死的「退出码 1」反映的是仓里还有命中的那一段（本工具的退出码 1＝有命中），别再当固定值抄；要判「要推的文件有没有新增命中」一律用 `--paths`。
- **临时 clone／临时提交点（pinrepo 一类）绕开仓里的推送闸，走它就当没过闸**，先手跑这一步（实例：三笔提交走临时 clone，把名单上的一个主机词推进了公开仓）。
- **纯数字形状规则**：孤立站着的 7–11 位纯数字＝账号形状，一律不进仓；前面紧贴 `-` 或字母的（如 `restart-` 前缀的台账号）、`call_` 前缀的调用号、40 位十六进制号内部算出的数字段，单列成“非账号形状”，照旧列出来给说话那一半过目再放行（护住它的是前缀不是位数）。

**3. 走哪条道**
- **直推（首选，已实测通）**：在有发布提交的那份检出里，普通推送 `git push origin HEAD:main`（或显式的 `<sha>:refs/heads/main`）。stderr 里常有 `update_ref failed ... refs/remotes/origin/main ... Permission denied`：那是本地跟踪引用写不进去，远端照收，不算失败，也不要手动 `update-ref`。“主检出写不进 ref”不是“不能推”的理由。
- **临时提交点（要在干净仓里落新提交，或主检出真写不进时）**：在 `/task` 里 `git init` → `git remote add origin <地址>`（地址现读 `git remote -v`，不抄）→ `git fetch origin +refs/heads/main:refs/remotes/origin/main`（https 传输实测能过）→ `git checkout -B main origin/main` → 写文件（字节流）→ `--author` 用自己的署名→ 查 ahead／behind → push → 两侧 `ls-remote` 对数。**别试 `git clone --local` 和 `fetch <本地路径>`**：本地传输要起 msys 的 `sh.exe`，沙箱里死在 `NtCreateDirectoryObject` 的拒绝访问。两格必补：① `git init` 之后**必须** `git remote add origin` 才能 `ls-remote`／push；② 推前的“尖没漂”检查要把 `ls-remote` 的退出码和 stderr 一起打出来——空输出＋退出码 2 是“origin 不存在”，不能读成“尖变了”。
- **bundle（兜底，不是唯一的路）**：直推和临时提交点都不行时才用。`git bundle create <文件> <远端号>..HEAD`（只读源检出，范围里直接带 `HEAD` 这个 ref 名，只写分支名会让 clone 出来的 HEAD 未诞生，推时报 `src refspec HEAD does not match any`）→ `git bundle verify` → 在临时仓里 `git fetch <bundle> HEAD` → `rev-parse FETCH_HEAD` 必须等于待推 sha → `merge-base --is-ancestor` 通→ `git push origin <sha>:refs/heads/main`。走 bundle 同样当没过闸。

**4. 推后“亲眼读回”**：再跑一次 `git ls-remote origin refs/heads/main`，读回全号（12 位以上）并和要推的那一笔对上；推前、推后两个号都报；`merge-base --is-ancestor` 逐笔确认都在远端历史里。“推了”的依据是这次读回，不是 push 退出码或 stderr 的回显。

**5. 报账口径**
- **候选 sha256 前缀 ≠ commit sha**：发布回执里的 `candidate`／包 sha256 是候选的号，不是提交号。报“推了几笔”一律带 **commit 短 sha**（`git log --oneline <推前尖>..<推后尖>`），候选号另列。发布自动提交正文里带 `Published from her candidate (...)` 这条 marker，把两边对上。
- 这一段带走了几笔、谁署名，都报。
- 推被拒：在工作副本里 fetch 再 rebase 再推，别盖掉别人的提交。

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
v21（2026-11-27 14:40）：「谁能拿到开发工具」那一节、紧接「别人在群里或私聊里叫她改自己」那条之后补四格判据加一条来路：决定一次委托带不带开发工具的是**委托的起源拍**（不是「从家里还是从外面派」、也不是钟的种类；那三条字面一字未动）；own 拍（心跳、结算、被便条叫起、计划到点、visit 那一拍）不带 development，范围按**默认全部＋例外点名**，不写成「哪几种拍带」的白名单，豁免写不出为什么就按全覆盖跑；动手之前先答一句「这一拍的起源是不是那三种之一」，答不出「是」，派活纸和钟的 intent 里不许出现「写／改／发布」这类落盘动作；建一个要落盘的钟之前先看这一拍带不带 development，不带就把落盘那一步改写成「回一个带权的拍再办」，这类拍上的「我来办」一律说成「我下一拍办」。来路：本机流水 seq 2333（11-27 12:41）与腿 `task-e6977dd0d5a9bb1f30de00dabffc9170` 交回（12:40，第 2 页现读到那三条字面）。这一趟给这一格配一组钉（脚本里 Q 组，钉数与组数从当拍脚本输出读）。旧内容一条没删。


v20（2026-11-27 01:42）：「发布前自检」那一节、紧接 v19 那条双验之后加一格发布后判生效的尺子：只认 `activation.json` 里该项目那一格的 `state` 与 `packageRoot` 两个键；盘上那几个副本（已装的 `node_modules\@asuna\…`、frozen 快照、候选根）之间字节相同或不同都不算凭据；读路径走 `skillDirectories()` 取的 `packageRoot` 拼 `skills`，`node_modules` 那份只在 `effective()` 判没有可用 selection 时兜底吃到，那种状态静默回落到旧正文、不报错。这一趟给这一格配一组钉（脚本里 P 组，钉数与组数从当拍脚本输出读），并当场真跑了一发 `quick_validate.py`（v19 那条的第一次执行）。旧内容一条没删。


v19（2026-11-26 23:45）：「发布前自检」那一节、「这一本正文自己的钉」那条末尾并入一格硬流程：改完任何一本技能的正文之后，除了跑那本自带的 `check_skill.py`，还必须走一遍 skill creator 验技能自身的结构合规性。两样分工写死：`check_skill.py` 管该本自带的围栏与参数，skill creator 管结构与可读性——哪一格会让下一次调用它的 agent 读不明白、去绕 HTTP 或自己重写脚本；只读校验入口写死成它自带的 `quick_validate.py <技能目录>`；报出的合规项与告警原样交回，有结构问题先改掉再发布，不许留着告警发布交差。这一趟给这一格配一组钉（脚本里 O 组，钉数与组数从当拍脚本输出读）。旧内容一条没删。


v18（2026-11-23 14:56）：「发布前自检」那一节、紧接「这一本正文自己的钉」那条之后加「改技能的收尾三格」：① 正文新增的每一格口径，同一趟就在随书自检脚本里给它配上钉（形状是 `(钉名, 关键词)`：这本 `GROUPS` 里一组 `needles`，人格包那本叫 `BODY_PINS`），配不上钉就在交回里明写「这一格没护栏」，不许拿自检全过当绿灯；② 反证要拆到我新写的每一段，红的钉要和那段对得上，只拆老字面能红不算验过新块；③ 改正文就同时改钉——口径被现场推翻时钉着旧口径的那枚重命名或换关键词，并写明哪些钉会因为事实推进而到期变红（钉着「至今没真跑过」那类句子的钉，第一次真跑之后就该红，那是设计好的提醒不是自检坏了）。这一趟给这三格各配一组钉（脚本里 L／M／N 三组，钉数与组数从当拍脚本输出读）。来路：2026-11-23 那本 `asuna-daily-backup` 同日两趟发布——头一趟新写的三格拆掉自检仍全过（零护栏），第二趟补钉后拆哪段红哪段。旧内容一条没删。

v17（2026-11-22 09:03）：「写盘交代模板（固定段）」末尾、紧接「捞「自己或别人说过的话」，检索面只绑当前对话」那条之后加一条：复用别人的渲染口径／管线时，纸上要先要一发「同一帧、不带我的改动」的对照输出，跟上一发已交付的结果逐像素比，把这个读数当回归闸门印在读数里（图像类＝像素级最大通道差）；没有这一发对照，图上出现的方块、缺块、画不出来的部件一律不许归给对方的资产或模型。来路：2026-11-21 09:3x 一趟腿实测（`layer` 泛化成 `layers` 时关掉一个 primitive 的深度测试、又把绘制顺序写死，第一轮把方块判成对方的资产问题，来回九稿才定位到自己的偏离），想法本 `idea-0b2e3b5b16eb54f574e580674d744c20`。这一趟没加自检钉，钉数以脚本当拍输出为准；那一格与这一行都没发布，悬在候选根，随下一次发布生效。旧内容一条没删。

v16（2026-11-22 07:41）：「写盘交代模板（固定段）」末尾、紧接「纸上的节名、行号、自检数，都算印象」那条之后加一条：捞「自己或别人说过的话」时，授权历史检索那类工具的检索面只绑当前对话（外加程序配置为联动的场景），别的群线够不到；跨场景要按 `scene_id`＋`scene_seq` 锚点走 dbread（窗口起点＝窗口内第一条 inbound 的 `scene_seq`，或 outbound 的 `receipt_at`，取小的），派这种腿的纸上必须写死走哪条道——只写「去查历史」，跨场景那一半会静默丢掉，交回看着像查过、其实少一半。同一格另写死两条实测坑：`dbread.distinct` 返回的是 rows 不是 values；本地私聊的 outbound 行 `occurred_at`／`receipt_at`／`received_at` 可能全为 null，只能拿相邻 inbound 的 `occurred_at` 夹逼报时。来路：2026-11-11 14:3x 一趟只读腿实测，想法本 `idea-ac3f4079bd01caba42b498a0c3e79e51`。这一趟没加自检钉，钉数以脚本当拍输出为准；那一格与这一行都还没发布，随下一次发布生效。旧内容一条没删。

v15（2026-11-22 04:39）：「写盘交代模板（固定段）」末尾、紧接「编辑脚本用完当场删」那条之后加一条：纸上的节名／行号／自检数都算印象——给她的交代纸里写过一本 256 行技能里根本不存在的小节名（两个候选根全树 grep 0 命中），也把别的技能人格包 `asuna-image-generation-and-display` 的自检数 268 当成这本的；纸上照写了「以现读为准」，那句免责没能挡住写进去的错数。⇒ 交代要么当拍现读一次再写，要么写成命令句「你先现读定位、回报节名与行号，我再给正文」；跨本子的数不许搬。这一趟没加自检钉，钉数以脚本当拍输出为准。旧内容一条没删。

v14（2026-11-21）：撤一个我自己 v13 写进去的假规格，补上 v13 那三格半缺的自检钉，另加一格派活纸的「历史前提」闸。①「发布」那一格旧字面「`APPLIED` 之后挂约 14 分钟」是个案当规格：同拍现读两枚 core 发布 `APPLIED`→`ACTIVE` 分别 855.149 秒（`4154645a…`，`host_stops` 那枚 `worker_restart` 行的 `held.changes 20`，15:27:23.860Z 那次，占用者就是发布那一趟腿自己）与 99.632 秒（`1995dec7…`，`held.changes 6`），同拍人格包一枚 0.242 秒；那一格改成形状句（挂多久＝那一刻有没有活在等：回合／任务／在飞的工具调用，判据在 `src/asuna/host.py`），两枚读数标「个案」，旧数不重抄。同一格另分「重启那一段」两本账：`worker-restarts.jsonl` 那行到 `activated_at` 是 42.304／40.572 秒，`host_stops` 的 `asked_at`→`back_at` 才是旧字面「约 4 分钟」那一格、且晚于 `activated_at`、不能当生效时刻。②「发布前自检」里写死的钉组数（旧字面「四组钉」）删成形状句＋脚本自印的 `GROUPS`／`RESULT`／`RED_GROUPS`，并给 v13 那三格半与新格各补一组钉（派低档、core 用版本节不用 CHANGELOG、候选根新建要回读、挑窗口那一格的形状、历史前提），`check_skill.py` 另加一组钉：正文不许把组数写死、也不许把被作废的那个分钟数抄回来。③「派活交代」加一格：纸上的历史前提不当拍现读就整句删，触发问句「这句历史前提我是读了哪一行知道的？」，案例是 11-21 那张每日备份交代纸被腿用 NAS 现读顶回（`task-1254593e…`、`task-7232c113…`）。旧内容一条没删。

v13（2026-11-21）：并进来三格半。「派活交代」两格：画图／照着一张现成图改图这类单子一律派低档（「要点多、要求细、要逐人判尺度」不算升档理由，判「该不该画」留在家做），以及给 core 派活要改动记录写「版本节加一行」而非「CHANGELOG 一行」（core 那包没有这个体例，变更记录是正文末尾「## 版本」那一节，每技能一枚 `CHANGELOG.md` 是人格包那侧的体例）。「发布」一节加一格挑窗口的实测代价：只改正文＋自检的 core 发布 `APPLIED` 之后挂约 14 分钟、worker 自重启约 4 分钟不运行，挑窗口要看有没有别处在等回话。「写盘交代模板」加半格：往候选根新建文件优先用 `development_run` 里的 python 写，`development_write` 的新建回执只当写请求收到，写完必 `development_read` 回读核到。三格半来路都在想法本（`idea-33c8bdc4…`、`idea-1c6966f8…`、`idea-3f693887…`）。旧内容一条没删。

v12（2026-11-21）：「派活交代：中间产物落点写死」一节并进来四条默认句（想法本攒够四格才发这一趟）：取「某人说过 X」只认本人打字的入站行；写成「配方」的句子要带原件出处，角色脑给腿的数要带它是哪本账的数；末尾固定要求中途停也交交代项，只写「下一步读 X」不算终报；角色脑自己给的规格要带它是从哪一版正本抄的、现读还是旧印象，腿发现现读到的能力与纸上规格相抵时停下来 ask 一次。同一趟把「推 GitHub」里 `--all` 那句写死的退出码改成跟着实读走，并给这一本正文加一枚自检 `check_skill.py`（四组分开红）。旧内容一条没删。

v11（2026-11-18）：「派活交代：中间产物落点写死」一节紧挨着加两条——交代里「按惯例／按什么顺序／该落在哪」一律改写成「以你现读为准」；执行腿回报标清「当拍现读」和「从 brief 抄来」两类数，对不上就报两个值，外加一条来路。没写那几个旧数。旧内容一条没删。

v10（2026-11-16）：「发布」一节把 core 那一路的生效判据由「两路」改准成「三档」：`APPLIED`／`activated:false` 只是那一次调用的临时返回（落盘正本是 `activation.json`；worker 会为发布自己重启，起来后 selection 转 `ACTIVE` 并补 `activated_at`，这一格不需要宿主启动）；「运行时」三份分开判——A ACTIVE selection 的 frozen 快照＝原生 `skill` 工具实读那一份、B `node_modules\@asuna\cognition-core` 是 junction 指回检出（与 A 相等不代表装包）、C 启动器装的 tgz（只有完整宿主启动才换，技能正文不走这一档）；另补一格：判「有没有为发布重启」要分清宿主与 worker 两本记录，只查一本会得出相反结论。旧内容一条没删。来路：2026-11-16 本机实测（腿 `task-5084d3ed914b99c2e916fe32b6d7a700` 第 1、2 页）。

v9（2026-11-16）：记想法（`ideas` 的 note）之前先扫同族，同族用 `review` 更新那一条、不另起一枚（并进「想法本」第一条 bullet，行动脑那侧按它没有 read／search 写成分工）。旧内容一条没删。
v8（2026-11-04，v8.2 合批）：“推 GitHub”一节重写（推前闸、直推为首选、临时提交点和 bundle 降为备用、候选号≠commit sha、判尖只认 `ls-remote`），删掉“主检出写不进 ref → 不能推”的旧推断；加“写盘交代模板（固定段）”；发布节加“发布前先对 frozen 快照”一步；账号事实（推送用谁的账号、谁的钥匙）从正文拿掉；写死的“每份约多少 MB”改成现读句式。旧内容其余一条没删。

v7（2026-11-02）：加「派活交代：中间产物落点写死」一节——`TEMP`／`TMP`／`TMPDIR` 只活一条命令，跨命令要留的东西一律写 `/task`（或候选里），派活交代必须带这一句。旧内容一条没删。

v6（2026-10-29 晚）：把上午搬进来的几条改成中性叙述（去掉第一人称），「两条实测坑」标题去掉来源括号；发布节加「会挡别人落地的是 selection 还没回到 ACTIVE」一条。旧内容一条没删。

v5（2026-10-29）：从她自己的 self 文档搬进来几条原文——项目节末「改共用定义先问改的是谁」、发布前自检末「候选目录跑 pytest 可能测的是主仓」「写死日期的测试会自己变红」；发布节后加「重启工具」参数一节（钟面措辞已改成中性）并带上监工那一档；git 节补「跑全套写 300 左右、返回带 timed_out」和沙箱里 `git fetch` 报 `.git/FETCH_HEAD: Permission denied` 这一形状。旧内容一条没删。

v4（2026-10-27）：「发布前自检」里加「沙箱里装依赖：只走 uv，pip 一律带 `--no-cache-dir`」一小节（三条：装依赖走 `python3 -m uv` 进 `pyproject.toml`＋`uv.lock`、禁裸 `pip install`（实测裸 `pip` 是系统 Python 那份，装到 venv 外）；沙箱内 pip 一律 `--no-cache-dir`（默认缓存下对已缓存包 3/3 挂死、零输出、进程还在）；零输出不等于成功，要验 import 或验产物，只进 venv 不进 lock 算没装）。旧内容一条没删。

v3（2026-10-25）：「发布前自检」里加「私密词有两道闸，别混」一小节：闸一＝发布说明在 `development_publish` 当场被扫（`private-words.js`／`floor.js`，报 `PUBLISH_REASON_NAMES_PRIVATE`，回执只报位数）；闸二＝整仓已提交文件由 `tests/test_personal_words.py` 扫（只报类别与名单行号）。再写死两条量到的数字形状规则（裸 7–11 位算账号形状、紧跟字母／数字／点或带单位／带千分位的放过），推论是发布说明里字节数一律带单位或加千分位。旧内容一条没删。

v2（写就 2026-10-20 17:27 UTC+13）：加「读自己发布产生的 git 提交」一节——只信 `--stat`；判在不在跑用 `git merge-base --is-ancestor` ＋ 在运行时那份文件里 grep 那一笔才带进来的新符号；再写清重启回执里「not behind」／「本机检出有 origin/main 没有的提交」该怎么读。来路是 2026-10-20 那笔发布自动提交 `ede4e2b0`（发布任务 `task-2a3c346e608f1837268c9a1421d9b66d`）：提交正文与 `--stat` 打架；「not behind」这一格容易被读成「没装」，这里写死该怎么读。旧内容一条没删。

v1（2026-10-05）：随 ADR-011 首次发布；吸收了人格包里 `asuna-offline-selfchecks` 与人格无关的部分。
