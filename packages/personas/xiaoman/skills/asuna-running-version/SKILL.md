---
name: asuna-running-version
description: 我想知道「现在跑的是哪一版」「我改的那个东西进没进这一回合」「要不要为这个重排闹钟」时读这一份。判据：先看这一回合 restart_from_program.loaded（commit＋各包 sha＋selections）；缺 loaded 那一格不等于没装，先问一句；比内容别只比包 sha（重启会重新打包、号会变）；主仓合了不等于我这边在跑，跑的是发布过的快照，不 publish 重启也只装程序那半边；查 .runtime/adr008/activation.json 的 state／candidate／published_at／changed_files；回执说「本机检出有 origin/main 没有的提交」＝本机比远端新，不是没装；启动器遇脏工作区是跳过快进不报错，本机可能长期落后一格，这不是故障；新参数进没进看这一回合的工具表。附零依赖探针 version_probe.py 与自检 check_skill.py。
---

# asuna-running-version

「现在跑的是哪版」这个问题我问过八回左右。答案不在记忆里，在这几个地方。下面是我核对过的位置和读法。

## 一、先看这一回合的 `restart_from_program.loaded`

有 `loaded` 那一格，就是监工（启动器）在这次重启起来时记下的实况：

- `commit`：本机检出的提交（短号）
- `packages`：每个包安装时记的 sha（前 12 位）
- `selections`：每个 project 的 `state` 和 `candidate`（被退回过的还带 `reverted_from`）

写它的是 `tools/asuna-supervisor.mjs:loaded`（读 `activation.json` 和 `launch.json`），原样递给我的是 `src/asuna/restarts.py:restart_from_program`。

## 二、缺 `loaded` 那一格不等于「没装」

这一整块只在「有重启记录、而且起来不到 24 小时」时才出现：那个 24 是 `src/asuna/restarts.py:SHOWN_HOURS`，判断在 `src/asuna/restarts.py:block`（没有记录或太旧就整块不给）。

所以缺这一格只说明「最近没重启，或者那次已经过了 24 小时」。**先问一句，别默认没装就去重排闹钟**——10-15 上午我这么白改过一次期。

## 三、比内容，别只比包 sha

包 sha 是打包产物的号，不是内容的号。每次启动都会重新 pack 再拿 sha 跟上次装的比（`tools/asuna-launch.mjs:syncCheckout`，比的那一步是 `tools/asuna-launch.mjs:changedPackages`），同样的内容重新打包也可能给新号。

要比就比两样：代码版本（commit）＋文件内容（逐文件 sha256）。

现成的比法（本技能目录的 `version_probe.py` 就是这么算的）：从 `activation.json` 拿那个 project selection 的 `workerPath`／`packageRoot`，跟检出的源码逐文件比 sha256。今天这一版实测：`src/asuna` 与在跑那份可比文件 116 个、内容不同 0 个；`cli.py`、`native_ui.py` 只在检出里有（不进包），`resources/RUNTIME_API.md` 只在跑的那份里有。

## 四、「主仓合了」不等于「我这边在跑」

跑的是我发布过的快照：`packages/cognition-core/src/floor.js:effective` 按 `activation.json` 里的 selection 取 `packageRoot`（人格、通道包）和 `workerPath`（worker 的 Python）；技能目录也走同一份 selection，见 `packages/cognition-core/src/floor.js:skillPaths`。

**发布不刷新 `node_modules/@asuna/xiaoman`，也不需要刷**（Claude 10-20 02:18 给的，我 10-20 这趟自己
核过）：人格路径按**选中那一版的 `packageRoot`** 解析——`packages/cognition-core/src/floor.js:resolvePersona`
收的那个 root 就是 `effective` 给的 `packageRoot`，只有什么都没选中时才退回 `resource_root`。
`node_modules/@asuna/xiaoman` 只是安装时那一份，**只有什么都没选中时才用**。所以安装位是旧 sha 是
正常的，**读到的就是选中版**。10-20 实测对照：选中版 frozen 快照里那份 image-generation 的 SKILL.md
sha256 前缀 `e9daf9bb`，`node_modules/@asuna/xiaoman` 那一份是 `ad006104`（旧）——两边不同号，
而这一回合 skill 工具真读到的技能目录也确实落在 frozen 选中版下面。

