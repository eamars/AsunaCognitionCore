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

写它的是 `tools/asuna-supervisor.mjs:190-203`（`loaded()`，读 `activation.json` 和 `launch.json`），原样递给我的是 `src/asuna/restarts.py:254`。

## 二、缺 `loaded` 那一格不等于「没装」

这一整块只在「有重启记录、而且起来不到 24 小时」时才出现：`src/asuna/restarts.py:19`（`SHOWN_HOURS = 24`）、`:244-245`（没有记录或太旧就整块不给）。

所以缺这一格只说明「最近没重启，或者那次已经过了 24 小时」。**先问一句，别默认没装就去重排闹钟**——10-15 上午我这么白改过一次期。

## 三、比内容，别只比包 sha

包 sha 是打包产物的号，不是内容的号。每次启动都会重新 pack 再拿 sha 跟上次装的比（`tools/asuna-launch.mjs:121-141`），同样的内容重新打包也可能给新号。

要比就比两样：代码版本（commit）＋文件内容（逐文件 sha256）。

现成的比法（本技能目录的 `version_probe.py` 就是这么算的）：从 `activation.json` 拿那个 project selection 的 `workerPath`／`packageRoot`，跟检出的源码逐文件比 sha256。今天这一版实测：`src/asuna` 与在跑那份可比文件 116 个、内容不同 0 个；`cli.py`、`native_ui.py` 只在检出里有（不进包），`resources/RUNTIME_API.md` 只在跑的那份里有。

## 四、「主仓合了」不等于「我这边在跑」

跑的是我发布过的快照：`packages/cognition-core/src/floor.js:183-209` 按 `activation.json` 里的 selection 取 `packageRoot`（人格、通道包）和 `workerPath`（worker 的 Python）。

一个发布有三种状态，别混：

- `HOST_RESTART_REQUIRED`：还没装，等下次启动由启动器装
- `APPLIED`：装了，等 worker 下次起来才用
- `ACTIVE`：真在跑（worker 起来后自己写的）

所以「published」不是「running」，running 是 ACTIVE。适配器只从发布过的快照跑；东西改在候选里没发布，重启也替我上不了线，只会把检出里 pack 出来的那半边装上。

## 五、查 `activation.json`

- 位置：本机项目检出下的 `.runtime/adr008/activation.json`（别的 profile 在 `.runtime/adr008/profiles/<profile>/`，`tools/asuna-launch.mjs:166-169`）。
- 每个 project 看：`state`、`candidate`、`published_at`、`changed_files`、`previous`、`boot_probe`。
- 另有一格 `active`：上一次真跑起来的那份。selection 和 active 不一样，就说明发布了还没跑。

## 六、回执说「本机检出有 origin/main 没有的提交」＝本机比远端新

那是 `checkout.state = diverged`：本机有远端没有的提交，快进不了，这次装的是磁盘上原来的检出。**这不是「没装」**。10-15 我把这句读成没装，判错了一次。

全套状态和它们的原话在 `src/asuna/restarts.py:27-35`：`fast_forwarded`、`up_to_date`、`fetch_failed`、`not_main`、`changed_files`、`diverged`、`fast_forward_failed`。

## 七、脏工作区会让本机长期落后一格，这不是故障

`tools/asuna-launch.mjs:91-106` 的 `fastForwardCheckout`：先 fetch，只有「在 main 分支、跟踪文件没有改动、并且确实落后 origin/main」才快进；有没提交的改动就**跳过**（`changed_files`，`:96-97`），不覆盖也不报错。它从不 merge、rebase、reset。

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

## 版本

v1（2026-10-15）：首次固化。判据全是我这几天撞出来的（10-15 一天撞三回），代码位置和行号是当天在检出里逐条核对过的。附零依赖探针 `version_probe.py`（只读：loaded、activation 状态、逐文件内容比对、检出落后几笔）和自检 `check_skill.py`。

## 试用记录

- 2026-10-15 v1：`version_probe.py` 在候选里实跑——core selection `ACTIVE`、candidate `7480845c4ac1`、`published_at` 10-15 01:28；`src/asuna` 与在跑那份可比文件 116 个、内容不同 0 个；`cli.py`、`native_ui.py` 只在检出里有（不进包），`resources/RUNTIME_API.md` 只在跑的那份里有；检出 HEAD 落后 `origin/main` 1 笔、工作区 2 个未提交文件（所以下次重启的 `checkout` 仍会是 `changed_files`）。`restart/last.json` 那次（10-15 00:30）的 `checkout.state` 就是 `diverged`，正是我读错的那句。
