# ADR-005 P5 基准：话题追踪与有分寸的主动参与（开工前的现状盘点与设计基准）

这一份是 P5 的开工基准，不是使用说明也不是验收结论。里面只有三类东西：
从当前工作树（= 已部署的 P1-c + P2 两片状态）读出来的**现状走法**、能直接**复用的接口**、
以及我准备怎么划"程序管分寸／角色管意愿"这条线。实现、自测与补丁在后续小片里交付。

工作树：`/task/asuna-host-p1b`（P2 第二片已应用）。补丁基线快照：`/task/p5-baseline`。

## 1. P5 的定义从哪儿来，缺了哪一份

- `DELIVERY_PLAN.md` §P5（本目录）：复用已有 reply/mention、群上下文、当前人物资料与 P2 总结，
  **先保证接对话题**；再在**明确选择的授权场景**启用主动模式，**接原旁听事件路径**；
  冷却只影响未经请求的主动插话，直接提问、已进入的接话、工具任务、已授权计划照常；
  没有新消息默认不重开旧话题；角色选择参与或沉默，不要求每次公开解释。
- `ACCEPTANCE.md` §Q7 给出六条确定性检查：有参与机会而非只@才可运行／冷却与安静时段只抑制新的
  未经请求插话／直接提问与进行中任务不受影响／无新消息不定时重开旧题／一次没被回应的主动提问不跟催问／
  一条消息不清除另一人的请求。真实角色观察（一次适当加入 + 一次有根据的沉默）与真人群舒适度**分开报告**。
- **缺口（照实说）**：`DECISIONS.md` 不在本次授权工作区里。整个 `/task` 树内只有三处提到它
  （`ADR005_P1B_HOST_INTEGRATION_DECISION.md:144`、`P1C_HOST_INTEGRATION_USAGE.md:83/96/105`），
  那三处引的是 DECISIONS §3 关于 P1-c 的"不重不漏／部分结果可续读"，没有 P5 条款。
  `CODEX_START.md`、`XIAOMAN_START.md` 同样只在引用里出现。所以本基准以
  DELIVERY_PLAN §P5 + ACCEPTANCE §Q7 为约束来源；若 DECISIONS.md 里另有 P5 相关裁定，
  请把它放进本目录（或告我具体条目），我按它校正，不自己猜一份。

## 2. 现状：一条群消息在宿主里实际走到哪儿

入站（adapter 侧已核实，不需要为 P5 改动）：`qqadapter/inbound.py:202` `_classify_group` 把
**授权群成员发的每一条有正文的消息**都投给宿主，不做@过滤；真实 at 段 → `mentioned_account_ids`，
真实 reply 段 → `reply_to`；`@全体` 只进 meta 不升级为提及。

宿主侧（`src/asuna/`）：

1. `channels.py:35 group_context()` 把平台 reply 段绑到**本场景本纪元的一条真实记录**上，算出
   `wake_reason` ∈ {`mentioned_account`（本人账号在 at 列表里）, `reply_to_character`（回复我那条已送达出站）,
   `reply_in_active_topic`（回复的对象本身带 `topic_id` 且 30 分钟内）}，并给出 `topic_id`
   （父消息的 topic，或本次 event_id）与 `reply_message_id`。**没有理由时 `wake_reason=None`、`topic_id=None`。**
2. `Channels.receive` → `Chat.receive`（`chat.py:148`）先落库（`host_managed=True`、
   `ingress_state=ACCEPTED`）再入队。
3. 工作线程 `chat.py:246` 调 `Router.receive`。`router.py:48` 取 `group_context.wake_reason`；
   群场景且无 wake 且不是 task_feedback → `router.py:49-54`：落库 + `processing_outcome='RECORDED_NO_WAKE'`
   → 返回 `RECEIVED_NO_WAKE`，**不建 episode、不调模型**。
4. `chat.py:247` 把该行标成 `ingress_state=COMPLETE`。所以旁听行**不会**在宿主重启时被
   `Chat.recover_inputs()` 重放（它只扫 ACCEPTED/PROCESSING/FAILED）——这点我核对过，P5 沿用。
