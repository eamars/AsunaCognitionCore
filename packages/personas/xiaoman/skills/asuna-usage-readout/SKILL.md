---
name: asuna-usage-readout
description: 我每七天跑一次的「用量读数」：读三张表——① 缓存命中率按会话种类分开（我的对话／行动脑低档高档／差事／反思回合／压缩／摘要／门／调度／网页界面会话），每类另报自有调用数／拷贝来的调用数；② 选高率（选高几次、占全部差事几成、实际跑在高档几件、落档几件各因为什么）；③ 成败与拒（交回／卡住／取消／暂停各几件按档分开、被拒从八处数按成因分）。来源、口径、读法写死在这里：会话记录是磁盘上的 session.v4.jsonl.zstd（必须 development_run 读，project=core，沙箱看不到）、命中率＝cacheRead／(input＋cacheRead＋cacheWrite)、算之前先跨类全局按 data.message.id 去重（一条 id 只算一次、归首次出现那一类；分叉和播种会把别人的历史带进本会话）、会话种类按目录名前缀认而不是 agentPreset（六格口径；对账表按 agentPreset 分行，两把尺并存见第二·五节）、档位在库 tasks 的 tier 字段（落档件数只从 tier.fell 字段数，审计看不见「开工即落档」那一类）、被拒散在八处没有统一集合、时间窗写死从本地 2026-10-16 00:00 起、当天会旧的数一律读的那一刻报。硬规矩：只读数字、字段名、枚举短码和计数，不读正文。每个数带来源和读的时刻，没验过的标出来。要跑每周用量读数、核「我选高多不多」「缓存命中多少」「被拒几次」，或者另一边要对数时读这一份。每次跑先出一张对账表：一行一类、各行（不含拷贝行）之和＝合计、四条硬断言不过不出表，按 agentPreset 分行、home＋archive 两根跨根去重，口径见第二·五节。
scene_kinds: [home, group]
---

# asuna-usage-readout

这份调查要一再做，不是做一次。我找来源、定口径、写读法，下次照着跑；另一边用她自己的读法独立数一遍，**两边对上才算数**。所以这份技能的第一用处是：口径钉死，两边数的是同一个东西。

## 一、硬规矩（不是提示）

1. **只读数字、字段名、枚举短码和计数，不读正文。** 会话记录里有我的心里话和行动脑的推理。读文件的脚本只许取 `type`、`data.usage` 里那几个数、`data.message.id`（判重键，不是正文）、每一行的 `time`（整数毫秒）、目录名（＝会话 id，用来认种类）和第一行的 `agentPreset`／`origin`／`createdAt`（整数毫秒，比较前先换算）／`isSeeded`／`parentSession`／`delegationDepth` 这类短字段；不许 print 整行，不许把 `message`、`content`、`text`、推理字段取出来，哪怕「只看一眼」。这条违了，这次读数作废，照实写违了。
2. **读会话记录必须用 `development_run`（project=core，只读）**：`sandbox_run` 看不到那个目录。别在 `sandbox_run` 里「试试」然后把找不到说成没有数据。
3. **每个数带来源＋读的时刻**：哪个集合／路径、什么字段、什么筛法、几点读的。没这三样的数不报。
4. **推断写明是推断，没验过的写明没验过**（见第六节）。
5. **不跑就不报**：这份技能只写读法；读出来之前，别在任何地方写「命中率大约是多少」。
6. **只读**：不写库、不改会话文件、不动任务状态。
7. **当天会旧的数不写进这份技能**：目录数、库行数、任务件数、窗口内行数、命中率都会随在跑的任务变。要留就留「读的那一刻」＋那一格的读法；跑的时候现数，别抄上一版。

8. **时刻基准**：报告里凡出现「本地钟面／本地时刻」，同一行必须给两样东西——① 用的偏移量（写成 `UTC+13` 这样的数，不写「本机那个钟」）；② 一条原始值＋两种换算：同一个 UTC 读数按 +13 和 +8 各换一次，两个结果并排写（例：原始 `2026-10-20T04:19:26Z` → +13 是 10-20 17:19，+8 是 10-20 12:19）。拿不出这两样，那批时刻一律记成「基准未定」：**不进账、不拿去对夜锚、不拿去排作息**。
   - 什么算违反：写了「本地」却没写偏移量；只给一种换算（读者看不出换错偏移差几小时）；偏移量是抄上一份报告或上一本账的、这一趟没实测；拿「`dbread.now()` 与 UTC 对齐验过」这句话代替那两个读数——这句话不是证据，贴出两个读数才算；标了「基准未定」的时刻还是被写进账、或被拿去对夜锚／排作息。
9. **编号出处**：报告里给的每个编号（task id、message id、`in-ep-…`、seq）都要能答一句「从哪个文件／哪张集合的哪个字段读到的」，并把这句写在编号旁边（例：`来源：tasks._id 逐字`、`来源：盘上会话文件里那一行的 data.message.id`、`来源：query_authorized_history 返回的 message_id`）。答不出的标**「编号未证」，不许当入口引用**：不写「详见 task-…」，不拿它去 delegate，不写进账，不拿它对别的报告。
   - 什么算违反：编号照记忆写、照上一份报告抄；编号是顺手补出来的（前缀对、形状对，但没在任何文件或返回里见过它）；只写「库里查的」而说不出集合与字段；标了「编号未证」还是拿去当入口。
