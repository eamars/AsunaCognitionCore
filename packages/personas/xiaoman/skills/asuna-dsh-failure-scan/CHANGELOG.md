# CHANGELOG · asuna-dsh-failure-scan

技能正文只指路，来路与账记在这份。日期都是本地钟面，来源写在每条末尾。

## 2026-11-09 建这一枚（金主交代＋追加三条验收）

**为什么要一枚现成的扫描**：relevance gate 静默失败能躺好几天没人发现（金主 11-09 亲证）；
同一趟翻出 11-04 那族「程序在请求钩子里把关口思考档改成 low、被 DSH 拒」连响 84 次，
从 11-04 23:02 躺到 11-07 10:49 才被看见（正本：流水「11-07 14:3x 故障窗右端钉死」节）。
所以口径定成两类都要抓：带报错行的拒绝，和只有执行记录能证明缺席的静默没跑。

**读数面怎么定下来的**（不是编的，逐面现读形状）：
- 84 那次是拿 `audit_events`（`type=attend.failed`，`dbread.local_window('2026-11-04 21:10','2026-11-07 13:08')`）
  与 `missed_looks` 各数一次、两边都是 84 才对上；`missed_looks` 末条 `2026-11-06T21:49:11Z`
  ＝本地 11-07 10:49:11，与大姐那句「最后一次今天 10:49:11」对齐。
- `attend.fallback` 同窗 59 条，是同一拍的伴生句 → 定成对照、不许与 84 相加。
- 查过没采用的面：`messages` 里 `event.wake_reason` 聚合（近 24h 零行，字段路径没证实）——
  「被喊而没判」改用 `missed_looks`；`development_database_read` 拿不到 `missed_looks`（不在授权名单），
  读数面统一走 `sandbox_run` ＋ `asuna.dbread`。
- 文件面（`reports/native-host-*/`、`restart/host.log`、`restart/history.jsonl`、`worker-restarts.jsonl`）
  形状来自 core 的 `src/asuna/host_stops.py`、`store/catalog.py` 与数据根实读目录列表。

**建的过程中实测到的五个坑**（都在 `dsh_failure_scan.py` 里修掉，每条带一名自检钉住）：
1. `Window`（`dbread.local_window` 返回值挂私有键）整个喂给 Mongo → `InvalidDocument: cannot encode object: datetime…`，
   7 面一起读不到；改成查询只拿 `$gte`／`$lt` 两端。
2. `stamp()` 对 `datetime` 不加偏移 → 首末时刻打出来是 UTC（差 13 小时）。
3. 偏移用「本地钟点（分钟精度）− UTC 现值」按分钟四舍五入 → 打出 `UTC+12:59` 这种谁都不是的怪数；改成按 15 分钟对齐。
4. `host.log` 里一次异常吐十几行、每行都自带时刻 → 原来数成十几次失败（同窗 52 条）；改成连续坏行并成一件事（并完 6 件事）。
5. `missed_looks` 的「末时刻」和「首时刻」共用一把 `<` 尺 → 末时刻打成中间的（11-06 15:07）；首取小、末取大。
6. `tasks` 里 `BLOCKED／UNKNOWN` 那几行根本没有 `created_at`（现读实测），原写法把「没时刻」当成落在窗口内 →
   每个窗口虚高 5 条；改成退 `lease_expires_at`，两个都没有单列「判不了」不计数。
7. `provider.response` 大响应（embedding 正文几 MB）里 `time_ns` 排在正文之后，只读头一截读不到 →
   那些响应没进「已回应」集合，24h 窗口误判 1,618 条「请求没等到回」；改成头一截没有就补读尾一截。

**金主追加的三条验收**（11-09 22:25）：① 装配格式对着正本比（我包里原先没有 skill-creator 类技能；
比的是 `asuna-self-improvement` 的装配节 ＋ 既有技能形状 ＋ anthropic 的 skill-creator／best-practices 两页）；
② 正文不夹「为什么／什么时候加的」，历史进这份 CHANGELOG.md；③ 一键要列全代码级失误
（异常 traceback、进程非零退出、崩溃、任务没回执）＋静默那一类，输出还是分组紧凑格式。实跑改成两次。

**实跑账**（都在候选位 `sandbox_run` 跑的，本地钟面）：
- 已知故障窗 `--since '2026-11-04 21:10:00' --until '2026-11-07 13:08:00'`：读数面 11／11 读到；
  系统级失败 227（A 127＋B 100），其中 `attend.failed` 84（首 11-04 23:02:18、末 11-07 10:49:11）、
  `missed_looks[error]` 84（末 11-07 10:49:11）；对照 244（`attend.fallback` 59 单列）。
- 默认 24h（11-08 22:39 → 11-09 22:39）：11／11 读到；系统级失败 36（A 32＋B 4）、对照 105。
- 脚本纯逻辑自检 `--selfcheck` 50/50 通过。