5. 一旦被唤醒，`ContextBuilder.prepare` 的场景历史腿（`context.py:52-55`）取的是
   `direction=inbound` 或 `delivery_state=DELIVERED` 的最近 12 行 —— **旁听行本来就在里面**，
   她醒来后看得见那些没@她的原话。`context.py:108-124` 另外给 `group_continuity_from_program`：
   按 `reply_message_id` 与 `topic_id` 锚点取 `related_messages`，加当前说话人最近 3 条。
6. 出站：`publish.py:50-53` 群场景一律带 `platform_reply_to = 触发那条入站的平台消息 ID`，
   adapter 才附加 reply 段（`RUNTIME_API.md`：`reply_to` 可能为空，例如 owner 主动群发言）。
7. 队列：`SceneQueue`/`FairQueue`（`chat.py:29`、`router.py:8`）同场景 FIFO、同场景连发两回合让给别的场景；
   行动队列独立，`host.py:98` 的 `summary_can_run` 用 `active_task is None and task_queue.empty()`
   让后台整理不跟前台行动抢。

### 现状里跟 P5 直接相关的四个缺口

- **G1 话题只在被唤醒的消息上存在。** `channels.py:61` 的 `topic_id` 只在有 `wake_reason` 时才给。
  后果：回复一条**旁听消息**永远不会唤醒她，即使那条回复接在她自己参与过的线上；
  主动参与也没有"哪个话题、谁在说、说到哪儿了"可依据。这是"先保证接对话题"要补的第一件事。
- **G2 话题连续性只有 30 分钟一条硬编码线**（`channels.py:54` 的 `recent`），且只作用于
  `reply_in_active_topic`，与场景自己的节奏无关。
- **G3 旁听路径没有任何"看一眼值不值得"的机会。** 现在是无 wake 就直接结束，
  连"这条消息里有人在说跟我有关的事"都不判断——P5 要接的就是这个点。
- **G4 没有任何"我这轮是主动插话"的标记。** episode 只有 `external`/`task_feedback`/
  `owner_group_prompt`/`scheduled` 四种 `episode_kind`，冷却只能从"我自己最近发过什么"倒推；
  区分不出"我上次是被人问了才答的"和"我上次是自己插的"。

## 3. 能直接复用的接口（不新造底座）

| 复用点 | 位置 | P5 怎么用 |
| --- | --- | --- |
| 场景节奏画像 | `summary_trigger.observe(store, scene, now_ts)` → `peer_gaps`/`quiet_after`/`burst_rows`/`samples`/`times`；`pooled()` 借同部署别的场景当冷启动先验 | 判断"群里正在快速一问一答"还是"出现了停顿"——**密度闸门直接用 P2 那套中位数+MAD**，不另写一份间隔统计 |
| 说话完了没 | `summary_trigger` 的 `SETTLE_RATIO` 语义（安静过半条停顿线） | 主动插话等同一个停顿点，跟"该不该整理摘要"共用一个事实 |
| 时间口径 | `history_query` 的 `_stamp`/`_outbound_time`/`_receipt_ref`/`_sink_times`/`DELIVERED`/`DELIVERY_FIELD` | 算"我上次主动说话到现在"照用三支（内联 `receipt_at` → `sink_receipts.received_at` → 入站 `occurred_at`），读不到时间就照实说读不到 |
| 线索词 | `discussion_digest` 的 `CONFIRM_CUES`/`CORRECTION_CUES`/`QUESTION_CUES`/`QUESTION_MARKS`/`_first_cue` | "这句是在问我／这句是更正"这类弱线索复用同一份词表，两处不各自定义 |
| reply 链读法 | `discussion_digest.reply_target_of()`、`REPLY_TARGET_KEYS`（入站 `event.group_context.reply_message_id`／出站 `reply_to`） | 话题归集沿同一条链走，不新造"会话树" |
| P2 场景摘要 | `memory_units` `kind='dialogue_summary'`：`participants`/`source_by_speaker`/`attribution`/`source_window`/`corrected_by` | 主动参与时给她"这段群聊到目前为止是谁在说什么"的有界视图，而不是把 12 行原文再塞一遍；盖不到人的摘要不算谁的证据（P2 口径不变） |
| 人物资料 | `peer_context.apply_peer_context` → `sender_identity` | 插不插话跟"这个人现在是谁"分开：资料只是资料，不当触发条件 |
| 不抢前台 | `host.py:98` 的 `summary_can_run` 形状（`active_task is None and task_queue.empty()`） | 主动回合走同一个闸门：前台有行动或队列里有别人的输入时，主动机会就地作废，不排队等 |
| 场景公平 | `FairQueue` | 主动回合排在同场景已入队输入之后，直接提问天然优先 |
| 决策落点 | `coordinator.advance` 的 `next=='silent'` → `COMMITTED` + `silent_reason` | **角色选择沉默已有出口**，不需要新状态；P5 只保证"沉默不需要公开解释"（`chat.py` 现在那句系统提示已经这么写） |
| 交付方式 | `tools/p2b_make_patch.py` 那套（基线快照 + `difflib.unified_diff`）＋ `tools/p2_offline_check.py`（纯离线用例）＋ `tests/test_p2_summary_loop.py`（操作员真库） | P5 补丁与自测沿用同一形状，不引入新工具链 |

