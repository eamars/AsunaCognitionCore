---
name: asuna-dsh-failure-scan
description: 我家程序（认知核＋宿主 DSH）这一层失败的一键扫描：一条脚本把时间窗内两类失败全列出来——一类带报错行（关口被引擎拒、回合／行动脑／摘要／向量环节抛异常、上游非 2xx、进程非零退出、任务级异常），一类是静默没跑、只有执行记录能证明它缺席（关口该判没判、请求发出去没回、宿主或 worker 停过、该响的拍没响、任务卡住没回执）。用在每日晨扫（放在每日自省之后）和「这一段时间是不是有什么没跑」的核对上。口径写死：三组分开数（A 带报错行／B 静默没跑／C 对照＝伴生句与我自己的工具被拒，不计入失败总数）、每型给条数＋首末本地时刻＋最多三条样例行、窗口是本地钟点且偏移现读配对不背常数、全零输出一行 0、有面没读到不许印光一个 0。附实跑的读数面清单（11 面：审计、missed_looks、宿主停机、通道故障表、任务、宿主事件文件、控制台日志、重启记录），每面写是什么形状、抓哪一类、保留期多久；越界就报「没读到」不许拿能读的面冒充全量。零依赖离线自检 check_skill.py 与脚本 --selfcheck，依赖缺席判红不 stub。
---

# asuna-dsh-failure-scan

## 何时用

- 每日自省跑完之后，例行晨扫一次：最近 24 小时有没有我这一层（不是某个群友，是程序）的失败。
- 有人问「那几天是不是有什么没跑」、或我怀疑某个关口／环节静默罢工（它不报错不等于它跑了）。
- 扫出来的东西按型分开之后才谈修法：我这边能改的（关口判据、笔记、提示）我自己修；引擎／宿主侧的字面（`agent/request proposed reasoning effort … after step preparation fixed …`、`PI_AI_ERROR`、`Input does not match`）是金主或 claude 那一侧的活，转原文加时间窗。

## 一条命令

```sh
python3 skills/asuna-dsh-failure-scan/dsh_failure_scan.py                     # 最近 24 小时
python3 skills/asuna-dsh-failure-scan/dsh_failure_scan.py --hours 72
python3 skills/asuna-dsh-failure-scan/dsh_failure_scan.py --since '2026-11-04 21:10:00' --until '2026-11-07 13:08:00'
python3 skills/asuna-dsh-failure-scan/dsh_failure_scan.py --selfcheck          # 不连库不读盘的纯逻辑自检
```

跑的位置：`sandbox_run`（worker 的 python3，`asuna` 在那台解释器上能 import，也能看见数据根）。脚本依赖 `asuna.dbread`／`asuna.config`，**缺席就在 import 那一刻 ImportError**——不许替身、不许 try 掉。只读：查库＋读数据根下的运行文件，不写库、不落文件。

## 三组怎么分（不相加的两处写死）

- **组 A 带报错行的失败**：审计里的 `attend.failed`／`chat.error`／`execution.failed`／`execution.rejected`／`phase.failed`／`phase.rejected`／`turn.rejected`／`condense.failed`／`condense.size_failed`／`condense.plan_failed`／`embedding.failed`／`rhythm.watch_failed`／`tier.fell`／`system.render_drift`；宿主事件文件里的 `provider.error`、`provider.response 非 2xx`、`handover.lost`、`host.task_interrupted`；控制台日志里带时刻的异常（连续坏行并成一件事，一次异常吐十几行不算十几次）；`lane_faults`；带 `failure_type` 的任务；重启记录里没起来或试过几档的。
- **组 B 静默没跑**：`missed_looks`（关口该判没判，`cause` 分 clash／timeout／unanswered／cut／error）、`provider.request 无响应`（响应头里读不出 `status_code` 的那条另列成 `provider.response 状态码读不出`、自己标着「没真判」）、`host_stops` 的非计划停机、`rhythm.heartbeat_missed`、`schedule.stale_dispatch`、`schedule.stale_skipped`、`task.time_up`、`task.time_up_outcome`、卡住或老于阈值还挂着的任务。
- **组 C 对照（列条数、不计入失败总数）**：`attend.fallback`（**与 `attend.failed` 同一拍的伴生句，不许相加**）、`note.refused`（**是 `role_tool.refused` 的子集，不许相加**）、`role_tool.refused`（我自己那一侧被拒，不是系统坏了）、`state.conflict`、`turn.unsent_body`、`render.over_budget`、`host.inbound_slow`（入站变慢）。

## 输出怎么读

