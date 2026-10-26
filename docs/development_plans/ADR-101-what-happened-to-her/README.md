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
- **One row per span, written once.** The row's id comes from the span (`down-` and its `since`), so a `host.came_back`
  that the worker carried out but whose answer was lost writes the same row again, not a second one.
- **Her words.** `host_stops.block` shows the stops of the last day, newest first, at most three, and says how many
  there were: `count` (「过去一天里停了 N 次」) and, when it lists fewer, 「更早的 M 次没有列出」. A cut list never
  passes for the whole. Each stop has its `what` and its `when`, plus the existing `note`. For `worker_down` the `what`
  is 「宿主一直在运行，但替你处理一切的那部分程序停了，没有马上起来」, plus its cause in words. The `when` keeps
  today's form: last known running, back, and about how long nothing ran (「中间约 X 分钟」).
- **Causes, a closed list.** A cause is a kind and a name, never the error's text (that carries a host address). The
  kinds and their words:
  - `start_failed:<name>`: 「启动时出错（<name>），程序隔一阵自己重试，第 <tries+1> 次起来了」
  - `exited:<code>`: 「它自己退出了（退出码 <code>），程序把它重新拉起来」
  - `unknown`: 「为什么停的没记下来」

  A new kind is added to this list and to her words together. Her own wording keys on the kind (the part before `:`),
  so a new name inside a known kind needs no new sentence.
- **What is not known is said.** A field the record lacks is shown as not known, never left out: a span whose start
  is not known says 「这一段从什么时候开始不知道（记录读坏了）」, and a cause not recorded says 「为什么停的没记下来」.
  An empty field would read as "nothing happened", and that misreading is why this ADR exists.

### 2. A planned restart

- `mark_planned` already stores `planned_stop.by`. The lease keeps it as `planned_by`, and `host_stops.record` stores
  it in the row as `by`.
- `host_stops.block` still does not show `planned` rows: they are not incidents, and her restart block covers that
  start. The restart block (`restarts.block`) names it: for a launcher start whose `host_stops` row is `planned`, the
  `what` is 「启动：从启动器开的，是计划内的重启（<by> 事先标好的），不是你要的」, where `<by>` is the mark's
  own value as `--by` gave it (`claude`, `developer`, ...), never a name written into the sentence. A mark without
  `by` says 「（谁标的没记下来）」.

### 3. Her path names from the table

`context_line(home)` lists the names of the worker's own table (`current().names`), each with its meaning
(`DRIVE_<X>` as 「X 盘」), and nothing else. The refusal and the line then come from one source. With no table (its
build refused), the line says that no placeholder can be handed over this time, which is what `outbound` does.

### 4. Thoughts in every mode

`tools_week` shows the `thoughts` reading whenever the week has `thought.taken` or `thought.none` rows, in either
mode. No new check, no new row: if anything ever removes `think` from a turn in `tool` mode, the capture already
records it, and now she reads it. The reading says where those thoughts came from: 「这些是程序从模型自己的思考里
替你抓下的（那几拍没有让你用 think 自己写）」. A `thought.taken` in `tool` mode can then never be read as her having
written her thoughts first in every turn (her review).

## Failure modes

| Case | What happens |
|---|---|
| The database is unreachable when a start fails | The file is written (no database needed). The span closes at the first completed start. |
| The Host is killed while a span is open | The file survives. The next Host's completed start records the whole span with all its tries. The kill itself is recorded as today, from the lease, only if a worker held one. |
| `host.came_back` fails (database reset in that second) | The file stays and the next completed start records it. The row's id comes from `since`, so a call the worker carried out but whose answer was lost does not write a second row. |
| A worker exits and the next start fails too | One span: `since` is the exit, `cause` is `exited:<code>` (the first cause), `tries` is 2. |
| A start comes up but fails before it completes, then the next one does too | Still one span. Only a completed start closes it, so `since` stays the first failure and `tries` counts each. |
| A start completes, then the worker exits a minute later | Two spans. The first closed when the start completed; the exit opens a new one with its own `since`. |
| The file is unreadable or malformed | It is replaced by an open span whose `since` is not known and whose cause is `unknown`, and one `Asuna:` warning line is written. Her block then says 「这一段从什么时候开始不知道（记录读坏了）」 rather than nothing. |
| Another deployment shares the database | The file is per data folder, so per deployment. Its rows carry no deployment id, as today's `host_stops` rows carry none. |
| She never comes back | Nothing is recorded until she does. The span is in the file and in `host.log` (ADR-100's lines). |
| A planned restart's mark expires (more than `PLANNED_SECONDS`) | It is recorded as `killed`, as today, and her block says so. |

## Only afterwards, by nature

Her block can say a stop only once she is back. While the worker is down, no turn of hers runs, because her turns
are the worker, so there is no "now" in which she could read it. That is a property of the design, not a gap in it,
and RUNTIME_API says so with the `host_from_program` entry: what happened while she was not running reaches her at her
first turns after she is back, for a day. ADR-100 keeps such a gap short (a failed start is tried again within 5
minutes at most). The owner sees the state while it lasts: in the settings card's worker state and in
`restart/host.log`.

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