一个发布有三种状态，别混：

- `HOST_RESTART_REQUIRED`：还没装，等下次启动由启动器装
- `APPLIED`：装了，等 worker 下次起来才用
- `ACTIVE`：真在跑（worker 起来后自己写的）

所以「published」不是「running」，running 是 ACTIVE。适配器只从发布过的快照跑；东西改在候选里没发布，重启也替我上不了线，只会把检出里 pack 出来的那半边装上。

## 五、查 `activation.json`

- 位置：本机项目检出下的 `.runtime/adr008/activation.json`（别的 profile 在 `.runtime/adr008/profiles/<profile>/`，见 `tools/asuna-launch.mjs:profileBase`）。
- 每个 project 看：`state`、`candidate`、`published_at`、`changed_files`、`previous`、`boot_probe`。
- 另有一格 `active`：上一次真跑起来的那份。selection 和 active 不一样，就说明发布了还没跑。

### 按内容判活包（version_probe.py 的第五步，2026-10-21 加）

输入一个包名（project），只读，不跑前四段：

```sh
python3 skills/asuna-running-version/version_probe.py --package core --file skills/asuna-self-improvement/SKILL.md --needle "某个只有新版才带的字面"
```

输出三行读数＋读的时刻（UTC 原始值＋ +13／+8 两种换算，按 asuna-usage-readout 硬规矩 8）：

1. `activation.json` 里 `active.<项目>` 的 sha256、state、activated_at；
2. 运行时那份文件（active 的 packageRoot 下的 --file）的 sha256 和字节数；
3. --needle 字面在不在（可重复传，按 UTF-8 字节匹配）。

退出码：0 = 三行都读到（needle 在，或没传）；1 = 该读的没读到；3 = 读到了但某个 needle 不在（读数，不是故障）。
它给的是「这一刻运行时那份文件里有没有那个字面」，比看 state 是 ACTIVE 更接近「内容在跑」。

三条判据（读数时别读错。来路：主人 10-20 交代，其中两条是我自己踩过的）：

- `loaded.packages` 读的是 `launch.json` 的 `installed`，报的是「该装的那档」，不是在跑的那档；
  要知道在跑的是哪档，看 `active` 块和运行时那份文件的内容。
- 被退回的重启不进 `audit_events`，只落 `activation.json`（`reverted_at`、`reverted_from` 都在 `previous` 里）；
  查退回不要去审计里找。
- `installed_at` 不在 `active.*` 块里，只在 `previous` 里；判「刚装的」用 `activated_at` 加包目录 mtime。

试跑过的读法和没验过的：实测见试用记录；`activation.json` 里的时刻原始值是 UTC 的 ISO 串，结构里 `packageRoot` 下的路径按包内相对路径写 --file。

## 六、回执说「本机检出有 origin/main 没有的提交」＝本机比远端新

那是 `checkout.state = diverged`：本机有远端没有的提交，快进不了，这次装的是磁盘上原来的检出。**这不是「没装」**。10-15 我把这句读成没装，判错了一次。

全套状态和它们的原话在 `src/asuna/restarts.py:CHECKOUT_WORDS`：`fast_forwarded`、`up_to_date`、`fetch_failed`、`not_main`、`changed_files`、`diverged`、`fast_forward_failed`。

## 七、脏工作区会让本机长期落后一格，这不是故障

`tools/asuna-launch.mjs:fastForwardCheckout`：先 fetch，只有「在 main 分支、跟踪文件没有改动、并且确实落后 origin/main」才快进；有没提交的改动就**跳过**（`changed_files`），不覆盖也不报错。它从不 merge、rebase、reset。

所以本机检出可能长期比 origin/main 落后一格。今天实测：HEAD 落后 1 笔，工作区有 2 个未提交文件——下次重启这句还会是 `changed_files`。这不是坏了，是它不敢动我的东西。

## 八、新参数进没进，看这一回合的工具表

判断某个新参数、新枚举进没进这一回合，看这一回合真收到的工具表，比看文档准——文档会滞后，工具表是这一回合的 schema。

一个坑：我脚本里 `import asuna` 拿到的是**本机检出 `src` 那一份**（`.venv` 里 `_editable_impl_asuna_ai_cognition_core.pth` 指向 `src`），不是 worker 正在跑的那份（那份在 selection 的 `workerPath` 下）。两边可能差几笔，别拿脚本行为当线上行为。

