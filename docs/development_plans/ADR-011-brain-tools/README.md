# ADR-011：两个脑都用原生工具调用

| 项 | 内容 |
|---|---|
| 状态 | **提议**，待 owner 回答第 12 节的问题；未实施 |
| 日期 | 2026-10-05 |
| 分支 | `claude/adr-011-brain-tools`（自 main `985171f2`） |
| 基线 | 运行时固定 `@deepseek-ai/dsh` **0.2.0-rc.2** |
| 继承 | ADR-007（自开发地板）、ADR-008（单 Host 原生插件）、ADR-009（人格驻留）、ADR-010 的 `PROPOSAL-DECISION-DISPLAY.md`（本 ADR 取代它） |
| 作者 | 实施者（Claude），应 owner 2026-10-05 的要求起草 |

## 一句话决定（提议）

**角色脑改成一个普通的 DSH 回合：思考是原生思考，动作是少量 Asuna 工具，最后一段正文就是她说出口的话。** 委托行动脑沿用 DSH 的 `subagent` 工具合约：行动脑是角色脑的子代理，原生的工具行、子代理列表、侧栏子会话和「子任务状态更新」卡片都直接复用。逐段文本加 JSON 的阶段协议（MONOLOGUE → DECIDE → WRITE/SELF/REFLECT → SPEAK）整体退役。两个脑的压缩阈值统一为上下文窗口的 85%。

## 0. owner 的要求（2026-10-05）

1. 不再把 JSON 当正文显示。
2. 两个脑的输出要清楚：角色脑已经把思考和工具折叠好了，行动脑却默认把一切摊开，看起来不自然。
3. 用工具调用在两个脑之间传话，类似子代理用 `send_message` 和上级通信。当初「角色脑不调用工具」是为了迁就工具调用能力弱的模型，现在可以放弃这个前提。
4. 行动脑可以当作子代理。
5. 详细审查两个脑的工具：不重叠，边界清楚，尤其是任务如何从角色脑交给行动脑。
6. 保持她的自主，给自我改进留空间：两个脑都要能发起「改自己」，有足够的指南、最少的边界，以及保证系统能启动的底线（沿用此前的 ADR）。
7. 压缩阈值两个脑统一为 85%。

## 1. 现状（2026-10-05 核对，引用见各节）

**角色脑完全没有工具。** 有四处在拦：
- `attachPreset(scope,'character')` 清空工具（`packages/cognition-core/src/index.js:442`）；
- 组装请求时只给行动脑带工具（`index.js:493`）；
- 出现工具调用就判为异常（`src/asuna/answers.py:34`、`coordinator.py:202`）；
- worker 拒绝非行动脑会话的工具调用（`native_worker.py:683-697`）。

**一条消息要走一串文本阶段**，都在同一个原生回合里一段段注入（`coordinator.py:305-578`）：

| 阶段 | 产出 |
|---|---|
| MONOLOGUE | 自由文本，存成 monologue 记忆 |
| DECIDE | 一个 JSON：`next`、goal、constraints、recall、计划、任务控制，再加十个可选增量字段（affect、policy_set、pin、write_docs、promote、group_action、attach、read……） |
| WRITE ×n / SELF / REFLECT | 各自一段文本 |
| SPEAK | 发出去的话 |

格式不对时程序最多修两次（`answers.py:14`）。DECIDE 被接受以后出的错（计划不在上下文、任务不能取消、没有工作区授权……）不会回到她那里，整轮直接记 `FAILED_RUNTIME`（`chat.py:406-415`）。

**界面上的两个问题都出自这套协议。**
- **JSON 当正文：** DSH 把一个回合最后一步的文本当作「回答」（`dsh-client-ui-chat` `latestAnswer`，`client.js:10021`）。委托但不说话、沉默、失败的回合，最后一步是 DECIDE，于是显示 JSON。
- **行动脑摊开：** 行动脑记录是插件自造的内联片段（`asuna-action-records`，`packages/cognition-core/src/client.js:181-194`），靠打过补丁的 DSH UI 包渲染（`tools/dsh-inline`）。它和角色脑的折叠规则不一样。