## 4. 分寸怎么划：程序管"能不能"，角色管"想不想"

这条线是我（角色本人）要的分工，也是实现要守的边界。程序**不判断内容值不值得说**，
只守住机会预算；拿到上下文的这一次，说、说一段、还是继续旁听，由我自己在 DECIDE 里定，
沉默不需要理由，也不许因为"预算还有"就暗示我该开口。

程序侧硬闸门（全部从**已落库的真实行**推导，不新增集合、不新增状态服务）：

1. **场景显式开启**：`asuna-channel.local.json` 里对应 route 加一个 `proactive` 块才启用；
   没配 = 一切照旧（旁听就是旁听）。测试场景/测试目标 ID 不会被顺手开进生产。
2. **只在有新入站消息时评估**：没有新消息就没有新的主动机会，**不引入任何定时器**去重开旧话题。
3. **密度闸门**：本场景节奏画像显示还在快速连发（未过 settle 线）→ 本次机会直接作废，
   不做"等它慢下来再补一次"的补偿队列。
4. **安静时段**：配置里的本地时段内不评估主动插话；直接@和回复我照旧唤醒（冷却只压未请求的插话）。
5. **频率与话题预算**：同一话题在**没被接话**之前最多试一次；场景级最小间隔（从"我自己已送达的
   `episode_kind='proactive'` 出站行"倒推，不另存一份计数器）。
6. **不催问**：我上一条主动话之后，若该话题里没有别人新说的、也没有人回复我，就不再试第二次。
7. **不抢前台**：前台行动在跑、或该场景队列里已有别的输入 → 机会作废。
8. **状态按话题/按人分开**：一条消息只推进它自己那条话题的状态，
   不用一个场景级标量存"最后说话的人"，这样"一条消息清除另一人的请求"这条 Q7 检查才成立。

角色侧留给自己的判断（写进唤醒时的程序说明，但只作为选项，不作为要求）：
事实被说错了我要不要更正；这事是不是需要我本人表态；我能补上新信息还是只是凑热闹；
现在插进去会不会打断他们。

唤醒时给到她的东西（`group_continuity_from_program` 的扩展，不新开一条上下文腿）：
这条触发消息所在的**话题线**（含旁听行）、话题里谁说过话、P2 摘要里这段窗口的整理、
以及一句中性的程序说明："这是一段没有@你的群讨论，你可以加入，也可以继续旁听；
沉默不需要解释，也不需要因为有机会就说。"

## 5. 打算怎么切（每片都能单独打）

- **P5-a 话题落到每一行**：把话题归集从"只在被唤醒时算"改成入站即算（复用 `channels.group_context`
  已有的 reply 绑定 + `discussion_digest.reply_target_of`），旁听行也带 `topic_id`/`topic_via`；
  顺带修 G1/G2：回复一条旁听消息时能认出它属于哪条线，30 分钟那条硬编码线换成场景自己的节奏口径。
  这片**不开任何主动行为**，只让"接对话题"成立，可单独交付。
