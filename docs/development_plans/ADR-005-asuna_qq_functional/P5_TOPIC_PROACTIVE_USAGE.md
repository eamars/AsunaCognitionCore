# P5 话题追踪＋有分寸的主动参与：用法与边界

对应 DECISIONS §7、DELIVERY_PLAN §P5、ACCEPTANCE §Q7。改动只有四个文件：
新增 `src/asuna/proactive.py`，在 `channels.py`／`context.py`／`chat.py` 各挂一处。
没有新集合、没有新服务、没有新定时器；不打开开关的场景行为与今天完全一致。

## 1. 怎么打开（按场景 opt-in，一处配置）

在现有 `channels.<通道>.routes.<路由>` 里加一个 `proactive` 块：

```json
"proactive": {
  "enabled": true,
  "utc_offset_minutes": 480,
  "quiet_hours": [["23:00", "08:00"]],
  "merge_window_seconds": 10,
  "min_interval_seconds": 120,
  "probe_interval_seconds": 180,
  "max_per_hour": 2,
  "dense_max_gap_seconds": 30,
  "urgent_cues": ["紧急", "急事", "故障", "崩了", "挂了", "报错", "出问题了", "救命"]
}
```

- 没这个块、或 `enabled` 不是 `true` ⇒ 一律不评估（`not_enrolled`），旁听行一个字段都不多写。
- 私聊场景不看这个开关：`not_a_group_scene` 直接拦（DECISIONS：私聊默认不主动开题）。
- owner 建议先只给一个现有授权群打开，其余群留关。
- 回滚＝删掉这个块。没有需要迁移的状态：所有判断都从已落库的行现算。

## 2. 一条没@她的群消息的走法

1. adapter 照旧把授权群里每条有正文的消息投进宿主（P5 不改 adapter）。
2. `channels.group_context()` 给这一行算出 `topic_id`／`topic_via`；唤醒口径一个字没改：
   只有@她、回她说的话、或回一条"本身被唤醒过"的近期消息才算接话。
3. 落库 → `router.receive()` → 没有 wake_reason ⇒ `RECEIVED_NO_WAKE`，不调模型（P2 之前就这样）。
4. 落库之后，`chat._proactive_consider()` 才做一次分寸判断：`proactive.observe()` 从真实行里读
   现况，`decide()` 过闸门。拦下来就把闸门名单写进那一行（`PROACTIVE_HOLD`）＋一条证据，结束。
5. 放行则把**同一条入站行**升级为主动回合（`wake_reason=proactive_unprompted`、
   `PROACTIVE_WAKE`），按原事件重新入队——不新增一行原文，`episode_kind` 仍是 external。
6. 出队真要跑之前 `_proactive_stale()` 再核一次闸门：这中间她可能已经说过一句、或前台开始忙了。
   拦下就标 `PROACTIVE_HELD`，不建 episode、不调模型。再核只认 `wake_reason=proactive_unprompted`
   的那几行——被@的接话照跑，一个字段都不多写。
7. 上下文里她看到的是整条话题线（含没@她的旁听行）＋一句中性说明：可以加入，也可以继续旁听，
   沉默不需要理由。说多少、说不说，仍是角色自己定；程序只回答"现在能不能问一句"。

## 3. 闸门名单（拦下时 `proactive.holds` 里会出现的名字）

| 闸门 | 拦的是什么 | 依据／怎么调 |
|---|---|---|
| `not_enrolled` | 这个场景没开主动模式 | route 的 `proactive` 块 |
| `not_a_group_scene` | 私聊／非群场景 | 不可调（DECISIONS） |
| `trigger_without_time` | 触发行读不到发生时间 | 不拿写入时间或序号冒充，照实拦 |
| `quiet_hours` | 安静时段（默认 23:00–08:00，按 `utc_offset_minutes`） | `quiet_hours` 可改可清空；`urgent_cues` 命中只放宽这一道闸 |
| `candidate_merge_window` | 最近 10 秒内已有≥2 条群消息：这波片段还没发完 | `merge_window_seconds`（0＝关掉）。不排队等、不逐条回 |
| `dense_exchange` | 最近≤6 个到达间隔中位数 ≤30 秒、且 < 本场景停顿线一半：正在快速一问一答 | `dense_max_gap_seconds`；停顿线复用 P2 的实测节奏（`quiet_after`） |
| `probe_cooldown` | 距上次"问她要不要说"不足 180 秒（她选了沉默也算问过） | `probe_interval_seconds` |
| `scene_cooldown` | 距上次**已送达**的主动插话不足 120 秒 | `min_interval_seconds`（DECISIONS §7 的 120 秒） |
| `hourly_cap` | 本场景一小时内已主动开口≥2 次 | `max_per_hour`（我加的保守项，比 DECISIONS 更紧） |
| `topic_attempt_unanswered` | 这条话题上我插过一句、没人明确接话 | 不可调：不催问。无关的新消息不算"接了" |
| `foreground_busy` | 前台行动在跑，或本场景队列里已排着别人的输入 | 不可调：直接请求与任务反馈永远优先 |

