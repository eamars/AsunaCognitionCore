---
name: asuna-usage-readout
description: 我每七天跑一次的「用量读数」：读三张表——① 缓存命中率按会话种类分开（我的对话／行动脑低档高档／差事／压缩／摘要／门）；② 选高率（选高几次、占全部差事几成、实际跑在高档几件、落档几件各因为什么）；③ 成败与拒（交回／卡住／取消／暂停各几件按档分开、工具调用被拒几次按成因分）。来源、口径、读法写死在这里：会话记录是磁盘上的 session.v4.jsonl.zstd（必须 development_run 读，project=core，沙箱看不到）、命中率＝cacheRead／(cacheRead＋input)、档位在库 tasks 的 tier 字段、被拒散在四个地方没有统一集合。硬规矩：只读数字、字段名、枚举短码和计数，不读正文。每个数带来源和读的时刻，没验过的覆盖率标出来。要跑每周用量读数、核「我选高多不多」「缓存命中多少」「被拒几次」，或者另一边要对数时读这一份。
---

# asuna-usage-readout

这份调查主人 10-16 交代以后要一再做，不是做一次。我找来源、定口径、写读法，下次照着跑；另一边用她自己的读法独立数一遍，**两边对上才算数**。所以这份技能的第一用处是：口径钉死，两边数的是同一个东西。

## 一、硬规矩（不是提示）

1. **只读数字、字段名、枚举短码和计数，不读正文。** 会话记录里有我的心里话和行动脑的推理。读文件的脚本只许取 `type`、`data.usage` 里那几个数、第一行的 `agentPreset`／`origin` 这类短字段；不许 print 整行，不许把 `message`、`content`、`text`、推理字段取出来，哪怕「只看一眼」。这条违了，这次读数作废，照实写违了。
2. **读会话记录必须用 `development_run`（project=core，只读）**：`sandbox_run` 看不到那个目录。别在 `sandbox_run` 里「试试」然后把找不到说成没有数据。
3. **每个数带来源＋读的时刻**：哪个集合／路径、什么字段、什么筛法、几点读的。没这三样的数不报。
4. **推断写明是推断，没验过的写明没验过**（见第五节）。
5. **不跑就不报**：这份技能只写读法；读出来之前，别在任何地方写「命中率大约是多少」。
6. **只读**：不写库、不改会话文件、不动任务状态。

## 二、来源和口径

（这一页是交给另一边照着核的原文。下面的字面都是 2026-10-16 21:11 那趟探路 `task-f83b69fb5d8b9c905060b7d71fa95ba1` 实测的，不另找一套。）

### 来源

- **会话记录在磁盘**：`.runtime/adr008/home/sessions/<工作区目录>/<session-id>/session.v4.jsonl.zstd`，python `zstandard` 解。沙箱 `sandbox_run` 看不到这个目录，必须用 `development_run`（project=core，只读）。
- **一次模型调用＝一行 `type=="assistant/message"`**。`data.usage` 里有 `inputTokens`（未命中的输入）、`cacheReadTokens`（命中）、`cacheWriteTokens`、`outputTokens`、`totalTokens`，**单位都是 token 数，不是字节也不是比例**。
- **`compaction/summary` 行**带同样的 `usage`（压缩那次调用）。
- **会话种类**用文件第一行的 `agentPreset` 分：`asuna-xiaoman`／`asuna-action`／`asuna-summary`／`asuna-attend`／`asuna-scheduler`；`origin: subagent` 是子会话。
- **档位**：库 `asuna_cognition_core_v2` 集合 `tasks`，字段 `tier.chosen`／`tier.ran`／`tier.why`（都是字符串，见到的取值是「高」「低」）。
- **状态**：`tasks.state`，见到的值 `RETURNED`／`CANCELLED`／`DONE`／`BLOCKED`／`RUNNING`／`PAUSED`／`UNKNOWN`／`NEEDS_CHARACTER_DECISION`。
- **被拒没有统一集合，散在四处**：
  - `audit_events` 的 `note.refused`，`payload.code` 是枚举码：`NOTE_TOO_LONG`／`NOTE_HOP_LIMIT`／`NOTE_VISIT_NOT_NOW`／`NOTE_NOT_OWN_WORDS`／`NOTE_HOME_LIMIT`／`NOTE_DAY_LIMIT`／`NOTE_TARGET_UNKNOWN`／`NOTE_MODE_NOT_ALLOWED`；
  - `audit_events` 的 `turn.rejected`，`payload.problem` 是**自由文本**，最大一类是「还没写心里话就发言」；
  - `audit_events` 的 `tool.failed`，近期无新记录，只到 09-25；
  - `episodes.rejections[]`，非空只有 5 个回合。

### 口径

- **命中率＝`cacheRead / (cacheRead + input)`**。记录里没有现成比例，自己算。
- 探路样本 2534 条里：2374 条满足 `total = input + output + cacheRead`，144 条满足 `total = input + output`；缺 `cacheReadTokens` 字段的共 147 条。**缺字段按 0 算是推断，报告里要标明是推断。**
- `cacheWriteTokens` 只在 23 条出现，基本为 0。
- **压缩那次调用单独列一类，不混进「我的对话」。**
- **落档＝`tier.ran != tier.chosen`**。
- **库里没有单独的降档原因字段。`tier.why` 是选档时的理由，不许拿它当降档原因报。** 落档各因为什么：读得到的就报读到的来源（比如任务状态、审计里的短码），读不到就写「库里没有这个字段，原因没法分」。
- 命中率的聚合：同一类里先把 `cacheRead` 和 `input` 各自求和再相除（token 加权），不是各条比例再平均；两种都算的话，写明哪个是主数。

