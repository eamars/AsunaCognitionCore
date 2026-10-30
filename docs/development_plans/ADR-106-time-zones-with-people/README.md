# ADR-106: Time zones with people, not with groups

Status: requirements recorded 2026-10-27; designed to final 2026-10-29 with the owner's three decisions below (the
question tool, his recommended options each time) and one fresh review whose findings are fixed in this page. Built
2026-10-29 on `claude/eloquent-shannon-fcxodi` (`Built`, below); not landed, not yet read by Xiaoman. The local Claude
Code takes the readings, brings it to her and lands it.

The ask, in one line: **she lives on one clock in every conversation, and no zone is hard-coded per group**. Anything
wider is not in this ADR (`Not in this ADR` lists what was found and left out).

## The owner's words (2026-10-27, verbatim)

In the question tool, asked whether two lines of her usage-readout skill may keep this machine's UTC offset:

> For now don't focus too much about details like this. Later I will discuss with you to remove the timezone
> information from the database, and only use the local TZ. The TZ seems causing more confusion than the problem it
> solved.

Then, recording this requirement:

> the idea is to remove the hard coded TZ from the group. She seems confused with TZ with me. so perhaps in the future
> the TZ can be softly tied with each person. In her note. Not a mechanical placeholder for each group. This is just
> my coarse direction, and I want you to grill me when the rest of ADRs are complete.

Then, adding to it:

> The idea is to make Xiaoman "not serving others". Like a real person, she don't need to consider other's timezone.
> If she does, she can keep in her note, not a mechanical reminder every time. The core idea is "do not assume", and
> "keep her the center of her world".
>
> And some of the question can be answered "what if she is a real person".

## What exists (read in the code on `cc8c00627132`, 2026-10-29)

Counts of the deployment (18 of 29 scenes, 348 of 354 plans) are the earlier reading of 2026-10-27, read-only; they are
re-read before building (`Before building`).

### Where a zone is stored or chosen

| Datum | Where | Read by |
|---|---|---|
| a group's zone | `scenes.timezone`, written only by her `place_timezone` tool (`places.set_zone`) | `schedule_rules.scene_timezone` (every conversation's clock), `places.group_zone` (the "their clock" line) |
| a route's zone | `routes.<id>.schedule.timezone`, `routes.<id>.timezone`, `routes.<id>.schedule.utc_offset_minutes` in the deployment's settings; nothing in the program writes them | `scene_timezone` |
| the deployment's zone | top-level setting `timezone` (the Web settings card's "Time zone"; no check on the value) | `scene_timezone` (4th), `persona_model.timezone` (2nd), `tools/memory_pilot_report.py` |
| her rhythm's zone | policy key `rhythm.timezone` (a "private" key: a package may not default it; she can still write it with `set_policy`) | `persona_model.timezone`: rhythm block, nightly settlement, night stage, visit counts, heartbeat pause, her home tasks' `ASUNA_TIMEZONE` |
| a plan's zone | `plans.timezone` and `plans.tz_source`, written at create and update **for every kind of plan**; a daily or weekly plan's zone is also held by DSH's own scheduler (`time_zone`) | `scene_timezone` (1st) |

### The order a conversation's clock is resolved in