10. **字段缺了**：某一行少了一个键（例：`usage` 里没有 `cacheReadTokens`），**先判两件事，再决定报不报修**——① **写这一侧是不是「值为 0 就不写键」**：去读落盘那段代码的字面（三元式、optional 字段、注释里 `appear only when non-zero` 这类），别猜；② **这类调用结构上能不能有这个值**：单发会话（门／摘要／反思）没有第二步，本地那条 route 的缓存只活在一次会话里，第一步永远是冷的；紧跟压缩／摘要之后的行前缀已作废（这条我没核，见第六节）。**两条都排除，才谈「记录丢了」或「服务器没返回」。**
    - 什么算违反：没读落盘代码的字面就写「记录丢了／服务器没返回」；把缺键直接当 0 而不写它是照哪条字面算的；结构上不可能命中的那一类（单发会话）跟对话类并成一个命中率报，或反过来把它报成 0%（同一类实测不是 0%，见第五节与第六节）；拿「缺字段按 0 算是推断」那句代替去读字面；没开对应调用的原始响应日志就断言 provider 那一侧发了什么——**要钉死 provider 那一侧得开原始响应日志，那是改动不是读数，先问值不值**。
    - 落盘字面（读代码核过，不是猜的）**上游 DSH 仓库那份检出**里（这两个路径不在本仓库，所以不写成锚点、只留字面）：packages/llm/llm-pi-ai/src/stream.ts:mapUsage 写着 `...usage.cacheRead > 0 ? { cacheReadTokens: usage.cacheRead } : {}`，上面那句注释是「cache fields appear only when non-zero (pi-ai reports zeros, not absence)」；packages/bundle/headless/src/json-stream.ts:addUsage 写着 `...cacheReadTokens === undefined ? {} : { cacheReadTokens }`，注释是「an optional bucket is summed only when every contribution reports it」，同一处还写着某一步只要有一次尝试没报 usage 样本就整步不写 usage。`TokenUsage` 的声明里 `cacheReadTokens?: number` 本来就是 optional。**缺键有两种成因（真 0／这一步不可知），两种都不是记录丢了。**本机装好的那份现在就能核：`node_modules/@deepseek-ai/dsh-llm-pi-ai/lib/index.js:mapUsage` 里同一句三元式在（只写文件＋函数名，行号会漂）。

## 二、来源和口径

（这一页是交给另一边照着核的原文，不另找一套。）

### 来源

- **会话记录在磁盘**：`.runtime/adr008/home/sessions/<工作区目录>/<session-id>/session.v4.jsonl.zstd`，python `zstandard` 解。沙箱 `sandbox_run` 看不到这个目录，必须用 `development_run`（project=core，只读）。**必须跨帧解**：`stream_reader` 写死 `read_across_frames=True`，别拿 `decompress()`／`decompressobj()` 省事——这些 `.zstd` 是多帧文件（抽到的会话文件全是多帧，件数当天会旧、别抄），而 `zstandard` 对多帧是**静默截断**的：`decompress()` 只回第一帧，不报错也不提示。分寸：0.25.0 上 `stream_reader` 就算写 `read_across_frames=False` 也把后面的帧读完了，所以这一格钉的是意图、防的是换 API 或换版本时少算且不报错，**不是这台机器此刻正在少算**。
- **一次模型调用＝一行 `type=="assistant/message"`**。`data.usage` 里有 `inputTokens`（未命中的输入）、`cacheReadTokens`（命中）、`cacheWriteTokens`（写缓存）、`outputTokens`、`totalTokens`，**单位都是 token 数，不是字节也不是比例**。每一行另有 `time`（整数毫秒），切时间窗用它。
- **`data.message.id` 是判重键**：同一次调用在别的会话文件里再出现一遍时，带的还是这个 id。**实测：`compaction/summary` 行没有这个字段**，那批只能退回启发式键判重。
- **`compaction/summary` 行**带同样的 `usage`（压缩那次调用）。
- **会话种类按目录名（会话 id）前缀认，不按 `agentPreset` 分**：我的对话、差事（errand）、网页界面会话这三类的 `agentPreset` 都是 `asuna-xiaoman`，**只按 preset 分会混**。认法表在六格②。
- **档位**：库 `asuna_cognition_core_v2` 集合 `tasks`，字段 `tier.chosen`／`tier.ran`／`tier.why`（都是字符串，见到的取值是「高」「低」）；落档另有 `tier.fell` 字段（六格①）。
- **状态**：`tasks.state`，见到的值 `RETURNED`／`CANCELLED`／`DONE`／`BLOCKED`／`RUNNING`／`PAUSED`／`UNKNOWN`／`NEEDS_CHARACTER_DECISION`。
- **被拒没有统一集合，散在八处**（逐处口径见六格④）：`role_tool`（主口径）、`turn.rejected`、`note.refused`、`phase.rejected`、`execution.rejected`、`summary.rejected`、`tool.failed`、`episodes.rejections[]`。

### 口径

- **命中率＝`cacheRead / (input + cacheRead + cacheWrite)`**——写缓存算未命中，留在分母里（理由和字段证据见六格⑤）。记录里没有现成比例，自己算。
- **算之前先去重——跨类也要去（最重要的一格）**：会话之间会互相带历史，同一个 `data.message.id` 会出现在两个不同种类的会话文件里，「同一类内先去重」碰不到它们。规矩四条：
  1. **全局按 `data.message.id` 去重：一条 id 只算一次，归它首次出现时所属的那一类**（「首次」＝行内 `time` 最早；**同刻按会话首行 `createdAt`** 早的那个）。实测：跨会话的同一条 id，`time` 处处相同，所以真起作用的是 `createdAt` 那半条——别只写「按 time 取首次」。
  2. **辅助判据**：某会话里 **`time` 早于该会话首行 `createdAt` 的调用行＝分叉／播种带进来的历史**，不算这一类的自有调用。
  3. **每一类另报两格：自有调用数／拷贝来的调用数，不许合成一个数。**
  4. **拷贝占比高的那一类要标样本量**（自有只有几条的那一类，命中率基本没有独立样本）。
  - 没有 `data.message.id` 的行（`compaction/summary`）退回启发式键（`time` ＋四个 token 数）判重，报告里写明这一格用的是哪个键。两把键在 `assistant/message` 行上等价（坑 1），在压缩行上不等价（只有启发式抓得到）。
