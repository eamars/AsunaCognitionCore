# ADR-106: Time zones with people, not with groups

Status: requirements recorded 2026-10-27; designed to final 2026-10-29 with the owner's three decisions below (the
question tool, his recommended options each time). Not built. Built on `claude/eloquent-shannon-fcxodi`; the local
Claude Code lands it and brings it to Xiaoman.

The ask, in one line: **she lives on one clock in every conversation, and no zone is hard-coded per group**. Anything
wider (her usage-readout skill, other ADRs' times) is not in this ADR.

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
| the deployment's zone | top-level setting `timezone` (the Web settings card's "Time zone"; no check on the value) | `scene_timezone` (4th), `persona_model.timezone` (2nd) |
| her rhythm's zone | policy key `rhythm.timezone` (a "private" key: a package may not default it; she can still write it with `set_policy`) | `persona_model.timezone`: rhythm block, nightly settlement, night stage, visit counts, heartbeat pause, her home tasks' `ASUNA_TIMEZONE` |
| a plan's zone | `plans.timezone` and `plans.tz_source` (written at create and update); a daily or weekly plan's zone is also held by DSH's own scheduler (`time_zone`) | `scene_timezone` (1st) |

### The order a conversation's clock is resolved in

`schedule_rules.scene_timezone`: the plan's stored zone, the route's, the scene's, the deployment's, then UTC; a name
the machine cannot load falls to the route's fixed offset, then to the host's clock as a fixed offset (no daylight-saving
rules). Counted by `grep` on `cc8c00627132`: 47 call sites in 20 modules ask `scene_timezone` or `local_time.zone_of`
(`context.py` 11, `schedule.py` 6, `role_tools.py` 5); `persona_model.timezone` (her rhythm's resolver, a second one) is
imported at 15 sites in 8 modules; 24 modules in all. Five helpers resolve a zone again on their own:
`Scheduler.zone_of`, `Coordinator._zone`, `carried._zone`, `restarts._zone` and `self_review._zone`.

### The root cause

The program treats the clock as a property of the room. Her `place_timezone` tool says so to her ("设了以后，那边几点、
你在那个群定的计划，都按那个群的钟"): one field, `scenes.timezone`, is at once "where those people are" (what she knows
about them) and "which clock every time in that room is drawn on and every plan made there fires by". The same text
("20:00") then names different moments in different rooms. The broken invariant: **one time text must name one moment for
her, in every room.** A rule that fixes the group zone case and leaves the class (a time drawn on a clock that is not
hers) would be a bandage; the class has these instances, found in this reading:

1. A reminder written "20:00" in a room whose zone is not hers fires at another hour on her clock (Xiaoman's own
   account, question 4 below).
2. A plan written with an explicit offset (`20:00+09:00`) is worded on the **UTC** face (`schedule_rules.describe`
   passes `timezone.utc` for an `at_utc` rule), while its `next_fire_at` in the same row is on the room's face. Measured
   2026-10-29 on the module with a demo zone: description `10/30 11:00`, the same moment on the zone's face `10/31 00:00`.
3. The plans of other rooms she sees at home (`your_plans_there`) are worded on each room's own face and sit beside
   home's `next_fire_at`.
4. Changing a plan's timing keeps its old zone (`Scheduler.update` reads the plan's stored zone first), so an edit she
   writes on her clock is read on the room's.
5. Her usage-readout skill's own record: a task wrote an offset it never read, because no program source gave her one.
   The fix is on the program's side (one clock, converted by the program), not another rule for her to follow.

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

Consequences of his words and of those three, not asked again (they are the "remove the hard coded TZ from the group"
and "not a mechanical placeholder"): her `place_timezone` tool is removed, and with it the `their_clock` line of her
places view and `scenes.timezone`. Whatever she knows about where a group's people are lives in her notes, which the
program never reads. Nothing in the program converts a time for anyone else.

## Design

### 1. One resolver, `schedule_rules.her_zone(config)`

Returns `{'name', 'tz', 'source'}` with `source` one of `setting`, `machine`, `unset`:

1. `config['timezone']` when the zone database can load it → `setting`.
2. Else the machine's zone, from the environment variable `ASUNA_HOST_TIMEZONE` (set by the Host, §7), else `TZ`, each
   only when it loads → `machine`.
3. Else UTC → `unset`.