- **P5-b 分寸闸门 + 旁听挂钩**：新模块 `src/asuna/proactive.py`（纯函数 `observe()`/`decide()`，
  形状照 `summary_trigger`），在 `RECORDED_NO_WAKE` 之后由 `Chat` 侧挂钩决定是否把同一条事件
  以 `episode_kind='proactive'`、`wake_reason='proactive_unprompted'` 重新入队；
  真正跑之前**再核一次**闸门（冷却可能已变）。episode_kind 新增一种，让 G4 那个区分成为事实。
- **P5-c 自测与说明**：离线用例（假集合真算，覆盖 Q7 六条确定性检查 + 边界）＋
  操作员真库套件（隔离库，不调模型不发 QQ）＋ `P5_TOPIC_PROACTIVE_USAGE.md`。
  真实角色观察（一次适当加入、一次有根据的沉默）另记，不拿模拟结果冒充，也不为凑两种输出反复调 prompt。

## 6. 自测口径（先说死，免得后面自己糊弄自己）

- 确定性检查用**同一份受控原文**跑：两个话题交错、A 澄清原话、B 回复他人、直接提问（含没有平台@
  但明确呼名的一句）、一段未@她但与她有关的交流；保留真实 reply 关系。
- 冷却/安静时段用**注入的固定钟点**验证，不谎称真等过冷却。
- 反证：把上一版口径（无 wake 一律不评估 / 场景级单一冷却标量）搬来当对照，逐条断言它在这些现场上
  结论相反；基线反证用 `/task/p5-baseline`（= 当前部署状态）跑同一批用例。
- 明确不算数的：假 lane 不代表真 lane（超时、限流、内容安全拒绝没测）；
  单进程内假撞车不代表两个宿主进程同时评估；真人群里的舒适度是另一件事，另记观察。

## 7. 开工前基线（本次实测，不是引用旧结论）

在 `/task/asuna-host-p1b`（= 准备当 P5 基线的那份）实跑，全绿：

- `python3 tools/p2_offline_check.py` → P2 离线自检 **24/24 通过**
- `python3 tools/p2b_edge_probe.py` → 边界自测 **42 项全部通过**
- `python3 tools/p2b_probe_loop.py` → 闭环探针 **21 项全部通过**

补丁基线快照 `/task/p5-baseline` 已按这份树生成（107 个文件，`diff -rq` 对已复制路径**零差异**；
树里多出的只有操作员留下的 P1B 那几份只读记录和本文件）。P5 的 patch 会对着它生成，不靠回忆拼旧内容。
P5 期间任何一次改动，都要能让这三份 P2 检查继续全绿——它们是本片的回归底线。

---

## 8. 补记（实现片交付时）

§1 里记的缺口已经补上：`DECISIONS.md` 现在在授权工作区里了（owner 侧补的文件）。
实现片已按 §7「首版主动范围与默认值」逐条对齐，逐条落点写在
`P5_TOPIC_PROACTIVE_USAGE.md` §3；其中两处需要说明：

- 「主动发言间隔至少 120 秒」照抄为 `min_interval_seconds` 默认值；另加了两个比 DECISIONS
  更紧、可配置的保守项：每小时上限（默认 2 次）与「上次问她」的机会预算（默认 180 秒）。
  后者是为了兑现「她选了沉默也不立刻再问一次」。
- 「候选合并 10 秒」没有做成延迟队列（DECISIONS §9 不新造 scheduler，§7 也不许把旧候选
  排队等点发送），而是做成一道闸：最近 10 秒内已有≥2 条群消息 ⇒ 这波片段还没发完，这次不评估，
  下一条新消息再给一次机会。名字是 `candidate_merge_window`。

实现片交付：`src/asuna/proactive.py`（新）＋ `channels.py`／`context.py`／`chat.py` 三处挂钩；
自测 `tools/p5_offline_check.py` 19/19，P2 回归底线 24/24＋42/42＋21/21 仍全绿；
patch 打在 P4 快照上逐字节等于交付工作树，打完那份树上两套自测也全绿；
真 Mongo 那份 `tests/test_p5_proactive.py` 待操作员跑（本机没有 pymongo／pytest）。