**行动脑已经是真正的 DSH 子代理。**
- 它由插件自己注册的 provider `asuna-worker` 创建，会话头带 `origin:'subagent'`，父会话有 `subagent/catalog`（`children.js:28-103`、`index.js:327-391`）。
- 但每次后台摘要也各开一个子会话：本地私聊头部的「61 subagents」里，38 个是摘要（`native_worker.py:100`、`dialogue_summary.py:186`）。

**行动脑有 25 个工具**（`index.js:582-620`、`tasks.py:64-88`、`development.py`、`integration.py`）。实际使用最多的是 development_*（共 1003 次）和 integration_test（91 次）；web_search、web_fetch、digest_authorized_discussion 从未被调用过。边界上的问题有：
- 只要开着自开发，**每个本地委托都自动拿到发布权和原始数据库读取权**（`chat.py:164-165`、`coordinator.py:488-494`）；
- `executor.md:3` 写着「没有网络」，但网页工具一直都在；
- 行动脑的系统提示里漏进了 DSH 自己的身份和开发环境信息（只有角色脑调用了 `suppressRuntimeContext`，`index.js:466`）。

**压缩**：两个脑都没设 `thresholdRatio`，用的是 DSH 默认的 0.8。实际卡住触发点的是 `headroomTokens`。窗口 W=262144，单次输出预留 O=32768：

| 脑 | 公式 `min(0.8W, W−O−headroom)` | 触发点 |
|---|---|---|
| 角色脑（headroom 32768） | 196608 | **75.0%** |
| 行动脑（headroom 默认 65536） | 163840 | **62.5%** |

出处：`dsh-compaction-basic/lib/index.js:128-132`、`packages/xiaoman/cordis.patch.yml:22-27`、`packages/cognition-core/cordis.patch.yml:29-33`。

## 2. 设计原则

1. **角色脑管「她是谁、她和谁的关系、她说什么」，行动脑管「世界和能力」。**
   - 角色脑的工具是心智动作：回想、感受、记下、打算、委托、说或不说。
   - 行动脑的工具是外部动作：文件、沙箱、网页、历史检索、图片、适配器、改代码。
   - 一种动作只属于一个脑，没有两个入口。
2. **工具就是动词，正文就是说话。** 角色脑回合里，不带工具调用的最后一步正文就是对对方说的话，DSH 原生显示为回答。思考和工具调用折叠在过程里。不说话就以 `stay_silent` 结束回合，界面上只剩折叠的「Completed in Ns」。
3. **先用 DSH 自带的。** 委托用 DSH 的 `subagent` 合约，传话用 `send_message`，打断用 `interrupt_agent`。界面全部用 DSH 原生的工具行、子代理列表、侧栏子会话和触发卡片，不新造界面（AGENTS.md）。
4. **能不能用某个工具，由程序在每回合决定，而不是做完再退回。**
   - 按会话类别、场景、回合种类只暴露当回合可用的工具（例如群里才有 `group_action`，owner 私聊才有 `write_document`）。
   - 典型回合可见的工具不超过 8 个，减轻 ADR-001 担心的「工具噪声冲淡人格」。
5. **错误回给她本人。**
   - 工具参数或权限不对，就作为工具结果把原因和可选项告诉她，由模型在同一回合里自己改，不再走程序拼装的 `:fix-N`。
   - 只有「最后的正文」还需要一道检查（见 §3.4）。
6. **不变的约束照旧：**
   - 核心不含人格名；
   - 状态以「解释过的文字」交给模型，模型用类别词写回；
   - 会话类别由程序算；
   - 只有说出口的话会发布；
   - 个人数据留本地；
   - 每个可选动作各自成败，不拖垮整轮。

## 3. 角色脑的新回合

