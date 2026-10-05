# ADR-010：把 Asuna 做成可经 DSH 分发的插件

| 项 | 内容 |
|---|---|
| 状态 | **已批准**（owner 2026-10-05，§6 五项已定）；未实施 |
| 日期 | 2026-10-05 |
| 基线 | main `78a10fc4`（ADR-009 合并）；运行时固定 `@deepseek-ai/dsh` **0.2.0-rc.2** |
| 继承 | ADR-007（自开发地板）、ADR-008（单 Host 原生插件）、ADR-009（人格是插件、个人数据留本地） |
| 作者 | 实施者（Claude），应 owner 2026-10-05 的要求起草 |

## 一句话决定（提议）

**Asuna 以三类普通 DSH bundle 分发——核心 `@asuna/cognition-core`、通道包（如 `@asuna/napcat-qq`）、人格包——装进任意 DSH Web profile 后，只靠 DSH 自己的「添加插件」和设置页就能跑起来；仓库只是开发源，不再是运行前提。** DSH 0.2 没有 market；按 owner 的决定（§6），不发 npm registry，核心与通道包的 `.tgz` 作为本仓库（owner 账号下的公开 GitHub 仓库）的 Release 资产发布，知道链接的人用 `dsh plugin add <.tgz 的 https 地址>` 安装。

## 1. 事实：DSH 0.2 的「市场」是什么

以下来自 rc.2 源码（`639ed015`）的核对，路径相对 DSH 仓库：

- **没有 marketplace、registry 或目录服务。** 插件就是声明了 `dsh.bundle` 的普通 npm 包；`dsh plugin add <spec>` 只是在 profile 目录里跑 pnpm（`apps/cli/src/plugin.ts:70-107`）。
- **安装来源**：registry 包名加版本范围、本地路径或 `file:`/`link:`、本地或 http(s) 的 `.tgz`、git 地址（`packages/boot/plugin-manager/src/install-spec.ts:14-91`）。私有 registry 不会回落到公共源（`registry.ts:54-76`）。
- **安装流程**：先锁定 profile 并留快照；预检 `@deepseek-ai/dsh*` 对等依赖范围；`pnpm add`；装完复检，不兼容就回滚；最后把包追加到 `dsh.profile.bundles`（`operations.ts:284-536`）。DSH 不验签名，只有 pnpm lockfile 的完整性。
- **Web「插件」页**只列 profile 已装的 bundle。「Official」一栏是写死的四个实验包（`app-boot/src/profile.ts:205-218`）。「添加插件」要手填 spec，没有版本选择，也不能升级，只能卸了重装。
- **元数据**：必需 `name`、`version`、`dsh.bundle.patch`；可选 `description`、`icon`（包内 ≤256 KiB）、`locale/<lang>.json` 里的 `meta.title` 和 `meta.description`、`dsh.client`（浏览器端）。没有 permissions、kind 或 keywords 字段。
- **安装脚本默认被拦**：pnpm 11 不跑依赖的 build 脚本，除非用户把包加进 profile 的 `allowBuilds`，所以包里要放构建好的产物（`docs/user/develop/basic/publish.md:159-184`）。
- **非 JS 运行时**：DSH 不负责为插件提供或定位 Python 之类的解释器。
- **数据与凭据**：DSH 不给插件分数据目录（`$DSH_HOME` 下所有 profile 共用）。凭据库在 `<home>/.credentials.yaml`；`role('secret')` 只在表单里隐藏，值仍写进 patch 文件。
- **版本兼容**只看 `@deepseek-ai/dsh*` 对等依赖范围（含预发布）。`engines.dsh` 只是声明，不检查。个别包的豁免记在 `compatibility.json`。

## 2. 事实：Asuna 今天离不开本仓库的地方