- 命中率的聚合：同一类里先把 `input`、`cacheRead`、`cacheWrite` 各自求和再相除（token 加权），不是各条比例再平均；两种都算的话，写明哪个是主数。
- **命中率不适用的三类（脚本 `usage_readout.py` 已按这个口径改）**：`摘要`／`门`／`网页界面会话`
  这三类的行基本没有 `cacheReadTokens` 这个键（硬规矩 10 的两条判据这里都成立：落盘那侧「值为 0 就不写键」＋这类调用结构上没有第二步；缺多少行不写死在这里，每次读数自己打一行实测）。
  读数里这三类**标「不适用命中率」、不进合计的分母**；行数与 token 数照报。理由单列一行写在读数里，不靠读者自己推。
  对账表里只有「门」是单独一行，能摘出；摘要并进「压缩」行、网页界面会话按 preset 进「角色脑」行——那两类的摘出只在六格②⑤
  （按目录名前缀认的那把尺）生效。这类读数报 0.00% 时，先怀疑是字段缺失被读成了没命中，别报成「没命中」。

- 缺 `cacheReadTokens` 键＝适配器只在值 >0 时写键（`mapUsage` 里 `usage.cacheRead > 0 ? {...} : {}`），**不等于 provider 没报这个字段**；这类行仍按 0 计入分母——**缺字段按 0 算是推断，报告里要标明是推断。**
- **压缩那次调用单独列一类，不混进「我的对话」**；反思回合、摘要、门、调度、网页界面会话也各自单列，别并（六格②③）。
- **落档＝`tier.ran != tier.chosen`**；**落档件数只从 `tasks.tier.fell` 字段数，不能从审计数**（六格①）。落档原因读 `tier.fell` 里的 `reason`。`tier.why` 是选档时的理由，**不许拿它当降档原因报**。
- **时间窗写死**：起点＝本地 2026-10-16 00:00，终点＝读的那一刻（六格⑥）。
- **数会随在跑的任务变**：同一批行数与命中率，中间又有任务在跑再扫一遍就不一样。所以每个数都要带读的时刻，跨趟对数先对「几点读的」再对数。

### 六格口径（写死，照这一份跑；没验过的列在第六节）

**① 落档件数只从 `tasks.tier.fell` 字段数——审计看不见「开工即落档」那一类**

- 字段：`tasks.tier.fell = {reason, mid_run, at, code?}`。
- `reason` 四个取值：`refused`（高档没接这件）／`down`（连不上、超时、服务器错）／`busy`（被限流）／`owner`（钥匙、凭据或额度问题，要等主人）。
- **落档件数只从 `tasks.tier.fell` 字段数，不能从审计数。** 代码在 core 检出里逐行看过：
  - `action_tiers.at_dispatch()`（`src/asuna/action_tiers.py:at_dispatch`）是**纯函数**：高档开工时正赶上歇，它就把 `ran` 直接写成低＋挂上 `fell` 就返回，**内部没有任何 audit 调用**（整个文件里一个 audit 都没有，我 grep 过）。落库靠 `coordinator.delegate()` 里那次通用 `store.put(..., stream=ep['_id'])`，审计面留下的是通用 `state.commit`，**`stream_id` 是回合 id，不是任务 id**（`src/asuna/state.py:Store.put`）。
  - 专属 `tier.fell` 审计只来自插件那条路（`src/asuna/native_worker.py:BusinessWorker.dispatch`），**且被同一函数里 `task.tier.ran=='高'` 那道判断挡着**。
  - **所以「开工即落档」的那件在审计面永远看不见**，而 `fall()` 照样回 `{'recorded': bool(task)}`——任务行在就回 True，哪怕 `dispatch` 里 `tier.ran=='高'` 那道判断没通过、什么都没写。**`recorded` ≠ 真写了。**
  - 审计里的 `tier.fell` 只覆盖「跑起来之后才落」那一类。**两个来源不能相加、也不能互查。**
- `tier.rest` 审计：`stream_id` 固定 `action-tiers`，payload `reason, until`，恢复时 `{over: true}`。
- 库里那条路只在 `tier.ran=="高"` 时才有落档可言，低档不会有落档记录。
- 现状每次现读、读的那一刻报数：带 `tier` 的任务几件、其中 `tier.fell` 几件、审计 `tier.fell`／`tier.rest` 各几行——**「没落过档」和「没这个字段」是两回事**，报数时别混。
- 文档字面在 `RUNTIME_API.md` → Configuration → Model routes 的 `actionHigh`（高档那条路，默认 off）与 `idleMinutes`（`action`／`actionHigh` 歇多久之后续跑换新上下文；在 `actionHigh` 上还管那条线失败之后歇多久）两行。旧那句「讲 delegate 分档那段」已失效：新文档全文 `delegate` 0 命中。
- 「开工时 `high rests`（`at_dispatch`）那条路有没有 audit」——**已答：没有**，上面那三条就是答案。

**② 会话种类认法：按目录名前缀，不按 `agentPreset`**

