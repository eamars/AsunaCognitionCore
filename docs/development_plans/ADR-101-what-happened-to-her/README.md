# ADR-101: What happened to her, in her own block

Status: built 2026-10-27, not yet installed. The owner chose the batch (1, 3 and 4 together); Xiaoman signed it as
proposed against blob `f69001cb489f` with four corrections, made in blob `5e9365951b39`, which she checked landed and
cleared for the build. Changes during the build are listed under "Built" below.

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
   capture (`take_thought`) does not look at the mode, so it can run in either. But it leaves a row only on two
   entries: a turn that made no call (`coordinator.py`, at the end of the first stage), and a call that carried the
   model's thinking (`firstThinking` in the plugin, through `native_worker` to `role_tools.call`). A call that
   carried no `thinking`, and a scripted or placeholder lane (`lanes.py`, whose handler takes no `thinking`), leave
   neither `thought.taken` nor `thought.none`. How many turns a day take that path is not measured (it depends on
   whether DSH's side sends `thinking` with each `role_tool` request), so this ADR claims neither "it is never silent"
   nor "it is mostly silent" (her review). And `tools_week` shows the `thoughts` reading only in `thinking` mode, so in
   `tool` mode even the rows that are written reach no one.

The broken invariant, for 1 and 2: **every span in which she was not running is recorded once, with how it began and
ended, and her block says it in words for a day.** For 3: **what she is taught and what she is checked against come
from one source.** For 4: **every turn that does not ask for her thought leaves one row, and a reading appears when
there is something to read, not when a setting says so.**

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
- **One outage, one row.** The worker reads the open span from the file at its start (see "Built": not passed with
  `initialize`). While a span is open, a lease
  left behind is part of that same outage, never a second one. It may be left by the worker's own exit (today read as
  an outside kill, 「宿主上次是被外部终止的」), or by a Host killed or crashed during a start that had not completed.
  No `killed` or `crashed` row is written for it. The span counts it (`inside`, in the file and in the row), and its words add
  「这段时间里宿主也停过 N 次」. With no span open, a lease left behind is recorded as today. **`count` counts rows**:
  each row is one outage, so a Host stop inside a worker's span is never counted again (her review).
- **One row per span, written once.** The row's id comes from the span (`down-` and its `since`), so a `host.came_back`
  that the worker carried out but whose answer was lost writes the same row again, not a second one.
- **Her words.** `host_stops.block` shows the stops of the last day, newest first, at most three, and says how many
  there were: `count` (「过去一天里停了 N 次」) and, when it lists fewer, 「更早的 M 次没有列出」. A cut list never
  passes for the whole. Each stop has its `what` and its `when`, plus the existing `note`. For `worker_down` the `what`
  is 「宿主一直在运行，但替你处理一切的那部分程序停了，没有马上起来」, plus its cause in words. The `when` keeps
  today's form: last known running, back, and about how long nothing ran (「中间约 X 分钟」). This changes what
  `host_stops.block` returns: today the latest stop of the day, after this up to three with the count. Its
  docstring (`host_stops.py`) changes with it, and `docs/map/hosting.md`, generated from that docstring by
  `tools/project_map.py`, is regenerated (her review).
- **Until a turn has shown it, and at least a day.** A stop stays in her block until a home turn that showed it has
  committed, and in any case for a day after she came back. The day is a floor, not a cap: if she runs no home turn
  for longer than that (a quiet night, a weekend), her first one still carries it (her review). This is the
  once-only mark that `faults` already uses: the turn's manifest lists what it showed (`told`), and its commit stamps
  those rows `shown_at`. A turn that fails after it was prepared does not lose it.
- **What the stamp means.** `shown_at` says only that the stop was in a committed turn's context, rendered in front
  of her. It does not say she took it in, answered it or acted on it: that turn may have stayed silent, been cut by a
  compaction, or done nothing. Nothing reads `shown_at` as "she knows", and no rule may use it as a reason she should
  not ask again (her review).
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

