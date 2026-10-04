# ADR-010：把 Asuna 做成可经 DSH 分发的插件

| 项 | 内容 |
|---|---|
| 状态 | **提议**，待 owner 审阅；未实施 |
| 日期 | 2026-10-05 |
| 基线 | main `78a10fc4`（ADR-009 合并）；运行时固定 `@deepseek-ai/dsh` **0.2.0-rc.2** |
| 继承 | ADR-007（自开发地板）、ADR-008（单 Host 原生插件）、ADR-009（人格是插件、个人数据留本地） |
| 作者 | 实施者（Claude），应 owner 2026-10-05 的要求起草 |

## 一句话决定（提议）

**Asuna 以三类普通 DSH bundle 分发——核心 `@asuna/cognition-core`、通道包（如 `@asuna/napcat-qq`）、人格包——装进任意 DSH Web profile 后，只靠 DSH 自己的「添加插件」和设置页就能跑起来；仓库只是开发源，不再是运行前提。** DSH 0.2 没有 market，「上架」就是发布到 npm registry（公开或私有）并满足 DSH 的 bundle 元数据。

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

### D8 DSH 版本兼容（B7）
对等依赖从精确 `0.2.0-rc.2` 改成范围 `>=0.2.0-rc.2 <0.3.0`，前提是 CI 在每个已发布的 0.2.x 上都跑过安装探针（`tools/probe_plugin_install.mjs`）和 JS 测试。在那之前保留精确版本，并在 README 里写明。

### D9 已安装模式下的自开发（G5）
- 项目来源改成**已安装包的目录**（只读）。候选放在 `dataRoot/self-development/<project>`；发布产物仍是不可变工件，放在 `dataRoot/artifacts`。从不写 `node_modules`，这一点与现在的地板一致。
- 只有在设置里显式指定一个仓库检出目录时，才把它当作 `repository` 格式的 core 项目（owner 开发机）。
- 加一个「导出候选差异」操作，把她的改动导成 patch，方便提回上游仓库。
- 候选与来源对齐：今晚就碰到过，候选里留着她几天前改的旧文件，发布会把旧代码带回去（STATUS 后续项）。地板在发布前要检查：她改过的文件，如果对应的来源从基线之后也变过，就拒绝发布并列出这些文件，让她先合并。这一条与分发无关，现在就该做。

### D10 发布工程
- 版本：semver；人格契约版本（`contract`）单独声明，核心声明支持哪些契约版本。
- 发布：CI 依次打包、跑测试、跑个人数据扫描（`check_staged_secrets.py --personal --all` 必须为 0）、安装探针，然后 `npm publish --provenance`。
- 公开还是私有由 owner 定（见第 6 节）。人格包默认只发私有源，或只给本地 `.tgz`。

### D11 隐私
公开包里只能有占位符与合成夹具（ADR-009 R-6、R-7）。发布前的扫描结果是硬门槛。示例配置只用文档保留地址与号段。

## 5. 分阶段计划（提议）

| 阶段 | 内容 | 验收 |
|---|---|---|
| M0 | D9 的「候选与来源对齐」检查；补 `icon`/`locale` | 旧候选不能把旧代码发布出去；插件卡显示名称与图标 |
| M1 | D3 数据目录、D6 凭据进 DSH 凭据库、删掉 `workspace`/`configPath` | 全新 profile 用 `dsh plugin add <tgz>` 装上，只经设置页配置就能启动；owner 现有 profile 不受影响 |
| M2 | D2-A：首启用 uv 建 venv | 没有仓库也没有 `.venv` 的机器上，首次启动自动建好环境，状态行说清进度和缺什么 |
| M3 | D5 沙箱抽象（先 `wsl-bwrap` 和 `none`） | `none` 时相关能力关闭并如实说明；`wsl-bwrap` 行为与现在一致 |
| M4 | D7-B 内联渲染特性检测；向 DSH 上游提 D7-A 的 PR | 没有补丁 UI 包时页面正常，行动脑走原生子会话 |
| M5 | D10 发布流水线；按 owner 的选择发到私有或公共 registry | 在干净机器上照 README 安装成功 |

每个阶段都在**隔离的合成 profile** 上验收（AGENTS.md），owner 的真实 profile 最后切换。

## 6. 需要 owner 决定的事

1. 核心和通道包发到**公共 npm**，还是**私有 registry**？（人格包默认私有。）
2. Python 交付先用 **D2-A（要求本机有 uv）**，还是直接做 **D2-B（自带解释器）**？
3. v1 继续**要求 MongoDB**（推荐），还是现在就评估内嵌存储？
4. 内联渲染走 **先 B 后 A**（推荐），还是只等上游？
5. 开源许可证。

## 7. 风险

- DSH 0.2 还在预发布阶段，插件 API 可能变；版本范围要靠 CI 守住。
- 首启建 venv 依赖网络和 PyPI（或镜像）；离线环境需要另给 wheel 包。
- 不把 Mongo 做成可选，会挡住只想试一试的用户；这是 v1 有意接受的代价。
- 上游可能不接受 Chat 片段工厂；D7-B 保证没有它也能用。

## 8. 相关但独立的提议（不在本 ADR 范围内）

角色脑决定「不说话」（委托且不先说，或沉默）时，那一轮的最后一步是 DECIDE 的 JSON，DSH 会把它当成这一轮的回答显示出来。DSH 原生的做法是把委托做成**工具调用**：参数由 schema 校验，失败作为工具错误回给模型，这也就是 answers.py 想做的那种如实回告。这样角色脑与行动脑就是 DSH 原生的父 agent 与子 agent 关系，渲染自然一致。这是阶段协议的设计变更，单独提方案，等 owner 决定。
