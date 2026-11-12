---
name: asuna-dsh-failure-scan
description: 我家程序（认知核＋宿主 DSH）这一层失败的一键扫描：一条脚本把时间窗内两类失败全列出来——一类带报错行（关口被引擎拒、回合／行动脑／摘要／向量环节抛异常、上游非 2xx、进程非零退出、任务级异常），一类是静默没跑、只有执行记录能证明它缺席（关口该判没判、请求发出去没回、宿主或 worker 停过、该响的拍没响、任务卡住没回执），另有一组计划没排上／晚交到（`schedule.*` 五个 type）。用在每日晨扫（放在每日自省之后）和「这一段时间是不是有什么没跑」的核对上。口径写死：四组分开数（A 带报错行／B 静默没跑／D 计划没排上／晚交到／C 对照＝伴生句与我自己的工具被拒，不计入失败总数）；合计报的是记录数，同一件事同落 A 与 B 两面时另报按事件去重的件数（两笔账谁也不冒充谁）；窗口超出保留期就顶部打一行「可能数少（超出保留期）」，不许静默；数出 0 只报「库里没有」，不写「没发生过」；名单外的 audit type 一行都不数；每型给条数＋首末本地时刻＋最多三条样例行；窗口是本地钟点且偏移现读配对不背常数；全零输出一行 0；有面没读到不许印光一个 0。附计划延迟分档（plans.next_fire_at ↔ schedule.dispatched，两把尺并排、都不判原因，与 schedule.handoff_late 不是一把尺）。附实跑的读数面清单（13 面：审计四个名册、missed_looks、宿主停机、通道故障表、任务、宿主事件文件、控制台日志、重启记录、计划表），每面写是什么形状、抓哪一类、保留期多久；越界就报「没读到」不许拿能读的面冒充全量。零依赖离线自检 check_skill.py 与脚本 --selfcheck，依赖缺席判红不 stub。
---

# asuna-dsh-failure-scan

## 何时用

- 每日自省跑完之后，例行晨扫一次：最近 24 小时有没有我这一层（不是某个群友，是程序）的失败。
- 有人问「那几天是不是有什么没跑」、或我怀疑某个关口／环节静默罢工（它不报错不等于它跑了）。
- 想核对「计划到点了没响、晚交了没」——这一枚里另有一档延迟分档，只看时刻差、不判原因。
- 扫出来的东西按型分开之后才谈修法：我这边能改的（关口判据、笔记、提示）我自己修；引擎／宿主侧的字面（`agent/request proposed reasoning effort … after step preparation fixed …`、`PI_AI_ERROR`、`Input does not match`）是金主或 claude 那一侧的活，转原文加时间窗。

## 一条命令

```sh
python3 skills/asuna-dsh-failure-scan/dsh_failure_scan.py                     # 最近 24 小时
python3 skills/asuna-dsh-failure-scan/dsh_failure_scan.py --hours 72
python3 skills/asuna-dsh-failure-scan/dsh_failure_scan.py --since '2026-11-04 21:10:00' --until '2026-11-07 13:08:00'
python3 skills/asuna-dsh-failure-scan/dsh_failure_scan.py --selfcheck          # 不连库不读盘的纯逻辑自检
python3 skills/asuna-dsh-failure-scan/dsh_failure_scan.py --no-files           # 只查库那几面
```

跑的位置：`sandbox_run`（worker 的 python3，`asuna` 在那台解释器上能 import，也能看见数据根）。脚本依赖 `asuna.dbread`／`asuna.config`，**缺席就在 import 那一刻 ImportError**——不许替身、不许 try 掉。只读：查库＋读数据根下的运行文件，不写库、不落文件。

## 四组怎么分（不相加的两处写死）