`schedule_rules.scene_timezone`: the plan's stored zone, the route's, the scene's, the deployment's, then UTC; a name
the machine cannot load falls to the route's fixed offset, then to the host's clock as a fixed offset (no daylight-saving
rules). Counted by `grep` on `cc8c00627132`: 47 call sites in 20 modules ask `scene_timezone` or `local_time.zone_of`
(`context.py` 11, `schedule.py` 6, `role_tools.py` 5); `persona_model.timezone` (her rhythm's resolver, a second one) is
imported at 15 sites in 8 modules; 24 modules in all. Five helpers resolve a zone again on their own:
`ScheduleService.zone_of`, `Coordinator._zone`, `carried._zone`, `restarts._zone` and `self_review._zone`. Six sites
write `zone if is_iana(zone) else 'UTC'`, so a name the zone database loads but that is not `Area/Location` gets two
clocks (`schedule.py` 284, 298, 709; `places.py` 333, 376; `role_tools.py` 2646).

### The root cause

The program treats the clock as a property of the room. Her `place_timezone` tool says so to her ("设了以后，那边几点、
你在那个群定的计划，都按那个群的钟"): one field, `scenes.timezone`, is at once "where those people are" (what she knows
about them) and "which clock every time in that room is drawn on and every plan made there fires by". The same text
("20:00") then names different moments in different rooms. The broken invariant: **one time text must name one moment for
her, in every room.** A rule that fixes the group-zone case and leaves the class (a time drawn on a clock that is not
hers because of where it was read) would be a bandage. The instances of the class, found in this reading and the
review, each checked on the code:

1. A reminder written "20:00" in a room whose zone is not hers fires at another hour on her clock (Xiaoman's own
   account, question 4 below).
2. A plan written with an explicit offset (`20:00+09:00`) is worded on the **UTC** face (`schedule_rules.describe`
   passes `timezone.utc` for an `at_utc` rule), while the same moment on the room's face reads differently. Measured
   2026-10-29 with a demo zone: description `10/30 11:00`, the moment on the zone's face `10/31 00:00`.
3. The plans of other rooms she sees at home (`your_plans_there`) are worded on each room's own face and sit beside
   home's `next_fire_at`; the projection's notes are dropped by a whitelist (`context.py:809`).
4. The block she reads when a plan fires (`scheduled_plan_from_program`, `context.py:969`) carries the plan's raw
   `rule`. A wall-time `at` is naive, `local_time._moment` reads it as UTC and shifts it: a `20:00` plan in a demo zone
   nine hours ahead of UTC reads `10/31 05:00` there (measured 2026-10-29). A `clock` rule shows its bare `HH:MM`.
5. Changing a plan's timing keeps its old zone (`ScheduleService.update` reads the plan's stored zone first), so an
   edit she writes on her clock is read on the room's; and restating the same timing returns early at
   `schedule.py:863` (`current['rule'] == rule and current['intent'] == intent`), so an old plan could never be put on
   her clock by saying the same time again.
6. Her usage-readout skill's own record: a task wrote an offset it never read, because no program source gave her
   one. The program converts; she is not given an offset to carry.

## Decided with the owner (2026-10-29, the question tool; his recommended options each time)