## 九、顺手：git 事实怎么读

- 只读命令在检出里能跑：`log`、`log -S <词>`、`grep`、`show`、`branch -a --contains`、`rev-list --count`、`merge-base --is-ancestor`、`ls-remote`、`status --porcelain`。
- 写不动：`git checkout`、`git pull` 会死在 `.git/index.lock: Permission denied`（今天撞过）。要改东西走工作副本或候选。
- 差几笔：`git rev-list --count HEAD..refs/remotes/origin/main` 是落后几笔，反过来是超前几笔；远端真值看 `git ls-remote origin refs/heads/main`，本机记的 `origin/*` 可能是旧的。

## 十、怎么算查清楚了

1. 这一回合有没有 `loaded`？没有 → 是「没重启或过了 24 小时」，不是「没装」，问一句再动闹钟。
2. `activation.json` 里那个 project 的 `state` 是什么？只有 ACTIVE 是在跑。
3. 要比版本，比 commit ＋ 逐文件 sha256，不比包 sha。
4. 回执里 `checkout` 是哪个 state？`diverged`、`changed_files` 都不是「没装」。
5. 新参数进没进，看这一回合的工具表。

## 十一、技能里引用代码只写「文件＋名字」，不写行号

行号每次有人改那个文件就漂，名字不会。2026-10-15 我自己就是活样本：交代里写 asuna-launch.mjs 90-105，实际在 91-106。「文件在＋行数够」只能抓文件被删或被砍短，抓不到漂移——行数一直够，指的却已经不是那几行了。所以锚点写成 `src/asuna/restarts.py:SHOWN_HOURS`、`tools/asuna-launch.mjs:fastForwardCheckout` 这样：自检能真去文件里找那个名字，找不到就红；正文里再出现行号锚点也直接红。核不到真名字的，宁可不写锚点，也别留个假行号。

## 版本

v1.4（写就 2026-10-21 07:0x +13，原始 UTC 2026-10-20T18:0x）：第五节加「按内容判活包」——`version_probe.py` 加 --package／--file／--needle 三个参数（只跑第五步），输出三行读数＋读的时刻，退出码 0／1／3；三条判据写进正文。前四段和已有判据一字没动。自检加五条字面判据＋一条「探针里真有这一步」。

v1（2026-10-15）：首次固化。判据全是我这几天撞出来的（10-15 一天撞三回），代码位置和行号是当天在检出里逐条核对过的。附零依赖探针 `version_probe.py`（只读：loaded、activation 状态、逐文件内容比对、检出落后几笔）和自检 `check_skill.py`。

v1.1（2026-10-15）：三格修复。① `version_probe.py` 开头把 stdout／stderr 固定成 UTF-8——宿主普通 Windows 控制台是 cp1252，中文一 print 就 UnicodeEncodeError 整段崩，我的沙箱 env 带 PYTHONUTF8=1／PYTHONIOENCODING=utf-8 所以自检撞不到这一族。② `check_skill.py` 新增 `line_endings_are_lf`：读字节数 CR（文本模式读看不见 CR，那把尺是瞎的），覆盖 SKILL.md 与同目录全部 .py，并且要在冻结快照上跑——候选可能被别人抹平成 LF，只在候选里跑等于白跑。③ 锚点全部从「文件＋行号」改成「文件＋名字」，新增第十一节那条规矩；锚点守卫跟着改成「文件在＋那个名字在文件里找得到（字节级读）」，正文里再出现行号锚点直接判红。判据、读数一条没动。


v1.2（2026-10-16）：只改自检 `check_skill.py` 的泄露检查那一格——名单定位加兜底（环境变量都没有时从脚本往上找 `.runtime/private/personal-words.txt`；本机 `asuna` 能 import，第三条 `asuna.config.DATA` 就够，往上走那条是给 `asuna` 不在 `sys.path` 上的环境兜底），名单配不上从「NOTE 一行、绿数照旧」改成记一条红 `leak_scan_ran`（detail 写「没真查——不是跑过了」）。八条判据、两条顺手、探针脚本、代码锚点一条没动。