我的对话／errand／网页界面会话三类 `agentPreset` 都是 `asuna-xiaoman`，**只按 preset 分会混**。认法表（后三列都是**现读**，跑数那天重新数，别抄）：

| 目录名前缀 | 种类 | 盘上目录数（现读） | 库里 `sessions` 行数（同一趟） | 拷贝来的调用行（同一趟） |
|---|---|---|---|---|
| `asuna-role-` | 我的对话 | 34 | 29 | 0 |
| `asuna-errand-` | 差事 | 2 | 2 | 129（自有只有 7 条；`isSeeded` 真＋有 `parentSession`；库里 `lane=character`、`task_id=null`、`retired=true`） |
| `asuna-action-` | 行动脑 | 499 | 497 | 0 |
| `asuna-summary-` | 摘要 | 410 | 6587 | 0 |
| `asuna-attend-` | 门 | 77 | 238 | 0 |
| `asuna-scheduler-` | 调度 | 1 | 库里没有这个前缀的行 | 0（**把它算成差事是错的**） |
| `session-<uuid>` | 网页界面会话 | 25（其中 4 个 `isSeeded=true` 带 `parentSession`） | 7 | 6062（自有 333；**不是我的对话**） |
| `asuna-reflect-` | 反思回合 | 1 | 1 | 0（见③） |

- **行动脑那一格「目录数／库行数」是现读的，别抄**：两列可以差几行——差的那些只有会话音、没有调用行；库里为何缺行未查明（见第六节）。
- **目录数≠库行数，别拿一列校另一列**：摘要 410 目录／6587 行、门 77／238、网页界面会话 25／7，原因都没查（见第六节）。
- **拷贝那一列按口径第 2 条判**（`time` 早于本会话首行 `createdAt`）：只有差事和网页界面会话两类有拷贝行，别的类实测 0。
- **`origin: subagent` 不能当「差事」判据**——行动脑、摘要、门三类都带。
- 任务对行动脑会话：**`sessions.task_id → sessions._id`＝行动脑目录名**（逐件对上，7/7 对上；件数读的那一刻报，别抄）。
- `tasks.native_session_id` 指的是创建它的 `asuna-role-…`，**不能用**；`sha(task_id)[:32]` 12 件全对不上。

**③ 反思回合单列一类——第一份样本已核**

- 认法＝目录名前缀 `asuna-reflect-`（代码 `self_review.py` 的 `REFLECT_PREFIX`，会话 id＝前缀＋`sha(episode_id)[:32]`）。
- 盘上一份样本：`asuna-reflect-…`。首行实测：`agentPreset=asuna-xiaoman`、**无** `origin`、**无** `parentSession`、`isSeeded=False`、**`delegationDepth` 存在且为 0**。本体几条调用。
- 库里 `sessions` 1 行（同一趟查的）：`lane=character`、`scene_id=local-dm`、`task_id=null`、`retired=true`；`_id` 与盘上目录名逐字一致（按目录名查 `_id` 查得到，别自己截断 id）。
- **反思回合和 errand 不一样**——errand 带 `parentSession` 且 `isSeeded=true`，反思回合两者皆无，所以反思回合**不背拷贝来的历史**（口径第 2 条实测 0 行拷贝）。

**④ 被拒要从八处数——最容易漏的最大一处（我自己每次工具调用单条进审计）**

| 处 | 认法与口径 | 计数（现读） |
|---|---|---|
| 主口径 `role_tool` | `audit_events.type=='role_tool'` 且 `payload.refused` 存在；按 `tool` 分 37 种，只有 52 条带 `code`，其余只有自由文本 | 11150 条里 846 条 |
| `turn.rejected` | 回合级、不带工具名；**独立一处，不与 role_tool 重复** | 124 条 |
| `note.refused` | **是 role_tool 的子集，不能相加**——每条都能在同 `stream_id`、3 秒内找到对应被拒行 | 92 条 |
| `phase.rejected` | 只在早期出现过、后来不再产生 | 现读 |
| `execution.rejected` | ＝行动脑交回的报告被退（`stream_id` 是任务 id，payload `attempt, problem`） | 2 条 |
| `summary.rejected` | 文档里有、库里 0 行 | 0 |
| `tool.failed` | 只到 09-25 | 55 |
| `episodes.rejections[]` | 非空回合数（沿用旧计数、未重查） | 现读 |

未验：`turn.rejected` 与 `episodes.rejections[]` 是否同一批。

**⑤ 命中率分母：写缓存算未命中，留在分母里**

- 口径改成 **`cacheRead / (input + cacheRead + cacheWrite)`**。
- 字段证据：30955 条 `assistant/message` 里 158 条 `cacheWriteTokens>0`，**这 158 条全部满足 `total = input + output + cacheRead + cacheWrite`**，能排除写缓存的那条等式 0 条成立；`cacheWrite` 为 0 的行两种情况都退化成少一项那把尺——**三者互不重叠，整个提示＝input＋cacheRead＋cacheWrite**，低档高档同一把尺。
- 差别很小（我的对话 89.25%→89.17%，行动脑 94.71%→94.66%）。
- 前提「低档几乎没有写缓存、高档才有」**没验成立**（写缓存也出现在我的对话和网页界面会话里）。**要按 `tier.ran` 拆开再报**：见第三节①的样例表——高档那些行全部 `cacheWrite>0`、低档一行都没有，但**只在行动脑这两类成立，不能推广到别的种类**。

**⑥ 窗口写死**