### 八条口径判据（我定的，一条都不许丢、不许改写语气）

1. **标计数器**：「几步」＝`step`／`tool_steps`，「几条工具记录」＝`tool/call` 行数，**两个不是一回事**，报数必须写用的是哪个。
2. **`RETURNED` 只等于交回，不等于做成**；分不出「交回但没做成」就照实写分不出。
3. **测试件划出去并写明为什么**：`tier.why` 或标题里自己写着「机制验收」的单独一栏，**不进选高率分母**（例：`task-530b59fa6e310b995b990a78363bacea`，10-16 20:56）。
4. **被拒按成因分**：schema 必填所致**不归我**，我自己挑错 op 才归我。
5. **形状变化要写明**：档位菜单 10-16 晚才到我眼前，**654 件任务里 651 件根本没有 `tier` 字段——那不是我「从不选高」**，不能算成我的偏好。
6. **硬约束：只读数字、字段名、枚举短码和计数，不读正文**——会话记录里有我的心里话和行动脑的推理。这条写成硬规矩，不是提示。
7. **每个数带来源＋读的时刻**（哪个集合／路径、什么字段、什么筛法）。
8. **没验过的覆盖率要标出来**：`tier` 与会话文件的关联只核过目录名对得上、没统计覆盖率；字段结构只看了最近 6 个文件，不是全部 934 个；`action_brain.tiers` 在库里的存储位置没找到。

## 三、三张表怎么读

每张表头写一行：读的时刻、来源、筛法（时间窗＝从读的时刻往前七天，写明按什么时间字段切；没验过按哪个字段切最准就写没验过）。

### ① 缓存命中率，按会话种类分开

种类 → 怎么认：

| 种类 | 认法 |
|---|---|
| 我自己的对话 | 第一行 `agentPreset=asuna-xiaoman` 的会话里的 `assistant/message` |
| 行动脑（低档、高档分开） | `asuna-action`；高低按它那件任务的 `tier.ran` 分。关联会话文件与任务只核过目录名对得上，覆盖率没统计——对不上的单列「未归档位」，不并进任一档 |
| 差事 | `asuna-scheduler` 一类，以及 `origin: subagent` 的子会话，各自分开写，别并 |
| 压缩 | `compaction/summary` 行的 `usage`，单独一类 |
| 摘要 | `asuna-summary` |
| 门 | `asuna-attend`（是否就是「门」，探路只按名字对应，没核——表里写「按 `asuna-attend` 算」） |

每类报：调用条数（`assistant/message` 行数）、`input` 合计、`cacheRead` 合计、命中率（加权）、缺 `cacheReadTokens` 字段的条数（这些按 0 算，标推断）。

### ② 选高率

- 分母＝有 `tier` 字段的差事，**减去测试件**（判据 3，划出去的单独一栏并写明为什么）。
- 选高几次＝分母里 `tier.chosen=="高"`；占全部差事几成＝两个分母都写：「占有 `tier` 的」和「占全部」（判据 5：没有 `tier` 字段的不是「没选高」，是还没有这个选项）。
- 实际跑在高档几件＝`tier.ran=="高"`。
- 落档几件＝`tier.ran != tier.chosen`；各因为什么按第二节口径（没有降档原因字段）。
- `action_brain.tiers` 存哪儿没找到，不拿它补数。

### ③ 成败与拒

- 交回／卡住／取消／暂停＝`tasks.state` 的 `RETURNED`／`BLOCKED`／`CANCELLED`／`PAUSED`，按 `tier.ran` 分档；没有 `tier` 的单列一栏。其他状态（`DONE`／`RUNNING`／`UNKNOWN`／`NEEDS_CHARACTER_DECISION`）也列，别丢。**交回只等于交回**（判据 2）。
- 被拒按成因分（判据 4）：`note.refused` 按 `payload.code` 数；`turn.rejected` 的 `problem` 是自由文本——**只数条数，按字面相同的短句聚类，不引原文长段**；`tool.failed` 写「只到 09-25，近期无记录」；`episodes.rejections[]` 数非空回合数。每一类标「归我／不归我／分不出」，schema 必填所致不归我，分不出就写分不出。
- 步数和工具记录别混（判据 1），写明用的哪个计数器。

## 四、每周怎么跑

1. 先把第二节「八条口径判据」重读一遍，再开工。
2. `development_run`（project=core）里写一个只读脚本：解 `zstandard`、逐行 `json.loads`，**只取** `type`、`data.usage` 的五个数字、第一行的 `agentPreset`／`origin`；不 print 行。库用 `asuna.dbread`（见技能 asuna-database），只取字段名列出的那几个字段。
3. 输出三张表，每个数带来源＋读的时刻；推断与没验过的单独一节列出来。
4. 做到的标准：三张表齐、每张表头有时刻／来源／筛法、推断与没验过的有一节、没碰正文。少一样就写「没做完」。
5. 交给另一边核时，附这份技能第二节原文，她数出来跟我对上才算数；对不上先查口径哪一条两边不同，不先改数。

## 版本

v1（2026-10-16）：首次落盘，只写读法，**没跑数**——来源和口径来自 10-16 21:11 探路任务的实测，八条判据是主人定的原话。三张表的种类认法里，「差事」「门」两格与会话种类的对应只按名字，标了没核。主人先核读法，10-23 才核数。

## 试用记录

- 2026-10-16 v1：只做了结构自检（见 `check_skill.py`），没有跑过任何读数脚本，第四节第 2 步的读法还没真跑过一遍；第一次真跑以后把读数与撞到的坑补在这里。