- 表头三行：窗口（本地钟点＋怎么定的）、**时刻配对行**（`dbread.now()` 与同一刻 UTC 两个原值＋推出的偏移，按 15 分钟对齐；同一个 UTC 另给换 +8 的结果）、**读数面 已读 X／没读到 Y**。
- 每型：`条数＋首 本地时刻 末 本地时刻`，下面最多三条样例行（时刻＋流号前缀＋那一行错误；绝对路径、内网地址、长十六进制号换成占位，正文不搬）。
- 全零且每面都读到 → 只输出一行 `0`，rc 0。有面没读到却也全零 → 不印光一个 `0`，另起行列没读到的是哪几面（那种 0 是「没查」）。
- 退出码：0 = 扫完（有失败也是 0）；2 = 判不了（一面都没读到、或窗口不合法）。

## 11 个读数面（各是什么形状、能追多远）

| 面 | 形状 | 抓什么 |
| --- | --- | --- |
| `audit_events`（三组各一次聚合） | `{stream_id, seq, type, occurred_at(UTC 文本), payload}`，type 名册现读 | 关口／环节／回合级失败与拒 |
| `missed_looks` | `_id`＝回合 id，`scene_id`、`at`(UTC 文本)、`cause` 五档 | 关口该判没判——只有这张表能证明「它没跑」 |
| `host_stops` | `how`(planned／killed／crashed／worker_down／worker_restart)、`alive_until`、`back_at`、`exit_code`、`cause` | 宿主被外部终止、崩掉、worker 停过、计划外重启 |
| `lane_faults` | `channel_id`／`lane`／`stage`／`error`／`hour` 必填，`count`、`first_posted_at`、`last_posted_at`；按小时聚合 | 通道层（入站、出站投递）故障计数 |
| `tasks` | `state`、`failure_type`、`created_at`（老行可能没有，退 `lease_expires_at`） | 任务级异常、卡住、老于阈值没回执 |
| `role_tool` 带 `payload.refused` | 按 `payload.tool` 分组 | 我自己那一侧被拒（对照） |
| 数据根 `reports/native-host-*/NNNNN-<type>.json` | `{seq, type, payload, prev_hash, time_ns, event_hash}` 哈希链，每宿主运行一个目录 | `provider.error`、非 2xx、请求无响应、任务丢、入站慢 |
| 同上 `provider.request`／`provider.response` | `call_id` 配对；`time_ns` 排在正文之后，大响应要补读文件尾 | 发出去没等到回（静默没跑） |
| 数据根 `restart/host.log` | 混合文本：只有带 `…Z` 时刻的行算一条；CRLF 与 LF 混 | 宿主控制台的异常（含 traceback） |
| 数据根 `restart/history.jsonl` | `{id, down_at, attempts[{rung,ok,at}], result, back_at, loaded}` | 起没起来、试了几档、崩掉 |
| 数据根 `worker-restarts.jsonl` | `{at, reason}`，`worker asked: …` 是计划内 | worker 非零退出、启动失败 |

## 追得多久、什么时候会数少

- `missed_looks` 只留 7 天，且清理靠家回合触发：窗口越界只会数少，不会报错。
- `audit_events` 定期清（`role_tool` 留得久些），保留期与上限现读 `audit.pruned` 那条，别抄这里。
- `lane_faults` 按小时留固定天数；`reports/` 每次宿主运行一个目录，脚本按 mtime 粗筛、真时刻看 `time_ns`。
- `host.log` 是单文件追加，只读末尾 8 MiB；窗口比这段更早时那一面就是「不完整」，别看它报 0。
- 「无响应」的宽限 10 分钟（刚发出去还没回的不算），所以窗口右端那 10 分钟不计。
- 没读到的面在表头列名并附真原因；**报告里写全量之前先写这几面读到了没有**。

## 还没核实的（别当已知）

- `turn.rejected` 与 `episodes.rejections[]` 是不是同一批（沿用 `asuna-usage-readout` 那格的未决）。
- `tasks` 里「未回执」只到「卡住／老于阈值」这一层：跨重启但已交回的任务会不会被误列，没测过。
- `host.log` 的「异常事件」按连续行并块：宿主若把一次异常的两半中间插进别的日志，会拆成两件。
- `provider.response` 非 2xx 只看 `status_code`；DSH 自己重试了几次、有没有最后成功，这一层看不见。

## 相关

- 这一枚为什么这么定、建它时实测到的坑与两次实跑账，记在同目录 `CHANGELOG.md`；正文只指路，不夹历史。
- 每日自省（`asuna-daily-review`）跑完接这一趟；被拒的八处散在哪、去重口径看 `asuna-usage-readout`；「我改的那版在不在跑」看 `asuna-running-version`。