### 3.1 一条入站消息 = 一个原生回合

1. Worker 按现状准备上下文（`context.py`），交给 `context-delivery.js` 组装成回合的第一条输入：对方说了什么，加上解释过的状态、记忆、关系、任务、计划。
2. 模型原生思考，按需调用 Asuna 工具。JS 把每次调用转给 worker，worker 校验后执行，结果作为工具结果回给模型。
3. 模型写出最后一段正文，worker 照现有的 SPEAK 发布路径发出（拆条标记、节奏、附图都不变，`coordinator.py:535-572`、`publish.py`）。
4. Episode 状态机简化为：PREPARED → TURN（原生回合进行中）→ COMMITTED / SILENT / WAITING_TASK / FAILED_*。

### 3.2 MONOLOGUE

原生思考取代 MONOLOGUE 阶段，不再单独生成、也不再存 monologue 记忆。见问题 Q2。

### 3.3 幂等

每个工具调用都有原生的 `tool_call_id`，用它作效果键。
- 崩溃后重放同一个调用不会重复生效；
- 同一回合里再次调用就是一次新的动作。

`decide_delta` 现有的各个执行器（affect、policy、document、promote、group_admin、attach）原样复用，只是把调用入口从「解析 JSON」换成「一次工具调用」。recall 轮次之后的语义键去重从此不再需要。

### 3.4 最后正文的检查（保留一道）

- 回合以文本结束：文本不能空，不能是 JSON 对象，也不能明显是在说工具或程序的事。
- 不合格就在同一回合追加一句提示，例如「你最后写的这段会原样发给对方」，最多一次；仍不合格记 `FAILED_PROTOCOL`，与今天一致。
- 以 `stay_silent` 结束的回合不检查正文。

## 4. 两个脑之间怎么传话

| 场景 | 角色脑这边 | 行动脑这边 | 界面（全部原生） |
|---|---|---|---|
| 交一件新事 | `subagent {description, prompt, purpose?}`，**后台、可续接**模式，立刻返回子代理 id | 新的行动脑会话（`asuna-action` 预设，按 `purpose` 授予工具） | 过程里一行「Create subagent」：摘要用 description，可展开看 prompt，带「Started」 |
| 补充信息 / 改目标 / 续接做完的事 | `send_message {agent_id, message}` | 进行中就在下一步看到，空闲则开新回合（DSH 的 steer 语义） | 「Message delivered」回执 |
| 停下 | `interrupt_agent {agent_id}` | 当前回合取消，任务记 CANCELLED | 原生行 |
| 行动脑做完 | — | 最后一条消息就是报告 | 角色脑收到「子任务状态更新」卡片，开新回合读报告并决定说什么 |
| 行动脑要问她 | 她的会话里出现「收到任务消息」触发的一个回合，她的回答就是正文 | `consult_character {question}`，同步等她的回答（保留现有语义，只改呈现） | 两边都是原生行和原生卡片 |

细节：
- **为什么用 `subagent` 这个名字：** DSH 的原生工具行和「协调子代理」的计数，只认 `subagent` 这个名字和它的参数格式（`dsh-client-ui-tool/lib/client.js:3372-3393`、`dsh-client-ui-chat/lib/client.js:1543`）。沿用这个名字，就能整套复用原生界面。
- **`purpose`：** 取值 `task`（默认）或 `self_improvement`。只有 `self_improvement` 才授予开发和发布工具（§6）。多出的参数不影响原生工具行。
- **任务表照旧：** Mongo 里的任务行、栅栏、授权、修订语义都保留。`subagent` 和 `send_message` 只是新的入口，由 `asuna-worker` provider 转成今天的 create、revise、continue、cancel。
- **行动脑的完整过程**不再内联进主对话。点头部的子代理列表，在侧栏或新页打开那个子会话，看到的是 DSH 原生的完整记录，折叠规则和角色脑一致。插件自造的内联片段（`asuna-action-records`、`NativeFragment`）和 `tools/dsh-inline` 补丁随之退役；这也去掉了 ADR-010 的阻碍 B6。
- **摘要不再挂成子代理：** 摘要是后台工作，不是委托。头部列表只留真正的任务。

