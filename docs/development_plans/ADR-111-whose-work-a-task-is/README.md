# ADR-111: Whose work a task is

Status: **Decided** 2026-10-30. The owner gave the rule and answered five questions the same day (below); the lead
(Claude Code, big sis) revised the design to them on branch `claude/elegant-goodall-2ip12g`, from `main` at
`ac620ad17d40`. Nothing is built. A fresh reviewer read the first draft against the code and re-checked its fixes; the
revision to the owner's rule was read again by the same reviewer (the review, at the end). **Owner's rule for this ADR:
the character does not read it until the feature is fully built**; she was not contacted while it was written.

The design to the end: [design.md](design.md) (the survey with its commands, the interfaces, the life cycle of every
text and stored field, the failure modes, the tests and the landings).

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
> is needed, is categorical and mapped by the program.

The owner, on the first version of this page (2026-10-30, verbatim):

> My rule: She won't read it until the feature is fully built.
>
> I think the issue is, no one treats the home line as the ONLY place that is supposed to handle external requests.
>
> Yes the agent line can handle request and it should have the development permission, but this line is NEVER
> intended to handle other misc tasks.
>
> So my bottomline is, any misc request goes to home line, and not randomly picking any line that has development
> permission.

The evidence is the lead's (task records since 10-20, counted by structure only), not re-derived here: on the agent
line 197 tasks were started by a message there, 82 by a result turn, 41 by her own plan firing and 8 by a note; in QQ
groups 137, 22, 16 and 16 by a visit; in the owner's chat 23, 33, 22, 11, plus 46 self-development turns, 17 heartbeat
turns and 3 errand visits. Agent-line tasks rose to 59 a day on 10-27 and 10-28. All 23 agent-line tasks from the
10-29 evening to the 10-30 afternoon carried the development grant, a long-form writing task for a group's client
among them.

In scope: where a task and a plan run, for whom, with which grants, and everything that follows (folder, result turn,
steering, what she reads). Anything wider is said as wider.

## The owner's decisions (2026-10-30, in the question tool)

1. **Work someone asks for in a group runs in that group,** for that member: their folder, the group's limits, the
   result where they asked.
2. **The home line is only the Web chat.** Even misc work the owner asks in his own platform DM runs and reports in the
   Web chat.
3. **No one else gets the development tools:** only the owner, a coding agent on its own line, and her own
   self-development turns. Her sister's line, the other members of a home group, and her heartbeat plans and notes lose
   them; what they ask is misc and goes to the home line.
4. **Visits keep today's behaviour** ("I'd prefer the current behavior if not conflict with my previous
   requirements"): a task she starts on her own visit runs in the group she visits.
5. **In a group she names whose request a task answers** when several people's lines are in her turn; without it the
   task is the opener's.

## What exists (counted on `ac620ad17d40`; commands and the full census in design.md §1)

- **Two code paths write a new task**, both in `coordinator.py`: `delegate` (its callers: the `delegate` tool and
  `ask` to the action brain), which copies `scene_id`, `scope_key`, `requester_id` and `policy_epoch` from the turn
  that called it (from home's turn on an errand, ADR-066), and `message_action` (a finished task continued), which
  copies them from the turn.
- **The grants come from the turn's kind and scene,** not from who asked or what the work is: `development_granted`
  gives the development grant to every `external`, `scheduled` and `self_development` turn in an owner-private
  conversation, to a trusted note's turn, and to a result turn whose task had it. On an agent line that is every turn,
  and a task begun in a result turn keeps the grant, so a line with the grant draws every kind of work.
- **No line is the place for misc work.** A task runs wherever the turn that started it happened to be: a result turn
  runs in its task's conversation, a plan fires where it was made, and anything begun in either stays there.
- **The person on an internal turn is a placeholder.** A visit enters a group as the first member of its route, sorted
  by id (`places.visitor`). A task begun there runs in that member's folder, they may steer it, and the refusal for
  another member's task tells her they asked for it (`OTHERS_TASK`); her visit may steer and stop that member's own
  tasks; the plans list and the plan update and cancel fences go by that person too.
- **The person on a group turn is the one who opened it.** A request from B that she answers in a turn A's line opened
  becomes A's task.
- **44 functions in 13 modules read these fields of a task by name,** and a few more select tasks by them (design.md
  §1.5). Most already read "the task's conversation and person" as "where it runs and for whom". They are right as
  soon as those fields are.

## The rule (the owner's, made exact)

**Work is done where it belongs, and the program decides where; she never picks a line.**

1. **A public conversation's work runs in it,** for whoever there asked (their folder, its limits, its result there);
   her own work on a visit runs there too, in a folder of hers.
2. **Development asked for on an agent's line runs on that line:** by its agent, or by the owner joining the line.
3. **Everything else runs on the home line, the Web chat:** misc work arising in any owner-private conversation (the
   owner's own DM, an agent line, her sister's line, a home group), her own work at home, her self-development.
4. **The development tools go only with development work** the owner, an agent on its own line, or her
   self-development asked for.

The program decides from two things: `whose`, a record of who asked and where, written once when a turn opens and
carried along results, plans and errands; and one mark she gives a task, `develop` (this changes or runs her own
machinery). Only she can tell development from misc, so the rule needs the mark; everything else is the program's.

## Decisions (the lead's, following from the owner's)

1. **One record, `whose`** (`{by: words | standing | own, scene_id, person_id}`), decided by one function from stored
   state, kept on episodes, tasks and plans (design.md §2.1, §2.2).
2. **Inherited along the chain, never across a less trusted step:** a result turn has its task's `whose`, a plan's
   firing the plan's, an errand turn home's; a turn opened by a note from outside takes the writing turn's own place and
   never a home conversation (ADR-088).
3. **One function places a task** from `whose` and `develop` (design.md §2.3): the conversation it runs in, the person
   it is for there, its folder. Grants follow from the place and `whose` only (`grants.for_whose`), never from the turn
   that started it. A continuation runs where its task runs, with its task's grants.
4. **Plans place the same way,** as misc: a plan fires in the public conversation it belongs to or on the home line.
   The agent line hosts no plans; her `line` plans to a peer line stay as the owner decided on 2026-10-06. A plan made on
   an errand fires at home.
5. **She chooses only what the program cannot know:** `develop` (shown where it can be earned), and in a group the
   person whose request it is (`for`, a label from her turn).
6. **Her visit's task gets a folder of her own in that group,** made on first need and kept like a member's folder,
   instead of the first member's. Nothing else of visits changes (owner's decision 4).