| # | 依赖 | 位置 |
|---|---|---|
| B1 | profile 里写死仓库绝对路径：`workspace`、`configPath`、`python`，以及 `repository` 格式的 core 项目 | `tools/setup_native_profile.py:78-88` |
| B2 | Python worker 用仓库 `.venv`；依赖要手工装 | `packages/cognition-core/src/worker.js:11-15`、`NATIVE_PLUGIN.md` |
| B3 | 运行状态（activation、launch、开发基线、候选、集成目录）在仓库的 `.runtime/` 下 | `floor.js:62-64`、`integration.py` |
| B4 | 必须有外部 MongoDB（唯一状态真相） | ADR-009 原则 1 |
| B5 | 沙箱写死 `wsl -d Ubuntu … bwrap` | `floor.js:190-197`、`sandbox.py` |
| B6 | 主会话里的行动脑内联渲染靠两个**打了补丁的 DSH UI 包**（`0.2.0-rc.2-asuna.1`），不是 bundle，而且与 DSH 自带的同名；Web 安装器会拒绝 | `tools/build_dsh_inline.mjs` |
| B7 | 对等依赖钉死 `0.2.0-rc.2`，换任何 DSH 版本都会被拒 | `packages/cognition-core/package.json` |
| B8 | 安装工具只能在仓库里跑（`node_modules/.bin/dsh.cmd`、`tools/import_native_credentials.mjs`） | `setup_native_profile.py` |
| B9 | 没有 `icon` 和 `locale/`，插件卡只显示包名 | 各 `package.json` 的 `files` |
| B10 | 业务凭据在 profile 的 `cordis.patch.yml` 里是明文 | `src/index.js:36` |

## 3. 目标与非目标

**目标**
- G1：在任何一个 DSH 0.2 Web profile 里，用 Web「添加插件」或 `dsh plugin add` 装上核心、一个通道、一个人格就能用，不需要克隆仓库。
- G2：配置只经过 DSH 设置页，凭据只进 DSH 凭据库。
- G3：不改、不替换 DSH 自带的包；需要 DSH 改的地方提给上游。
- G4：人格包和通道包各自独立发布；私人人格（比如小满）**从不**发到公共源。
- G5：已安装模式下自开发仍然可用（候选、试运行、发布、回滚）。

**非目标**
- 不自建 market、目录服务或更新器。
- 不把 Python worker 改写成 JS。
- 不做多租户，不改 DSH。
- 不迁移 owner 现有的数据（沿用 ADR-009 的规则：开发期不做历史转换）。

## 4. 逐项决定（每项给选项与取舍，标出推荐）

### D1 包的划分与元数据
保持现在的三类包。核心与人格无关（ADR-009 R-5）；通道包带平台代码（ADR-009 D8-8）；人格包只放人格资源。三类都补上 `icon`、`locale/zh.json` 与 `locale/en.json` 里的 `meta.title`/`meta.description`，以及准确的 `description`。

**许可证（owner 定）：** 核心与通道包用 **GPLv3**（`"license": "GPL-3.0-only"`，仓库根放 `LICENSE`）。已核对兼容：DSH、cordis 与 JS 依赖是 MIT；内嵌的 websocket-client 与 pymongo 是 Apache-2.0；其余 Python 依赖是 BSD/MIT/MPL-2.0，均可并入 GPLv3 作品。人格包不随发布，不加许可证。

### D2 Python worker 怎么交付（B2）
- **A（推荐）**：Python 源码已经在包的 `python/` 里。再带上 `uv.lock`；插件第一次启动时，在 Asuna 数据目录里用 `uv sync --frozen` 建 venv。不靠 postinstall，正好绕开 DSH 拦安装脚本。前提是本机有 `uv`（或 Python 3.12+ 和 pip），设置页的状态行检查并说清楚缺什么。
- B：按平台发可选依赖包，带独立 Python（python-build-standalone，每个约 30–60 MB）。不需要任何前提，但包大、构建矩阵复杂。适合以后面向非开发者时再做。
- C：用 TS 重写 worker。工作量与风险都不划算，不采用。

### D3 数据目录（B1、B3）
所有运行状态（activation、开发候选与基线、集成目录、发布产物、日志）挪到 `$DSH_HOME/asuna/<profile>/`，由一个设置项 `dataRoot` 决定（默认就是这个路径）。删掉 `workspace` 与 `configPath` 两个设置；worker 的 `ASUNA_DATA_ROOT` 指向 `dataRoot`。owner 现在的 profile 继续用 `.runtime/adr008`：把 `dataRoot` 设成它即可，不搬数据。

### D4 状态存储（B4）
- **A（推荐，v1）**：继续用 MongoDB 作为外部依赖。ADR-009 的修订链、审计重放、CAS 都建在它上面。设置页填 `mongo_uri`（凭据），状态行显示连接情况；文档写清楚这是前提。
- B：内嵌存储（SQLite 或 DSH storageDomain）。要重写 Store、审计与 `$inc` 计数器，风险大，v1 不做，以后单独立 ADR 评估。