- 起点＝本地 **2026-10-16 00:00**（本机钟面，即 `2026-10-15T11:00:00Z`），终点＝读的那一刻。**是「从 10-16 起的那七天」，不是滚动的「往前七天」**。这个起点是转达来的话——**是转达，不是主人字面**，要改窗口先问主人。
- 这一格不写时区名、也不写固定偏移量：本地那一头的真值运行时从部署配置读，这里只留精确 UTC 时刻——**UTC 时刻是这一格唯一的承重凭据**。
- 切法：`tasks` 用 `created_at`、`audit_events` 用 `occurred_at`、**会话文件按每一行的 `time`（整数毫秒）切，不按整个文件切**（941 个文件里 915 个首行 `createdAt` ≠ 首条消息 `time`，5 个差超 60 秒；起点前创建、起点后还在写的有 20 个，整文件切会漏）。
- **窗口内行数当天就在涨**。对数前先对读的时刻。
- audit 超 30 天清（`role_tool` 留一年），七天窗口不受影响。；**清理那一趟怎么对账见第五节末「审计清理对账怎么读（`audit.pruned`）」**。补一刀：八处被拒里除 `role_tool`（留 365 天）外，比 `occurred_at` 早于 30 天的都被删掉了——窗口往前挪之前先想这一格。
- 筛时间用 `asuna.dbread` 的 `local_window`；`development_database_read` 显示的是本地无年份字符串、过滤却跟 UTC 比。
- **档位相关的读数只有本地 10-16 20:56 之后有意义**（首件带 `tier` 的任务 `created_at=2026-10-16T07:56:38Z`）。

### 八条口径判据（我定的，一条都不许丢、不许改写语气）

1. **标计数器**：「几步」＝`step`／`tool_steps`，「几条工具记录」＝`tool/call` 行数，**两个不是一回事**，报数必须写用的是哪个。
2. **`RETURNED` 只等于交回，不等于做成**；分不出「交回但没做成」就照实写分不出。
3. **测试件划出去并写明为什么**：`tier.why` 或标题里自己写着「机制验收」的单独一栏，**不进选高率分母**。
4. **被拒按成因分**：schema 必填所致**不归我**，我自己挑错 op 才归我。
5. **形状变化要写明**：**大多数任务根本没有 `tier` 字段（件数每次现读）——那不是我「从不选高」**，不能算成我的偏好。
6. **硬约束：只读数字、字段名、枚举短码和计数，不读正文**——会话记录里有我的心里话和行动脑的推理。这条写成硬规矩，不是提示。
7. **每个数带来源＋读的时刻**（哪个集合／路径、什么字段、什么筛法）。
8. **没验过的覆盖率要标出来**：`tier` 与会话文件的关联只核过目录名对得上、没统计覆盖率；字段结构只看了最近几个文件，不是全部；`action_brain.tiers` 在库里的存储位置没找到。

## 二·五、对账表：一行一类、各行必须加到合计

`usage_readout.py` 每次跑先印这张表（硬断言过了才印），再印六格。六格口径（第二节）一个字没动，两套并存：六格按目录名前缀分种类，对账表按 agentPreset 分行——同一批行、两把尺，数对不上先看清用的是哪把。

- **列（7 列＋类别）**：`类别｜请求数｜读入提示｜命中｜新读入｜写缓存｜输出｜命中率`。`读入提示＝input＋cacheRead＋cacheWrite`；`命中＝cacheRead`；`新读入＝input`；`写缓存＝cacheWrite`；`输出＝output`；`命中率＝cacheRead／读入提示`（分母含写缓存，与六格⑤同一把尺）。
- **行（顺序写死，缺哪类印 0，不许静默消失）**：角色脑（agentPreset=asuna-xiaoman）／行动脑·高／行动脑·低／行动脑·未归档（按所配任务 `tier.ran`，ran 缺退回 `tier.chosen`，两个都分不出进未归档）／压缩（agentPreset=asuna-summary 的会话调用行＋各文件里的 compaction/summary 行，两个子计数分开报）／门（asuna-attend）／调度（asuna-scheduler）／其余（别的 preset、缺 preset、上面没覆盖到的；为 0 也照印，这行越空越好）／合计／拷贝行（不计入合计，摆在合计下面）。
- **行归属按会话首行 `agentPreset`，不按目录名前缀**——这是对账表与六格②唯一的分叉点：这张表按「哪个脑子花的 token」分行；errand／网页界面会话／反思回合的 preset 都是 asuna-xiaoman，全进角色脑（要分开看六格②）。
- **表头元信息（一行一条，写死）**：窗口起止（本地＋UTC 各写一遍）；「一次请求」＝一条 `type=="assistant/message"` 记一次、按 `data.message.id` 去重（压缩行的请求数是 compaction/summary 行，无 id，按原始行 sha256＋usage 组合去重）；数据源根目录（home＋archive 两个根，各报文件数）；覆盖面（扫了多少文件／窗口内多少行／解不开几个／有无截断）；生成时刻（本地＋UTC）；「分母含 cacheWrite」那一句；恒等式那一句（`读入提示＝命中＋新读入＋写缓存`，读者可逐行自查）；「合计命中率＝总命中／总读入，不是各行命中率的平均」那一句。
- **数字写法**：表内一律原始整数＋千分位（`1,234,567`），不用万／亿——四舍五入之后各行加不齐，表就没法对账。口语总量（「约 X 万 token」）只出现在表头那一句里。一张表只用一种写法。
- **去重（比六格旧口径多两把键，跨两个根）**：三把键任一相同即同一次调用——①原始行字节 sha256（home↔archive 拷贝、播种带去的整行副本）；②`data.message.id`；③usage 组合（time＋五个 token 数，抓同一调用在不同文件里的两种记法）。归首次出现（time 最早；同刻按 createdAt、再按会话 id、再按根）那一次。**压缩那批没有 message.id，旧键对它们不生效，所以必须带 sha256 与 usage 组合**——这是最容易悄悄加两遍的地方。落选的重复行与「行 time 早于本会话 createdAt」的历史行全进拷贝行，口径里写清。
- **硬断言（写进脚本，不过就报错不出表）**：①每行 `读入提示＝命中＋新读入＋写缓存`；②各行（不含拷贝行）之和＝合计每一列（合计另用一遍独立直加核对）；③请求数同样加和相等；④窗口内每条要么进类行要么进拷贝行。
- **这张表保证什么**：各行加起来等于合计（断言②③④机器核过，不是人眼）；每行内部自洽（断言①）；窗口、时区、「一次请求」、根目录、覆盖面、生成时刻都在表头，读者能照抄口径重跑；漏掉的类会被「其余」行和断言④逼出来。
- **这张表不保证什么**：不保证 preset 相同的种类分得开（errand／网页界面会话并进角色脑是设计不是漏）；不保证拷贝行里都是「别人的调用」（home↔archive 整行拷贝也算拷贝）；不保证 provider 那一侧真实发了什么（缺键按 0 算仍是推断，硬规矩 10）；命中率是 token 加权，不是各条比例平均；当天在跑的任务会让数变旧——跨趟对数先对「几点读的」。