- **组 A 带报错行的失败**：审计里的 `attend.failed`／`chat.error`／`execution.failed`／`execution.rejected`／`phase.failed`／`phase.rejected`／`turn.rejected`／`condense.failed`／`condense.size_failed`／`condense.plan_failed`／`embedding.failed`／`rhythm.watch_failed`／`tier.fell`／`system.render_drift`；宿主事件文件里的 `provider.error`、`provider.response 非 2xx`、`handover.lost`、`host.task_interrupted`；控制台日志里带时刻的异常（连续坏行并成一件事，一次异常吐十几行不算十几次）；`lane_faults`；带 `failure_type` 的任务；重启记录里没起来或试过几档的。
- **组 B 静默没跑**：`missed_looks`（关口该判没判，`cause` 分 clash／timeout／unanswered／cut／error）、`provider.request 无响应`（响应头里读不出 `status_code` 的那条另列成 `provider.response 状态码读不出`、自己标着「没真判」）、`host_stops` 的非计划停机、`rhythm.heartbeat_missed`、`schedule.stale_dispatch`、`schedule.stale_skipped`、`task.time_up`、`task.time_up_outcome`、卡住或老于阈值还挂着的任务。
- **组 D 计划没排上／晚交到**：`schedule.fault_told`（到点没排上、这一拍告诉了她；`payload.failed_at` 才是故障时刻）、`schedule.fault_unreported`（连给开发者的说明都没写进去）、`schedule.handoff_late`（超过巡查线才交到手上，`payload.due` 是 DSH 的 `acceptedAt`）、`schedule.handoff_failed`（晚交那一拍自己抛异常）、`schedule.handoff_watch_failed`（晚交巡查自己抛异常）。这五个 type 是较近才装上的，更早的窗口数出 0 是**库里没有**，不是那件事没发生过。
- **组 C 对照（列条数、不计入失败总数）**：`attend.fallback`（**与 `attend.failed` 同一拍的伴生句，不许相加**）、`note.refused`（**是 `role_tool.refused` 的子集，不许相加**）、`role_tool.refused`（我自己那一侧被拒，不是系统坏了）、`state.conflict`、`turn.unsent_body`、`render.over_budget`、`host.inbound_slow`（入站变慢）。
- **只数名册里的 type**：三张审计名册（A／B／D）就是查询的 `$in` 名单，库里另有别的 type 也不进任何一组——加新类型要动名册，不改名册就一行都数不到（自检钉着这一条）。

- **本机断端类（推断）降对照**：`host.log` 里栈末落在 `channels.py` 的 `wfile.write`、异常是 ConnectionReset（10054）／ConnectionAborted（10053）的那一族，三样都在同一件事里才归这一类，列在组 C 下「`host.log[本机断端类（推断）]`」，不进报数。归类是推断（本机通道 HTTP 服务写回时对端提前断开），`lane_faults` 没行只是旁证，不是正面证据；只有异常名、没有 `channels.py` 栈帧的照旧留在组 A。
- **RUNNING 未回执的分界是 UTC 的 ISO 文本**：`tasks.created_at` 存的是 UTC 的 ISO 文本（带 `T`），分界文本必须用同一把尺算（窗口起点的 UTC 减阈值），不许拿本地钟面的「年-月-日 时:分:秒」去比：那样偏移差一个时区差，空格还排在 `T` 前面，同一天里比较恒偏小。

## 双面去重、保留期与「0」的说法

- **合计那行报的是记录数**（旧口径一字不改）：`合计：系统级失败 N 条（A a＋B b＋计划排期 d）；对照 C 条`。
- 同一件事可能在两面各留一条：`attend.failed` 与 `missed_looks[error]` 是同一个回合的两面（连接键＝`audit_events.stream_id` ＝ `missed_looks._id`）。这时下面另起一行：`按事件去重：系统级失败 N 件（记录 N 条 − 双面重复 N 条）`，并在那两型下面各注一句「双面：与某面同一批事件 N 条（同一件事在两面各记一次，不相加）」。**晨报要报就两件都说**，别拿记录数当件数吓人。
- 配对写死在脚本的 `OVERLAP_PAIRS` 里（现在只有 `attend.failed ↔ missed_looks[error]` 这一对），配不上的不猜；哪一面查不到或条数多过判定上限，就写「判不了」，不印 0。
- **保留期**：窗口起点早于某面的已知保留期（`missed_looks` 7 天、`audit_events` 30 天、`lane_faults` 30 天）或早于这一趟真读到的最前一行（`host.log` 只读末尾 8 MiB）时，表头之后打一行 `可能数少（超出保留期）：…`，逐面写清为什么；全在期内也打一行「保留期核查：…→ 在期内」，让看的人知道这一趟查过。
- **数出 0 只说「库里没有」**：某一组、某一型、某一个档数是 0，输出写「库里没有」；读不到的面写「没读到」；任何一行都不写「没发生过」——0 只说明这一窗口这些面里查不到这一行。

## 计划延迟分档（两把尺并排，都不判原因）