### D5 沙箱（B5）
引入 `SandboxBackend` 抽象，后端有 `wsl-bwrap`（Windows，现状）、`bwrap`（Linux）和 `none`。`none` 时，自开发、集成和行动脑的 `sandbox_run` 都关闭，并在能力清单里如实说明（ADR-009「如实告知」原则）。设置页列出探测结果。先查 DSH 0.2 有没有可复用的沙箱服务（会话事件里已经有 `sandbox/mode`），有就接 DSH 的，没有才用自己的。

### D6 配置与凭据（B10、B8）
业务凭据改存 DSH 凭据库，patch 里只留 `{"$secret": name}`。删掉旧的 `configPath` JSON 配置入口。`setup_native_profile.py` 只作为 owner 开发机的「从仓库装」工具保留，分发路径不再需要它。

### D7 行动脑内联渲染（B6）
- **A（推荐）**：把补丁里的 Session 级 Chat 片段工厂（ADR-008 2026-10-03 修订）整理成提给 DSH 上游的 PR。
- B：分发版先不带内联渲染，行动脑记录走 DSH 原生子会话（今天已经有：标题栏的 subagents 菜单和子会话页）。插件启动时检测 Chat 有没有这个工厂，没有就不挂片段。主会话里看不到行动脑的过程，但不会出错。
- 推荐**先 B 后 A**：分发不被上游节奏卡住，上游合并后自动恢复内联。
- **owner 定（2026-10-05）：补丁留在本地，由安装插件的 agent 打。** 发布物附一份写给安装 agent 的说明（`INSTALL.md`）：可选地取 DSH rc.2 源码、用 `tools/build_dsh_inline.mjs` 构建两个补丁 UI 包并装进 profile。插件照 B 做特性检测：有工厂就内联，没有就走原生子会话，不出错。

### D8 DSH 版本兼容（B7）
对等依赖从精确 `0.2.0-rc.2` 改成范围 `>=0.2.0-rc.2 <0.3.0`，前提是 CI 在每个已发布的 0.2.x 上都跑过安装探针（`tools/probe_plugin_install.mjs`）和 JS 测试。在那之前保留精确版本，并在 README 里写明。

### D9 已安装模式下的自开发（G5）
- 项目来源改成**已安装包的目录**（只读）。候选放在 `dataRoot/self-development/<project>`；发布产物仍是不可变工件，放在 `dataRoot/artifacts`。从不写 `node_modules`，这一点与现在的地板一致。
- 只有在设置里显式指定一个仓库检出目录时，才把它当作 `repository` 格式的 core 项目（owner 开发机）。
- 加一个「导出候选差异」操作，把她的改动导成 patch，方便提回上游仓库。
- 候选与来源对齐：地板发布时已经会拒绝「她改过、而来源在她的基线之后也变过」的文件（`EFFECTIVE_PROJECT_CHANGED: <文件>`），所以旧候选不会把旧代码带回去。但拒绝来得晚：她可能在旧文件上做完一整轮修改才发现。建议在 `development_files` 里直接标出这类文件（`stale: true`），让她动手前就知道要先合并。

### D10 发布工程
- 版本：semver；人格契约版本（`contract`）单独声明，核心声明支持哪些契约版本。
- 发布：依次打包、跑测试、跑个人数据扫描（`check_staged_secrets.py --personal --all` 必须为 0）、安装探针，然后把核心与通道包的 `.tgz` 挂到本仓库的 GitHub Release（按版本打 tag）。不发 npm。
- 人格包不作为发布资产；它在仓库里的现状照旧（owner 2026-10-05：仓库与历史保持公开现状）。

### D11 隐私
公开包里只能有占位符与合成夹具（ADR-009 R-6、R-7）。发布前的扫描结果是硬门槛。示例配置只用文档保留地址与号段。

## 5. 分阶段计划（提议）

| 阶段 | 内容 | 验收 |
|---|---|---|
| M0 | D9 的 `stale` 标记；补 `icon`/`locale` | 她改过、来源也变过的文件在列表里就标出来；插件卡显示名称与图标 |
| M1 | D3 数据目录、D6 凭据进 DSH 凭据库、删掉 `workspace`/`configPath` | 全新 profile 用 `dsh plugin add <tgz>` 装上，只经设置页配置就能启动；owner 现有 profile 不受影响 |
| M2 | D2-A：首启用 uv 建 venv | 没有仓库也没有 `.venv` 的机器上，首次启动自动建好环境，状态行说清进度和缺什么 |
| M3 | D5 沙箱抽象（先 `wsl-bwrap` 和 `none`） | `none` 时相关能力关闭并如实说明；`wsl-bwrap` 行为与现在一致 |
| M4 | D7-B 内联渲染特性检测；向 DSH 上游提 D7-A 的 PR | 没有补丁 UI 包时页面正常，行动脑走原生子会话 |
| M5 | D10 发布流水线：GitHub Release 挂核心与通道 `.tgz`；`INSTALL.md` 给安装 agent | 在干净机器上用 Release 链接安装成功 |