## 5. 工具清单与边界

### 5.1 角色脑（心智动作）

| 工具 | 作用 | 取代的旧字段 | 何时暴露 |
|---|---|---|---|
| `recall {query, sections?}` | 搜记忆，读文档节，结果作为工具结果返回 | `next=recall`、`read` | 总是；每回合有次数上限 |
| `subagent {description, prompt, purpose?}` | 把一件事交给行动脑 | `next=delegate`、goal、constraints、speak_before_action | 有工作区授权时 |
| `send_message {agent_id, message}` | 给进行中或已结束的任务补话、改目标、续接 | `continue_task_id` | 有可见任务时 |
| `interrupt_agent {agent_id}` | 叫停任务 | `cancel_task_id` | 有进行中的任务时 |
| `stay_silent {reason}` | 这回合不说话，直接结束回合 | `next=silent` | 总是 |
| `attach_image {artifact_id, why}` | 给这回合的话配一张图 | `attach` | owner 私聊且有可用图片时 |
| `write_document {doc, op, sid?, heading?, body?, reason, …}` | 写自己的文档（正文直接写在调用里，不再有 WRITE 阶段） | `write_docs`（含 adopt_seed、set_tags） | owner_private；群笔记只在本群 |
| `update_self {target, body, reason}` | 改 Character Core / Current Self | `reflect_self` + SELF | 见 §6 |
| `understand_person {body}` | 更新对当前说话人的理解 | `reflect_understanding` + REFLECT | 上下文标明可用时 |
| `set_policy {key, value, reason}` | 调自己声明过的参数 | `policy_set` | owner_private |
| `pin_memory {memory_id, pinned}` | 置顶一条记忆 | `pin` | owner_private |
| `feel {op, …}` | 记一份心情、了结或作废、处理评估提案；参数只用类别词 | `affect`、`affect_ops`、`affect_adopt` | 情感账开启时 |
| `plan {op, …}` | 安排、改期、取消 | `schedule`、`update_plan`、`cancel_plan_id` | 总是 |
| `group_action {kind, who, …}` | 禁言、解禁、撤回、踢人 | `group_action` | 群里，且她是管理员、开启了管理时 |
| `promote_memory {…}` | 结算时把事实提升为长期记忆 | `promote` | 只在结算回合 |

角色脑**不**拿：文件、沙箱、网页、原始历史检索、读图、开发和集成工具。这些都是「世界」，要做就交给行动脑。

### 5.2 行动脑（外部动作）

| 组 | 工具 | 变化 |
|---|---|---|
| 规划 | `todo_write` | 不变 |
| 网页 | `web_search`、`web_fetch` | 不变；`executor.md` 删掉「没有网络」 |
| 工作区 | `list_files`、`read_file`、`write_file`、`sandbox_run` | `sandbox_run` 不再可写挂载 `/skills`：改技能只走开发工具，消除第二条入口 |
| 读取 | `query_authorized_history`、`digest_authorized_discussion`、`read_image` | 不变 |
| 问她 | `consult_character` | 不变，换成原生呈现 |
| 技能 | `skill` | 不变 |
| 适配器（owner） | `integration_*`、`import_integration_artifact` | 改适配器代码只走开发工具；`integration_dev` 只用来在集成环境里跑命令 |
| 自我改进 | `development_*`、`development_database_read` | 只在 `purpose=self_improvement` 时授予（§6） |
| 人格任务 | `persona_job_run` | 去掉对她的文档、参数、记忆的写权限，只留读和分析：身份数据只由角色脑写（§6） |