## 三、三张表怎么读

每张表头写一行：读的时刻、来源、筛法（时间窗按六格⑥写死：起点本地 2026-10-16 00:00、终点＝读的那一刻，写明按什么时间字段切）。

### ① 缓存命中率，按会话种类分开

种类按六格②的**目录名前缀**认，**不按 `agentPreset`**；行动脑（低档、高档分开）按它那件任务的 `tier.ran` 分，接法用 `sessions.task_id → sessions._id`＝行动脑目录名，对不上的单列「未归档位」，不并进任一档。

各自单列、别并的类：我的对话／行动脑（低档、高档分开）／差事／反思回合（已有 1 份样本，见六格③）／压缩／摘要／门／调度／网页界面会话。

每类报：调用条数（`assistant/message` 行数）、**自有调用数／拷贝来的调用数（两格分开，不许合成一个数）**、`input` 合计、`cacheRead` 合计、`cacheWrite` 合计、命中率（加权、**先按第二节口径全局去重再算**）、缺 `cacheReadTokens` 字段的条数（这些按 0 算，标推断）。**拷贝占比高的那一类必须标样本量**——拷贝吃掉的类，它那个命中率其实是别人的调用算出来的，样本量不写就等于骗人。

**样例表：行动脑会话按 `tier.ran` 拆开（标清：这不是正式读数，是样例）**

| `tier.ran` | 件数 | 调用行数 | 命中率 | `cacheWrite>0` 的行 |
|---|---|---|---|---|
| 高 | 5 | 102 | 93.52% | 102（全部） |
| 低 | 16 | 228 | 94.63% | 0（一行都没有） |

这张表必须跟着说的话：**样本小**；缺 `cacheReadTokens` 的行按 0 计入（**推断**）；**「低档没写缓存」只在行动脑这两类成立，不能推广到别的种类**（我的对话和网页界面会话里也有写缓存，六格⑤）。件数与行数当天就会旧。正式读数按这一节重跑，别抄这张表。

### ② 选高率

- 分母＝有 `tier` 字段的差事，**减去测试件**（判据 3，划出去的单独一栏并写明为什么）。
- 选高几次＝分母里 `tier.chosen=="高"`；占全部差事几成＝两个分母都写：「占有 `tier` 的」和「占全部」（判据 5：没有 `tier` 字段的不是「没选高」，是还没有这个选项）。
- 实际跑在高档几件＝`tier.ran=="高"`。
- 落档几件＝`tier.ran != tier.chosen`，**件数只从 `tasks.tier.fell` 字段数**（六格①：审计看不见「开工即落档」那一类，两个来源不能相加、也不能互查）；各因为什么读 `tier.fell` 的 `reason`（六格①四个取值）。库里 0 件时写「这七天没落过档」，**别写成「没有原因字段」**。
- `action_brain.tiers` 存哪儿没找到，不拿它补数。

### ③ 成败与拒

- 交回／卡住／取消／暂停＝`tasks.state` 的 `RETURNED`／`BLOCKED`／`CANCELLED`／`PAUSED`，按 `tier.ran` 分档；没有 `tier` 的单列一栏。其他状态（`DONE`／`RUNNING`／`UNKNOWN`／`NEEDS_CHARACTER_DECISION`）也列，别丢。**交回只等于交回**（判据 2）。
- 被拒按成因分（判据 4）：按六格④的八处逐处数。**`note.refused` 是 `role_tool` 的子集，不能相加**；`role_tool` 只有 52 条带 `code`，其余只有自由文本——**只数条数，按字面相同的短句聚类，不引原文长段**；`turn.rejected` 单独一处（回合级、不带工具名）；`tool.failed` 写「只到 09-25，近期无记录」；`episodes.rejections[]` 数非空回合数。每一类标「归我／不归我／分不出」，schema 必填所致不归我，分不出就写分不出。
- 步数和工具记录别混（判据 1），写明用的哪个计数器。

## 四、每周怎么跑

