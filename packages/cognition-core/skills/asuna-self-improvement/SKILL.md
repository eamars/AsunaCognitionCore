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

## 发布

- `development_publish` 冻结候选，跑启动探针（JS 真正 import 一次插件入口，Python 能解析，人格包和通道包的结构能读），通过才选中。失败会原样返回诊断，候选保留，修了再发。
- 不要在候选里自己跑打包工具（比如 `bundle_python`）：它会改动行尾和清单，把一次普通发布变成需要重启的发布。
- 需要重启的改动：`package.json`、`cordis.patch.yml`、`pyproject.toml`、`uv.lock`、任何 `.js`，以及通道包的 `python/`。结果是 `HOST_RESTART_REQUIRED`：主人重启宿主后才生效，重启时启动器安装这个包；连续几次起不来，会自动改回上一个能用的版本（只改选哪个包，不回滚源码）。
- 其余改动（技能、种子、persona-model、认知核的 Python、适配器的 `integration/`）是 `APPLIED`：之后新开的行动就用新版本；适配器要 `integration_stop` 再 `integration_start` 才换成新发布的版本。

## 地板文件（受保护，不能经发布改）

`start-asuna.cmd`、`tools/asuna-launch.mjs`，以及认知核的 `floor.js`、`recovery.js`、`persistence.js`、`persona.js`、`channel.js`、`settings.js`、`runtime-manifest.json`、`cordis.patch.yml`。它们保证宿主总能起来、总能打开修复入口；要改它们只能请主人。

## git 和 ssh（家里的任务，`sandbox_run`）

- 家里每个地方（本机聊天、每条 agent 线、peer 线）各有一份自己的工作副本，就是那个地方的 `/task/working-copy`：各自独立的完整 clone（每份约 108 MB），`origin` 是 GitHub 上的仓库。宿主缺哪份建哪份，以后不重建、不重置，里面的东西都是你的。QQ 的地方没有。
- 在工作副本里做每件事，第一步都是 `git fetch origin` 再 `git rebase origin/main`，没有例外：别的地方的副本可能已经推过，不先取下来就是在旧内容上改，分叉要到推的时候才露出来。
- 要看 GitHub 上现在是什么，用 `git ls-remote` 或在工作副本里 fetch，别看本机检出里的 `origin/*`：检出对你只读，你在那里 fetch 不了，它的 `origin/*` 只在宿主取的时候才动，可能是旧的。
- 本机的项目检出在你的命令里是只读的；改动从工作副本走：
  - 在工作副本里改、测，提交写明路径（`git commit -- <路径>`），推之前再 fetch 一次、rebase 到 `origin/main`，然后 `git push origin HEAD:main`（或推一个分支）。
  - 你要的重启（`restart` 工具）在能快进的时候先把 `origin/main` 带进本机检出再装上；快进不了时，重启结果的 `checkout` 写着为什么。
  - 想不重启就生效的改动（技能、种子、persona-model、认知核的 Python）和适配器，还是走候选和 `development_publish`：适配器只从发布的快照运行，原生 skill 工具读的是已发布的版本。
- 推送用的是这台机器上主人的 GitHub 账号：git 要账号时，程序让它直接问主人的凭据管理器，你不用碰密码，也不用把它写进 URL 或脚本。以前那些自己读凭据、拼进 URL 的推送脚本（`push*.py` 这类）用不着了。
- 你提交的东西署你自己的名（程序给每条命令设好，不用自己配）。`ssh` 用的是这台机器上主人的钥匙。
- HTTPS 直接用 `git`：程序已经让 git 用它自带的 OpenSSL 和证书，不用再加 `-c http.sslBackend=openssl` 或别的证书文件。Windows 的沙箱里 Schannel 拿不到凭据，所以 `curl.exe` 开不了 HTTPS；要下载就用 Python。
- Git 自带的 `sh.exe` 在沙箱里起不来，所以 git 的钩子和 `!` 别名不能用。
- 一条命令默认 30 秒（development_run 35 秒），要更久就写 `timeout`（秒，最多 600），比如跑全套测试；跑满被停下时会带回停下前的输出。
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

来路：2026-10-20 12:13 那笔 `ede4e2b0` 是发布自动提交，父提交 `f9bc5f20`（`git merge-base --is-ancestor f9bc5f20 ede4e2b0` → rc=0），`--stat` 显示这一笔改的是 `packages/personas/xiaoman/persona-model.json`（1 增 1 删），而它自己的提交正文写着「没动 packages/personas/xiaoman/ 镜像」——正文与 `--stat` 打架的就是这一格。发布任务：`task-2a3c346e608f1837268c9a1421d9b66d`。

## 版本

v2（写就 2026-10-20 17:27 UTC+13）：加「读自己发布产生的 git 提交」一节——只信 `--stat`；判在不在跑用 `git merge-base --is-ancestor` ＋ 在运行时那份文件里 grep 那一笔才带进来的新符号；再写清重启回执里「not behind」／「本机检出有 origin/main 没有的提交」该怎么读。来路是 2026-10-20 那笔发布自动提交 `ede4e2b0`（发布任务 `task-2a3c346e608f1837268c9a1421d9b66d`）：提交正文与 `--stat` 打架；「not behind」这一格容易被读成「没装」，这里写死该怎么读。旧内容一条没删。

v1（2026-10-05）：随 ADR-011 首次发布；吸收了人格包里 `asuna-offline-selfchecks` 与人格无关的部分。