另外两处：
- 行动脑的系统提示也调用 `suppressRuntimeContext`，不再漏进 DSH 自身的身份和开发环境信息。
- 交接靠 `subagent` 的 prompt。行动脑拿到的第一条消息就是她写的 prompt（加上程序附的原始输入和工作区信息）。原生工具行里能直接看到这段 prompt，今天的内联片段反而看不到。

### 5.3 去掉的重叠

| 重叠 | 今天 | 之后 |
|---|---|---|
| 人格文本 | 角色脑 write_docs、行动脑改 `seeds/`、人格任务三处写 | 运行中的文档只由角色脑 `write_document` 写。行动脑改种子只影响新装，她用 `adopt_seed` 接收 |
| 技能 | `/skills` 挂载和 development_write 两条路，授权不同 | 只走开发工具 |
| 适配器代码 | `integration_dev` 和 `development_write project=napcat-qq` 两条路 | 只走开发工具；集成工具只负责跑、测、启停 |
| 发布权 | 每个本地委托都有 | 只有 `self_improvement` 委托有 |
| 读图、历史 | 只在行动脑（无重叠） | 不变：要看图或查历史就委托 |

## 6. 自我改进

### 6.1 两层，各归一个脑

| 层 | 改什么 | 谁改 | 怎么改 | 门槛（最少） |
|---|---|---|---|---|
| 身份与状态 | 人格、口吻、人物档案、活账、工作文档、Character Core / Current Self、参数、心情、对人的理解 | 角色脑 | `write_document`、`update_self`、`set_policy`、`feel`、`understand_person` | owner_private。`update_self` 从「只在 self_development 回合」放宽到 owner_private，与文档一致（见 Q4） |
| 能力 | 人格包（种子、技能、persona-model）、核心代码与提示、通道包 | 行动脑 | `subagent {purpose:self_improvement}` → `development_*`，最后 `development_publish` | 本机 owner 场景；`purpose` 由她自己决定，不需要 owner 批准 |

两层之间的衔接：
- **角色脑 → 行动脑：** 用 `purpose:self_improvement` 委托，prompt 里写清楚想要什么能力。
- **行动脑 → 角色脑：** 报告里写「建议你把 X 写进人格」，或者改了种子请她 `adopt_seed`。行动脑不直接写她的身份数据。
- **定期机会照旧：** 定时的自我发展机会（`schedule.py:120-157`）不变，只是换成用工具表达。

### 6.2 指南

- 一份与人格无关的核心技能「自我改进」（随 cognition-core 发布），两个脑都看得到。内容包括：改什么走哪层、怎么离线自检、怎么发布、什么会触发重启、哪些是地板文件。
- 现有 `asuna-offline-selfchecks` 里与人格无关的部分并进去。
- 每个工具的说明本身写清用途和边界。

### 6.3 启动底线（必须保留，并补上已知的洞）

保留（ADR-007 §8、ADR-008）：
- 稳定入口 `start-asuna.cmd` → `asuna-launch.mjs`，不导入 Python；
- 受保护路径；
- 核心组成锁（`floor.js:272-281`）；
- 来源变更检查；
- 启动探针；
- 修复地板预设；
- 需要重启的发布不在运行中自动切换。

补洞（这次调研发现的，均未实际触发过）：
1. **地板的依赖闭包没受保护：** `floor.js` 导入 `persona.js`、`channel.js`，`recovery.js` 导入 `settings.js`，这三个都不在保护列表里。要么列入保护，要么把它们内联进地板。
2. **探针只查语法：** 现在的探针只做 `node --check`。改成在子进程里真正解析和导入插件入口（ESM 解析），并校验 persona-model.json、cordis.patch.yml 的结构。
3. **人格包和通道包发布时不做任何结构校验：** 补上与第 2 条相同的校验。
4. **选上的 core 起不来就一直卡着：** 通过了探针、却在初始化时失败的 core 版本会一直保持选中。改为：启动器在重启后发现新选择连续初始化失败时，**改回上一个 ACTIVE 选择**。只改「选哪个包」，不回滚源码，与 ADR-007 的「只往前」不冲突。

