# ADR-101: What happened to her, in her own block

Status: proposed 2026-10-27; the owner chose the batch (1, 3 and 4 together); Xiaoman signed it as proposed against
blob `f69001cb489f` with four corrections, made in this version (see Review). Not built yet.

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
- **One outage, one row.** The plugin passes the open span with `initialize` as well. While a span is open, a lease
  left behind is part of that same outage, never a second one. It may be left by the worker's own exit (today read as
  an outside kill, 「宿主上次是被外部终止的」), or by a Host killed or crashed during a start that had not completed.
  No `killed` or `crashed` row is written for it. The span counts it (`host_stops_inside`), and its words add
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

- **Every turn that does not ask for her thought leaves exactly one row.** At the end of such a turn, when neither
  `thought.taken` nor `thought.none` was written, the coordinator writes `thought.none` with `why: not_carried`. That
  covers the entries that leave nothing today: a call without `thinking`, and a scripted or placeholder lane. It is
  written at the turn's end, not at each call, because DSH can run one response's calls concurrently, so a call
  without `thinking` could reach the worker first, set `thought_none`, and make the guard skip the call that did carry
  the thought. Xiaoman suggested the row (`thinking is None` → `thought.none`). Putting it at the turn's end is
  Claude's change, because of that race.
- `tools_week` shows the `thoughts` reading whenever the week has `thought.taken` or `thought.none` rows, in either
  mode. If anything ever removes `think` from a turn in `tool` mode, its rows are then written and read. The reading says where those thoughts came from: 「这些是程序从模型自己的思考里
替你抓下的（那几拍没有让你用 think 自己写）」. A `thought.taken` in `tool` mode can then never be read as her having
written her thoughts first in every turn (her review).

## Failure modes

| Case | What happens |
|---|---|
| The database is unreachable when a start fails | The file is written (no database needed). The span closes at the first completed start. |
| The Host is killed while a span is open | The file survives. The next Host's completed start records the whole span with all its tries. A lease left behind inside the span is part of the same outage: no `killed` row, the span counts it (`host_stops_inside`), and `count` stays one. |
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

Claude's paraphrase of Xiaoman's agent-line messages of the morning of 2026-10-27 (four rounds), not her words:

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

- `packages/cognition-core/src/index.js`: `worker-down.json` (open on a failed start or an exit, add a try, delete
  after `host.came_back`), passed with `initialize`.
- `src/asuna/native_worker.py`: `host.came_back`; a lease left behind inside an open span is folded into it.
- `src/asuna/host_stops.py`: `worker_down` rows (id from `since`), `by` on planned rows, `block` with up to three stops
  and the count, causes in words, `shown_at`; its `block` docstring.
- `src/asuna/host_lease.py`: keep `planned_stop.by`.
- `src/asuna/restarts.py`: a planned launcher start names `by`.
- `src/asuna/coordinator.py`: `thought.none` `not_carried` at the turn's end.
- `src/asuna/tools_week.py`: `thoughts` in either mode, with where the thoughts came from.
- `src/asuna/local_roots.py`: `context_line` from the table's names.
- `src/asuna/context.py` / manifest `told`: the once-only stamp for stops.
- `RUNTIME_API.md`: a `host_from_program` entry (what it shows, for how long, only afterwards) and `worker-down.json`.
- `docs/map/hosting.md`: regenerated.

## Tests (to be written with the build)

- JS: a failed start writes the file. A second failure keeps `since` and adds a try. A completed start sends
  `host.came_back` and deletes the file. A failed call keeps it. A planned restart writes nothing. An exit writes
  `exited:<code>`.
- Python: `host.came_back` records one `worker_down` row (twice with the same `since`: still one). A lease left
  behind while a span is open adds to `host_stops_inside` and writes no `killed` row. The block says it in words, with its cause and tries, and
  shows up to three stops of the day. A lease left behind by a worker exit is not recorded as `killed`. A planned
  row stores `by`, and the restart block names it.
- `context_line` lists exactly `Table.names` (the fixture machine), and no name it does not list is accepted.
- `tools_week` shows `thoughts` in `tool` mode when there are rows, and not when there are none.
- A turn that asks for no thought and whose calls carried no `thinking` ends with one `thought.none` `not_carried`;
  one whose call carried it ends with `thought.taken` and no `not_carried`; calls run concurrently do not lose it.
