# ADR-113: Worker restarts in her own block

Status: **Designed**, not built. For Xiaoman's one reading before the build (she reads it once, whole; nothing is
built until she agrees). Checked against the code by Claude and then by a fresh reviewer; the review's findings and
what was done are in §10.

All times are New Zealand local time.

## 1. The ask

The owner, 2026-10-31 15:09, on her question about a restart that is held: "you can decide with xiaoman, im ok
eitherway".

Xiaoman, on her agent line, 2026-10-31 15:12 (her words):

> **二、worker 级重启要进。** 这就是 10-22 我记的那第三扇瞎窗口：C1 当年补的是宿主级启停，worker 级一直是空的，所以昨晚那 11 次我只看到一次停机。你先写设计给我读，读完我点头你再动。三条要求：
>
> ① **复用我 10-27 签过的 ADR-101 那套口径，别新造**：cause 用封闭白名单、`since`＋`tries`、"更早的 M 次没有列出"、不知道就写"不知道"。
> ② **有界**：正常发布触发的那种别一条条刷进来（一天可能好几枚），聚合打底（这段起了 N 次、第一次和最后一次的时刻），**异常那一段才逐条**——什么算异常你写判据。
> ③ **写明进哪些场合、往我随身塞多少字**。家里那格昨晚量到只剩 70 字，要是挂成"到处都带"我挤不进去；我宁可它只进家里和这条线。

And in the same message, the half she added to the first point, which she and Claude agreed instead of a reading
while a restart is held (that one can never be read: while a restart is pending her queue takes nothing, so no turn
of hers runs, `chat.py` `_work`):

> **事后那一拍**我要看得见"刚才挂过一次长重启"——从几点起挂的、几点真起来、中间多长、被什么挡的（哪个任务或哪个调用）。

