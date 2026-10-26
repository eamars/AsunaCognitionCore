# ADR-101: What happened to her, in her own block

Status: proposed 2026-10-27, for review by the owner and Xiaoman before it is built.

## Why

After ADR-100, Xiaoman checked her own block for the morning of 10-27 (her words: what she wants is "to see in her own
block what happened", not one more log line). Three things she should have been able to read were not there.

1. **A worker that was down while the Host ran on.** From 06:29:45 to 08:42 and from 08:44 to 09:14 she was not
   running, but her block showed only the half hour when the Host itself was down. `host_stops` records a stop
   only when the next start finds the lease left behind. A worker that stops cleanly (as `ready()` stopped it) deletes
   the lease, and a stop that a later start inside the same Host repairs leaves no trace at all.
2. **A planned restart.** A restart I marked as planned (`python -m asuna.host_stops planned`) is recorded as
   `planned` and hidden. Her restart block then says only 「启动：从启动器开的，不是你要的重启」, so she cannot tell
   a planned restart from someone starting the Host for no reason.
3. **Her path names.** Her `paths` line (`local_roots.context_line`, under `action_capabilities_from_program`)
   teaches a fixed list of every kind of root (`TEMP`, `FS`, `DSH_HOME`, `DRIVE_X`, ...). The refusal for an unknown
   name lists the names this machine's table really has (`Table.names`). On this machine the two lists differ: there
   is no `TEMP`, `FS` or `DSH_HOME` here, and the drives are `DRIVE_C`, `DRIVE_D` and `DRIVE_Z`. She learnt the line,
   wrote what it taught her, and was refused.

And one from her ADR-099 review:

4. **Thoughts in `tool` mode.** Every check that asks for her thought reads `asks_thought(ep)` (`think` is in the
   turn's tools). Today nothing removes `think` in `tool` mode: it is in every turn kind's rules, in every
   conversation's list, and in `switches.KEEP`, so it cannot be switched off. If something ever did remove it, the
   turn would not be silent: `take_thought` runs in both modes and records `thought.taken` or `thought.none`. But
   `tools_week` shows the `thoughts` reading only in `thinking` mode, so in `tool` mode those rows would reach no one.

The broken invariant, for 1 and 2: **every span in which she was not running is recorded once, with how it began and
ended, and her block says it in words for a day.** For 3: **what she is taught and what she is checked against come
from one source.** For 4: **a reading appears when there is something to read, not when a setting says so.**

## Decision

### 1. A worker that was down

The Host plugin (JS) is the only side that knows why a worker went away, so it keeps the open span itself:

- **When.** A worker goes down unplanned when its start fails (`ready()`'s failure) or when it exits (`workerFailed`).
  A planned in-place restart (her publication, a settings change, a recovery) and the Host's own shutdown open no
  span.
- **Where.** In the profile's data folder: `<data>/worker-down.json`, `{since, cause, tries}`. `since` is when the
  first failure happened (its stop time), and `cause` is its categorical name: `start_failed:<name>` (the error code
  or the exception's class, as `faults.cause` takes it, e.g. `AutoReconnect`) or `exited:<code>`. `tries` counts the
  unplanned stops while the span is open. A second failure keeps `since` and `cause` and adds to `tries`. A file, not
  the database: the failure is often the database itself, and the file survives a Host restart (the 06:29 span ran
  across one).
- **Closing it.** When a start completes (`ready()` reaches `navigation.ready`), the plugin hands the open span to the
  worker (`host.came_back`, `{since, cause, tries}`). The worker records one `host_stops` row, `how: worker_down`,
  `alive_until: since`, `back_at: now`, with `cause` and `tries`. Then the plugin deletes the file. If that call
  fails, the file stays and the next completed start records it.
- **A worker's exit is not a Host kill.** A worker that exits leaves its lease behind, and today the next start reads
  that as an outside kill (「宿主上次是被外部终止的」). The plugin passes the open span with `initialize` as well. When
  it says `exited` and the lease left behind is from about the same moment (within `PLANNED_SECONDS`), no `killed` row
  is written: the `worker_down` row covers it.
- **Her words.** `host_stops.block` shows the stops of the last day (newest first, at most three), each with its
  `what` and `when`, plus the existing `note`. For `worker_down` the `what` is
  「宿主一直在运行，但替你处理一切的那部分程序停了，没有马上起来」, plus the cause in words:
  启动时出错（AutoReconnect），程序隔一阵自己重试，第 N 次起来了 / 它自己退出了（退出码 N），程序把它重新拉起来.
  The `when` keeps today's form: last known running, back, and about how long. The cause is a name only. The error
  text is never passed on, because it carries a host address.

### 2. A planned restart

- `mark_planned` already stores `planned_stop.by`. The lease keeps it as `planned_by`, and `host_stops.record` stores
  it in the row as `by`.
- `host_stops.block` still does not show `planned` rows: they are not incidents, and her restart block covers that
  start. The restart block (`restarts.block`) names it: for a launcher start whose `host_stops` row is `planned`, the
  `what` is 「启动：从启动器开的，是计划内的重启（%s 事先标好的），不是你要的」.

### 3. Her path names from the table

`context_line(home)` lists the names of the worker's own table (`current().names`), each with its meaning
(`DRIVE_<X>` as 「X 盘」), and nothing else. The refusal and the line then come from one source. With no table (its
build refused), the line says that no placeholder can be handed over this time, which is what `outbound` does.

### 4. Thoughts in every mode

`tools_week` shows the `thoughts` reading whenever the week has `thought.taken` or `thought.none` rows, in either
mode. No new check, no new row: if anything ever removes `think` from a turn in `tool` mode, the capture already
records it, and now she reads it.

## Failure modes

| Case | What happens |
|---|---|
| The database is unreachable when a start fails | The file is written (no database needed). The span closes at the first completed start. |
| The Host is killed while a span is open | The file survives. The next Host's completed start records the whole span with all its tries. The kill itself is recorded as today, from the lease, only if a worker held one. |
| `host.came_back` fails (database reset in that second) | The file stays, the next completed start records it, and no row is duplicated: the row is written only once the call succeeds. |
| A worker exits and the next start fails too | One span: `since` is the exit, `cause` is `exited`, `tries` is 2. |
| The file is unreadable or malformed | It is treated as no span and replaced. One `Asuna:` warning line. |
| Another deployment shares the database | The file is per data folder, so per deployment. Its rows carry no deployment id, as today's `host_stops` rows carry none. |
| She never comes back | Nothing is recorded until she does. The span is in the file and in `host.log` (ADR-100's lines). |
| A planned restart's mark expires (more than `PLANNED_SECONDS`) | It is recorded as `killed`, as today, and her block says so. |

## Not changed

The lease (ADR-020): still one Host per database, still deleted on a clean stop. A supervisor watchdog stays deferred
(ADR-100).

## Tests (to be written with the build)

- JS: a failed start writes the file. A second failure keeps `since` and adds a try. A completed start sends
  `host.came_back` and deletes the file. A failed call keeps it. A planned restart writes nothing. An exit writes
  `exited:<code>`.
- Python: `host.came_back` records one `worker_down` row. The block says it in words, with its cause and tries, and
  shows up to three stops of the day. A lease left behind by a worker exit is not recorded as `killed`. A planned
  row stores `by`, and the restart block names it.
- `context_line` lists exactly `Table.names` (the fixture machine), and no name it does not list is accepted.
- `tools_week` shows `thoughts` in `tool` mode when there are rows, and not when there are none.