每个阶段都在**隔离的合成 profile** 上验收（AGENTS.md），owner 的真实 profile 最后切换。

## 6. owner 的决定（2026-10-05）

1. **分发：** 不发 npm（公共或私有 registry 都不发）；用本仓库、owner 的账号发布——核心与通道 `.tgz` 挂 GitHub Release，知道链接的人可以装。仓库本身是公开的，owner 选择保持现状（人格包和历史都不动）。
2. **Python：** D2-A，首启用 `uv sync --frozen` 在数据目录里建 venv。
3. **状态存储：** v1 继续要求 MongoDB。
4. **内联渲染：** 补丁留在本地，由安装插件的 agent 打（D7）；插件做特性检测，没有补丁就走原生子会话。
5. **许可证：** GPLv3（兼容性已核对，见 D1）。

## 7. 风险

- DSH 0.2 还在预发布阶段，插件 API 可能变；版本范围要靠 CI 守住。
- 首启建 venv 依赖网络和 PyPI（或镜像）；离线环境需要另给 wheel 包。
- 不把 Mongo 做成可选，会挡住只想试一试的用户；这是 v1 有意接受的代价。
- 上游可能不接受 Chat 片段工厂；D7-B 保证没有它也能用。

## 8. 相关但独立的提议（不在本 ADR 范围内）

（已被 ADR-011 取代：委托如今就是角色脑的工具调用。下面保留原文。）

角色脑决定「不说话」（委托且不先说，或沉默）时，那一轮的最后一步是 DECIDE 的 JSON，DSH 会把它当成这一轮的回答显示出来。DSH 原生的做法是把委托做成**工具调用**：参数由 schema 校验，失败作为工具错误回给模型，这也就是 answers.py 想做的那种如实回告。这样角色脑与行动脑就是 DSH 原生的父 agent 与子 agent 关系，渲染自然一致。这是阶段协议的设计变更，方案见 [PROPOSAL-DECISION-DISPLAY.md](PROPOSAL-DECISION-DISPLAY.md)，等 owner 决定。

## 9. 实施记录

### M0（2026-10-05，`b9f19c27`、`f3bb6c25`）
插件卡片带标题、说明和图标（`package.json` 的 `icon`、`locale/<lang>.json`）；开发候选里源已移动的文件标为 stale（D9）。

### M1（2026-10-05，`01d6e3e1` 起）
- **数据目录（D3）**：地板的 `dataRoot`（默认 `$DSH_HOME/asuna/<profile>/`）是一个 profile 写东西的唯一地方：activation、候选与基线、工作目录、通道授权、证据；worker 在其中运行，`ASUNA_DATA_ROOT` 指向它。候选（`work/`）与基线永远在同一个数据目录里，避免「候选找不到基线 → 发布把文件当删除」。D9 写的 `dataRoot/self-development` 实际落在 `dataRoot/work/self-development`，与 worker 的通道工作目录同在 `work/` 下。owner 的 profile 按 owner 选择设为 `<checkout>/.runtime`、地板状态在 `adr008`，什么都没搬，Mongo 里存的绝对路径照样有效。
- **删掉的设置**：`workspace`、`configPath`、部署里的 `dsh_home`、`workdir`、`chat.workspace`（本地聊天固定在 `<data>/work/local-user`）。worker 只读 profile 的设置，不再读 `config/local.json`；核心候选发布前的 boot probe 改为由运行中的 Core 用 `validate_settings` 对现有库校验。
- **锁**：守一个数据库或一个端点的锁放在每用户一处（`ASUNA_LOCK_ROOT`，默认 `<temp>/asuna-locks`），宿主锁按库的地址与库名取键，两个 profile 指同一个库仍然互斥；文件锁在 POSIX 上也能用。
- **凭据（D6）**：设置里只存引用 `{"$secret":"ASUNA_…"}`（环境变量式名字），值只在 DSH 凭据库。键名含 `mongo_uri`、`api_key`、`token`、`password`、`secret` 的都必须是引用（JS 与 Python 同一条子串规则）。Core 启动或校验时解析，交给 worker 用一次；设置页用 DSH 自带的只写控件直接写凭据库，只显示「已配置／未配置」。setup 工具把旧的明文 `secrets` 与按路径命名的引用一次性搬过去；空值视为没有凭据，不建引用。
- **全新 profile**：没有设置时状态是「unconfigured」而不是失败；地板没有开发项目时不给集成目录（不再在启动时报 `DEVELOPMENT_PROJECT_NOT_AUTHORIZED`）；设置页为缺的必填部分预填起始值；本地聊天的 scene/person/persona 有默认值；输出上限留空时用模型自己的默认。
- **验收**：`tools/probe_fresh_profile.mjs` 建一个空的 DSH home，`dsh plugin add` 核心、合成人格与 QQ 通道三个 tgz，只准备 DSH 自己的东西（不会被调用的合成模型服务、凭据库里的库地址）；之后只经设置页配置，Apply 后显示「Business worker: ready · Mongo: connected」，数据全部落在 `$DSH_HOME/asuna/fresh/`。合成库与临时 home 事后删除。owner 的现网 profile 每一步都用真实消息验证过。
- **遗留**：Python 解释器仍是一个路径设置（M2 换成 uv）；嵌入端点仍要求本机/内网地址。