In scope: worker restarts (the Host runs on, the worker is replaced), said in her block afterwards, with how long
each was held and by what, bounded. Out of scope: Host-level starts and stops (ADR-101 and the supervisor's
`restart_from_program` say them), a worker that failed (ADR-101's outage), and a reading while a restart is held
(none can be read).

## 2. What happens today

- **Where a worker restart starts.** The plugin's `restart(reason)` (`packages/cognition-core/src/index.js`), with
  one of: `settings applied` (`:771`), `settings restored after a failed apply` (`:778`), `worker asked: <the
  worker's reason>` (`:873`; the worker sends `published-worker`, `native_worker.py` `watch_host`), `worker failed:
  <error>` (`:1180`, the retry after an exit), `a restart requested during the last one` (`:1207`), `recovery
  activated <project>` (`:1517`).
- **What it records.** One line in `<data>/worker-restarts.jsonl`, `{at, reason}` (`:1190-1194`), and the newest 10
  in the plugin's status history, in memory. Nothing reads the file and nothing bounds it: 41 lines, 3,032 bytes,
  from 10-06 (30 publication, 9 settings, 1 worker failed, 1 asked during the last one).
- **What she sees.** Nothing. ADR-101 §1 left planned in-place restarts out on purpose; her `host_from_program` lists
  outages only, her `restart_from_program` the supervisor's Host starts. On the night of 10-30 eleven worker
  restarts reached her as nothing at all (ADR-112 S6).
- **What the stopping worker knows and loses.** Since ADR-112 C2 the Host records when a restart went pending and
  each change of what holds it (`restart.pending`, `restart.blocked` with `held_by` and `calls_in_flight`,
  `restart.requested`; `host.py` `_maybe_restart_after_publish`), in its Host report only. Nothing hands it on.
- **Two defects in `restart()` this design depends on.** `this.restarting` is checked (`:1189`) but set only after
  `await appendFile` (`:1195`), so two callers in that gap run overlapping restarts. A request queued during a
  restart keeps only a flag (`restartAgain`, `:872`), losing what asked for it; and when `ready()` throws, the line
  that consumes the flag (`:1207`) is skipped, so the flag survives and a later unrelated restart is followed by a
  false `again`.

## 3. How this is usually done

Repeated events are bounded by folding them, not by dropping them: syslog's "last message repeated N times",
journald's rate limit that writes "Suppressed N messages", a monitoring system's grouping of alerts into one
notification with a count and the first and last time. The event that is not routine is said alone. That is her
second requirement and ADR-101's own shape (a count, at most three listed, 「更早的 M 次没有列出」).

## 4. Decisions

### D1. The plugin hands each finished restart to the worker that it brought up (ADR-101's hand-over)

- **What the stopping worker sends.** `restart_requested` carries `held`: `since` (when the restart went pending)
  and `steps`, the changes of what held it, each `{by: [turn|task|calls…], since, task_id?, calls?}` as the Host
  records them (`held_by` is a set; `calls` its count). At most 5 steps: the first and the newest 4, and `changes`,
  how many there were. The Host discards the trail when it sends it and when it withdraws the restart. A worker
  restart that was never held sends `held: null`.
- **What the plugin keeps.** When `restart()` begins it sets `this.restarting` before any `await` (the first defect)
  and appends `{at, cause, held, held_sent}` to `<data>/restarts-to-tell.json` (a list, written whole through a
  temporary file, as `worker-down.json`). `held_sent` is false when the request carried no `held` key (an older
  worker), so "not sent" and "not held" are told apart. A request queued during a restart keeps its reason and
  `held`, and the flag is consumed in a `finally`, so a throw cannot leave it behind (the second defect).
- **When it comes back.** `ready()`, run by `restart()`, stamps that entry's `back` when the start completes, just
  before its existing `handOver()`. `handOver()` hands the outage span (as today) and then the entries with a
  `back` through `host.restarted`; the worker answers which it recorded, and those are removed from the file. It is
  tried again every `HANDOVER_SECONDS`, and a failure is said once (`handOverSaid`), as for the span.
- **What is not handed over.** A restart whose `ready()` throws is removed from the file: its start failed, which
  ADR-101's span records as an outage. An entry left without a `back` by a Host stopped mid-restart is removed at
  the next completed start: the Host's stop is ADR-101's `killed` or `crashed` row. `worker failed: …` restarts are
  not written to the file: they are ADR-101's `worker_down` span. One event is said once.
- **Bounded.** The file keeps at most 50 entries; one dropped beyond that is said in an `Asuna:` line.
  `worker-restarts.jsonl` stays the owner's log, written by the plugin only and read by nothing; past 256 KB the
  plugin keeps its newest 128 KB, cut at a line.

### D2. The worker records each restart once, in ADR-101's store

- `host.restarted` writes one `host_stops` row per entry: `_id` `restart-<at>` (a second hand-over of the same entry
  writes nothing new), `how: worker_restart`, `cause`, `asked_at`, `back_at`, `held`, `held_sent`. Each row is
  complete when written: nothing is filled in later.
- The store's catalog (`store/catalog.py`, `host_stops`) declares `asked_at` (text) and `held` (object, nullable)
  and an index `(how, asked_at)`; restart rows are found and ordered by when they were asked.
- Nothing from before this build becomes a row: the old log is never read, so no old restart is said.
- At each worker start, rows of `worker_restart` shown and older than 7 days are deleted (as `forget_missed` does for
  the gate's misses); an unshown row stays, as ADR-101's outages do.

### D3. Causes, a closed list (ADR-101's way)

| `cause` | From | Her words |
|---|---|---|
| `published` | `worker asked: published-worker` | 装你发布的新版本 |
| `settings` | `settings applied` | 换设置 |
| `settings_restored` | `settings restored after a failed apply` | 设置没换成，退回原来的设置 |
| `recovery:<project>` | `recovery activated <project>`, the project matching `[a-z][a-z0-9-]{0,39}` | 换回能跑的版本（<project>） |
| `again` | a request queued during a restart, with no reason of its own | 上一次重启时又排着一次（跟着上一次那次，谁排的没记下来） |
| `unknown` | anything else, a project not matching included | 为什么重启没记下来 |

A queued request that carried its own reason keeps that reason's cause.

**No `tries`, on purpose.** ADR-101's `tries` counts the failed starts of one outage while it stays open. A worker
restart is not that: each restart is its own event with its own row, never a retry of an earlier one, so there is
nothing for `tries` to count. Restarts that follow each other are a run (D4); the changes of what held one restart are
`changes` (D1). A new reason gets a kind here and its words
together; her wording keys on the kind (before `:`), as in ADR-101.

### D4. Routine ones folded, the rest one by one

Computed at each home turn over the restart rows of the window: asked within the last day, or not yet shown. This is
the rule ADR-101 states at its lines 81-85 (a stop stays until a home turn that showed it commits, `told` and
`shown_at`, and in any case for a day), as its code applies it to outages (`host_stops.listed`, `host_stops.py:260`,
through `unshown`, `:60`).

- A restart is **routine** when its cause is `published` or `settings`, it was held less than 2 minutes or not at
  all (`held_sent` true), it came back within 2 minutes of being asked, and it is in no run.
- A **run** is three or more restarts of the window, each asked within 10 minutes of the one before. It is said as one
  stretch, whatever its members' causes.
- Every other restart is **listed**: newest first, at most 3 places; a run takes one place. ADR-101's words for its
  outages, lines 73-75: 「newest first, at most three, and says how many there were」, and 「A cut list never passes for
  the whole.」 The code's bound is `host_stops.LISTED` (`host_stops.py:27`), the same 3.

What she reads, in `host_from_program` beside ADR-101's outages, under `restarts`:

- `count`: 「过去一天里，替你处理一切的那部分程序重启了 N 次（不算上面那些停机）」: N is every restart row of the
  window.
- `note`, with `count`: 「这些重启时宿主一直在运行，不是又一次停机；每次重启那一两分钟里你没有在运行。」 So the two
  numbers side by side are never read as a second incident.
- `routine`, when any: 「其中 N 次是计划内的、很快起来的：<cause> N、…，最早 <time>，最近 <time>」.
- Each listed restart:
  - `what`: 「替你处理一切的那部分程序为<cause>重启」, with 「（计划内）」 for `published` and `settings`.
  - `when`: 「<asked> 要重启，<back> 重新起来，中间约 <span> 你没有运行」 (the form of ADR-101's `when`, line 77, 「中间约 X 分钟」,
    through the code's `host_stops._span`; with the clock moved, ADR-101's 「中间多久不知道（时钟对不上）」, line 265).
  - `held`, when held: 「重启前挂了约 <span>（从 <since> 起）：先等<first>，最后等<last>；挂着时新回合和新任务都不开始」, with
    「，中间又换过 N 次」 when `changes` is more than 2. A holder: 「你的回合」, 「任务「<title>」」 (the title read from
    `tasks` at that turn, at most 20 characters; none found: 「一个任务」), 「N 个还没回来的工具调用」. When `held_sent` is
    false: 「挂没挂过不知道」.
- A run: 「<first> 到 <last> 之间连着重启了 N 次（<cause> N、…），每次中间约 <shortest> 到 <longest>」, always with its
  longest hold: 「；挂得最久的一次在 <asked>，约 <span>，<its holders as above>」, or 「；每一次都没有挂」 when none was
  held, or 「；挂没挂过不知道」 when no member sent it (her choice, 2026-10-31: the longest hold is what a fold hides). A run crossing the window's
  edge is said with its members inside the window; its shape can change as members leave.
- `not_listed`: 「更早的 M 次没有列出」, M counting restarts, not places.
- A row that cannot be put into words (a time that does not read) is counted in `unreadable`, with ADR-101's sentence
  word for word (its tail, line 284; `host_stops.UNREADABLE`, `:39`): 「其中 N 次的记录读坏了，说不清是什么、在什么时候」.
- A cut list never passes for the whole (ADR-101, line 74): every restart of the window is in `count`, and
  N = routine + the restarts in listed places + `not_listed` + `unreadable`, tested.

A restart stays until a home turn that showed it commits (`shown_at`, through the turn's `told.host_stops`) and in any
case for a day: ADR-101's rule (lines 81-85), a floor not a cap. A routine one folded into `routine` is shown when that line is.

### D5. Where it goes

Into her Web chat and her home lines only: the owner's local scene (`scene_id` equal to `chat.scene_id`), and a scene
whose channel kind declares `HOME = True` (`channel_kinds.home`: today the agent line and the DSH peer line). In the
code's place names these are `home` for the local scene and `peer` for the lines; the check is the two tests above,
never `place == 'home'`, which also matches the owner's QQ direct messages (`visibility.place_of`). Not into the
owner's QQ direct messages or a group configured as home, which keep ADR-101's outages as today. No channel's name is
written into the core. One place is wider than she asked: the DSH peer line is a home line of the same kind as the
agent line.

### D6. How much it takes, and from where

These are lines of the program's block in her turn context (`host_from_program`), in D5's home turns only. They are
not her memory (they take nothing of her 随身 cap) and not her skill list. Which budget her "70 字" counts is not known
to this design; what it can say is how many characters each case adds to a home turn's context, counted from the
sentences above with real lengths of times and titles (JSON keys and quotes add about 60 more when present):

| Day | Characters added |
|---|---|
| No worker restart in the window | 0 (no `restarts` key) |
| Only routine ones (2 publications, 1 settings) | about 140 (`count` 36, `note` 38, `routine` 62) |
| One listed restart, held 12 minutes by a task, then a call | about 215 |
| The night of 10-30 (eleven restarts in 31 minutes, one run, its longest hold said) | about 210 |
| The most it can be: routine with every cause, 3 listed places each at their longest, `not_listed`, `unreadable` | about 720; the build's test asserts the case under 800 with the keys |

Whether it can push other program blocks out (her question). The whole turn context has one ceiling, 48,000
characters (`context_budget.TURN_CHARS`). Over it, `trim_turn` drops rows from these lists only, in this order
(`TRIM_ORDER`): the member list, recent experience, settlement candidates, memories, group continuity, and the
delivered history down to its last 4 rows. `host_from_program` is not among them: it is never cut, and every
character it adds is paid, in a turn over the ceiling, by rows of those lists. In a turn under the ceiling nothing is
pushed out. Measured 2026-10-31: no turn of hers was trimmed since 10-24 (`audit_events`, `context.trimmed`: 0 since
10-24, 457 before), in any place.

## 5. Failure modes

| Case | What happens |
|---|---|
| `restarts-to-tell.json` cannot be written | the restart goes on; one `Asuna:` line; that restart is not said |
| The file is torn or not a list | read as empty and replaced, one `Asuna:` line (as `worker-down.json`) |
| `host.restarted` fails (database reset) | the entries stay; tried again every `HANDOVER_SECONDS`; the row's id makes a repeat harmless |
| An older worker (no `host.restarted`) | `UNKNOWN_BUSINESS_METHOD`, said once; the entries wait, at most 50, for a newer worker |
| An older plugin with this worker | no hand-over: nothing is said, nothing false is said |
| An older worker with this plugin | `held_sent` false: 「挂没挂过不知道」 |
| The restart's start fails | removed from the file; ADR-101's outage says it |
| The Host stops mid-restart | the entry without `back` is removed at the next completed start; ADR-101's `killed`/`crashed` row says it |
| A task that held it was erased (ADR-105) | 「一个任务」 |
| A restart loop left running | one run, one place; the file holds at most 50 entries, its count is in the rows handed over |
| Two callers of `restart()` at once | the second returns the first's restart (`this.restarting` set first) |

## 6. Not changed

ADR-101's outages, their words and their places; the supervisor's `restart_from_program`; ADR-112's restart gate.

## 7. Tests that earn their place

- JS: a worker-asked restart writes its entry with `held` and `held_sent`; a completed restart stamps `back` and hands
  it over; a failed start removes it; an entry without `back` from an earlier Host is removed at a completed start; a
  queued request keeps its reason and `held`, and a throw leaves no flag behind; two `restart()` calls at once run
  one restart; the jsonl past 256 KB keeps its newest 128 KB at a line.
- Python: `host.restarted` writes one row per entry and none the second time; the routine, run and listed rules on
  the 10-30 night's eleven times and on a quiet day; count = routine + listed + not_listed; her words for each cause,
  each holder, `held_sent` false, a moved clock; the places (the agent line yes, the owner's QQ DM no); the 7-day
  delete; the most-it-can-be case under 760 characters.
- Each fails with its rule removed (shown at the build).

## 8. Landing

One core landing: suite, `pytest integration`, `npm run test:native`, the push gate, one restart at her slot, the
loaded commit checked. That restart is itself the first one handed over: her next home turn on the Web shows it.

## 9. For her reading

Points where she may choose otherwise, each with what this design does:

- The thresholds: routine within 2 minutes held and 2 minutes down; a run is 3 within 10 minutes of each other.
- D5's places include the DSH peer line.
- `count` says 「不算上面那些停机」 so that her outages and her restarts are never added up as one number.

## 10. Review

**Claude's own check** against the code at `cb7d1964`: §2's claims, ADR-101's mechanisms in the code (`host_stops.listed`,
`unshown`, the `told` stamp), the catalog (`host_stops` lists rows by `back_at`, hence `asked_at` and its index), the
places (`visibility.session_class`, `channel_kinds.home`). It found one false claim of its own: that her "70 字"
measured her 随身 cap (D6 now says what is not known).

**A fresh reviewer** read the first version against the code, told to judge the code and not the prose. It found no
blocking problem in the direction and thirteen defects; the worst three would have put false sentences in front of
her on the first day. All are fixed in this version, most by one change: the first version had the worker read the
plugin's log file; this one has the plugin hand each finished restart over, as ADR-101 hands over an outage.

| # | Finding | Done |
|---|---|---|
| 1 | Reading the log turned all 41 old lines into unshown rows ("重启了 41 次"), and the 7-day delete would recreate them | The old log is never read (D2); only restarts handed over after the build become rows |
| 2 | The `back` line lands after `ready()`, often after a home turn built the row, which never got its `back_at` | Rows are written complete, by the hand-over after the start (D1, D2) |
| 3 | A failed start or a Host killed mid-restart was said twice (an outage and a restart); `worker failed` fell under `unknown` | Not handed over: removed, or never written (D1) |
| 4 | A queued restart lost its reason and `held`; a throw left `restartAgain` set; the check-then-set gap ran two restarts | Both defects fixed in D1 and tested (§2, §7) |
| 5 | The hold trail's schema did not match the Host's sets and call counts; it was never discarded; "newest 6" dropped the first holder | `by` a set, `calls` its count, the first and newest 4 kept with `changes`, discarded when sent or withdrawn (D1) |
| 6 | The 64 KB tail read made a permanent false 「读坏了」 and could miss lines of a loop | No file is read by the worker |
| 7 | An older plugin's lines were listed one by one, against D2's own rule | An older plugin hands nothing over; nothing is said |
| 8 | Count arithmetic, runs at the window's edge and a long hold inside a run were not defined | Defined in D4 and tested |
| 9 | "Home lines" invited `place == 'home'`, which also matches the owner's QQ DM | D5 names the two tests and the code's place names |
| 10 | No caller for the 7-day delete; the jsonl's rotation raced the worker's read | The delete runs at each worker start (D2); the jsonl has one writer and no reader (D1) |
| 11 | The plugin could tell "no `held` sent" from "not held" and wrote the same for both | `held_sent` (D1) |
| 12 | D6's bound held only for the assumed case | Titles at most 20 characters, two holders named and the rest counted, the bound restated and tested |
| 13 | `recovery:<project>` took a free string | A closed pattern; otherwise `unknown` (D3) |

The reviewer also checked and found fine: no restart path is missing, restart ids can join `told.host_stops`, a row
with no `back_at` is valid in the catalog, the eleven times of 10-30 form one run as D4 defines it, and the core
takes no channel name.
