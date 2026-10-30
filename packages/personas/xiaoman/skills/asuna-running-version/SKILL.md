---
name: asuna-running-version
description: 我想知道「现在跑的是哪一版」「我改的那个东西进没进这一回合」「要不要为这个重排闹钟」时读这一份。判据：先看这一回合 restart_from_program.loaded（commit＋各包 sha＋selections）；缺 loaded 那一格不等于没装，先问一句；比内容别只比包 sha（重启会重新打包、号会变）；主仓合了不等于我这边在跑，跑的是发布过的快照，不 publish 重启也只装程序那半边；查 .runtime/adr008/activation.json 的 state／candidate／published_at／changed_files；回执说「本机检出有 origin/main 没有的提交」＝本机比远端新，不是没装；启动器遇脏工作区是跳过快进不报错，本机可能长期落后一格，这不是故障；新参数进没进看这一回合的工具表。附零依赖探针 version_probe.py 与自检 check_skill.py。
scene_kinds: [home, group]
---

# asuna-running-version

答案不在记忆里，在这几个地方。下面是核对过的位置和读法。

## 一、先看这一回合的 `restart_from_program.loaded`

有 `loaded` 那一格，就是监工（启动器）在这次重启起来时记下的实况：

- `commit`：本机检出的提交（短号）
- `packages`：每个包安装时记的 sha（前 12 位）
- `selections`：每个 project 的 `state` 和 `candidate`（被退回过的还带 `reverted_from`）

写它的是 `tools/asuna-supervisor.mjs:loaded`（读 `activation.json` 和 `launch.json`），原样递给我的是 `src/asuna/restarts.py:restart_from_program`。

## 二、缺 `loaded` 那一格不等于「没装」

这一整块只在「有重启记录、而且起来不到 24 小时」时才出现：那个 24 是 `src/asuna/restarts.py:SHOWN_HOURS`，判断在 `src/asuna/restarts.py:block`（没有记录或太旧就整块不给）。

所以缺这一格只说明「最近没重启，或者那次已经过了 24 小时」。**先问一句，别默认没装就去重排闹钟**。

## 三、比内容，别只比包 sha

包 sha 是打包产物的号，不是内容的号。每次启动都会重新 pack 再拿 sha 跟上次装的比（`tools/asuna-launch.mjs:syncCheckout`，比的那一步是 `tools/asuna-launch.mjs:changedPackages`），同样的内容重新打包也可能给新号。

要比就比两样：代码版本（commit）＋文件内容（逐文件 sha256）。

现成的比法（本技能目录的 `version_probe.py` 就是这么算的）：从 `activation.json` 拿那个 project selection 的 `workerPath`／`packageRoot`，跟检出的源码逐文件比 sha256。比的时候，`cli.py`、`native_ui.py` 只在检出里有（不进包），`resources/RUNTIME_API.md` 只在跑的那份里有，这三个不算差异。

## 四、「主仓合了」不等于「我这边在跑」

跑的是我发布过的快照：`packages/cognition-core/src/floor.js:effective` 按 `activation.json` 里的 selection 取 `packageRoot`（人格、通道包）和 `workerPath`（worker 的 Python）；技能目录也走同一份 selection，见 `packages/cognition-core/src/floor.js:skillPaths`。

**发布不刷新 `node_modules/@asuna/xiaoman`，也不需要刷**：人格路径按**选中那一版的 `packageRoot`** 解析——`packages/cognition-core/src/floor.js:resolvePersona`
收的那个 root 就是 `effective` 给的 `packageRoot`，只有什么都没选中时才退回 `resource_root`。
`node_modules/@asuna/xiaoman` 只是安装时那一份，**只有什么都没选中时才用**。所以安装位是旧 sha 是
正常的，**读到的就是选中版**。

一个发布有三种状态，别混：

- `HOST_RESTART_REQUIRED`：还没装，等下次启动由启动器装
- `APPLIED`：装了，等 worker 下次起来才用
- `ACTIVE`：真在跑（worker 起来后自己写的）

所以「published」不是「running」，running 是 ACTIVE。适配器只从发布过的快照跑；东西改在候选里没发布，重启也替我上不了线，只会把检出里 pack 出来的那半边装上。

## 五、查 `activation.json`

- 位置：本机项目检出下的 `.runtime/adr008/activation.json`（别的 profile 在 `.runtime/adr008/profiles/<profile>/`，见 `tools/asuna-launch.mjs:profileBase`）。
- 每个 project 看：`state`、`candidate`、`published_at`、`changed_files`、`previous`、`boot_probe`。
- 另有一格 `active`：上一次真跑起来的那份。selection 和 active 不一样，就说明发布了还没跑。

### 按内容判活包（version_probe.py 的第五步）

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

判据（读数时别读错）：

