# ADR-111: Whose work a task is

Status: **Proposed** 2026-10-30. Designed by the cloud lead (Claude Code, big sis) on branch
`claude/elegant-goodall-2ip12g`, from `main` at `ac620ad17d40`. Nothing is built. The owner's eight questions (below)
are open. One fresh reviewer read the first draft (`d7e7decd7126`) against the code, then re-checked its fixes
(`affd95133a06`); its 14 findings, the eight items of its re-check and what was done with each are at the end. The character has not read this page and was not contacted while it was written.

The design to the end: [design.md](design.md) (the survey with its commands, the interfaces, the life cycle of every
text and stored field, the failure modes, the tests and the landings).

## The ask (the lead's brief, 2026-10-30, verbatim in its essentials)

> The owner saw her dispatch work into the wrong conversations: client writing for a QQ group running as tasks on a
> coding agent's line (`agent:home:dm:claude-code`), and, more than once, tasks landing in an unrelated group.
>
> The broken invariant: the program has no notion of whose work a task is. A task belongs to the conversation of
> whatever turn happened to call delegate, and everything after that stays there.
>
> A task carries whose work it is: the conversation and the person it serves. Wherever the program can know that, the
> program decides it (the person whose words asked, the origin a plan keeps, an errand's home). Her choice, where one
> is needed, is categorical and mapped by the program. Grants, where the result turn happens, follow-up plans and what
> she sees of the task all follow that answer, not the turn that happened to start the task. Treat this as the lead's
> direction, not a settled answer: if the code shows a smaller or better invariant, argue for it.

The evidence is the lead's (task records since 10-20, counted by structure only), not re-derived here: on the agent
line 197 tasks were started by a message there, 82 by a result turn, 41 by her own plan firing and 8 by a note; in QQ
groups 137, 22, 16 and 16 by a visit; in the owner's chat 23, 33, 22, 11, plus 46 self-development turns, 17 heartbeat
turns and 3 errand visits. Agent-line tasks rose to 59 a day on 10-27 and 10-28. All 23 agent-line tasks from the
10-29 evening to the 10-30 afternoon carried the development grant, a long-form writing task for a group's client
among them.

In scope: whose work a task is and a plan is, and everything that follows from it (grants, folder, where the result
turn happens, who may steer it, what she reads). Anything wider is said as wider.

## What exists (counted on `ac620ad17d40`; commands and the full census in design.md §1)

- **Two code paths write a new task**, both in `coordinator.py`: `delegate` (its callers: the `delegate` tool and
  `ask` to the action brain), which copies `scene_id`, `scope_key`, `requester_id` and `policy_epoch` from the turn
  that called it (from home's turn on an errand, ADR-066), and `message_action` (a finished task continued), which
  copies them from the turn.
- **The grants come from the turn's kind and scene,** not from who asked: `grants.development_granted` gives the
  development grant to every `external`, `scheduled` and `self_development` turn in an owner-private conversation, to a
  trusted note's turn, and to a result turn whose task had it. On an agent line that is every turn. A task begun in a
  result turn keeps the grant, so the chain never loses it.
- **The person on an internal turn is a placeholder.** A visit enters a group as the first member of its route, sorted
  by id (`places.visitor`); a note enters as the route's person; a heartbeat and a self-development turn as the owner.
  A task begun there records that person as the one who asked: it runs in their folder, they may steer it, and the
  refusal for another member's task tells her that person asked for it (`OTHERS_TASK`). Nobody did. The other way
  round, her visit may steer and stop that member's own tasks. The plans list and the plan update and cancel fences
  go by the turn's person, so plans made on a visit appear in that member's turns and are theirs to change, and theirs
  on her visits.
- **The person on a group turn is the one who opened it.** A request from B that she answers in a turn A's line
  opened becomes A's task.
- **Every follow-up stays where the first turn was.** A result turn runs in the task's conversation, a plan fires in
  the conversation it was made in, and anything begun in either stays there. A plan made on an errand fires in the
  destination group with the intent she wrote while holding home's authority.
- **44 functions in 13 modules read these fields of a task by name,** and a few more select tasks by them (the
  conversation's task list, the hand-back queue, publication's walk back to the first input; design.md §1.5). Most of
  them already read "the task's conversation and person" as "whose it is" (its folder, its class, its history and
  pictures, its list, where its result goes). They are right as soon as those fields are right.

## The invariant (proposed)

**A task is for the one whose authority its turn acts with: a person whose words asked, in the conversation they asked
in, or herself; her own work is home's. The program records that answer once, when the turn is opened, from stored
state only; every task and plan the turn makes copies it, and everything about them is read from it. Inheritance never
crosses a less trusted step.**

This is smaller than "the conversation and the person it serves" as a free choice. The code already computes the
authority of a turn in four places (the speaker, `errands.home_turn`, ADR-088's `_as_place`, the session class); it
only never wrote down whose that authority was, and filled the gap with placeholder people. Making the answer a record
removes the placeholders and the per-kind guesses together. Letting her name any conversation as the one served was
considered and set aside: from home it hands a public group work begun with home's view, and from a group it would
reach home's grants (design.md §2.4).

## Decisions (proposed; the owner's are the questions below)

1. **One record, `whose`,** decided by one function, `whose.of_turn`, from stored state: `{by, scene_id, person_id}`
   with `by` one of `words` (a person's words asked), `standing` (a self-development turn: the owner's standing ask)
   and `own` (her own). Episodes and plans keep the whole record; a task keeps only `whose_by` (and `develop`), because
   its own conversation and requester fields are the rest (design.md §2.1).
2. **Inherited along the chain, never across a less trusted step.** A result turn has its task's `whose`, a plan's
   firing the plan's (honored only where the plan lives), an errand turn home's (ADR-066). A turn opened by a note from
   outside takes the writing turn's own place, never what that turn carried from elsewhere and never a home
   conversation; when that leaves nothing, the turn acts for no one and hands over and plans nothing (ADR-088). A turn she
   opened herself (a heartbeat, a visit, the nightly settlement, her own trusted note) is `own`.
3. **A task's own fields are its `whose`.** `scene_id`, `scope_key`, `policy_epoch` and `requester_id` are those of
   `whose`, so every reader that already treats them as "whose" stays as it is. Only the readers that meant "the turn
   that handed it over" change: the consult check and its persona, the executor's input, the session the task is drawn
   in, the folder check in `delegate`, the steering fence's person (design.md §1.5).
4. **Grants follow `whose` only,** through one function, `grants.for_whose`, which replaces `development_granted` and
   the event's integration profile at every place a task's grants are decided (delegate, a continuation, the
   capabilities block of her turn). No turn kind and no scene decides them any more. A continuation keeps its task's
   grants, never the turn's.
5. **Her own work is home's.** A task of hers whose `whose` names an owner-private conversation (a heartbeat, her
   trusted note on a line, a visit to a home group) runs in home's folder and reports at home, the way an errand's task does. Her own work
   in a public conversation has no task (question 1).
6. **She chooses only what the program cannot know, from a list it maps:** at home, that the work is her own
   (`for: 你自己的`, question 4); in a group, which person whose line is in the turn asked for it (`for`: their label,
   question 8).
7. **A task shows no line of another conversation.** Its input keeps its meaning; every read of it that reaches a model
   is fenced by the task's conversation (the executor's read gets the fence the hand-back and the consult have).
8. **Plans live and fire where their `whose` is.** One rule replaces three: a plan made on an errand is home's, one made
   from an outside note is its origin's (as ADR-088 decided), one with `line` is hers in that line. The plans list and
   the plan update and cancel fences go by the plan's `whose` person (question 5).
9. **Nothing is re-routed.** When the conversation of `whose` is gone, fenced or left, a result is suppressed and a
   plan's failure recorded as today; neither is ever handed to another conversation.
10. **What she reads says whose,** from one versioned table (`whose.WHOSE_VERSION`), in three places only: the
    `delegate` result, the result item of a result turn and the plan block of a plan's firing. The last two are added
    when the turn is prepared, never written into the stored event, so a redelivered or rebuilt event stays byte for
    byte what was stored (`ingress.py` refuses one that differs). Nothing is added to every turn (design.md §4, §8).
11. **Old records keep their meaning.** A task or plan without `whose` reads it from the turn that made it (episodes are
    kept), placed where the row lives, and nothing inherited from an old task gets more than it stored. Nothing
    rewrites a row (design.md §2.5).

## The owner's questions

Each is a trade-off or changes what she can do. My recommendation is first; the cost of the other is said.

1. **Her own work in a group (a visit, a plan she made on one).** *Recommended:* none: such a turn has no `delegate`,
   and what she wants done she takes home with a plan or a note. Cost of the alternative (a folder of hers in each
   conversation, made on first need and erased with it): a new kind of folder with its own life cycle and erasure, and
   a result turn in a group that nobody there asked for. Sending such a task home instead (the reviewer's suggestion)
   was set aside: the visit read what anyone there wrote, and its task would reach home's folder, sandbox and
   credentials. Cost of the recommendation: about 16 visit tasks in ten days lose their path; a picture or a look-up
   for a visit is commissioned at home first.
2. **The development grant needs her mark per task.** *Recommended:* yes: `delegate` takes `develop` (true when the
   work changes or runs her own machinery: code, skills, packages, adapters), and it gates both the development tools
   and integration; a self-development turn's tasks count as marked. Cost of the alternative (`whose` alone): every task
   the owner or an agent asks for gets both grants, the writing task above included. Cost of the recommendation: a
   forgotten mark fails loudly (`CAPABILITY_DENIED` says why) and costs one run.
3. **Who earns the development grant.** *Recommended (the lead's rule):* the owner's own words in his conversations, an
   agent's words on its own line, and her self-development turns. Cost of the alternative (today's): her sister on the
   peer line (ADR-050), any member of a home group (owner, 2026-10-18), and her own heartbeat plans and trusted notes at
   home (owner, 2026-10-12) keep reaching the development tools. Cost of the recommendation: those three lose it; her
   sister's ask becomes an idea she decides on in self-development (ADR-011 §6.2).
4. **At home she may say "this is mine".** *Recommended:* yes, the one value `你自己的`, shown only in owner-private
   conversations. Cost of the alternative (no choice): work she does on an agent line for someone else stays recorded
   as the agent's, its result returns to that line and the line keeps filling. Cost of the recommendation: one field
   and a judgement each time; a wrong pick moves home a result the agent waited for, which the `delegate` result says.
5. **A plan made on an errand fires at home.** *Recommended:* yes (the invariant). Cost of the alternative (today,
   ADR-066 row 1): it fires in the destination as that group's, with an intent written while she held home's
   authority, so home's words enter a public session. Cost of the recommendation: to say something there later she
   sends another errand.
6. **A paused task is continued by the one it serves.** *Recommended:* yes: after a restart, a task resumes on the words
   of its own person in its own conversation (its asker; for a task of hers at home, the owner, as today). Today only the owner in the local chat can continue a paused task, and
   `task` finds only tasks of the turn's own conversation and person, so a paused agent-line task can never be
   continued. This is wider than the ask; it is listed because it is a reader of `requester_id`. Cost of the
   alternative: those tasks stay paused for good.
7. **The narrow agent grant follows the agent's plans and results.** *Recommended:* yes, since it falls out of the
   invariant (an agent's plan carries the agent's `whose`). Cost of the alternative (the 2026-10-11 rule: a plan carries
   only the owner's grant): an exception kept by hand in `schedule.py`. Cost of the recommendation: an agent's plan that
   fires can start or read its adapter (`integration_start`, `integration_status`), only with `develop`.
8. **In a group she may say whose request a task answers.** *Recommended:* yes: `for` takes the label of another person
   whose line is in this turn (`people_from_program`); without it the task is the opener's. Cost of the alternative:
   B's request answered in A's turn stays A's (A's folder, A may steer it), said in the `delegate` result. Cost of the
   recommendation: a second form of `for` in groups (+109 characters in the tool list there) and a label to copy.

## Earlier decisions this keeps (design.md §1.6)

- ADR-011 §6.1: the development tools go with the owner's own delegations and her self-improvement turns and their
  results; never to anyone else's request (§6.2).
- ADR-066: a task begun on an errand is home's, drawn in home's session; the errand turn stays the record of the
  hand-over (`_why_then`, the waiting turn, the delegation depth).
- ADR-018: a note never grants anything; a result turn inherits from its task; a group's task reports to that group
  (ADR-017).
- ADR-088: a turn opened by a note from outside acts with its origin's authority, and so does everything it creates.
- ADR-075: the tier belongs to the task and its continuations.
- ADR-107: an admission ends as a mark on the grant; the folder, person and scene stay.
- ADR-108 D5: a program-woken turn shows no speaker; the authorizing person stays on the episode.

## The review (one fresh reader of `d7e7decd7126`, against the code)

The reviewer re-ran the survey's counts and got the same. Each finding was checked against the code before it was
taken; what was done is in the right column.

| # | Finding | Severity | Done |
|---|---|---|---|
| 1 | The errand row and the outside-note row combined: a note written home on an errand inherited home's authority back into home (escalation); an errand sent from an outside-note turn landed its task in the origin group | blocker | Inheritance stops at an outside note: its turn takes the writing turn's own place, computed without the errand row; an errand carries home's `whose` only when it lives at home, else `own` there (§2.2) |
| 2 | An empty `raw_input_refs` crashes `feedback`, `_short_event` and the recovery walk, and drops the task out of the task list's sort; the `delegate` result would say the action brain sees the asker's words | blocker | `raw_input_refs` keeps today's meaning and is never empty; every model-facing read of it is fenced instead; `BRIEF_ONLY` when the input is elsewhere (§3.3, §3.4) |
| 3 | The result and plan texts change between rebuilds and break `ingress.py`'s identity check | major | Found also by the lead's own check: the words are added at preparation into the result item and the plan block; the stored event is unchanged (§3.5, §3.6) |
| 4 | `own` on home lines kept the placeholder (the line's speaker as requester) and broke in home groups | major | Taken in the form the reviewer proposed for owner-private conversations: her own tasks are home's (§2.4). Not for visits to public groups (question 1) |
| 5 | Reading old records as `words` widened grants and kept the visit placeholder; L1 tasks without `develop` would lose their grant on continuation | major | Old rows read `whose` from the turn that made them, placed where the row lives; an old task's `develop` is its stored grant, and nothing inherits more than it stored (§2.5) |
| 6 | Plans recorded at L1 but still living in a group would hand home's authority to that group's turn | major | L1 writes no `plans.whose` (audit only); a plan's `whose` is honored only in the conversation it lives in (§2.2, §7) |
| 7 | Plan update and cancel are fenced by the turn's person, so the placeholder still steers plans; `there` and moved plans ignore the plan's `whose` | major | Fences by the plan's `whose` person; `there` from the plan; a plan made again after it fired copies the old `whose` (§3.6) |
| 8 | The plans-list query names an undeclared field and a None fence finds nothing | major | Catalog entries for `whose` and `whose.person_id`; the view written with `Exists` and `IsNull`; its unit test beside the store contract (§3.6, §6) |
| 9 | "Suspended once" does not hold (`_deliver_locked` puts a repeating plan back to ACTIVE) and is not needed | major | Dropped; a failing plan records its outcome as today and is never moved (§9) |
| 10 | The `external` row records who opened the turn, not who asked | major | Said as the opener; question 8 lets her name another person in the turn |
| 11 | The crash gap is already closed (`_run_turn` merges `of_episode` on resume) | minor | Decision and section dropped; the failure row cites the existing merge |
| 12 | Consult took the hand-over turn's persona and context | minor | From the task's session row (§3.4) |
| 13 | Tasks would store a second copy of their own fields; `STANDING` stored; `chosen` only for the audit | minor | Tasks store `whose_by` and `develop`; standing read at preparation; `chosen` in the audit (§2.1) |
| 14 | Wording and counts: `message_action` copies from the turn; development reports are on home lines, not only home; question 6's "the owner's words" cannot reach an agent-line task; the integration check undefined; `DEVELOP_NOT_HERE` had no text; the result's count left out the label; `ep['errand']` is set after `prepare`; no row for a gone note | minor | All corrected in the README and design.md (§1.2, §2.2, §3.1, §3.4, §5, §8) |

Five more the lead found while folding these in, each fixed in design.md: in a self-development turn, `你自己的` keeps
the self-development answer (the work is already hers at home); a continuation's check compares only "the turn reaches
the task's grants", since a continuation no longer takes the turn's; "her own work is home's" is decided by the class
of the conversation `whose` names, not the turn's (an errand runs in a group's session with home's `whose`); a paused
task is continued by its own person, which for her own home tasks is the owner, as today; and every task written
before L2 (L1's included) reads a missing `develop` as its stored development grant.

**The re-check of `affd95133a06`.** Findings 2, 3, 6 and 9 were fixed as written. Its remaining items, each checked
against the code and fixed in design.md:

| | Item | Done |
|---|---|---|
| A | An outside note sent on into a home group (home groups are not among the conversations an onward note is kept from, `visibility.owner_private_scenes`) fell back to `own` at home | The outside row never names a home conversation; with nothing left, the turn has no `whose` and hands over and plans nothing (§2.2) |
| B | An errand turn could not change the home plan it made (`Schedule.update` fences the turn's scene); her own group plans (person none) could not be found by the fences | `there` comes from the plan whenever the plan's scene is not the turn's; a none person is matched with `IsNull` (§3.6) |
| C | `own` on a line still had the line's speaker as its person, so her note's turn could steer the speaker's tasks and the speaker could change her line plans | `own` has a person only in the local chat (§2.1, §3.7) |
| D | A task L1 recorded for a visit or a line kept the placeholder in its result turn | The result row gives no person to `own` outside the local chat (§2.2) |
| E | An old row whose turn was erased has none of the inputs `of_turn` needs | A missing or erased turn answers `own` there, earning nothing (§2.2) |
| F | `IsNull` matches only a stored null; rhythm plans have no `whose` | `whose.person_id` always written; `whose` declared nullable (§3.6) |
| G | A task she names for B kept A's line as its input | Its input is B's newest line in the turn (§3.3) |
| H | "Recomputed at each preparation" was wrong: a turn is prepared once and a resumed turn reuses its stored context | Said as computed once, kept in the episode's context (§3.5, §4.1) |

## Not in this ADR

- A group she has left or that was disbanded has no state (ADR-107 has no rule for it); results said there fail at
  the adapter and show as failed deliveries. Giving that state is its own ADR.
- A fair task queue across conversations (ADR-050's deferred item).
- The owner's view of a task's `whose` in the Web thread: a new UI field needs his approval; the records and audit
  carry it.
- The publication activation turn (`host._complete_activations`) stays a self-development turn at home: it reports her
  own published change, not the task's result, which went to its `whose` already.
- A repeating plan that keeps failing to fire records its outcome at every occurrence, as today.
- Tracing the owner's "random group" case on the live data. The design closes both suspects (visits, plans made on
  them) structurally; the trace, by structure only, is the first landing's check.