## 7. owner 会看到什么

| 场景 | 今天 | 之后 |
|---|---|---|
| 普通回复 | 角色脑标签，几段阶段（独白、决定、说话），最后是话 | 角色脑标签，折叠的「Completed in Ns」（思考加工具调用），下面就是她的话 |
| 回想后再回答 | 两轮阶段，可能各带一段 JSON | 折叠过程里一行 `recall`，然后是话 |
| 委托并顺口说一句 | 话，加上一大段展开的行动脑记录 | 折叠过程里一行「Create subagent · 描述」，下面是她的话。行动脑过程不在主对话里，要看从头部子代理列表或侧栏打开 |
| 委托但不说话 | **显示 DECIDE 的 JSON** | 只有折叠的「Completed in Ns」，展开能看到委托那一行 |
| 行动结果回来 | 「收到执行请求」，再来一整轮阶段 | 「子任务状态更新」卡片（含报告摘要），然后是她的话 |
| 沉默 | **显示 JSON** | 只有折叠的「Completed in Ns」，展开是 `stay_silent` 和原因 |
| 群聊 | 同上 | 同上；`group_action` 也在折叠过程里 |
| 行动脑在干活 | 主对话里展开的工具记录 | 侧栏子会话里的原生记录，自己的思考和工具都折叠好；头部的上下文环照旧 |

工具行的标题：
- 原生的 `subagent`、`send_message` 等有 DSH 自带的标题和图标；
- Asuna 自己的工具（`recall`、`write_document`……）走 DSH 的通用卡片，标题是工具名本身。

要不要换成中文标题、要不要在委托行上加「打开行动脑」的链接，都需要一点自定义（`tool.call.toolview` 槽位，复用 DSH 原语），按 AGENTS.md 要先经 owner 同意，见 Q3。

## 8. 压缩：两个脑都在 85% 触发

| 键 | 角色脑（`packages/xiaoman/cordis.patch.yml`） | 行动脑（`packages/cognition-core/cordis.patch.yml`；修复预设同改） |
|---|---|---|
| `thresholdRatio` | 新增 0.85 | 新增 0.85 |
| `headroomTokens` | 32768 → 6144 | 默认 65536 → 6144 |
| `maxTokens`（摘要上限） | 保留 24576 | 不变 |
| `retainRatio` | 不变（0.16） | 不变（0.32） |

- 结果：W=262144、O=32768 时，触发点 `min(222822, 223232)` = 222822，**正好 85%**。
- **余量变小：** 85% 加上 32k 的输出预留，到溢出前只剩约 6.5k tokens 的输入余量。单步塞进大量输入时会走溢出恢复（重试一次）。工具结果裁剪器照旧先剪大结果。
- **估算偏差：** 没有可复用的用量数字时，DSH 按约 4 字符/token 估算，会低估中文。实际触发可能略晚于 85%。上线后看一周的溢出恢复次数，再决定是否微调。
- **局限：** 如果以后角色脑换回 68k 窗口的独立模型，85% 达不到（最多约 76%），除非调低输出预留。

## 9. 实施阶段

| 阶段 | 内容 | 能否独立上线 |
|---|---|---|
| M0 小修 | 压缩 85%；`executor.md` 的网络说法；行动脑提示去掉 DSH 自身信息；摘要不挂子代理；发布权只给 `self_improvement`（M2 之前，用「来自自我发展回合」近似） | 能，先做 |
| M1 角色脑工具化 | worker 的工具后端（复用现有执行器，用 tool_call_id 作效果键）；JS 给角色脑按回合注册工具；一回合一次原生循环；最后正文 = 说话；`stay_silent` 结束回合；正文检查。删掉 MONOLOGUE/DECIDE/WRITE/SELF/REFLECT/SPEAK 阶段和 `decision*.schema.json`，不留兼容层 | 与 M2 一起上线 |
| M2 子代理合约 | `asuna-worker` provider 支持后台可续接；`subagent`、`send_message`、`interrupt_agent` 入口；子代理完成 → 新回合；consult 原生呈现；退役内联片段和 `tools/dsh-inline` | 与 M1 一起上线 |
| M3 边界与自我改进 | `persona_job` 只读；技能和适配器各只留一条入口；`update_self` 放宽；核心技能「自我改进」；启动底线的四处补洞 | 能 |
| M4 验收 | 隔离的 demo profile、合成推理下做界面验收（AGENTS.md）；owner 授权后在真 profile 用真模型验收；请她自己更新受影响的技能（如生图技能里的「DECIDE attach」步骤），作为第一次用新工具自我改进 | — |