- `loaded.packages` 的包名只来自 `launch.json` 的 `installed`，digest 由选择覆盖，所以它报的是**在跑的那一档**；
  在那之前那一版报的是「该装的那档」，不是在跑的那档。
  ⚠ 那半句「选择覆盖 digest」只在测试夹具里证实过，我真文件上两边 sha 本来就相同（＝空转），**不算现场验过**。
  这一格不许读成「监工块能证明在跑哪版」，在不在跑仍然只认两样——
  `activation.json` 的 `active.<项目>.sha256` ＋ **运行时那个包里那份文件的 sha／内容**；
  `loaded.packages`、`loaded.commit`、监工回执那句状态话**都不算凭据**。
  另：`loaded.commit` 是**启动那一刻的 HEAD**，不是修代码那个提交——别拿修它的提交号去对号。
- 被退回的重启不进 `audit_events`，只落 `activation.json`（`reverted_at`、`reverted_from` 都在 `previous` 里）；
  查退回不要去审计里找。
- `installed_at` 不在 `active.*` 块里，只在 `previous` 里；判「刚装的」用 `activated_at` 加包目录 mtime。
- 过期选择的形状要自己算：`selections` 是整个抄 `activation.json` 的 `projects`（我真文件里 `dsh-peer`
  还挂着 `ACTIVE`），而 `packages` 里没有那个键 ⇒ **键差集＝「选择说 ACTIVE、包不在」**；代码不算这个差集
  也不标它，`loaded()` 从不读 `packageRoot`。

`activation.json` 里的时刻原始值是 UTC 的 ISO 串，结构里 `packageRoot` 下的路径按包内相对路径写 --file。

## 六、回执说「本机检出有 origin/main 没有的提交」＝本机比远端新

那是 `checkout.state = diverged`：本机有远端没有的提交，快进不了，这次装的是磁盘上原来的检出。**这不是「没装」**。

全套状态和它们的原话在 `src/asuna/restarts.py:CHECKOUT_WORDS`：`fast_forwarded`、`up_to_date`、`fetch_failed`、`not_main`、`changed_files`、`diverged`、`fast_forward_failed`。

## 七、脏工作区会让本机长期落后一格，这不是故障

`tools/asuna-launch.mjs:fastForwardCheckout`：先 fetch，只有「在 main 分支、跟踪文件没有改动、并且确实落后 origin/main」才快进；有没提交的改动就**跳过**（`changed_files`），不覆盖也不报错。它从不 merge、rebase、reset。

所以本机检出可能长期比 origin/main 落后一格。工作区有没提交的改动时，下次重启这句还会是 `changed_files`。这不是坏了，是它不敢动我的东西。

## 八、新参数进没进，看这一回合的工具表

判断某个新参数、新枚举进没进这一回合，看这一回合真收到的工具表，比看文档准——文档会滞后，工具表是这一回合的 schema。

一个坑：我脚本里 `import asuna` 拿到的是**本机检出 `src` 那一份**（`.venv` 里 `_editable_impl_asuna_ai_cognition_core.pth` 指向 `src`），不是 worker 正在跑的那份（那份在 selection 的 `workerPath` 下）。两边可能差几笔，别拿脚本行为当线上行为。

## 九、顺手：git 事实怎么读

- 只读命令在检出里能跑：`log`、`log -S <词>`、`grep`、`show`、`branch -a --contains`、`rev-list --count`、`merge-base --is-ancestor`、`ls-remote`、`status --porcelain`。
- 写不动：`git checkout`、`git pull` 会死在 `.git/index.lock: Permission denied`。要改东西走工作副本或候选。
- 差几笔：`git rev-list --count HEAD..refs/remotes/origin/main` 是落后几笔，反过来是超前几笔；远端真值看 `git ls-remote origin refs/heads/main`，本机记的 `origin/*` 可能是旧的。

## 十、怎么算查清楚了

1. 这一回合有没有 `loaded`？没有 → 是「没重启或过了 24 小时」，不是「没装」，问一句再动闹钟。
2. `activation.json` 里那个 project 的 `state` 是什么？只有 ACTIVE 是在跑。
3. 要比版本，比 commit ＋ 逐文件 sha256，不比包 sha。
4. 回执里 `checkout` 是哪个 state？`diverged`、`changed_files` 都不是「没装」。
5. 新参数进没进，看这一回合的工具表。

## 十一、技能里引用代码只写「文件＋名字」，不写行号

行号每次有人改那个文件就漂，名字不会。「文件在＋行数够」只能抓文件被删或被砍短，抓不到漂移——行数一直够，指的却已经不是那几行了。所以锚点写成 `src/asuna/restarts.py:SHOWN_HOURS`、`tools/asuna-launch.mjs:fastForwardCheckout` 这样：自检能真去文件里找那个名字，找不到就红；正文里再出现行号锚点也直接红。核不到真名字的，宁可不写锚点，也别留个假行号。