Pure and cheap (no I/O, no store): `ZoneInfo` caches. It replaces `scene_timezone`, `local_time.zone_of`,
`persona_model.timezone` and their fixed-offset and host-local fallbacks (`_zone`, `zone_unavailable`, `tz_source`,
`utc_offset_minutes`). The `tzdata` package is a pinned dependency, so a name that is valid always loads. Every call
site that took a scene for its zone takes none (the 47 sites above; the arguments go with the function, not left as
dead parameters). The five helpers above become `her_zone` calls or go. `schedule_rules.plan_zone(plan, her)` is the one
other resolver: the plan's stored zone when it loads, else hers. `local_time.for_model`, `stamp`, `face` and `line_stamp` keep their shape; only the zone they are given changes.

### 2. Her clock block

`schedule_rules.local_clock` returns `{'now_local', 'weekday'}`. `timezone` and `tz_note` go; so do the rhythm block's
`timezone` and `note` (its `local_time` already drops when it equals `now_local`, and now always does), the plan tool's
echo of `timezone`, and the zone in the plan tool's refusal ("现在是 …（周几）"). `block_guide.py` says the `_at` fields
are on the clock of `clock_from_program`.

### 3. Plans

- **Create.** `zone = her_zone`; `next_fire` computes the moment as today; an `at` written without an offset is then
  stored as that moment (`{'at': <ISO moment with offset>, 'at_utc': True}`, the form an `at` with an offset already
  takes), so an appointment no longer needs a zone. `after`, `every` need none. `clock` (daily, weekly) is a habit and
  follows her clock: the plan stores her zone's name (`plans.timezone`), and DSH is given the same name
  (`native_recurring`, as today). `tz_source` is no longer written. The retry check ("same plan, same content") compares
  the stored rule with the moment-pinned rule, which is deterministic for one zone.
- **Update.** With a timing in the call, the zone is hers, `plans.timezone` becomes hers, and the result carries one
  line when the plan's zone was another ("这条原来按另一个钟面排，现在按你的钟"). With a wording change alone, the
  plan keeps its zone and its timing, as it does today.
- **Re-arm and dispatch** (`_rearm`, the native-recurring branch, the legacy migration) use `plan_zone`: a plan fires by
  the zone it was made in. `ensure_settlement` and the night stage use `her_zone`; settlement still needs a zone that is
  known (`source != 'unset'`) and an `Area/Location` name for DSH's daily rule.
- **What she reads.** `schedule_rules.project(plan, her, moment)`: a `clock` rule and a legacy wall-time `at` are
  worded on the plan's zone; an `at_utc` rule, `next_fire_at` and everything else on hers (this fixes instance 2). When
  the plan's zone and hers read different hours at the plan's next fire, the row gains `clock_note`: "这条的钟点写在另一个钟面上，
  比你的钟快（慢）N 小时；到点以 next_fire_at 为准" (hours, and minutes when there are any, as `places.clock_gap` words a
  gap today; that function goes with the group zone and its wording moves here). No note when
  they read alike, and none for a plan with no next fire. A plan zone the database cannot load keeps today's
  `timezone_note` wording, without the name (the plan is read on her clock).