`plans.next_fire_at` 与 `audit_events` 里 `schedule.dispatched` 的时刻之差，分四档报（≤1 分钟／1–2 分钟／>2 分钟／>5 分钟，>5 在 >2 里再数一遍），每档报条数＋最晚三条的计划名与时刻。派发那一刻 core 已把 `next_fire_at` 推到下一次，所以两把尺分开摆、各标各的读法：

- **晚到（按下一次钟点倒推，仅循环计划末次派发）**：应响＝`next_fire_at − 周期`（`rule.every_seconds` 直读，每日 `clock` 记一天），只对每个计划在这一窗最晚那一条成立。软肋写死在输出末尾：真晚到时「下一次」是按当下重算的，晚的那一截被推平，>5 分钟那一档可能照样量不到——量不到只说明这一趟没读到。
- **字面（计划文档里应响时刻还没被推）**：派发时不动 `next_fire_at` 的那类计划，差值本身就是字面晚到。
- **对不上（`next_fire_at` 已是下一次）**：往前推过一格以上的（更早的窗口整窗都会落在这里），单列条数，不倒推。
- **null（一次性 FIRED）**：一次性计划响过一次后 `next_fire_at` 被清空，上面两把都套不上；样例行按 `rule.at`（带 UTC 字样）或 `created_at + after_seconds` 复原应响时刻，写着「单列，未进档」；本地钟面的 `rule.at` 不硬算。
- 这一把与组 D 的 `schedule.handoff_late` **不是一把尺**：那一条量的是 DSH `acceptedAt` → worker 接收，巡查线 300 秒，只在超过那条线时才落行。

## 输出怎么读

- 表头：窗口（本地钟点＋怎么定的）、**时刻配对行**（`dbread.now()` 与同一刻 UTC 两个原值＋推出的偏移，按 15 分钟对齐；同一个 UTC 另给换 +8 的结果）、**读数面 已读 X／没读到 Y**、**保留期核查行**（必要时后面再跟一行「可能数少（超出保留期）」）。
- 接着两笔账：`合计：系统级失败 N 条（A…＋B…＋计划排期…）；对照 C 条`，以及必要时 `按事件去重：… 件（记录 N 条 − 双面重复 N 条）`。
- 每型：`条数＋首 本地时刻 末 本地时刻`，下面最多三条样例行（时刻＋流号前缀＋那一行错误；绝对路径、内网地址、长十六进制号换成占位，正文不搬）；双面同事件的型多一行「双面：与…」。
- 末尾是**计划延迟分档**那一档（两把尺＋对不上＋null＋判不了的）。
- 全零且每面都读到 → 只输出一行 `0`，rc 0。有面没读到却也全零 → 不印光一个 `0`，另起行列没读到的是哪几面（那种 0 是「没查」）。
- 退出码：0 = 扫完（有失败也是 0）；2 = 判不了（一面都没读到、或窗口不合法）。

## 13 个读数面（各是什么形状、能追多远）

| 面 | 形状 | 抓什么 |
| --- | --- | --- |
| `audit_events`（A／B／D／C 四个名册各一次聚合） | `{stream_id, seq, type, occurred_at(UTC 文本), payload}`，type 名单来自脚本里的名册 | 关口／环节／回合级失败与拒、计划没排上与晚交 |
| `missed_looks` | `_id`＝回合 id，`scene_id`、`at`(UTC 文本)、`cause` 五档 | 关口该判没判——只有这张表能证明「它没跑」 |
| `host_stops` | `how`(planned／killed／crashed／worker_down／worker_restart)、`alive_until`、`back_at`、`exit_code`、`cause` | 宿主被外部终止、崩掉、worker 停过、计划外重启 |
| `lane_faults` | `channel_id`／`lane`／`stage`／`error`／`hour` 必填，`count`、`first_posted_at`、`last_posted_at`；按小时聚合 | 通道层（入站、出站投递）故障计数 |
| `tasks` | `state`、`failure_type`、`created_at`（老行可能没有，退 `lease_expires_at`） | 任务级异常、卡住、老于阈值没回执 |
| `role_tool` 带 `payload.refused` | 按 `payload.tool` 分组 | 我自己那一侧被拒（对照） |
| 数据根 `reports/native-host-*/NNNNN-<type>.json` | `{seq, type, payload, prev_hash, time_ns, event_hash}` 哈希链，每宿主运行一个目录 | `provider.error`、非 2xx、请求无响应、任务丢、入站慢 |
| 同上 `provider.request`／`provider.response` | `call_id` 配对；`time_ns` 排在正文之后，大响应要补读文件尾 | 发出去没等到回（静默没跑） |
| 数据根 `restart/host.log` | 混合文本：只有带 `…Z` 时刻的行算一条；CRLF 与 LF 混；这一面另报实际读到的最前时刻 | 宿主控制台的异常（含 traceback） |
| 数据根 `restart/history.jsonl` | `{id, down_at, attempts[{rung,ok,at}], result, back_at, loaded}` | 起没起来、试了几档、崩掉 |
| 数据根 `worker-restarts.jsonl` | `{at, reason}`，`worker asked: …` 是计划内 | worker 非零退出、启动失败 |
| `plans` ↔ `audit_events`（`schedule.dispatched`） | `plans`：`_id`、`intent`、`status`、`rule`、`next_fire_at`、`created_at`；派发行 `stream_id`＝计划 id | 计划延迟分档（上面那一档），不判原因 |