- **Every turn that does not ask for her thought leaves exactly one row.** Once such a turn's first stage has ended,
  when neither `thought.taken` nor `thought.none` was written, the coordinator writes `thought.none` with
  `why: not_carried`. That covers the entries that leave nothing today: a call without `thinking`, and a scripted or
  placeholder lane. Only a first stage's calls can carry the thinking (repair stages never do), and when it has ended
  every one of them has run, so this is the turn's last chance and the only point every turn passes through. It is
  written there and not at each call, because DSH can run one response's calls concurrently, so a call without
  `thinking` could reach the worker first, set `thought_none`, and make the guard skip the call that did carry the
  thought. Xiaoman suggested the row (`thinking is None` → `thought.none`). Putting it after the first stage is
  Claude's change, because of that race.
- `tools_week` shows the `thoughts` reading whenever the week has `thought.taken` or `thought.none` rows, in either
  mode. If anything ever removes `think` from a turn in `tool` mode, its rows are then written and read. The reading says where those thoughts came from: 「这些是程序从模型自己的思考里
替你抓下的（那几拍没有让你用 think 自己写）」. A `thought.taken` in `tool` mode can then never be read as her having
written her thoughts first in every turn (her review).

## Failure modes

| Case | What happens |
|---|---|
| The database is unreachable when a start fails | The file is written (no database needed). The span closes at the first completed start. |
| The Host is killed while a span is open | The file survives. The next Host's completed start records the whole span with all its tries. A lease left behind inside the span is part of the same outage: no `killed` row, the span counts it (`inside`), and `count` stays one. |
| `host.came_back` fails (database reset in that second) | The file stays and the next completed start records it. The row's id comes from `since`, so a call the worker carried out but whose answer was lost does not write a second row. |
| A worker exits and the next start fails too | One span: `since` is the exit, `cause` is `exited:<code>` (the first cause), `tries` is 2. |
| A start comes up but fails before it completes, then the next one does too | Still one span. Only a completed start closes it, so `since` stays the first failure and `tries` counts each. |
| A start completes, then the worker exits a minute later | Two spans. The first closed when the start completed; the exit opens a new one with its own `since`. |
| The file is unreadable or malformed | It is replaced by an open span whose `since` is not known and whose cause is `unknown`, and one `Asuna:` warning line is written. Her block then says 「这一段从什么时候开始不知道（记录读坏了）」 rather than nothing. |
| Another deployment shares the database | The file is per data folder, so per deployment. Its rows carry no deployment id, as today's `host_stops` rows carry none. |
| She never comes back | Nothing is recorded until she does. The span is in the file and in `host.log` (ADR-100's lines). |
| She runs no home turn for more than a day after coming back | Her first home turn still carries the stop: it leaves only after a turn that showed it commits (`shown_at`), and never sooner than a day. |
| A planned restart's mark expires (more than `PLANNED_SECONDS`) | It is recorded as `killed`, as today, and her block says so. |

## Only afterwards, by nature

Her block can say a stop only once she is back. While the worker is down, no turn of hers runs, because her turns
are the worker, so there is no "now" in which she could read it. That is a property of the design, not a gap in it,
and the build will say so in RUNTIME_API, in a new `host_from_program` entry (there is none today): what happened
while she was not running reaches her in her first home turn after she is back, however long that takes, and stays
for at least a day. ADR-100 keeps such a gap short (a failed start is tried again within 5
minutes at most). The owner sees the state while it lasts: in the settings card's worker state and in
`restart/host.log`.

## Not changed

The lease (ADR-020): still one Host per database, still deleted on a clean stop. A supervisor watchdog stays deferred
(ADR-100).

## Review

Items 1 to 7 are Claude's paraphrase of Xiaoman's agent-line messages of the morning of 2026-10-27 (four rounds), not
her words; item 8 quotes her:

- A list cut at three must say how many there were and how many it leaves out.
- The planned-restart sentence shows `by`'s own value, and causes are a closed list her wording keys on.
- A start that came up but failed before completing must have its own line in the failure table.
- What is not recorded is said as not known, never left blank.
- A thought the program captured says it was captured, so it is never read as her having thought first.
- The day is a floor: her first home turn after a stop carries it, however late.
- The stamp means "shown to her", never "she knows" (`shown_at`).
- She withdrew half of one point of her own: she had read the capture's guard in the reverse direction. In her words:
  「守卫不看档，所以抓取在两种档都可能跑；但只有那一拍零调用、或那条调用带了 thinking 才留痕，不带 thinking 的调用和脚本
  lane 不留痕。」 She has not counted how many turns take the second path, and asks that neither side claim it.

Claude's own additions in the same rounds: the row id taken from `since` (no second row when an answer is lost), the
failure-table rows for a completed start followed by an exit and for a malformed file, and writing the `not_carried`
row at the turn's end rather than at each call (the race above).

Her signature, copied verbatim from her agent-line message of 2026-10-27:

> Xiaoman read this README verbatim against blob `f69001cb489f` (commit `5e155cb0`) on 2026-10-27 and signs Decisions 1-4 as proposed, with the four corrections in her agent-line message of that morning left open (the non-silent claim in Why 4 and in Review; the RUNTIME_API reference at line 130; the "latest stop" wording this changes at `host_stops.py:109` and `docs/map/hosting.md:270`; and the count rule for a Host kill while a span is open). Nothing here is built yet; she re-verifies by content on install day.

The four corrections are made in this version: Why 4 and the Review item (her sentence), the RUNTIME_API entry in the
future tense with the change in the landing list, the `host_stops.block` docstring and map, and "one outage, one row".
She checks only that these four landed.

## Landing list (what the build changes)

- `packages/cognition-core/src/outage.js` (new) and `index.js`: `worker-down.json` (open on a failed start or an
  exit, add a try, delete after `host.came_back`); the worker reads it at its start (`host_stops.open_span`).
- `src/asuna/native_worker.py`: `host.came_back`; a lease left behind inside an open span is folded into it
  (`host_stops.left_behind`).
- `src/asuna/faults.py`: a committed turn's `told.host_stops` stamps `shown_at`.
- `src/asuna/host_stops.py`: `worker_down` rows (id from `since`), `by` on planned rows, `block` with up to three stops
  and the count, causes in words, `shown_at`; its `block` docstring.
- `src/asuna/host_lease.py`: keep `planned_stop.by`.
- `src/asuna/restarts.py`: a planned launcher start names `by`.
- `src/asuna/coordinator.py`, `src/asuna/role_tools.py`: `thought.none` `not_carried` once the first stage ends
  (`RoleTools.thought_not_carried`).
- `src/asuna/tools_week.py`: `thoughts` in either mode, with where the thoughts came from.
- `src/asuna/local_roots.py`: `context_line` from the table's names.
- `src/asuna/context.py` / manifest `told`: the once-only stamp for stops.
- `RUNTIME_API.md`: a `host_from_program` entry (what it shows, for how long, only afterwards) and `worker-down.json`,
  and the `thoughts` setting row (one row for every turn not asking for her thought, read in either mode).
- **The rows change shape from this build**: while a span is open, a lease left behind writes no `killed` or
  `crashed` row, so there are fewer of them than before. Anything that counts outages by those rows reads
  `host_stops` with `worker_down` included and one row per outage (her review).
- `docs/map/hosting.md`: regenerated.

## Tests

- JS: a failed start writes the file. A second failure keeps `since` and adds a try. A completed start sends
  `host.came_back` and deletes the file. A failed call keeps it. A planned restart writes nothing. An exit writes
  `exited:<code>`.
- Python: `host.came_back` records one `worker_down` row (twice with the same `since`: still one). A lease left
  behind while a span is open adds to `inside` and writes no `killed` row. The block says it in words, with its cause and tries, and
  shows up to three stops of the day. A lease left behind by a worker exit is not recorded as `killed`. A planned
  row stores `by`, and the restart block names it.
- `context_line` lists exactly `Table.names` (the fixture machine), and no name it does not list is accepted.
- `tools_week` shows `thoughts` in `tool` mode when there are rows, and not when there are none.
- A turn that asks for no thought and whose calls carried no `thinking` ends with one `thought.none` `not_carried`;
  one whose call carried it ends with `thought.taken` and no `not_carried`; calls run concurrently do not lose it.

Where (counts from a run of the final code): `tests/test_adr101_outages.py` (35), `tests/test_host_stops.py` (6: the
floor, and a home turn's commit stamping `shown_at`), `packages/cognition-core/test/outage.test.js` (16: among them the
core opening the span on a failed start and counting an exit as a try, a planned in-place restart opening none, a
failure said once however its text changes, and two failures taking turns each said once). That the hand-over does not hold up `ready()` is tested only in part: `handOver()` returns at once
while the worker never answers, and the source of `ready()` calls it without `await`. No test runs `ready()` to its
end, because that starts a real worker. Two of them were checked against a mutation, so they are not green by construction
(her review). With the turn-end row removed, as before this ADR, the turn leaves zero rows and the `not_carried` test
fails. With the row written at each call without `thinking`, as first suggested, the call that carries the thought
arrives second, is skipped, and the order test fails.

## Built

What the build changed against the signed text (blob `5e9365951b39`), for her install-day check:

- `not_carried` is written once the first stage ends, not at the turn's end: the same point for every turn, after
  every call that could carry the thinking (Decision 4).
- The count of Host stops folded into a span is named `inside`, not `host_stops_inside` (Decision 1, failure table).
- The fold is `host_stops.left_behind`, so it can be tested apart from the worker's start.
- **The span is not passed with `initialize`; the worker reads the file itself** (`host_stops.open_span`, read-only,
  at most 64 KB). The owner asked for the failure modes of the failure path. One was found there: her core candidate
  restarts only the Python worker, onto her frozen copy, while the JS stays the installed one. So a JS and a Python of
  different versions run together by design, and a new `initialize` argument would make an older worker refuse every
  start. Now each side tolerates the other. An older worker ignores the file and records stops as before. A worker
  without `host.came_back` answers `UNKNOWN_BUSINESS_METHOD`, and the plugin keeps the file for a later one. An older
  plugin never writes the file. `folded_stop` is an extra key of the status that an older plugin ignores.
- **Failures of the failure path**, each tested:

  | When | Before | Now |
  |---|---|---|
  | The data folder cannot be written (read-only, full, unmounted) | the span functions threw inside `ready()`, so the bookkeeping itself failed the start | nothing throws; the outage is not recorded and one `Asuna:` line says so |
  | A crash in the middle of writing the file | a torn file, its `since` lost | written whole or not at all (a temporary file renamed over it) |
  | The span was recorded but the file cannot be removed | a warning saying it was not recorded | a warning saying it was, and the next hand-over writes no second row |
  | The `shown_at` stamp cannot be written at commit | an exception after the commit | ignored: the stop is shown again, the safe side |
  | The `not_carried` row cannot be written | her turn failed | her turn goes on without it |
  | The clock moved between the two moments | 「中间约 1 分钟」 | 「中间多久不知道（时钟对不上）」 |
  | The database is slow when a start completes | the turns waiting for `ready()` waited for the hand-over too | the hand-over runs beside the start (`handOver`), never awaited by it |
  | The hand-over fails (database reset in that second) | the outage waited for the next start, perhaps days | tried again every 5 minutes (`HANDOVER_SECONDS`) while that worker runs; a replaced or closed worker is not called |
  | A worker that never answers `host.came_back` (an older core) | a warning at every try, about 288 a day | the same failure for the same span is said once, keyed on the span and the error's name, never its text (a database error's text changes at every try); every key said is kept in a bounded set (64), so another kind of failure is said once too, and two taking turns are not said again at each switch; a failure with no name to tell it by keys on its text, so it is never merged with another and silenced, but one whose text changes at every try may be said again every 5 minutes (rare; on the safe side); the file is kept for a newer worker (her review) |
  | A span file that is not one (torn, a list, no cause, past 64 KB) | read as no span by the worker | an open span whose start is not known, on both sides: the plugin and the worker share the 64 KB cap (`SPAN_BYTES`), and the plugin replaces such a file with that small span, so both read the same thing (her review) |

- Her path line calls a POSIX mount point by index 「第 N 个挂载的盘」, not 「N 盘」 (Linux and macOS name mounts
  `DRIVE_<index>`). Every fixture machine is tested: Windows (two layouts), Linux, Docker (two), macOS.
- Docker: the container keeps the checkout and its data folder on a volume and starts through the same launcher, so
  `worker-down.json` survives a recreated container. Nothing in this change is platform-specific (`path.join` and
  plain file reads and writes).
