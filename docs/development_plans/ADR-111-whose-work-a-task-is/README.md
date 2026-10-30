# ADR-111: Whose work a task is

Status: **Proposed** 2026-10-30. Designed by the cloud lead (Claude Code, big sis) on branch
`claude/elegant-goodall-2ip12g`, from `main` at `ac620ad17d40`. Nothing is built. The owner's questions (below) are
open. One fresh reviewer read the design against the code; the findings and what was done with each are at the end.
The character has not read this page and was not contacted while it was written.

The design to the end: [design.md](design.md) (the survey with its commands, the interfaces, the lifecycle of every
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
  `ask` to the action brain) and `message_action` (a finished task continued). Each copies `scene_id`, `scope_key`,
  `requester_id` and `policy_epoch` from the turn that called it (from home's turn on an errand, ADR-066).
- **The grants come from the turn's kind and scene,** not from who asked: `grants.development_granted` gives the
  development grant to every `external`, `scheduled` and `self_development` turn in an owner-private conversation, to a
  trusted note's turn, and to a result turn whose task had it. On an agent line that is every turn. A task begun in a
  result turn keeps the grant, so the chain never loses it.
- **The person on an internal turn is a placeholder.** A visit enters a group as the first member of its route, sorted
  by id (`places.visitor`); a note enters as the route's person; a heartbeat and a self-development turn as the owner.
  A task begun there records that person as the one who asked: it runs in their folder, they may steer it, and the
  refusal for another member's task tells her that person asked for it (`OTHERS_TASK`). Nobody did. The other way
  round, her visit may steer and stop that member's own tasks. The plans list of a group turn is filtered by the
  turn's person, so plans made on a visit appear in that member's turns, and theirs on her visits.
- **Every follow-up stays where the first turn was.** A result turn runs in the task's conversation, a plan fires in
  the conversation it was made in, and anything begun in either stays there. A plan made on an errand fires in the
  destination group with the intent she wrote while holding home's authority.
- **44 functions in 13 modules read these fields of a task by name,** and a few more select tasks by them (the
  conversation's task list, the hand-back queue, publication's walk back to the first input; design.md §1.5). Most of
  them already read "the task's conversation and person" as "whose it is" (its folder, its class, its history and
  pictures, its list, where its result goes). They are right as soon as those fields are right.

## The invariant (proposed)

**A task is for the one whose authority its turn acts with: a person whose words asked, in the conversation they asked
in, or herself. The program records that answer once, when the turn is opened, from stored state only; every task and
plan the turn makes copies it, and everything about them is read from it. Her choice is needed only to say that work is
her own and belongs at home.**

This is smaller than "the conversation and the person it serves" as a free choice. The code already computes the
authority of a turn in four places (the speaker, `errands.home_turn`, ADR-088's `_as_place`, the session class); it
only never wrote down whose that authority was, and filled the gap with placeholder people. Making the answer a record
removes the placeholders and the per-kind guesses together. Letting her name any conversation as the one served was
considered and set aside: from home it hands a public group work begun with home's view, and from a group it would
reach home's grants (design.md §2.4).

## Decisions (proposed; the owner's are the questions below)

1. **One record, `whose`,** decided by one function, `whose.of_turn`, from stored state: `{by, scene_id, person_id}`
   with `by` one of `words` (a person's words asked), `standing` (a self-development turn: the owner's standing ask)
   and `own` (her own). It is stored on the episode when the turn is opened and copied, in the same write, into every
   task and plan the turn makes (design.md §2).
2. **Inherited along the chain, never across a less trusted step.** A result turn has its task's `whose`, a plan's
   firing the plan's, an errand turn home's (ADR-066). A turn opened by a note from outside has its origin's (ADR-088). A
   turn she opened herself (a heartbeat, a visit, the nightly settlement, her own trusted note) is `own` where it runs.
3. **A task's own fields are its `whose`.** `scene_id`, `scope_key`, `policy_epoch` and `requester_id` are those of
   `whose`, so every reader that already treats them as "whose" stays as it is. Only the readers that meant "the turn
   that handed it over" change: the consult check, the executor's input, the session the task is drawn in, the folder
   check in `delegate` (design.md §1.5).
4. **Grants follow `whose` only,** through one function, `grants.for_whose`, which replaces `development_granted` and
   the event's integration profile at every place a task's grants are decided (delegate, a continuation, the
   capabilities block of her turn). No turn kind and no scene decides them any more.
5. **Her own work in a public conversation has no task.** `own` in a group or someone else's chat has no folder of
   anyone's, so a visit (and a turn her own plan opens there) hands nothing to the action brain (question 1).
6. **She chooses only at home, and only one thing:** `delegate`'s `for` takes one value, `你自己的` (yours), which makes
   the task `own` at home: its folder and result are home's, and it carries no development or integration grant unless
   it is a self-development turn's. The field is shown only in owner-private conversations (question 4).
7. **A task shows no line of another conversation.** The input the action brain and her result turn are given is read
   within the task's own conversation; the executor's read gets the fence the hand-back and the consult already have.
8. **Plans live and fire where their `whose` is.** One rule replaces three: a plan made on an errand is home's, one made
   from an outside note is its origin's (as ADR-088 decided), one with `line` is hers in that line. The plans list shows
   a person's turns their plans and her own turns hers (question 5).
9. **Nothing is re-routed.** When the conversation of `whose` is gone, fenced or left, a result is suppressed and a plan
   suspended, each recorded; neither is ever handed to another conversation.
10. **What she reads says whose,** from one versioned table (`whose.WHOSE_VERSION`), in three places only: the
    `delegate` result, the result turn's text and a plan's firing. Nothing is added to every turn (design.md §4, §8).
11. **The crash gap is closed by reading the rows.** A turn resumed after a crash lists the tasks whose `episode_id` is
    the turn (`task_records.of_episode`), not the episode's own list, which the crash can leave short.
12. **Old records keep their meaning.** A task or plan without `whose` reads as `words` from its own conversation and
    person, which is what the code assumed when it was written. Nothing rewrites it (design.md §2.5).

## The owner's questions

Each is a trade-off or changes what she can do. My recommendation is first; the cost of the other is said.

1. **Her own work in a group (a visit, a plan she made on one).** *Recommended:* none: such a turn has no `delegate`,
   and what she wants done she takes home with a plan or a note. Cost of the alternative (a folder of hers in each
   conversation, made on first need and erased with it): a new kind of folder with its own life cycle and erasure, and
   a result turn in a group that nobody there asked for. Cost of the recommendation: about 16 visit tasks in ten days
   lose their path; a picture or a look-up for a visit is commissioned at home first.
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
4. **She may say "this is mine".** *Recommended:* yes, the one value `你自己的` at home. Cost of the alternative (no
   choice): work she does on an agent line for someone else stays recorded as the agent's, its result returns to that
   line and the line keeps filling. Cost of the recommendation: one field and a judgement each time; a wrong pick moves
   a result home that the agent waited for, said in the `delegate` result.
5. **A plan made on an errand fires at home.** *Recommended:* yes (the invariant). Cost of the alternative (today,
   ADR-066 row 1): it fires in the destination as that group's, with an intent written while she held home's
   authority, so home's words enter a public session. Cost of the recommendation: to say something there later she
   sends another errand.
6. **A paused task is continued by the one it serves.** *Recommended:* yes: after a restart, a task resumes on the words
   of its `whose` person in its conversation (the owner keeps his say at home). Today only the owner in the local chat
   can continue a paused task, and `task` finds only tasks of the turn's own conversation, so a paused agent-line task
   can never be continued. This is wider than the ask; it is listed because it is a reader of `requester_id`. Cost of
   the alternative: those tasks stay paused for good.
7. **The narrow agent grant follows the agent's plans and results.** *Recommended:* yes, since it falls out of the
   invariant (an agent's plan carries the agent's `whose`). Cost of the alternative (the 2026-10-11 rule: a plan carries
   only the owner's grant): an exception kept by hand in `schedule.py`. Cost of the recommendation: an agent's plan that
   fires can start or read its adapter (`integration_start`, `integration_status`), only with `develop`.

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

## The review (one fresh reader, against the code)

To be filled in with the reviewer's findings and what was done with each.

## Not in this ADR

- A group she has left or that was disbanded has no state (ADR-107 has no rule for it); results said there fail at
  the adapter and show as failed deliveries. Giving that state is its own ADR.
- A fair task queue across conversations (ADR-050's deferred item).
- The owner's view of a task's `whose` in the Web thread: a new UI field needs his approval; the records and audit
  carry it.
- The publication activation turn (`host._complete_activations`) stays a self-development turn at home: it reports her
  own published change, not the task's result, which went to its `whose` already.
- Tracing the owner's "random group" case on the live data. The design closes both suspects (visits, plans made on
  them) structurally; the trace, by structure only, is the first landing's check.