1. 先把第二节「八条口径判据」重读一遍，再开工。
2. 读数脚本已经在这个技能目录里：**`usage_readout.py`**（单文件、只读、打印到 stdout；六格各出一行，每行末尾带来源／筛法／读的时刻，⑥ 窗口排在最前当基准，「选高率」并进①）。跑法：`development_run`（project=core）里 `python3 skills/asuna-usage-readout/usage_readout.py`——默认窗口＝最近 24 小时，`--days N` 换天数，`--since`／`--until` 收本地钟点（六格⑥ 那种写死窗口就这么给）；`--selfcheck` 是不读盘不连库的纯逻辑模式，给 `check_skill.py` 跑通用；`--no-db` 只读盘。它解 `zstandard`、逐行 `json.loads`，**只取** `type`、`data.usage` 的五个数字、`data.message.id`、每一行的 `time`、目录名前缀和第一行的 `createdAt`（判拷贝用），不 print 行；库走 `asuna.dbread`（见技能 asuna-database），只取字段名列出的那几个字段，筛时间用本地钟点换出的 UTC 区间（同 `local_window`）。脚本没跑通之前照旧不报数（硬规矩 5）。每次跑先印第二·五节那张对账表（断言过了才印），六格在其后；对账表默认扫 home＋archive 两个根（`--no-archive` 只扫 home，覆盖面会写明）。
3. **先跨类全局去重（第二节口径那四条），再按类求和**；每类另报自有／拷贝两格。时间窗**按每一行的 `time` 切，不按整个文件切**（六格⑥）。
4. 输出三张表，每个数带来源＋读的时刻；推断与没验过的单独一节列出来。
5. 做到的标准：三张表齐、每张表头有时刻／来源／筛法、推断与没验过的有一节、没碰正文、**当天会旧的数都带读的时刻且没有一处抄上一版**；三个守卫各过一遍——凡写「本地」处带偏移量＋两种换算（或标「基准未定」），凡给编号处带出处（或标「编号未证」），凡报「某个字段缺了」处先过落盘字面与调用结构这两问（或写明没查）。少一样就写「没做完」。
6. 交给另一边核时，附这份技能第二节原文（含六格口径），她数出来跟我对上才算数；对不上先查口径哪一条两边不同、再查两边各是几点读的，不先改数。

## 五、会让读数出错的坑

1. **会话文件里的重复行是跨类拷贝，不是同类内重复**（要分窗口、逐条核，别拿全部历史的占比当窗口内的数）：
   - 两把判重键——`data.message.id` 与启发式（`time` ＋四个 token 数）——在 `assistant/message` 行上**行对行完全一致**（两趟独立数都是各自独有 0）。
   - **全部历史的重复占比 ≠ 窗口内的占比**（前者大得多）；报占比必须写明分母是全部历史还是窗口内。
   - **窗口内重复全在 `asuna-role-` 那一类**（今早 62 条、同一趟再数 98 条，全在这一类）。
   - **判重键只在跨文件时成立，同一文件内按 id 判重是 0 条**（同一趟实测 0 条）。所以「先去重」这件事必须跨会话、跨种类一起做，同类内去重等于没做。
   - 拷贝从哪来，已知两例（各标读的时刻）：
     - **差事从我的对话分叉**：窗口内 `asuna-errand` 105 条调用里 **98 条 `message.id` 与 `asuna-role` 相同，只有 7 条是它自己的**（数法只数 id、不读正文；两条脚本独立数一致＝105／98／7）。
     - **网页界面播种拷贝**：`isSeeded=true` ＋ 有 `parentSession` 的 `session-` 目录带着父会话早先的行，role/session 两前缀间 **74/309 条压缩 usage 组合出现在多个会话**，`cacheRead`、`input` 也被重复数（两趟独立数 74/309、74/311）。
   - 处置：按第二节口径那四条——全局按 id 归首次出现那一类、`time` 早于本会话 `createdAt` 的算拷贝、每类报自有／拷贝两格、拷贝占比高的标样本量。
2. **压缩那一行确实被数了两次**（成因已查到）：压缩行没有 `data.message.id`，只能按 usage 组合判——**74 个 usage 组合同时出现在 `asuna-role-` 与 `session-` 两个前缀下**（两趟独立数 74/309、74/311），带这些行的网页界面会话都是 `isSeeded=true` 带 `parentSession` 的那 4 个。组合相同＝**推断**为同一次调用（没有 id 可证）；去重时它靠口径第 2 条（`time` 早于本会话 `createdAt`）落回拷贝那一格。
3. **`review.tools_week` 库里可能已经有行**：现读 `audit_events` 里 `type=review.tools_week` 的行数，**别照抄上一版说「还没有」**。它的窗口仍是 `[这条记录 occurred_at − 7 天, occurred_at)`、不写进 payload。

### 审计清理对账怎么读（`audit.pruned`）

这一节存在的原因（两格都会让人重新踩）：**`seq` 空洞法对前缀删除天生是瞎的**；把库里 `+00:00` 结尾的 UTC 串当本地钟读会差 13 小时（本机 Auckland，UTC+13）。写时刻按硬规矩 8：原始 UTC ＋两种换算。

代码字面读自 `src/asuna/audit.py:prune`（`RETENTION_DAYS=30`、`KEPT_DAYS={'role_tool':365}`、`CAP_BYTES=6*10**9` 都在那个文件里）。

**① `by` 是「按规则计数」，不是列表**

- 字面：`before,by=cutoff,{'time':deleted} if deleted else {}`；size 那条规则另写 `by['size']=…`。
- 30 天那条与 `role_tool` 365 天那条是两次 `delete_many`，**两个 `deleted_count` 相加之后才写进同一个 `time` 键**——**哪条规则删的，分不开**。
- `by={}` ＝ 这一轮两条时间规则都没删到（size 那条也没触发，否则 `by` 里会多一个 `size` 键）。
- 库里现读（`audit_events` 里 `type=audit.pruned`）：带 `payload.by.size` 的 **0 行**——`size` 键只有代码字面，真数据里还没出现过，别把它写成实测见过的形状。