被@、回她说的话、已进入对话的接话、任务反馈与已授权计划**都不走这套闸门**：
它们在 `router` 里就醒了，`_proactive_consider()` 只在 `RECEIVED_NO_WAKE` 的旁听行上被调用。

## 4. 看得见的东西

- 那一行入站记录上：`processing_outcome`（`PROACTIVE_WAKE`／`PROACTIVE_HOLD`）与
  `proactive`（`wake`、`holds`、`signals`、`quiet_after`、`dense_median`、`burst_rows`、
  `since_wake`、`since_utterance`、`utterances_last_hour`、`topic_attempts`、`topic_responded`、
  `local_minutes`、`urgent_cue`、`note`；再核拦下时另有 `recheck_hold`／`recheck_at`）。
- 证据链：`proactive.wake`／`proactive.hold`／`proactive.enqueued`，都带闸门名单。
- 出站侧不新增标记：发送仍走既有发布通道，宿主侧靠 `wake_reason=proactive_unprompted` 分辨
  这是她自己插的话，不是别人问她。
- 操作者界面按已有通用行展示即可（DECISIONS §8：主动参与／沉默的原因类别＝`holds` 名单）。

## 5. 自测口径

- `python3 tools/p5_offline_check.py` ⇒ **19/19 通过**（假集合真算，无 Mongo／无 pytest／无模型）。
  覆盖 ACCEPTANCE §Q7 六条确定性检查＋owner 四条硬约束＋DECISIONS §7 表格逐条，
  外加两条护栏：主动这条腿自己炸了不许把一轮变成用户看得见的报错；再核不许拦下被@的那条接话。
- 基线反证：`--baseline`（四个文件换回 P4）与 `--hooks`（只回退三处挂钩）下这批用例都跑不起来，
  说明它们测的确实是这次的改动，不是自说自话。
- patch 本身也验过：`tools/p5_apply_patch.py` 把 `/task/P5_TOPIC_PROACTIVE.patch` 打在 P4 快照上，
  11 处上下文全对得上，结果与交付工作树逐字节一致；那份打完的树上 P5 19/19、P2 24/24 照样绿。
- P2 回归底线仍全绿：`tools/p2_offline_check.py` 24/24、`tools/p2b_edge_probe.py` 42/42、
  `tools/p2b_probe_loop.py` 21/21。P2 的唤醒口径、自适应触发、摘要闭环都没被改动语义。
- 真 Mongo 那一层由操作员跑 `tests/test_p5_proactive.py`（固定授权库
  `asuna_v2_test_p5_host_20260924`，`ASUNA_P5_CONFIG`／`ASUNA_P5_DATABASE` 可换）：
  真驱动、真集合校验、真 CAS，外加把离线用例与 P2 那批一起跑一遍防漂移。**本机开发域没有
  pymongo／pytest，这份还没跑过**，不冒充已验证。
- 没测的：真 lane、真群里的舒适度、多群并发下的实际观感。这些要 owner 真打开一个场景才知道。

## 6. 有意没做的

- 不建"每话题 agent"、知识图谱或全消息前置分类服务：话题号只从 reply／mention／已有行派生。
- 不做"候选排队等点发送"：冷却到期不会自动生成一句话，也没有新 scheduler（DECISIONS §9）。
  这波片段没发完就只是不评估，下一条新消息再给一次机会；没有"欠发言"。
- 不替角色算"要不要说"的分：闸门只回答"能不能问一句"。
- 语义上的话题延续／转移暂不自动判定（一条消息可以涉及两个主题），先只用可核对的 reply 链；
  误判可以事后由摘要更正，不靠猜。