7. **A task shows no line of another conversation:** every read of its input that reaches a model is fenced by the
   task's conversation.
8. **Nothing is re-routed** after the fact: a result whose conversation is gone is suppressed, a plan's failure is
   recorded as today.
9. **What she reads says where and for whom,** from one versioned table, in three places only: the `delegate` result,
   the result item of a result turn, the plan block of a plan's firing; the last two are added when the turn is
   prepared, never into the stored event. Nothing is added to every turn.
10. **A paused task continues on the words of the person it is for, where it runs:** at home the owner, as today; on an
    agent line its agent (today it never can).
11. **The agent line's narrow integration grant** goes with the agent's development tasks there, the same as the
    development grant, and nowhere else.
12. **Old records keep their meaning;** nothing rewrites a row (design.md §2.6).

## Earlier decisions this changes or keeps

- **Changed by the owner's decision 3:** ADR-050 (her sister's line keeps home rights, the development tools among
  them), the owner's 2026-10-18 decision (a home group keeps home's development rights for every member), and the
  owner's 2026-10-12 decision (her plans coming due and her trusted notes at home carry the development grant).
- **Changed by the rule:** ADR-066 row 1 (a plan begun on an errand fires in the destination) becomes home's; the
  2026-10-11 rule (a plan carries only the owner's integration grant) is replaced by decision 11.
- **Kept:** ADR-011 §6.1 and §6.2 (the development tools only with the owner's own delegations and her
  self-improvement, never anyone else's request); ADR-066 (an errand's task is home's); ADR-017 and ADR-018 (a group's
  task reports to that group; a note never grants; a result turn inherits from its task); ADR-088 (a turn opened by a
  note from outside acts with its origin's authority); ADR-075 (the tier belongs to the task and its continuations);
  ADR-107 (an admission ends as a mark; folders stay); ADR-108 D5 (a program-woken turn shows no speaker).

## The review

A fresh reviewer read the first draft (`d7e7decd7126`) against the code and found 14 problems, 2 of them blockers
(a note written on an errand could carry home's authority back home; tasks with no recorded input crashed the
hand-back). The lead checked each against the code and fixed it (`affd95133a06`); the reviewer re-checked those fixes
and found 8 more, all fixed (`877dff90b81a`). The full list, with what was done, is design.md §10. The redesign to the
owner's rule was then read by the same reviewer; its findings are design.md §10.3.

## Not in this ADR

- A group she has left or that was disbanded has no state (ADR-107 has no rule for it); results said there fail at
  the adapter and show as failed deliveries.
- A fair task queue across conversations (ADR-050's deferred item).
- The owner's view of where a task runs in the Web thread: a new UI field needs his approval; the records and audit
  carry it.
- The publication activation turn (`host._complete_activations`) stays a self-development turn at home.
- A repeating plan that keeps failing to fire records its outcome at every occurrence, as today.