### M2（2026-10-05，`3d46450c`）
- 包里带 `python/requirements.lock`：worker 依赖闭包的精确版本，由 `tools/pack_plugins.py` 从测过的环境冻结（保留平台标记）。D2-A 原写 `uv.lock`；改成锁定的 requirements 文件，uv 与 pip 都能用，打包的机器也不必装 uv。
- `python` 设置留空时，Core 首次启动在 `<data>/python` 里按锁文件建 venv：PATH 上有 uv 就用 uv（uv 还能自己取 Python），否则找 Python 3.12+ 用 pip；锁不变就复用。状态行显示「preparing · Building the Python environment with …」，找不到解释器时报 `PYTHON_NOT_FOUND`。地板检查候选也用同一个解释器。`python` 设置仍然优先（开发用的 checkout）。
- **验收**：全新 profile、Python 留空，保存时建好环境（这台机器没有 uv，走 `py -3.12` + pip），Apply 后「Business worker: ready · Mongo: connected」，worker 进程跑在数据目录的环境里。合成库与临时 home 事后删除。

### M3（2026-10-05）
- `sandbox_backend.py`：每个 worker 选一次后端，`sandbox_run`、受管集成进程、人格作业都经它取命令前缀与路径映射（原来三处各自写死 `wsl -d Ubuntu`）。设置 `deployment.sandbox`：`backend` 为 `auto`（默认）／`wsl-bwrap`／`none`，`wsl_distro` 默认 `Ubuntu`。`auto` 在 WSL 发行版里能找到 bubblewrap、python3、prlimit 时取 `wsl-bwrap`，否则取 `none` 并记下原因；明确写 `wsl-bwrap` 而探测不通时直接报 `SANDBOX_UNAVAILABLE`。
- `none` 时：`sandbox_run` 不进行动脑的能力清单，集成授权与自开发授权都不给，宿主不起受管集成进程，人格作业返回「没有沙箱」；她的能力清单里写明这些交不出去（只说能力，不说机器怎么配）。设置卡片状态行显示后端或没有的原因。
- Linux 的 `bwrap` 后端留到下一步（同一组命令去掉 `wsl` 前缀、路径不映射）。

### M4（2026-10-05，`fdeb2de6`）
- 客户端在渲染时查 slot 注册表里有没有 `factory:conversation.chat.content`（本地补丁 UI 包提供的 Chat 片段工厂）：有就在主会话里内联行动脑的记录；没有就让工作行打开 DSH 自己的子会话视图（「在侧栏打开完整过程」），不报错。
- 仓库根新增 `INSTALL.md`，写给安装 agent：前提、用 `dsh plugin add` 装 Release 的 tgz、在设置卡片上配置、可选地本地构建内联视图的两个补丁包。
- **验收**：全新 profile 用 DSH 自带 UI（没有补丁包），真实的演示人格委托一件 `sandbox_run` 的事，结果 1024 回来；工作行展开是「在侧栏打开完整过程」，点开是 DSH 原生子会话，页面无错误。合成库与临时 home 事后删除。
- 这次验收顺带发现：首启建的环境里没有 `tzdata`，Windows 上 zoneinfo 没有时区库，她的第一轮失败。worker 现在声明并锁定 `tzdata`。
- D7-A（向 DSH 上游提片段工厂的 PR）不在本仓库的权限内，留给 owner 决定何时提。
