# ADR-111: Whose work a task is

Status: **Built, not installed.** Decided 2026-10-30 by the owner (his rule and his answers, below); designed and built
by the lead (Claude Code, big sis) on branch `claude/elegant-goodall-2ip12g`: L1 installs at `e0f818e`, L2 at the
branch head, both on main as of `f2103a24` (design.md §8, with what the landing still has to check), after a fresh
review of the build (§10.5). **Owner's rule for this ADR: the character does not
read it until the feature is fully built**; she was not contacted while it was written or built.

The design to the end: [design.md](design.md): the survey with its commands, the record and how it is decided, the
interfaces, the life cycle of every text and stored field, the failure modes, the defects found, the tests and the
landings.

## The ask

The lead's brief (2026-10-30, its essentials verbatim):

> The owner saw her dispatch work into the wrong conversations: client writing for a QQ group running as tasks on a
> coding agent's line (`agent:home:dm:claude-code`), and, more than once, tasks landing in an unrelated group.
>
> The broken invariant: the program has no notion of whose work a task is. A task belongs to the conversation of
> whatever turn happened to call delegate, and everything after that stays there.
>
> A task carries whose work it is: the conversation and the person it serves. Wherever the program can know that, the
> program decides it (the person whose words asked, the origin a plan keeps, an errand's home). Her choice, where one
> is needed, is categorical and mapped by the program. Grants, where the result turn happens, follow-up plans and what
> she sees of the task all follow that answer, not the turn that happened to start the task.
>
> Grants follow the work: a development grant only for development work the owner, or an agent on its line, asked for
> there.

The owner (2026-10-30, verbatim):

> My rule: She won't read it until the feature is fully built.
>
> MY only intention is to make the home line the default place to handle requests from outside. That it.
>
> You may put the defect you find in the ADR, but you shall NEVER prompt for changes outside our agreed range and trick
> me allowing you to expand the scope.

The evidence is the lead's (task records since 10-20, counted by structure only), not re-derived here: on the agent
line 197 tasks were started by a message there, 82 by a result turn, 41 by her own plan firing and 8 by a note; in QQ
groups 137, 22, 16 and 16 by a visit; in the owner's chat 23, 33, 22, 11, plus 46 self-development turns, 17 heartbeat
turns and 3 errand visits. All 23 agent-line tasks from the 10-29 evening to the 10-30 afternoon carried the
development grant, a long-form writing task for a group's client among them.

**In scope:** whose work a task is, recorded once and followed by its grants, its result turn, its follow-up plans
and what she reads; requests from outside default to the home line. Everything else works as it does today.

## The owner's answers (2026-10-30, in the question tool)

1. Work someone asks for in a group runs in that group, for that member (as today).
2. The home line is the Web chat. (My question also moved what he asks in his own platform DM to the Web chat; that came
   from my over-reading of his rule and is withdrawn: his DM works as today.)
3. Only the owner, a coding agent on its own line, and her self-development turns get the development tools; no one
   else (the brief's rule).
4. Visits keep today's behaviour.
5. In a group, when several people's lines are in her turn, she names whose request a task answers; without it, the
   opener's.

## What exists (counted on `ac620ad17d40`; design.md §1)

- **Two code paths write a new task** (`Coordinator.delegate`, `Coordinator.message_action`); both copy the
  conversation, scope, epoch and person from the turn that called them (home's on an errand, ADR-066).
- **The development grant comes from the turn's kind and scene,** not from who asked: every `external`, `scheduled`
  and `self_development` turn in an owner-private conversation, a trusted note's turn, and a result turn whose task had
  it. On an agent line that is every turn, and a task begun in a result turn keeps the grant.
- **Her notes from outside already come home only to the Web chat or the owner's own DMs, never to an agent line**
  (`notes.targets`). Work for someone outside reaches an agent line only when she starts it in a turn of her own there:
  a result turn, a plan's firing, or the agent's message. Nothing records that the work is someone outside's, so it
  is filed as the line's, gets the line's development grant, and every result and plan after it stays on the line.
- **The person on a group turn is the one who opened it:** a request from B she answers in a turn A's line opened
  becomes A's task.

## The invariant

**A task records whose work it is: who asked, and where. The program decides that from stored state wherever it can,
and every result, plan and task that follows carries the same answer. Work runs where it was asked, as today; work for
someone outside that she takes on in one of her home conversations runs on the home line, the Web chat. The development
grant follows the record: only for what the owner, an agent on its own line, or her self-development asked for.**

## Decisions

1. **One record, `whose`** (`{by: words | standing | own | outside, scene_id, person_id}`), decided by one function
   from stored state when a turn opens, kept on the episode and copied into every task and plan the turn makes
   (design.md §2).
2. **Carried along the chain:** a result turn has its task's `whose`, a plan's firing the plan's, an errand turn home's
   (ADR-066). A turn opened by a note from outside takes the writing turn's own place, never a home conversation's
   (ADR-088).
3. **Requests from outside default to the home line.** In a home conversation, `delegate`'s `for` takes the place of
   the outside conversation the work is for (from her note places); the task then runs and reports on the Web chat,
   and whatever follows it stays there. That is the one change to where work runs.
4. **In a group, `for` takes the label of a person in her turn** (the owner's answer 5); the task is theirs, in that
   group, as today, with their line in the turn as its input. A home group takes either form, so the owner's request
   in a turn someone else opened there is his. On an errand there is no `for`: its task is home's, as today.
5. **The development grant follows `whose`:** the owner's own words in his conversations, an agent's words on its own
   line, her self-development. Not her sister's line, not a home group's other members, not her own heartbeat plans
   and notes (the owner's answer 3), and never work for someone outside. A task's result turn and its continuations
   earn no more than the task stored. Integration and every other grant stay as today; work for someone outside gets
   no integration grant.
6. **What she reads says whose,** from one versioned table, in three places only: the `delegate` result, the result
   item of a result turn and the plan block of a plan's firing; the last two are added when the turn is prepared, never
   into the stored event. Nothing is added to every turn.
7. **A task never shows a line of another conversation:** a task that runs on the Web chat for work begun on a line
   reads its input within the Web chat, so the action brain sees her brief, not the line's words as someone's request.
8. **Old records keep their meaning;** nothing rewrites a row (design.md §2.6).

The brief's "development work" is met by who asked, not by what the work is: telling development from other work an
earner asks for would need a mark from her on every task, which is outside the agreed range. The case that was seen
(an outside client's writing with the development grant) is closed by decisions 3 and 5.

## Defects found, not in this ADR

Found in the survey and the reviews; each with its evidence in design.md §6. None is designed here.

1. A visit's task runs in the folder of the route's first member by id (`places.visitor`), that member may steer it,
   and `OTHERS_TASK` tells her they asked; her visit may steer that member's own tasks; plans made on a visit are
   listed in that member's turns and changeable by them.
2. A task paused by a restart on an agent line can never be continued (only the owner in the Web chat may continue a
   paused task, and `task` finds only the turn's own conversation's tasks).
3. A plan made on an errand fires in the destination with an intent she wrote while holding home's authority.
4. A repeating plan whose conversation is gone records a failure at every occurrence.
5. `TaskService.feedback` fails on a result whose conversation no longer exists (it reads the missing scene's epoch).
6. A group she has left or that was disbanded has no state (ADR-107 has no rule for it).
7. A visit can enter a group as a member who has left (`places.visitor` skips only blocked senders).

## The review

A fresh reviewer read the first draft against the code (14 findings, 2 blockers), re-checked the fixes (8 more) and
read a later, wider version (8 more). Everything in those reviews that bears on what stays in this ADR is fixed in
it; the rest reviewed parts that are no longer here. The same reviewer read this version (4 findings, 2 major, all
fixed, and one more defect listed). A fresh reviewer then read the build (9 findings, no blocker, all fixed; the
tests now drive every path they guard, and reverting any one of 15 fixes fails one). design.md §10 lists them all.