- `your_plans_there` (other rooms' plans, at home) is projected the same way.

### 4. The group's zone leaves

Removed: the `place_timezone` tool (spec, `tool_place_timezone`, the name lists in `role_tools.py`, `reasons.py`, the
Host's labels, icon and key map in `client.js`); `places.group_zone`, `their_time`, `clock_gap`, `set_zone`, `zones`
and the `their_clock` row; `records/scenes.py:set_timezone`. The scene row's `timezone` is cleared by §8 and nothing
reads it. The route keys (`schedule.timezone`, `timezone`, `schedule.utc_offset_minutes`) are no longer read; the
deployment reading (`Before building`) says whether any route sets them.

### 5. Her rhythm key

`rhythm.timezone` leaves `PRIVATE_KEYS`, the core defaults and the schema's reserved names (a package that names it now
fails the schema's `additionalProperties`, as any unknown key). `set_policy` no longer offers it. A value already in the
policy ledger stays there: the ledger is append-only history, and nothing reads the key. Her rhythm (block, settlement,
night stage, visits, heartbeat pause, `ASUNA_TIMEZONE` for home tasks) uses `her_zone`.

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
`tools/clear_scene_zones.py` calls it: dry run by default, `--apply` to write, prints the count only. It is a detour:
the lead runs it once after the new code is installed and verified, and the next commit deletes both (the tool and the
function). Order is safe either way: once the new code runs nothing reads the stored value, and if the removal ran
first the old code would fall to the deployment's zone, which is the new behaviour. `plans.tz_source`
and `plans.timezone` on existing plans stay (the plan's own zone, §3); the policy ledger stays (§5).

### 9. Start evidence

One line per worker start in `reports/native-host-*`, no zone name: `clock.zone {source, setting_set, setting_loads}`.
Two states are failures the owner would want to see: the setting is set but cannot load (a typo, now silent to her),
and nothing is known (`unset`, she lives on UTC). It is the only place they show; nothing is added to a turn.

### 10. References changed in the same commits

`RUNTIME_API.md` (the `timezone` row and what it governs, the private-keys row, the clock block, the plan tool's result
and `clock_note`, the tool list), `RUN_ASUNA.md` (the `timezone` sentence), `docs/map/` (regenerated by
`tools/project_map.py`; hand-written answers that name the removed tool), `deploy/docker/README.md` only if its `TZ` row
no longer says what holds, the `asuna-database` skill's `scenes` line, the module docstrings of `local_time.py` and
`schedule_rules.py`. Current references show the present state, no history.

## Failure modes

No design here adds I/O, a wait or a queue; the resolver is a pure function of the settings and two environment
variables. For a slow, failing or hung item: nothing waits.

| State | What happens | Who sees it |
|---|---|---|
| setting set to a name that cannot load | machine's zone, else UTC | the start evidence line (`setting_loads: false`); she is not told |
| setting unset, Host reports a zone | she lives on the machine's zone | evidence `source: machine` |
| setting unset, no Host zone, no `TZ` | UTC | evidence `source: unset`; settlement is retired as today |
| a plan's stored zone cannot load | the plan is read and fires on her clock; its row says the zone is unreadable | her plans block |
| the deployment's zone is changed later | new plans use it; old plans keep theirs and say so when they differ; DSH's daily plans keep theirs | her plans block |
| the one-off removal is not run, or stopped halfway | nothing reads the stored value; run again | the tool's count |
| the new code is rolled back after the removal | the old code falls to the deployment's zone, which is the new behaviour | none |
| an older worker with a newer Host, or the reverse | the variable is ignored, or absent (§7) | none |

What changes once on the real system: the times she reads in the rooms that had a zone of their own now read on her
clock; lines the program wrote into those rooms earlier keep the old room's face for the months they stay (no history
conversion). One line to her at landing says so.

## Tests that earn their place

Unit, on the in-memory store, fast:

1. **One face** (`tests/test_her_clock.py`): the same moment gives the same `clock_from_program`, line stamp and plan
   row in two scenes when one carries a stale `timezone` and its route carries the old keys. Guards the silent
   leftover: data the removal missed must be inert.
2. **The resolver's four states** (the same file): setting; unset with `ASUNA_HOST_TIMEZONE`; unset with `TZ`; nothing →
   UTC; a setting that cannot load falls through. Guards "a typo makes her live on UTC without a sign".
3. **A plan row reads on one face** (`tests/test_plan_view.py`): description and `next_fire_at` agree for a wall-time
   rule, a moment-pinned rule and a `clock` rule; `clock_note` appears exactly when the plan's zone reads another hour at
   the next fire, with the right sign and span, and not otherwise. Guards instance 2 and the "other clock" confusion.
4. **Create pins an appointment, update moves a plan onto her clock** (`tests/test_schedule_rules.py` and the
   scheduler's own tests where they exist): an `at` without an offset is stored as a moment that does not change when
   the setting changes; a timing update rewrites the plan's zone and a wording update does not.
5. **The removal** (`tests/test_her_clock.py`, the `store` fixture on the memory adapter): `clear_timezones` clears only that field,
   returns the count, is idempotent, and leaves other scene fields as they were. It is a path that removes records, which
   AGENTS.md ranks first.
6. **The tool is gone** (`tests/test_tool_budget.py`, `tests/test_adr011_turns.py` updated): she is not offered
   `place_timezone`; the refusal that lists writable policy keys no longer names `rhythm.timezone`.
7. **The schema** (existing persona-model tests): a package that sets `rhythm.timezone` is refused.

Not tested, on purpose: the wording of `clock_note` beyond its sign and span; the Host's one-line environment variable
(its absence is covered by test 2, and the landing's check by content reads the evidence line on the real system).

The static checks and repository guards run unchanged: `test_store_boundary` (the owner module is the only code that
touches `scenes`), `test_one_clock`, `test_project_map`, `test_no_undefined_names`, `test_line_endings`.

## Landing and restart

One landing by the local Claude Code, after Xiaoman has read the page (step 4 of the discipline):

1. The `Before building` readings, in counts, on the real deployment.
2. Tests, the push gate, fast-forward to main.
3. The planned restart while she is quiet; tell her first; the running code is the commit's (`loaded.commit`).
4. Verify by content on the real system: a turn's `clock_from_program` has two keys; her plans block reads on one face;
   `place_timezone` is not in her tool list; the start evidence line names the source.
5. `python tools/clear_scene_zones.py` (dry run), then `--apply`; the count before and after, nothing else printed.
6. One message to her: what changed for her (below), and that earlier lines in the rooms that had a zone keep that face.
7. The next commit deletes the one-off tool and the function (§8).

## Before building: the readings the local Claude Code takes (counts, no zone names)

Zones are personal data: each answer is a count or one of *same / different / absent*, never the name.

1. Is the top-level `timezone` setting set, and does it load?
2. Is `rhythm.timezone` in her policy? Same as the setting, different, or absent? **If different, the owner chooses
   which one is hers and sets the setting to it before landing**: her rhythm moves to the setting at landing.
3. The Host's zone, a worker process's, a sandbox process's, and the setting: same or different? (Her own readout skill
   records one task that read the machine's clock at an offset that was not the log's; if the three differ, "the
   machine's zone" is ambiguous and the setting must be set.)
4. Scenes that carry `timezone`: how many; how many read another hour than the setting now, and in six months.
5. Routes that carry `schedule.timezone`, `timezone` or `schedule.utc_offset_minutes`: how many.
6. Plans in `CREATING`, `ACTIVE` or `SUSPENDED` that carry `timezone`: how many; how many read another hour than the
   setting at their next fire; how many of those are `clock` plans held by DSH.

The answers decide whether `clock_note` ever shows (6 = 0 means it will not at landing; it stays for the day the setting
changes), and whether the landing message to her has a rooms sentence (4 = 0 means it does not).

## What this changes for her (for her one reading)

- Every time she reads, in any room and at home, is on her one clock, with no zone name beside it.
- `place_timezone` and the "their clock" line of her places view are gone; what she knows about a group's people she
  keeps in her notes, if she wants it.
- A plan she writes is on her clock; a one-time plan is a moment; a plan from before may say it is on another clock.
- Her policy no longer has `rhythm.timezone`.
- Her usage-readout skill's text about offsets is hers; this ADR does not touch it.

## What the "real person" test answered (the questions of 2026-10-27)

| # | Question | Outcome |
|---|---|---|
| 1 | Which zone information leaves the database | the scenes' zones, her `rhythm.timezone` value's reader, the route keys' reader; the plans' zones stay as the plan's own (decision 2); the deployment setting stays as the one source (decision 1). An appointment is a moment; a habit follows her clock |
| 2 | "Only the local TZ" when the deployment moves | the setting is set once for her; the machine's zone only when it is not set (decision 1; Xiaoman's position holds when the setting is set) |
| 3 | Does the program read her note about a person | never; a reminder is on her clock (§6) |
| 4 | What she confused | a group line's clock (her own account); fixed at the class (the root cause above), not by a rule for her |
| 5 | A group with members in several zones | a group has no clock; there is hers and what she knows of each person |
| 6 | The zone is personal data | the setting and any note are in the settings and the database, never in tracked files; start evidence carries no name; her own skill text with the machine's offset is hers to change |
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

Her usage-readout skill and other skill text of hers (hers to change); the history of earlier ADRs' times; moving a plan
the owner or she made in another zone onto her clock at landing (decision 2); a Web settings card check on the zone's
value (a UI of our own; it needs the owner's approval first); ADR-103, ADR-107 and ADR-108 (107 and 108 build after this
one and touch the same context code, so they rebase on it).