1. **Her one clock: one deployment setting.** The existing top-level `timezone` setting is the only source. When it is
   not set, the machine's own zone as the Host reports it (no zone is hard-coded in the core); when the Host reports
   none, UTC. The per-group zones, the route zone keys and her policy key `rhythm.timezone` go; nothing is converted.
   A moved deployment keeps her zone as long as the setting is set (Xiaoman's position, 2026-10-27); an unset one
   follows "only use the local TZ".
2. **Plans: each keeps its own zone.** Every new plan is on her clock. A one-time plan is stored as an exact moment,
   so it never depends on a zone (an appointment stays that moment). A plan that already exists keeps firing as it was
   made; its words say so only when its clock differs from hers. Changing a plan's timing puts it on her clock and the
   reply says so. Nothing is rewritten at landing and nothing touches the live scheduler.
3. **What she reads: the face and the weekday, never a zone name.** No zone name in any turn, tool result or error. A
   script that needs her offset gets it from the program (`asuna.dbread` converts her face to UTC); what she keeps about
   her own place or anyone's is in her notes. Nothing is stored for this.

Consequences of his words and of those three, not asked again (they are "remove the hard coded TZ from the group" and
"not a mechanical placeholder"): her `place_timezone` tool is removed, and with it the `their_clock` line of her places
view and `scenes.timezone`. Whatever she knows about where a group's people are lives in her notes, which the program
never reads. Nothing in the program converts a time for anyone else.

## Design

### 1. One resolver, `schedule_rules.her_zone(config)`

Returns `{'name', 'tz', 'source', 'setting_unreadable'}` with `source` one of `setting`, `machine`, `unset`:

1. `config['timezone']` when the zone database can load it → `setting`.
2. Else the machine's zone, from the environment variable `ASUNA_HOST_TIMEZONE` (set by the Host, §7), else `TZ`, each
   only when it loads → `machine`.
3. Else UTC → `unset`.

`setting_unreadable` is true when a setting was given and does not load (it then falls to 2, 3). Pure and cheap (no I/O,
no store): `ZoneInfo` caches. It replaces `scene_timezone`, `local_time.zone_of`, `persona_model.timezone` and the
fixed-offset and host-local fallbacks (`_zone`, `zone_unavailable`, `tz_source`, `utc_offset_minutes`). The `tzdata`
package is a pinned dependency, so a name that is valid always loads. Every call site that took a scene for its zone
takes none (the 47 sites above; the arguments go with the function, not left as dead parameters). The five helpers
above become `her_zone` calls or go. `is_iana` stays only where DSH needs an `Area/Location` name: `native_recurring`
and `ensure_settlement`; the six `if is_iana(zone) else 'UTC'` sites use `her['tz']`.
`local_time.for_model`, `stamp`, `face` and `line_stamp` keep their shape; only the zone they are given changes.

### 2. Her clock block

`schedule_rules.local_clock` returns `{'now_local', 'weekday'}`. `timezone` and `tz_note` go; so do the rhythm block's
`timezone` and `note` (its `local_time` already drops when it equals `now_local`, and now always does), the plan tool's
echo of `timezone`, and the zone in the plan tool's refusal ("现在是 …（周几）"). `dbread`'s window receipt
(`Window.asked`) drops its `zone` name and keeps `local` and `utc`. `block_guide.py` says the `_at` fields are on the
clock of `clock_from_program`.

### 3. Plans

Two pure functions in `schedule_rules` carry the decisions, so they test without a scheduler: `has_wall_zone(rule)`
(true for a `clock` rule and for an `at` written without an offset: the rules whose meaning depends on a zone) and
`pin_at(rule, fire_at)` (a wall `at` becomes `{'at': <moment with offset>, 'at_utc': True}`, the form an `at` with an
offset already takes). `plan_zone(plan, her)` is the plan's stored zone when the rule has a wall zone and the zone
loads and differs from hers, else hers; a plan zone that does not load reads on her clock and says so without the name.

- **Create.** `zone = her_zone`; `next_fire` computes the moment; `rule = pin_at(rule, fire_at)`; only a `clock` plan
  stores a zone (`plans.timezone`, her name; DSH is given the same name through `native_recurring`, as today).
  `after`, `every` and a moment need none, so they store none and `tz_source` is not written. The retry check compares
  the stored rule with the pinned rule (deterministic for one zone).
- **Update with a timing.** The zone is hers; the rule is pinned; the early return ("nothing changed") applies only when
  the pinned rule and the wording are equal **and** the plan does not move (`has_wall_zone(rule)` and its stored zone is
  not hers). A plan that moves is saved with `timezone` = hers (or none when its new rule has no wall zone) and
  `last_update.from_timezone` = the old name; native handling is the existing in-place or re-create path with her zone.
  The tool's result carries the line in its own key `clock_note` ("这条原来按另一个钟面排，比你的钟快（慢）N 小时；
  现在按你的钟"), not in `note`, whose key the create-by-inference and fired-plan lines already use.
- **Update with a wording alone.** The plan keeps its zone and its rule; `timezone` is not written; the moment is
  computed with the plan's zone, as today.
- **Re-arm and dispatch** (`_rearm`, the native-recurring branch, the legacy migration) use `plan_zone`: a plan fires by
  the zone it was made in. `ensure_settlement` and the night stage use `her_zone`; settlement needs `source != 'unset'`
  and an `Area/Location` name for DSH's daily rule.
- **What she reads.** `schedule_rules.project(plan, her, moment)`: a `clock` rule and a legacy wall-time `at` are
  worded on the plan's zone; a moment, `next_fire_at` and every other rule on hers (this fixes instance 2). **Only** a
  rule with a wall zone can carry `clock_note`, and only when the plan's zone and hers read different hours at the plan's
  next fire: "这条的钟点写在另一个钟面上，比你的钟快（慢）N 小时；到点以 next_fire_at 为准" (hours, and minutes when there
  are any, as `places.clock_gap` words a gap today; that function goes with the group zone and its wording moves here). No
  note when they read alike, for an `after`, `every` or moment rule whatever zone the old row stored, and none for a plan
  with no next fire.
- **One brief.** `schedule_rules.plan_brief(plan, her, moment)` is `project` cut to `intent`, `description`,
  `next_fire_at`, `clock_note`. `your_plans_there` (other rooms' plans at home) uses it, which puts `clock_note` through
  the whitelist (instance 3). The due-plan block (`scheduled_plan_from_program`) drops its raw `rule` and takes
  `description` and `clock_note` from the same function (instance 4), keeping `last_occurrence_id`, `last_outcome` and
  `your_thought_then`.

### 4. The group's zone leaves

Removed: the `place_timezone` tool (spec, `tool_place_timezone`, the name lists in `role_tools.py`, `reasons.py`, the
Host's labels, icon and key map in `client.js`); `places.group_zone`, `their_time`, `clock_gap`, `set_zone`, `zones`
and the `their_clock` row; `records/scenes.py:set_timezone`. The scene row's `timezone` is cleared by §8 and nothing
reads it. The route keys (`schedule.timezone`, `timezone`, `schedule.utc_offset_minutes`) are no longer read; the
deployment reading (`Before building`) says whether any route sets them. `tools/memory_pilot_report.py` reads
`her_zone(config)['name']` instead of `config.get('timezone')`.

### 5. Her rhythm key

`rhythm.timezone` leaves `PRIVATE_KEYS`, the core defaults and the schema's reserved names and description (a package
that names it fails the schema's `additionalProperties`, as any unknown key). `set_policy` no longer offers it. A value
already in the policy ledger stays there: the ledger is append-only history, and nothing reads the key. Her rhythm
(block, settlement, night stage, visits, heartbeat pause, `ASUNA_TIMEZONE` for home tasks) uses `her_zone`.

### 6. Her notes about people

Nothing is built. A friend's zone is something she may write in her note about them; the program never reads it; a
reminder is on her clock; she works the other person's hour out herself, or gets it wrong, as a person can. The plan
tool still takes `at` with an offset for a moment she knows exactly.

### 7. The Host

`worker.js` adds `ASUNA_HOST_TIMEZONE: Intl.DateTimeFormat().resolvedOptions().timeZone` to the worker's environment (an
IANA name on every platform). The `session` binding (`native_worker.py`) gives the action brain's `web_search` her one
zone as before (`timezone`, `utc_offset_minutes`); `index.js` and `search.js` do not change. The Python side reads the
variable only when the setting is unset, so an older Host that does not set it leaves a newer worker on `TZ`, then UTC;
a newer Host with an older worker is ignored by it. Neither direction fails.

### 8. Data, once, at landing

`records/scenes.py:clear_timezones(store)` clears `timezone` from every scene that has it and returns the count (idempotent).
`tools/clear_scene_zones.py` calls it: dry run by default, `--apply` to write, prints the count only. It stays because the
owner's word is to remove the zone information from the database, and a zone name is personal data. It is a detour: the
lead runs it once after the new code is installed and verified, and the next commit deletes both (the tool and the
function). Order is safe either way: once the new code runs nothing reads the stored value, and if the removal ran
first the old code would fall to the deployment's zone, which is the new behaviour. `plans.tz_source` and
`plans.timezone` on existing plans stay (the plan's own zone, §3); the policy ledger stays (§5).

### 9. Start evidence

One record per worker start in `reports/native-host-*`, **pinned** (`Evidence(..., pinned=('runtime.ready',
'clock.zone'))`, or an unpinned kind would be pruned within hours: the file keeps its newest 3,000 records), no zone
name: `clock.zone {source, setting_set, setting_unreadable}`. The failures the owner would want to see: the setting is
set but does not load (a typo, now silent to her), and nothing is known (`unset`, she lives on UTC). A set-but-unreadable
setting is read as not set, so it falls to the machine's zone. There is no owner-facing card for it (a card is UI of our
own; it needs his approval first), so this record is where the lead sees it at landing and in readings; nothing is added
to a turn.

### 10. References changed in the same commits

`RUNTIME_API.md`: the `timezone` row (what it governs: the one clock, and the machine's zone when unset), the private-keys
row, the settlement row ("a zone is known"), and a new subsection under "Schedules" for the clock block, the plan tool's
result and `clock_note`; `RUN_ASUNA.md` (the `timezone` sentence; the systemd `TZ` line read against the new meaning);
`deploy/docker/README.md` (the `TZ` row, read against it); `docs/map/` (regenerated by `tools/project_map.py`, plus any
hand-written answer naming the removed tool); the `asuna-database` skill's `scenes` line and receipt lines;
`persona-model.schema.json`'s description; the docstrings of `local_time.py`, `schedule_rules.py`, `persona_model.py`
and `PRIVATE_KEYS`; the ADR index row. Current references show the present state, no history.

## Failure modes

No design here adds I/O, a wait or a queue; the resolver is a pure function of the settings and two environment
variables. For a slow, failing or hung item: nothing waits.

| State | What happens | Who sees it |
|---|---|---|
| setting set to a name that cannot load | read as not set: the machine's zone, else UTC | the pinned start record (`setting_unreadable: true`); she is not told |
| setting unset, Host reports a zone | she lives on the machine's zone; **at landing, a deployment whose setting is unset today moves from UTC to it** | the start record `source: machine`; the landing reading (1) |
| setting unset, no Host zone, no `TZ` | UTC | the start record `source: unset`; settlement is retired as today |
| a plan's stored zone cannot load | the plan is read and fires on her clock; its row says its zone is unreadable | her plans block |
| the deployment's zone is changed later | new plans use it; old `clock` plans keep theirs and say so when they differ; DSH's daily plans keep theirs | her plans block |
| an old plan is put on her clock by restating its time | not a no-op: it moves, and the result says so (§3) | the tool result |
| the one-off removal is not run, or stopped halfway | nothing reads the stored value; run again | the tool's count |
| the new code is rolled back after the removal | the old code falls to the deployment's zone, which is the new behaviour | none |
| an older worker with a newer Host, or the reverse | the variable is ignored, or absent (§7) | none |

What changes once on the real system: the times she reads in the rooms that had a zone of their own now read on her
clock; lines the program wrote into those rooms earlier keep the old room's face for the months they stay (no history
conversion). One line to her at landing says so.

## Tests that earn their place

Unit, on the in-memory store, fast. `tests/conftest.py` gets an autouse fixture that removes `TZ` and
`ASUNA_HOST_TIMEZONE` for every test (the resolver reads them; the suite and `tests/fixtures/world.json` assume UTC),
and a test that wants one sets it itself.

1. **No second resolver** (`tests/test_one_zone.py`, a static check in the style of `test_one_clock`): `src/asuna` and
   `tools` name `scene_timezone`, `zone_of(` and `persona_model.timezone`, or read the config's `timezone`, only in
   `her_zone`. Guards the class: a future call site that draws a room's clock again. (A test that gives `her_zone` two
   scenes would compare nothing, since it takes none.)
2. **The resolver's states** (`tests/test_her_clock.py`): setting; unset with `ASUNA_HOST_TIMEZONE`; unset with `TZ`;
   nothing → UTC; a setting that cannot load falls through and says so. A stale `scenes.timezone` on a scene row and
   old route keys in the config change nothing in the clock block, a line stamp or a plan row built for that scene.
   Guards "a typo makes her live on UTC without a sign" and the silent leftover.
3. **No zone name reaches a model** (the same file): with the setting set to a sentinel zone, the clock block, the
   rhythm block, a plan row, the due-plan block, the plan tool's refusal and result, and a `dbread` window receipt
   contain no sentinel text. Guards decision 3 across the producers the review found.
4. **A plan row reads on one face** (`tests/test_plan_view.py`): description and `next_fire_at` agree for a wall-time
   rule, a moment, a `clock` rule; `clock_note` appears exactly when a rule with a wall zone reads another hour at its next
   fire, with the right sign and span, and not for an `after`, `every` or moment rule whatever zone its row stores;
   `plan_brief` keeps `clock_note`; the due-plan block has no raw `rule`. Guards instances 2, 3 and 4.
5. **The decisions in pure functions** (`tests/test_schedule_rules.py`, stdlib only so her offline checks still run it):
   `pin_at` gives a moment that does not move when the setting changes; `has_wall_zone` by kind; `plan_zone`; the update
   decision (`moved_from`: a restated timing on another zone moves, on hers is a no-op; a wording alone keeps zone and
   rule).
5b. **The service applies them** (`tests/test_plan_zone_service.py`, `ScheduleService` over the in-memory store with a
   recording stand-in for DSH's scheduler; `test_p3_schedule.py`, named in the rules file's old docstring, never
   existed): create stores a zone only for a daily plan and pins an appointment; a retried create is the same plan; a
   restated time moves an old plan and DSH with it, and saying it again changes nothing and does not report the move
   twice; new wording keeps the plan's zone, rule and its `next_fire_at` on its own clock; re-arm uses the plan's
   clock.
6. **The removal** (`tests/test_her_clock.py`, the `store` fixture): `clear_timezones` clears only that field, returns
   the count, is idempotent, and leaves other scene fields as they were. It is a path that removes records, which
   AGENTS.md ranks first; it is the weakest of the seven and the only one that dies with the detour.
7. **The tool and the key are gone**: `place_timezone` is not offered; the refusal that lists writable policy keys does
   not name `rhythm.timezone`; a package that sets it is refused by the schema.

Existing tests that change with the behaviour: `tests/test_tool_budget.py` (the exact tool counts and sizes, the `COPIED`
pairs and `== CHARACTER[1]`), `tests/test_adr011_turns.py`, `tests/test_native_worker.py` (the session binding),
`tests/test_plan_view.py` (the zone dict), `tests/test_dbread.py` (the receipt's `zone`), the six `scene_timezone` tests
in `tests/test_schedule_rules.py`, `tests/test_persona_her_edits.py` and `tests/test_profile_compose.py` where they name
the key. A fixture zone carries the `personal-scan: ok` marker.

Not tested, on purpose: the wording of `clock_note` beyond its sign and span; the Host's one-line environment variable
(its absence is covered by test 2, and the landing's check by content reads the start record on the real system).

The static checks and repository guards run unchanged: `test_store_boundary` (the owner module is the only code that
touches `scenes`), `test_one_clock`, `test_project_map`, `test_no_undefined_names`, `test_line_endings`.

## Built (2026-10-29)

On the branch, in the checkout the build ran in. Python suites: 738 passed, 2 failed, 9 skipped; the two failures are
`tests/test_integration.py::test_stderr_timeout_and_a_snapshot_the_run_cannot_change` and
`tests/test_sandbox_backend.py::test_a_command_writes_only_its_task_folder_and_names_it_task`, which fail the same on
`cc8c00627132` untouched (no Host sandbox runner in the cloud). Node tests: 257 pass, 4 fail, 4 cancelled, the same
set as on `cc8c00627132` (turn-end compaction and ADR-098 roots, same cause). Integration tests were not run (no server).

Merged with main `1850b59` (2026-10-30; ADRs 108 and 109 and what they brought in): five conflicts, all text (three
source files, the tool-budget test, the generated map). Three places main added read a conversation's zone and now read
her clock: the action brain's tool results (`native_worker.py`), the pointer to a line in another conversation
(`people.py:source_of`), and the refusal of a plan that was not made (`role_tools.py:_plan_not_made`, which main had
lifted out of `plan`, and which no longer names a zone). The ADR-109 data child needs nothing of its own: it is given a
copy of the worker's config with every job and inherits its environment, so its history search draws on the same clock.
After the merge: Python 828 passed, 0 failed, 9 skipped (the private-words checks and the speech model are unchecked, not
passed); Node 276 pass, 4 fail, 4 cancelled. Main in a clean worktree gives 275 pass, 4 fail, 2 cancelled in the same
full run: the same four failures (three ADR-098 roots tests, the ADR-065 clone test) and the same four turn-end compaction
tests, which wait on a promise the cloud has no DSH to settle, so a full run counts two or four of them as cancelled;
the compaction file alone gives 8 pass, 4 cancelled on both trees, three runs each. None of the eight touches a zone.
Integration tests still not run. Map, secret and personal scans clean.

The new tests were checked by mutation: 22 reintroduced defects, 21 killed by the new tests (three first survived and
showed missing assertions, now added); the 22nd changed nothing the code did, because `plan_zone` already gives a rule
with no wall zone her clock, and the redundant condition was removed. What the build settled that the design left
open, and where it differs in detail:

- `records/scenes.py:clear_timezones` reads the scene rows and unsets the field on each that has it: the store refuses a
  condition on a field the catalog does not declare, and the field is no longer declared anywhere.
- `places.local_date(config, moment)` lost its model and policy arguments; `Coordinator._zone()` and `carried._zone(store)`
  stay as one-line calls of `her_zone`; `restarts._zone` only turns a zone name into the `{'tz': ...}` shape.
- `has_wall_zone` is not repeated where `plan_zone` already returns her clock (the `clock_note` gap is zero by then).
- The tool-budget test lists 30 tools and 20,564 characters (tiered, 21,000), measured on her tools as the model is
  sent them (ADR-108 D4b): `place_timezone` was 426 of that.
- Not run here, so for the landing's check by content: a real worker start (the pinned `clock.zone` record), the Host's
  `ASUNA_HOST_TIMEZONE`, the action brain's `web_search` stamps, and DSH's daily rule with a moved plan.

## Landing and restart

One landing by the local Claude Code, after Xiaoman has read the page (step 4 of the discipline):

1. The `Before building` readings, in counts, on the real deployment.
2. Tests, the push gate, fast-forward to main.
3. The planned restart while she is quiet; tell her first; the running code is the commit's (`loaded.commit`).
4. Verify by content on the real system: a turn's `clock_from_program` has two keys; her plans block reads on one face;
   `place_timezone` is not in her tool list; the pinned start record names the source.
5. `python tools/clear_scene_zones.py` (dry run), then `--apply`; the count before and after, nothing else printed.
6. One message to her: what changed for her (below), and that earlier lines in the rooms that had a zone keep that face.
7. The next commit deletes the one-off tool and the function (§8).

## Before building: the readings the local Claude Code takes (counts, no zone names)

Zones are personal data: each answer is a count or one of *same / different / absent*, never the name.

1. Is the top-level `timezone` setting set, and does it load? **If it is not set, she moves at landing from UTC to the
   machine's zone: the owner is told before.**
2. Is `rhythm.timezone` in her policy? Same as the setting, different, or absent? **If different, the owner chooses
   which one is hers and sets the setting to it before landing**: her rhythm moves to the setting at landing.
3. The Host's zone, a worker process's, a sandbox process's, and the setting: same or different? (Her own readout skill
   records one task that read the machine's clock at an offset that was not the log's; if the three differ, "the
   machine's zone" is ambiguous and the setting must be set.)
4. Scenes that carry `timezone`: how many; how many read another hour than the setting now, and in six months.
5. Routes that carry `schedule.timezone`, `timezone` or `schedule.utc_offset_minutes`: how many.
6. Plans in `CREATING`, `ACTIVE` or `SUSPENDED` **whose rule has a wall zone** (`clock`, or an `at` without an offset)
   and that carry `timezone`: how many; how many read another hour than the setting at their next fire; how many of
   those are held by DSH.

The answers decide whether `clock_note` ever shows (6 = 0 means it will not at landing; it stays for the day the setting
changes), and whether the landing message to her has a rooms sentence (4 = 0 means it does not).

## What this changes for her (for her one reading)

- Every time she reads, in any room and at home, is on her one clock, with no zone name beside it.
- `place_timezone` and the "their clock" line of her places view are gone; what she knows about a group's people she
  keeps in her notes, if she wants it.
- A plan she writes is on her clock; a one-time plan is a moment; a plan from before may say it is on another clock.
  The block she reads when a plan fires gives the plan in words, not its stored rule.
- Her policy no longer has `rhythm.timezone`.
- Her usage-readout skill's text about offsets is hers; this ADR does not touch it.

## The review of 2026-10-29 and where each finding is handled

One fresh reviewer read the first version of this page against the code (read-only). Its findings, each checked by me
on the code before it was taken; the numbers are its own.

| # | Finding | Handled |
|---|---|---|
| 1 | update's "nothing changed" return defeats decision 2; update must pin; the old zone must reach the tool; two `note` keys collide | §3 update; instance 5; `clock_note` is its own key |
| 2 | instances missed: the due-plan block, the `your_plans_there` whitelist, a zone name in `dbread` receipts, the six `is_iana ... 'UTC'` sites | §3 one brief; §2; §1; instances 3, 4 |
| 2 | UTC-sliced clock text in the digest, the week readout, the switch list, the self-review day | not this ADR (below) |
| 3 | tests read `TZ`; the suite assumes UTC | the autouse fixture |
| 4 | the service has no test harness; the class is `ScheduleService`; `test_p3_schedule.py` does not exist | decisions in pure functions, test 5; and a recording stand-in for the scheduler over the in-memory store, test 5b; the name corrected |
| 5 | the start record would be pruned; a typo fails open | §9: pinned, and `setting_unreadable`; the residual (no owner card) is stated |
| 6 | the note and the update line must depend on the rule kind; only wall-zone rules store a zone | §3 |
| 7 | missing guards: a sentinel sweep, a static guard; test 1 as first worded compared nothing | tests 1, 3, 4 |
| 8, 9, 10 | existing tests, docs and the landing gap omitted | the lists above; reading 1; `tools/memory_pilot_report.py` |
| 11 | the scene-clearing detour removes only an inert field | kept for the owner's word; §8 says why |

## What the "real person" test answered (the questions of 2026-10-27)

| # | Question | Outcome |
|---|---|---|
| 1 | Which zone information leaves the database | the scenes' zones; her `rhythm.timezone` value's reader; the route keys' reader; the zone a plan stored for a rule that has no wall zone; the plans' zones for `clock` rules stay as the plan's own (decision 2); the deployment setting stays as the one source (decision 1). An appointment is a moment; a habit follows her clock |
| 2 | "Only the local TZ" when the deployment moves | the setting is set once for her; the machine's zone only when it is not set (decision 1; Xiaoman's position holds when the setting is set) |
| 3 | Does the program read her note about a person | never; a reminder is on her clock (§6) |
| 4 | What she confused | a group line's clock (her own account); fixed at the class (the root cause above), not by a rule for her |
| 5 | A group with members in several zones | a group has no clock; there is hers and what she knows of each person |
| 6 | The zone is personal data | the setting and any note are in the settings and the database, never in tracked files; the start record carries no name; her own skill text with the machine's offset is hers to change |
| 7 | Migration | none: scenes' zones are cleared once (§8), plans keep theirs, the ledger keeps history |
| 8 | What her clock shows | the face and the weekday, never a zone name (decision 3) |

## Questions asked on 2026-10-27, kept as they were

Xiaoman takes part in this talk (she asked: her usage-readout skill's own rules depend on it, and she changes her rules
herself). The owner, 2026-10-27: "Yes totally, but only after all ADRs prior to ADR-106 are complete."

1. "Remove the timezone information from the database": which of it? Scenes' zones, plans' stored zones (348 rows),
   the config's top-level zone, or all? A plan stores its zone so that a configuration change does not move an
   appointment already made; what keeps that promise without it?
   *Real person:* an appointment she made is a moment, and it stays that moment wherever anyone is. A habit ("every
   morning at nine") follows her own clock. The test does not say whether plans of the first kind still need a
   stored zone once the moment itself is stored.
2. "Only use the local TZ": the local zone of the machine the worker runs on. What happens when the deployment moves
   (another host, a container whose zone is UTC by default)? Is the local zone then read from the host, or set once
   for the deployment?
   *Real person:* her clock is where she lives. Copying her to another machine does not move her house, so her zone
   would be set once for her, not read from whatever the host reports. This pulls against "only use the local TZ"
   and is the first thing to grill.
   *Xiaoman's position, 2026-10-27, which she brings to the talk:* when the deployment moves, her zone is set once for
   her, never read from the host.
3. "Softly tied with each person, in her note": does the program ever read that note to convert a time, or is it only
   for her to reason with (as she would remember that a friend lives in another country)? If only hers, a reminder
   she sets for that person is in which clock?
   *Real person:* the note is only for her. A reminder is in her own clock. If she wants to greet a friend at their
   morning, she works out the hour herself, or gets it wrong, as a person can.
4. "She seems confused with TZ with me": what did she confuse? Her clock with the owner's, or a group's with the
   owner's? The answer decides whether the problem is the data or the words she reads.
   *Real person:* no answer; this is a question of fact.
   *Xiaoman answered it herself, 2026-10-27,* from two plans she read in the database on 10-24: what she mixed up was
   neither her clock nor the owner's but **a group line's clock**. A reminder she wrote for that line as "20:00" was
   stored in the zone the line sets, so on her own clock it fired five hours later, after midnight; another, written as
   "21:30", fired on time by the line's clock, and on hers she read it as late. The gap is the zone the line carries,
   not her clock. She asks that it be recorded as a line of the program read against another clock face, not as her
   being careless with time; that day she made herself the rule to judge when a plan fires by `next_fire_at` alone.
   (Her exact words, with the zone and the local times, are kept outside the repository: zones are personal data.)
5. Groups whose members live in several zones: one clock for the group (the machine's), and each person's own zone
   only in her notes?
   *Real person:* a group has no clock. There is her clock, and what she happens to know about each person.
6. The time zone is personal data (AGENTS.md lists it with account ids and addresses); a person's zone in her note
   is in the database, not in tracked files. Does that hold for her notes as they are kept today?
   *Real person:* no answer; this is an engineering rule. Her own zone is personal data too: today's scan hits were
   this machine's zone written into her tracked skill files.
7. Migration: existing plans with stored zones, existing scene zones, and her existing notes that mention zones.
   *Real person:* no answer; this is a program problem.
8. What her clock shows. Today her clock block names the zone on every turn ("not a mechanical reminder every time").
   *Real person:* a watch shows the time, not the zone's name. Does she see a zone at all, and when: only when she
   asks, or when she is somewhere new?

## Constraints already known

- Stored records keep UTC; only what a model reads is converted.
- Core code and tracked files carry no real zone (AGENTS.md); examples use placeholders.
- The JS and Python sides may run different versions (RUNTIME_API).
- Platform-neutral: nothing assumes one social platform's notion of where a person is.

## Not in this ADR

Found while reading, wider than the ask, with data; the owner decides whether either enters:

1. **Clock texts the program cuts from a UTC string.** `discussion_digest.py` (`item["at"][11:16]`, the window stamps
   in `render()`), `tools_week.py` (the window as `since[:16]`, `until[:16]`), `reflection_map.py` (`r['until'][:16]` of
   a switch whose `until` is written with `isoformat()` of a UTC moment, `switches.py:99`) and `self_review.py` (the day
   of a note by UTC `%m-%d`) put a UTC hour or day into text beside faces on her clock. Read at the slicing lines; the
   digest's own `at` source is not traced. They are the same class as this ADR's invariant, but they do not depend on
   a room's zone, and this ADR does not change them.
2. **A wording-only plan update recomputes `next_fire_at` from now** (`schedule.py:861,892`). For an `after` or `every`
   plan the stored `next_fire_at`, which is what she reads and what she judges a plan by, then differs from the native
   scheduler's timing, which that update leaves alone.

Also not here: her usage-readout skill and other skill text of hers (hers to change); the history of earlier ADRs'
times; moving a plan made in another zone onto her clock at landing (decision 2); a Web settings card check on the
zone's value (a UI of our own; it needs the owner's approval first); ADR-103, ADR-107 and ADR-108 (107 and 108 build
after this one and touch the same context code, so they rebase on it).