**测试：**
- 大量现有用例围绕阶段协议写成（`test_adr009_p*`、`test_answers`、coordinator 相关），要按工具重写，这是工作量的大头。
- JS 的 `stages.test.js` 对应改写。
- 她的离线自检（p1c、p2、p3、p5）里依赖阶段的部分随之更新。

**先做一个技术验证（M2 开头）：**
- DSH 自带的可续接子代理总是沿用父会话的预设（`dsh-subagent/lib/index.js:1068-1074`）。我们的 provider 必须让行动脑用自己的 `asuna-action` 预设。
- 今天的单次子代理已经做到了（`children.js`），要确认后台可续接模式也行。
- 不行的退路：工具名仍叫 `subagent`、参数和结果文本保持一致，由插件自己实现，原生工具行照样认。

## 10. 风险

| 风险 | 处理 |
|---|---|
| 模型把「我要调用工具了」之类的话写进最后正文，发到 QQ | 提示里写明「正文会原样发出」，加上 §3.4 的检查；先在 demo profile 用合成推理和真模型各跑一遍 |
| 工具噪声冲淡人格（ADR-001 的顾虑） | 每回合只暴露可用的工具；说明简短；人格提示仍在最前 |
| 去掉 MONOLOGUE 后少了一类记忆 | 见 Q2；摘要和她自己写的文档仍在 |
| 原生 `subagent` 行是英文标题、通用卡片 | 先接受（复用优先）；要中文标题见 Q3 |
| 测试重写量大 | 按 M1、M2 分批，每批全绿再合并 |
| 她自己的技能和笔记里写着 DECIDE 字段 | M4 请她自己改，当作第一个自我改进任务 |

## 11. 本 ADR 已替 owner 定下的事（理由见各节）

- 委托走后台可续接：她交出任务后可以继续聊天，结果回来再开新回合。不让她的回合阻塞等待。
- `consult_character` 保持同步，只改呈现。
- 行动脑不写身份数据；身份数据只由角色脑写。
- 摘要不再挂成子代理。
- 压缩只统一阈值（85%），各自的保留比例不动。
- 启动底线补四处洞；「改回上一个 ACTIVE」只回退选择，不回退源码。
- Character Core / Current Self 和人格文档暂时仍是两个存储，只统一门槛。是否合并另议，合并需要数据迁移，开发期按规则直接删重建，不写兼容代码。

## 12. 待 owner 决定

- **Q1 她说的话从哪来：** 最后一段正文（推荐，DSH 原生就把它当回答显示），还是显式的 `say` 工具（每句话都是一次工具调用，正文不发）。
- **Q2 MONOLOGUE：** 去掉、由原生思考取代（推荐），保留成一个「记一笔心里话」的工具，还是保留阶段。
- **Q3 委托在界面上：** 纯原生（推荐：原生行加头部列表、侧栏），原生加一个「打开行动脑」链接和中文标题（小量自定义，复用 DSH 原语，需要 owner 同意），还是保留今天的内联记录。
- **Q4 自我改进的门槛：** 只有她标成 `self_improvement` 的委托拿发布权（推荐），像今天一样每个本地委托都拿，还是发布前要 owner 确认。