表里 12 行；表头那个 13 是把 `audit_events` 按四个名各算一面（A／B／D／C 各查一次）。

## 追得多久、什么时候会数少

- `missed_looks` 只留 7 天（core `host_stops.py` 的 `MISSED_KEPT_DAYS`，清理靠家回合触发）：窗口越界只会数少，不会报错——越界时输出顶部那行「可能数少（超出保留期）」会说话。
- `audit_events` 定期清（core `audit.py` 的 `RETENTION_DAYS`＝30 天，`role_tool` 另留 365 天）；这些天数为零时别抄这里的，现读 `audit.pruned` 那条更准。
- `lane_faults` 按小时留固定天数（core `lane_faults.py` 的 `KEEP_DAYS`）；`reports/` 每次宿主运行一个目录，脚本按 mtime 粗筛、真时刻看 `time_ns`。
- `host.log` 是单文件追加，只读末尾 8 MiB；这一面在输出里报的是**这一趟真读到的最前时刻**（不是猜的），窗口比它更早时保留期那行会点名。
- 「无响应」的宽限 10 分钟（刚发出去还没回的不算），所以窗口右端那 10 分钟不计。
- 延迟分档一次最多读 5000 条 `dispatched`，超了会在输出里明说只读了前 5000 条。
- 没读到的面在表头列名并附真原因；**报告里写全量之前先写这几面读到了没有**。

## 对账时定位排程会话里的一行

定位排程会话里的一行，用「会话目录名（＝scheduler id）＋行内 `seq`」，不能按完整 occurrence 串（`asuna-<uuid>:<seq>`）检索——那个串在行内根本不出现（行内 `data.id` 是另一个 UUID，形如 `schedule-<uuid>`），按整串搜会数出 0 行，再被读成「没有」。行内时刻只有 `time`（epoch 毫秒）和 `data.acceptedAt`（ISO），没有 `dispatchedAt`／`deliveredAt` 这类键；库里的 `schedule.dispatched` 是另一侧的另一行，两边要分别取，别当同一个时刻。

## 还没核实的（别当已知）

- `turn.rejected` 与 `episodes.rejections[]` 是不是同一批（沿用 `asuna-usage-readout` 那格的未决）。
- `tasks` 里「未回执」只到「卡住／老于阈值」这一层：跨重启但已交回的任务会不会被误列，没测过。
- `host.log` 的「异常事件」按连续行并块：宿主若把一次异常的两半中间插进别的日志，会拆成两件。
- `provider.response` 非 2xx 只看 `status_code`；DSH 自己重试了几次、有没有最后成功，这一层看不见。
- **一次性钟的晚到，倒推那把尺量不到**（`next_fire_at` 已被清空），样例行里那句「按 `rule.at` 复原」是替代读数、没进档；要精确复原每一次派发的应响时刻，得走 DSH 排程日志的 `acceptedAt` 或 `state.commit` 相邻快照——两条候补路都没做，账记在 `CHANGELOG.md`。
- 倒推只覆盖每个计划在窗口内的**末次**派发；更早的派发一律落「对不上」。本地钟面的 `rule.at`（没带 UTC 字样）没换算，写「复原不了」。

## 相关

- 这一枚为什么这么定、实测到的坑与历次实跑账，记在同目录 `CHANGELOG.md`；正文只指路，不夹历史。
- 每日自省（`asuna-daily-review`）跑完接这一趟；被拒的八处散在哪、去重口径看 `asuna-usage-readout`；「我改的那版在不在跑」看 `asuna-running-version`。