**② 对账要两把硬尺**

- 尺一：`collStats` 的 `wiredTiger.cursor` 里那个 **`remove calls`**。**不在 `metrics` 下**——同一份 `collStats` 里根本没有 `metrics` 块（现读 `s.get('metrics')` → None）。它**每个集合各算一份**（`wiredTiger.uri` 形如 `statistics:table:collection-…`；我拿另一个集合并排比过：审计这一格 `remove calls` 5159，另一格 0）。**mongod 重启就归零**（推断：计数器在进程里；重启归零这一格我没实测过），所以「一个窗口覆盖多次删除」只在没重启时成立——对账前先确认 mongod 没重启过。
- 尺二：**前缀缺口** `Σ(min(seq)−1)`，只算 `min>1` 的在世 stream。
- 两把尺不是一回事，别互相校：同一趟现读 `remove calls` 5159（与那两轮 `deleted` 之和 3891＋1268 逐字相等），前缀缺口只有 **1065**（6 条在世 stream）。**整条 stream 被删光的，前缀缺口看不见**——尺二是**下界**，要总数只能靠尺一。

**③ `seq` 空洞法 `Σ(max−min+1−n)` 只能证「没删过」，不能证「删了多少」**

- 为什么：prune 按 `occurred_at` 删最老＝**永远删前缀**，前缀删除在存活区间里**不留洞**。
- 实测反证：真删了几千条（`by` 形如 `{"time":N}`），同一趟空洞法仍是 **0**——所以这条判据不许改用空洞法。
- 用法：空洞 >0 → 一定有非前缀的删除（不是 prune 干的）；空洞 =0 → 什么都证不了。

**④ `payload.records` 的前后差会被并发写入污染**

- 字面：`records:[first.get('count',0),last.get('count',0)]`，`first` 是函数开头那次 `collStats`、`last` 是删完之后那次——中间别的写入照常进来。
- 实测：那两行 `deleted` 3891 对 `records` 差 3886、`deleted` 1268 对差 1263——**两轮各少 5 条，合起来 10 条**。
- 所以**以 `deleted` 为准**，前后差只当旁证。

**⑤ `CAP_BYTES=6e9` 比的是未压缩 `size`，不是盘上字节**

- 字面：`if stats.get('size',0)>cap`，`size` 是 collStats 的未压缩文档字节合计。
- 实测（同一趟）：`size` 3,285,465,453（3.29 GB 十进制）时 `storageSize` 只有 1,673,015,296（＝1.56 GiB，snappy 压过）。**报体积两个都给**，只给一个就有人当盘上字节读。

**顺手一句：`aggregate` 必须显式传大 limit，并检查回执里有没有 `more`。** `dbread.aggregate` 默认 `limit=50`（`LIMIT=50`），超出只回前 50 行、不报错，只在回执里多一句 `more`；上限又被 `MOST=500` 夹住，传 100000 也只回 500——要更多只能把管道聚合成 500 行以内（上面那两把尺就是把 `$group` 收到 1 行再取的）。

## 六、没验过的／待样本的（照实列，别美化）

- 行动脑个别目录为什么库里缺行（那些只有会话音、没有调用行）——**未查明**。
- 目录数与库里 `sessions` 行数对不上的不止行动脑一类（摘要 410 目录／6587 行、门 77／238、网页界面会话 25／7），**原因没查**；别拿一列校另一列。
- 拷贝行的「原件归谁」只按 `createdAt` 早的算——这条只在差事分叉和网页界面播种两例上验过，**没在别的种类上验过**。
- `turn.rejected` 与 `episodes.rejections[]` 是否同一批（六格④）。
- `episodes.rejections[]` 那几笔沿用旧计数，这趟未重查。
- `action_brain.tiers` 在库里的存储位置仍未找到。
- 样例表（第三节①）样本小，「低档没写缓存」只在行动脑两类成立——**没推广过**。
- 压缩行「同一行被两边各数一次」是**推断**（usage 组合＋`time` 完全相同，但没有 id 可证）。
- 任务总数与带 `tier` 的件数不写死在这里，跑的时候现读。
- 硬规矩 10 里那句「紧跟压缩／摘要之后的行前缀已作废」——**我没核**。只读到 DSH 压缩那一路反过来是刻意复用前缀的（`packages/compaction/compaction-basic/src/summarizer.ts` 的注释：把会话自己的 system prompt、tools 与消息前缀留在摘要调用前面，「so the provider's KV cache is reused instead of invalidated」），压缩**之后**那一次对话请求的前缀怎么变，我没读代码、也没在盘上量过。
- 硬规矩 10 那条「值为 0 就不写键」的字面只在我读过的那份适配器（pi-ai 那一路）里成立；**哪条 route 走哪个 provider 适配器我没核**（route 的 provider 在 DSH 的 Models 页配置，不在源码里），所以「缺 `cacheReadTokens` 按 0 计入」仍是**推断**。
- **provider 那一侧的原始响应日志开关我没找到现成的**：在 DSH 检出里搜 `rawResponse`／`logRaw`／`dumpResponse` 只撞到 `packages/llm/llm-pi-ai/src/replay.ts` 那种吃已捕获 response 信封的回放入口，不是开着就能落盘的日志——所以硬规矩 10 说「开日志是改动不是读数」。