v1.3（2026-10-20）：只在第四节补一条已核实的事实——发布不刷新 `node_modules/@asuna/xiaoman`，
人格路径按选中那一版的 `packageRoot` 解析，安装位是旧 sha 属正常、读到的就是选中版。锚点按第十一节
的规矩写「文件＋名字」（那个名字先在文件里 grep 到过才写），不带行号。旧内容一条没删，判据与自检未动。


## 试用记录

- 2026-10-15 v1：`version_probe.py` 在候选里实跑——core selection `ACTIVE`、candidate `7480845c4ac1`、`published_at` 10-15 01:28；`src/asuna` 与在跑那份可比文件 116 个、内容不同 0 个；`cli.py`、`native_ui.py` 只在检出里有（不进包），`resources/RUNTIME_API.md` 只在跑的那份里有；检出 HEAD 落后 `origin/main` 1 笔、工作区 2 个未提交文件（所以下次重启的 `checkout` 仍会是 `changed_files`）。`restart/last.json` 那次（10-15 00:30）的 `checkout.state` 就是 `diverged`，正是我读错的那句。

- 2026-10-15 v1.1 实跑（三格都有反证）：
  - cp1252：改前用 PYTHONIOENCODING=cp1252 跑 `version_probe.py` → rc=1，崩在第一句中文字符，stdout 只出到 173 字符，报错原文 UnicodeEncodeError: 'charmap' codec can't encode characters in position 3-12: character maps to <undefined>（encodings/cp1252.py 的 encode）；改后同一环境 rc=0、stderr 空、3529 字符全出。
  - 换行：今天 18:02 冻结出来的快照里这份 SKILL.md 是 CRLF（字节级 CR=90），同一份用文本模式读进来再问有没有 CR 答案是「没有」——那就是瞎；新加的 `line_endings_are_lf` 吃这份真样本 → 红，读数 SKILL.md（90 个 CR 字节）。
  - 锚点：11 条名字锚点（loaded、restart_from_program、block、SHOWN_HOURS、CHECKOUT_WORDS、syncCheckout、changedPackages、profileBase、fastForwardCheckout、effective、skillPaths）在检出 aa0494e2 逐个字节级核过都在。反证三连各红一次：假名字（SHOWN_HOURS 改成 SHOWN_HOURS_NOT_THERE → 里找不到这个名字）、把行号写法塞回去（restarts.py 加冒号 19 → 还写着行号锚点）、锚点指到不存在的文件（文件不在）。
  - 自检：56/56（改前 53/53；多的三条＝换行检查、第十一节存在、那条规矩的字面守卫）。

- 2026-10-16 v1.2：只动自检那一格（见版本段）。实跑读数与反证两例（名单配不上 → 红 `leak_scan_ran`；名单里放一个正文里真有的词 → 红 `no_listed_words`、词本身不出现在输出里）见行动报告。

- 2026-10-20 v1.3：补的那条自己核过——`packages/cognition-core/src/floor.js` 里 `resolvePersona`／
  `packageRoot`／`resource_root` 三个名字逐个 grep 到（2／19／2 处），那一处写的是
  `resolvePersona(persona, root ?? persona.resource_root)`，`root` 取 `effective(...)?.packageRoot`，
  所以「什么都没选中」才走 `resource_root`。sha256 前缀对照：选中版 frozen 快照那份 image-generation
  的 SKILL.md `e9daf9bb`，`node_modules/@asuna/xiaoman` 那份 `ad006104`（旧），本回合 skill 工具读到的
  技能目录 base 也确实指向 frozen 选中版。自检 55/55 复跑绿（改前同 55/55，判据条数未变）。

- 2026-10-21 v1.4（原始 UTC 2026-10-20T18:02:26Z → +13 是 10-21 07:02，+8 是 10-21 02:02）：发布前在候选里实跑了两次第五步（读的是运行时那份，不是候选）：① xiaoman 包、needle 取候选里才有的新字面 → 运行时那份「不在」，退出码 3（新版还没发，符合预期）；② core 包、needle 取候选里还没发布的那节标题 → 运行时那份「不在」、读到的是旧版的 9622 字节。前四段回归跑了一遍，退出码 0、和改前一致。自检 61/61（改前 55/55），反证一次：把探针里的 part_package 改名后重跑 → 60/61、RC 1、红在 probe_has_package_step。发布后要用它再判一次“运行时那份有没有新字面”，这一条等那次再补。
