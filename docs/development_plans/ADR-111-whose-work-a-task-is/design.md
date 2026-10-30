# ADR-111: whose work a task is, designed to the end

The README has the ask, the decisions and the owner's questions. This page has the survey with its commands, the record
and the one function that decides it, the interfaces, the life cycle of every text and stored field, the failure modes,
the tests and the landings. Where a part depends on an owner's question it says which, and is written for the
recommended answer; §7 says what changes under the other.

Placeholders follow the test fixtures (`tests/fixtures/world.json`): people `A`, `B`, `C`, conversations `dm-a`, `g1`,
`g2`; the local chat is `local-dm` with its person `local-user` (the owner); an agent line is `agent:<route>`.

## 1. Survey

### 1.1 Commands

All run on `ac620ad17d40` (2026-10-30, from the checkout root). Counts are from their output.

```bash
grep -rn "task_records.save(self.store, {'_id'" src/asuna --include=*.py          # where a new task is written: 2
grep -rn "plan_records.save(self.store, {'_id'" src/asuna --include=*.py          # where a new plan is written: 3
grep -rn "development_granted(" src/asuna --include=*.py | grep -v "def "          # 2 callers
grep -rn "event_profile(" src/asuna --include=*.py | grep -v "def "               # 6 callers
grep -rn "requester_id" src/asuna --include=*.py | grep -v "^src/asuna/records/\|catalog.py"   # 27 lines
grep -rn "offer_internal(\|offer_self_development(" src/asuna --include=*.py      # internal turns
grep -rn "ended_at" src/asuna/*.py                                                # ADR-107's end of admission
grep -rn "home_turn\|errands.carried\|_as_place\|outside_class" src/asuna --include=*.py
python3 readers.py                                                                # below
```

`readers.py` walks `src/asuna` (outside `records/` and the catalog) with `ast` and prints, for every read of
`scene_id`, `scope_key`, `policy_epoch`, `requester_id`, `development_grant`, `integration_profile`,
`raw_input_refs` or `native_session_id` through a variable named like a row (`task`, `current`, `latest`, `row`,
`given`, `closed`, `paused`, `cancelled`, `continued`, `theirs`, `stopped`), the enclosing function:

```python
import re, ast, pathlib
pat = re.compile(r"""(task|current|latest|row|given|closed|paused|cancelled|continued|theirs|stopped)(\[|\.get\()"""
                 r"""['"](scene_id|scope_key|policy_epoch|requester_id|development_grant|integration_profile|"""
                 r"""raw_input_refs|native_session_id)['"]""")
for f in sorted(pathlib.Path('src/asuna').rglob('*.py')):
    if 'records' in f.parts or f.name == 'catalog.py':
        continue
    src = f.read_text(encoding='utf-8')
    funcs = [(n.lineno, n.end_lineno, n.name) for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef)]
    for i, line in enumerate(src.splitlines(), 1):
        for m in pat.finditer(line):
            print(f, [n for a, b, n in funcs if a <= i <= b][-1:], m.group(3))
```

It finds 100 functions; 44 of them, in 13 modules, read a task (the rest read other rows with the same field names).
Those 44 and the readers that select tasks by these fields without naming them are §1.5.

### 1.2 Every path that creates a task

Two writes make a new task row: `Coordinator.delegate` (`coordinator.py`) and `Coordinator.message_action` (a
finished task continued, `continues_task_id`). Everything else reaches one of them.

| Path | Code | Its conversation and person today | Whose it is (this design) | Where the answer is in the code |
|---|---|---|---|---|
| `delegate` in a turn someone's words opened | `RoleTools.tool_delegate` → `Coordinator.delegate` | the turn's scene, scope, epoch; `requester_id` = the speaker | `words`: the speaker, here | the input event's `person_id` (the line's author), `scene_id` |
| `ask` with `to` 行动脑 | `RoleTools.tool_ask_ask` → `Coordinator.delegate` (`<call>:ask`) | as above | the turn's | as above |
| `ideas` review `adopt` | no task by itself; she then calls `delegate` | as above | the turn's | as above |
| `task` `message` on a finished task | `RoleTools.tool_task_message` → `Coordinator.message_action` | the **turn's** scene, scope, epoch and person; grants `_grants(ep)` must equal the task's | the continued task's `whose` (the same work) | the task row |
| `task` `message` on a running task | `message_action` (a `task_messages` row, no task) | — | — | — |
| a result turn (`task_feedback`) | `TaskService.feedback` opens it; she may `delegate` in it | the task's scene and requester; the development grant from the task (`development_granted`, `task_feedback` branch) | the task's `whose` | the input event's `task_id` |
| `consult` (the action brain asks her) | `Coordinator.consult` | the task's | the task's (no `delegate` in a consult turn) | the task row |
| an errand turn | `errands.carried` at ingest; `Coordinator.delegate` uses `errands.home_turn` | home's (ADR-066) | home's turn's `whose` | `ep['errand']['from']` |
| a self-development turn (offered, dice, night stage, publication) | `Chat.offer_self_development` | the local chat, the owner | `standing` (the owner's standing ask) | the episode kind |
| her plan firing (`scheduled`) | `Schedule._deliver_locked` → `Chat.receive` | the plan's scene and person; development in any owner-private conversation | the plan's `whose` | the event's `scheduled_plan_id` |
| a note of hers, trusted, home to home | `Schedule.note` → `offer_internal('note', …)` | the receiving conversation; its route's person (`notes.receiver`); development granted | `own`, where it opened (ADR-018: a note never grants) | the event's `note.id`, `notes.opening_for` |
| a note from outside, at home | as above | `delegate` refused (ADR-088 §4.2) | the origin's `whose` (for the plans it makes) | `notes.outside_class`, `note.from_episode` |
| a visit (her own, or a note of hers opening a group) | `Schedule.visit` / `Schedule.note` → `offer_internal('visit', …)` | the group; **the first member of the route by id** (`places.visitor`) | `own`, in that group: no task (question 1) | the episode kind and `visit.intent` |
| a heartbeat, the nightly settlement | `Schedule._presence`, `_settlement` | the local chat, the owner | `own`, at home | the episode kind |
| the owner on a home line he joins | `Chat.submit(scene_id=…)` | that line, the owner | `words`: the owner, on that line | the event's `person_id` |

### 1.3 Every path that creates or fires a plan

| Path | Code | The conversation it stores today | This design |
|---|---|---|---|
| `plan` create | `RoleTools.tool_plan` → `Schedule.create(ep, spec, where)` | the turn's; `where` = a note's origin (ADR-088) or a peer line (`line`) | the turn's `whose` conversation; `line` makes it `own` in that line |
| `plan` create on an errand | as above | the destination group, its visitor (ADR-066 row 1) | home's (question 5) |
| `plan` update, cancel | `Schedule.update`, `Schedule.cancel` | the same row | unchanged; the row keeps its `whose` |
| rhythm plans (heartbeat, settlement, condensing) | `Schedule._rhythm_plan` via `_owner_private_target` | the local chat, the owner | unchanged: their kind decides (`own`) |
| self-development and night stages | `Schedule._ensure_development_plan` | the local chat | unchanged: `standing` |
| firing | `Schedule._deliver_locked` | authorizes `plan.scene_id` with `plan.person_id`, checks the epoch and the route's members, sends a `scheduled` event there; carries `integration_profile` only when it is `owner` (the 2026-10-11 rule) | the event names the plan; the turn's `whose` is the plan's; the integration profile comes from it (question 7) |

### 1.4 How a result comes back

1. The executor finishes (`Chat._tasks` → `Executor.run` in the folder `workspace_folder(task.scene_id,
   task.requester_id)`), then `Chat.hand_back(task)` queues `{_feedback_task, scene_id: task.scene_id, person_id:
   task.requester_id}` in that conversation's queue (`SceneQueue`, keyed by scene).
2. `Chat._work` calls `TaskService.feedback`: the event is `task.scene_id` / `task.requester_id`, its session
   `task.native_session_id` (else the handing-over turn's), its text the result sentence, its `trusted_context_events`
   the result (cleaned by `machine_words.clean` outside home), the brief, her thought then (`_why_then`), the original
   input read **within the task's scope and epoch**, the key tool records; `integration_profile` is copied from the
   task so the result turn's `message_action` check passes. `Coordinator.ingest` opens a `task_feedback` turn.
3. `require_current_feedback` fences the turn: the task not cancelled, stale or paused, the same revision, the same
   scene, requester, scope and epoch, the scene's epoch unchanged.
4. The watchdog (`handover.lost`, `orphaned`, `Chat.sweep`) hands a lost result back again by cause, the same way.
5. `publish.py` finds where her words in a result turn go by walking back through `task_feedback` inputs to the first
   input (through `errands.home_turn`), and takes that input's channel, or the conversation's own route for a visit, a
   note or a plan's firing.
6. What she reads of tasks in a turn: `task_state_from_program`, from `records.tasks.recent_with_inputs(scene, scope,
   epoch)`: every task of the conversation (not by person), the open ones first, then three finished; each with
   `handover.status_words`, a report-pages note and the action brain's latest progress notes.
7. Paging: `task` `page` (`RoleTools.tool_task_page`) reads any of her tasks at home, and elsewhere only the tasks of
   the conversation it is in (`scene`, `scope`, `epoch` fence).

### 1.5 Who reads the task's fields, and what each assumes

Grouped by what the reader takes the fields to mean. "Follows" means the reader is right once the fields are `whose`'s;
"changes" names the change.

| Reads the fields as | Readers | This design |
|---|---|---|
| the conversation whose data the task may read | `history_query.query_for_task`, `discussion_digest.digest_for_task`, `vision` (`read_image_for_task`, `readable_image_scenes`, `scene_attachments`, `attachment_by_ref`, `task_attachment_context`, `stored_image`, `path_image`, `picture_to_edit`, `local_upload_bytes`, `media_source_url`), `received_files.received_from`, `ToolBroker.call` (artifacts' scope), `TaskService.valid` and `stale_reason` (the epoch fence), `cancel`, `pause_for_restart`, `Executor._run_claimed` (the execution binding) | follows |
| whose folder, class and tools | `Chat._tasks` (`workspace_folder`), `ToolBroker.bind`, `Executor._run_workspace` (grant, class, the action brain's persona and notes), `ToolBroker.call` (`allowed_capabilities`, `development_grant`, `integration_profile`), `NativeDevelopmentBridge.call` (`development_grant` and the owner-private class), `credentials.home_task` | follows; the two grant fields are written from `whose` (§2.3) |
| where the result is said | `Chat.hand_back`, `TaskService.feedback`, `require_current_feedback`, the watchdog, `publish.py`'s walk | follows; `publish.py` needs nothing new because a task is never handed to another platform conversation (§2.4) |
| who may steer or stop it | `RoleTools._own_task` (same scene, `requester_id` = the turn's person, same epoch), `Coordinator.message_action` (the grants check and the PAUSED rule), `TaskService.cancel` (`person_id` = `requester_id`), `Chat.stop` | the fence follows; the grants check reads `whose`; the PAUSED rule changes (question 6) |
| which list shows it | `records.tasks.recent_with_inputs` (by scene), `places.elsewhere`, `self_review.block`, `queue_words`, `place_words`, `capability_refusal` | follows; `capability_refusal`'s "这件是%s交的" becomes "这件算%s的" (the place it belongs to, not where it was handed over) |
| the session it is drawn in and its result runs in | `NativeWorker.parent_session`, `TaskService.feedback`, `message_action`, `Coordinator.consult`, `NativeLane` stage binding (`native_worker.py`, from the task since ADR-066) | changes for a task that is not the turn's conversation's: §3.3 |
| the input it answers | `Executor._run_claimed` (`raw_input_refs[0]`, **not fenced**), `TaskService.feedback` (fenced), `Coordinator.consult` (fenced, raises `CONSULT_SOURCE_MISSING`), `host._recover_tasks` (walks to the first input to decide whether to pause), `message_action` | changes: the executor read is fenced like the others; consult accepts no input (§3.4) |
| the turn that handed it over | `Coordinator.consult`'s `belongs` check (the errand or first turn's fields equal the task's), `tasks._why_then`, the waiting turn, `delegation_depth` | the `belongs` check is replaced by the task's own fields; the rest stays the hand-over's record (ADR-066) |
| the grants of a turn | `grants.development_granted` (kind + class), `integration.event_profile` (the turn's input), `Coordinator._grants`, `ContextBuilder.prepare`'s capabilities block | replaced by `grants.for_whose` (§2.3) |

Plans' fields are read by `Schedule._deliver_locked` (authorize, epoch, route), `records.plans.of_conversation` (the
plans list, filtered by the turn's person), `RoleTools.tool_plan` (update and cancel within the conversation),
`schedule_rules.project` (the words). The list filter changes (§3.6); the rest follows.

### 1.6 Earlier ADRs on this ground, and what this keeps

- **ADR-011** §6.1: the development tools go with the owner's own delegations and her self-improvement turns, and their
  result turns; §6.2: never anyone else's request (an idea at most). Kept, and made exact: §2.3. The code had widened
  it to every owner-private turn kind; question 3.
- **ADR-066**: a task begun on an errand is home's (its conversation, scope, epoch, person, session); the errand turn
  stays the record of the hand-over; every reader that grants or authorizes goes through `errands.home_turn`. Kept as
  one case of the inheritance in §2.2. Its row 1 (a plan begun on an errand resolves to the destination) is changed by
  question 5.
- **ADR-018**: a note never grants anything (§5.4); `task_feedback` inherits from its task; delegation depth stops a
  loop at 6 (§3.3). Kept: a trusted note's turn is `own` where it opened.
- **ADR-017**: a group's task reports to that group, not home. Kept: no path hands a task to another platform
  conversation.
- **ADR-088**: a home turn opened by a note from outside acts with its origin's authority, and so does everything it
  creates; its plans live and fire in the origin with the origin's person; "no new stored state". Kept as one case of
  §2.2; the plan path becomes the general rule (§3.6). This design does add stored state (the record), for the reason
  in §2.1.
- **ADR-075**: a task's tier and its `why` belong to the task and its continuations. Kept; a continuation also keeps
  its task's `whose`.
- **ADR-107**: an admission ends as a mark on the grant (`ended_at`); scene, epoch, members, person and folder stay.
  Kept; this design reads the mark to say so (§3.5) and changes nothing of it.
- **ADR-108 D5**: a program-woken turn shows no speaker; the authorizing person stays on the episode. Kept: `whose` is
  written beside it, not instead of it.
- **ADR-050**: the home lines keep home rights; the hand-back cleaning follows the class the report is shown in. The
  development part is question 3; the rest is kept.
- **ADR-106**: a plan keeps the zone it was made in. The same shape: a plan keeps the `whose` it was made with.

## 2. The invariant and its record

**A task is for the one whose authority its turn acts with: a person whose words asked, in the conversation they asked
in, or herself. The program records that answer once, when the turn is opened, from stored state only; every task and
plan the turn makes copies it, and everything about them is read from it.**

### 2.1 The record

```text
whose = {
  'by':        'words' | 'standing' | 'own',
  'scene_id':  the conversation it belongs to,
  'person_id': words: the person whose words asked; standing: the owner; own: the conversation's own person
               where it has one (the owner in the local chat, a line's or a DM's route person), none in a group,
  'chosen':    True only when she picked it (delegate's `for`, plan's `line`),
  'version':   WHOSE_VERSION,
}
```

The episode's own `person_id` stays the person the turn is authorized as (ADR-108 D5), the placeholder visitor
included; `whose.person_id` is the one the work is for, and in a group her own work is for no one there. A task's
`requester_id` is `whose.person_id`, which is never empty, because `own` in a group makes no task (question 1).

Why a record and not a derivation each time (ADR-088 derived its class each time): the answer is read long after the
turn, across a chain (a result turn three steps after the first ask, a plan firing next week), and every step would
otherwise re-walk notes, plans, tasks and home turns that may be gone by then. A record written once, in the same write
as the row that needs it, cannot drift from it.

### 2.2 The decision: `whose.of_turn(store, ep, event)`

One function in a new module `src/asuna/whose.py`, the only place that decides it. It reads stored rows only and calls
no model, so a restarted worker and a redelivered event compute the same answer.

| The turn | Its `whose` |
|---|---|
| on an errand (`ep['errand']`) | `of_turn` of the home turn that sent it (ADR-066) |
| `external` (a person's line) | `words`: the line's author, in this conversation |
| `task_feedback`, `consult` | the task's `whose` (the event's `task_id`) |
| `scheduled` | the plan's `whose` (the event's `scheduled_plan_id`) |
| `note` or `visit` opened by a note from outside, in an owner-private conversation (`notes.outside_class`) | `of_turn` of the turn that wrote the note (`note.from_episode`) |
| `note` (trusted), `visit` (her own, or opened by a note of hers), `presence`, `settlement` | `own`, in this conversation |
| `self_development` | `standing`, in the local chat |
| any kind added later | `own`, in this conversation (no grant until a decision gives one) |

A task or plan row without `whose` (written before this ADR) reads as §2.5 says. The class `notes.outside_class` needs
is computed from the scene and the person (`visibility.session_class`), since `of_turn` runs before the manifest
exists.

### 2.3 Grants: `grants.for_whose(store, whose, develop)`

One function replaces `development_granted` and the event's integration profile wherever a task's grants are decided:
`Coordinator._grants` (a new task, a continuation), `message_action`'s check, and the capabilities block of her turn
(what a task from here would get). Its words are one versioned table beside it.

| Grant | Given when (recommended answers to questions 2, 3 and 7) |
|---|---|
| development tools (`development_*`, `persona_job*`) | `earns_development(whose)` and (`develop` or `whose.by == 'standing'`), self-development enabled, the sandbox available |
| integration profile | the same condition; then `owner` when `owner_profile(scene, person)` holds, `agent_home` when `agent_home_profile(scene)` holds and the person is that line's own speaker, `owner` for `standing` when the local chat is the integration's binding (as `Chat.offer_self_development` decides today); else none |
| `sandbox_run`, stored credentials | `whose`'s conversation is owner-private for its person (`visibility.session_class`) |
| the folder | `workspace_grant(whose.scene_id, whose.person_id)`; none for `own` in a public conversation (question 1) |
| everything else (workspace tools, pictures, SVG, her word list) | as today |

`earns_development(whose)`: `standing`; or `words` where the person is the owner (canonical, `scene_links`) in an
owner-private conversation; or `words` on an agent line (`integration.agent_home_scene`) by that line's own speaker.
Nothing else: not `own`, not a peer line's speaker, not a home group's other members.

A task's grants are written on it when it is made (`development_grant`, `integration_profile`, `allowed_capabilities`,
as today) and never recomputed: every runtime reader keeps reading the stored fields.

### 2.4 Her choice, and why only this one

The program's answer is always defined, so she never has to choose. She may say one thing: that the work is her own.
`delegate`'s `for` takes the value `你自己的`, which makes the task `{by: own, scene_id: the local chat, person_id: the
owner, chosen: True}`: home's folder, home's result turn, no development or integration grant unless the turn is a
self-development turn's (then `standing` stands and `for` changes nothing but the record).

It is offered only in owner-private conversations. From a public conversation it would move work begun on what anyone
there wrote into home's folder and home's grants, which is ADR-088's case: so a public turn has nothing to choose, and
its tasks are always its asker's.

Naming any conversation as the one served (a group, a DM) was considered and set aside:

- from home toward a group, the task would run with the group's grants on a brief written with home's view, and its
  result would open a turn in the group that nobody there asked for; work for a group from home is home's work, and
  she carries it there herself (an errand, a note), as ADR-066 decided;
- the program cannot map a group to a person without one there having asked; any person it picks is a placeholder,
  the defect this ADR removes.

### 2.5 Old records

There is no history conversion (docs/DEVELOPMENT.md). Nothing rewrites a stored task, plan or episode.

- A **task** without `whose` was recorded with its conversation and requester as the one who asked, and its grants as
  stored. That stays its meaning. When a new task inherits from it (its result turn), `of_turn` reads it as
  `{by: words, scene_id: task.scene_id, person_id: task.requester_id}` and the new task's audit row says
  `inherited: unrecorded`. A chain begun before the install (a visit's task among them, with its placeholder person)
  keeps that answer until it ends; L1 counts how many are open.
- A **plan** without `whose` reads the same way from `plan.scene_id` and `plan.person_id`; it keeps firing where it was
  stored, an errand's plan in its destination included. Its stored `integration_profile` still goes on its event.
- An **episode** without `whose` (a turn in flight across the install) gets it from `of_turn` when it is read.

## 3. Interfaces

### 3.1 `src/asuna/whose.py` (new)

- `of_turn(store, ep, event) -> whose`: §2.2.
- `of(store, ep) -> whose`: `ep['whose']`, else `of_turn` on the episode's stored input.
- `of_task(task)`, `of_plan(plan)`: the stored record, else §2.5's reading.
- `own_home(config) -> whose`: her choice's record (§2.4).
- `standing(store, whose) -> 'here' | 'left' | 'blocked' | 'closed'`: whether the person can still be reached there:
  `left` when their grant on the group's route carries ADR-107's `ended_at`, `blocked` when the channel lists them in
  `blocked_senders` or her own block switch holds them (`switches.blocked`), `closed` when the conversation is a line she
  has closed (`lines.is_closed`).
- The words (versioned, `WHOSE_VERSION = 1`; a change to any of them bumps it), all addressing her as 你:

```python
TASK = {'words': '这件是%s托你的', 'standing': '这件是你自我改进时交的', 'own': '这件是你自己的事'}
PLAN = {'words': '这条计划为的是%s托你的事', 'standing': '这条计划是你自我改进时定的', 'own': '这条计划是你自己的事'}
RESULT_HERE = '结果回到这里'
RESULT_HOME = '结果回家里，这边的上下文不跟过去'
HANDED = '是你在%s交出去的'
STANDING = {'left': '（%s已经离开这个群了）', 'blocked': '（%s在这里被屏蔽了）', 'closed': '（这条线你关着）'}
PLAN_HOME = '建在家里（差事是家里托的）：到点在家里跑，带家里的权限'
OWN_PUBLIC = ('这一回合是你自己来的（出门看群、自己的计划或便条），这里没有谁托你，交不了事：'
              '要做的事回家再交，用 plan 或便条带回去。')
```

  `%s` is the person's label as she reads it in that conversation (`People.speaker`), or the place's title
  (`People.scene_title`); never an id.

### 3.2 Episodes

`Coordinator.ingest` computes `whose.of_turn` once, before `ContextBuilder.prepare` (which is given it), and writes
it on the episode in the same save, for both the gated (`ATTENDING`) and the prepared episode. `Coordinator.consult`
writes the task's on the consult episode. `Coordinator._attend` passes the stored one to `prepare`.

### 3.3 `Coordinator.delegate`

```text
whose  = whose.of(store, ep); if for == '你自己的': whose = whose.own_home(config)
refuse OWN_PUBLIC when whose is own in a public conversation (the tool is not offered there; this guards the call)
refuse DEVELOP_NOT_HERE when develop and not earns_development(whose)
scene  = scene_records.authorize(whose.scene_id, whose.person_id)
workspace_grant(config, whose.scene_id, whose.person_id)          # today: the turn's (home's on an errand)
development, integration, names = grants.for_whose(store, whose, develop)
session = the turn's own when whose is the turn's conversation (home's live one for an errand or a reflection, as
          `_task_session` does today); otherwise the session the resolver gives that conversation's own turn
raw    = ['in-' + authority turn] when whose is the authority turn's conversation and that input exists, else []
task   = {... as today ..., scene_id/scope_key/policy_epoch/requester_id from whose and its scene,
          whose, develop (when true), development_grant, integration_profile, allowed_capabilities, native_session_id}
audit  'task.whose' {by, chosen, develop, development_grant, integration_profile, class of whose's conversation,
          class of the turn's, inherited: 'unrecorded' when §2.5 applied}
```

The task is written in one save, as today; the episode's `task_ids` update after it stays as it is (§3.8 covers a crash
between them). The `delegate` result gains `for`: `TASK[by]` (with the label) + `；` + `RESULT_HERE` or `RESULT_HOME`;
its `note` keeps `HOME_TASK` on an errand and `REFLECTION_TASK` in a reflection.

The spec (`role_tools.TOOLS['delegate']`): the description gains `结果回到这件事的主人那里，交出时会说是谁的。`; two
parameters are added, `for` (`enum: ['你自己的']`) and `develop` (boolean), both left out by `placed_spec` in
conversations that are not owner-private (ADR-087 §4.3: a spec shows only what a turn there can use).
`DEVELOP_NOT_HERE` gets its `WORDS` entry (`tests/test_refusal_words.py`).

### 3.4 Continuations, consult, executor

- `Coordinator.message_action` (a finished task continued): the new row keeps the continued task's `whose` and
  `develop`; its grants are `for_whose(task.whose, task.develop)`. The turn may continue it when `_own_task` found it (as
  today) and the turn's grants reach the task's: a task with the development grant takes words only from a turn whose
  `whose` earns it, and the integration profiles must be equal (today's check, computed from `whose`). A `PAUSED` task
  continues on an `external` turn whose `whose` is the task's, or the owner's own words (question 6; today only the
  owner in the local chat).
- `Coordinator.consult`: the `belongs` equality goes; the consult is authorized by the task's own fields and runs in
  the task's session; an empty `raw_input_refs` (a task of hers named home) gives `original_input: null` instead of
  `CONSULT_SOURCE_MISSING`.
- `Executor._run_claimed`: the input is read within the task's scope and epoch, as `feedback` and `consult` read it.
- `host._recover_tasks`: an empty `raw_input_refs` is a task of a live turn and is paused like the others (today it
  would raise on `[0]`).

### 3.5 The result turn and the capabilities block

- `TaskService.feedback` (and the short hand-back): the event's text gains `TASK[by]`, `HANDED` when the task was
  handed over in another conversation, and `STANDING[...]` when the person is no longer reachable, then `。`. A result
  whose conversation no longer exists is suppressed, like one whose epoch changed (today it would fail on the missing
  scene). The task's `integration_profile` is still copied onto the event, so a result handed back across the install
  matches its stored input (`ingress.py` compares the two).
- `ContextBuilder.prepare`'s `action_capabilities_from_program`: `available` from `whose` (false for `own` in a public
  conversation); `development` present when `earns_development(whose)`, with `要它动你自己，delegate 写 develop。`;
  `integration` from `whose`; `run_code` from `whose`'s class; `delivery` reads
  `程序自动执行委托，结果作为独立事件回到这件事的主人那里（交出时会说是谁的）；等待时仍可聊天。`.
- The refusal of `delegate` in a turn where it is not usable reads `whose.by`: `OWN_PUBLIC` for her own turn in a
  public conversation, the existing `NOT_NOW['delegate']` otherwise.
- `capability_refusal` (the action brain's): the development line of `GIVEN_TO` reads
  `只给交的时候写了 develop 的任务：主人或 agent 在自己的线上托的、或自我改进时交的（自我开发要开着）`, and the place
  phrase reads `这件算%s的`.

### 3.6 Plans

- `Schedule.create`: the target is the turn's `whose` conversation and person (an errand turn's is home's; an
  outside-note turn's is its origin's, which is what `RoleTools._as_place` gives today); `line` makes it
  `{by: own, scene_id: the line, person_id: the line's person, chosen: True}`. The row carries `whose` and no longer
  writes `integration_profile`. `RoleTools.tool_plan` stops computing `where` for outside notes (the target comes from
  `whose`); on an errand its result says `PLAN_HOME`.
- `Schedule._deliver_locked`: the event's text gains `PLAN[by]` and `STANDING[...]`; the scheduled turn's `whose` is the
  plan's (§2.2). A repeating plan whose firing fails for good (`SCENE_MEMBERSHIP_DENIED`, `SCHEDULE_ROUTE_REVOKED`,
  `SCHEDULE_POLICY_STALE`) is set `SUSPENDED` with that outcome, once, instead of failing again at every occurrence; it is
  never moved to another conversation.
- The plans list (`records.plans.of_conversation` from `ContextBuilder.prepare`) is filtered by the turn's
  `whose.person_id` instead of its `person_id`: a plan is listed when its `whose.person_id` is the turn's (an old plan,
  without `whose`, by its `person_id` as today). At home and on a line every record has the conversation's one person,
  so the list is what it is today; in a group a member's turns list that member's plans and her own turns (a visit, her
  own plan's firing) list her own, which have no person. The plan row's own `person_id` stays the person its firing is
  authorized as (the visitor for her own plan in a group). The view states `Exists` on `whose` for the new rows, so the
  None rule (records/view.py) cannot match an old row by a missing field.

### 3.7 Steering: the same fence, with the person the work is for

`_own_task` keeps its fence (same conversation, same person, same epoch) and compares the task's `requester_id` with
the turn's `whose.person_id` instead of the episode's `person_id`; `task` `stop` passes the same person to
`TaskService.cancel`. At home, on a line and for a person's own turns these are the same person, so nothing changes
there. On a visit today the fence's person is the route's first member, so her visit may steer and stop that member's
tasks; with `whose` it is no one, so every task there answers `OTHERS_TASK`, naming the member who really asked.

### 3.8 The crash gap

`Coordinator._notice` lists the tasks a resumed turn already handed over from `task_records.of_episode(ep['_id'])` (the
task rows, which the crash cannot lose) instead of `ep['task_ids']` (written after the task, which it can). A repeated
call with the same call id finds the same task id, as today.

## 4. Life cycles

### 4.1 Every text she reads about a task or a plan

Brains: CB the character brain, AB the action brain, RG the relevance gate (which reads none of these).

| Text | Created | Used | Updated | Discarded | Survives |
|---|---|---|---|---|---|
| `delegate` description (+22 characters) | `role_tools.TOOLS` at import; placed per conversation (`placed_spec`) | CB, in the tool list of every request in every conversation that lists `delegate` | by a release only | never while the tool exists | worker and Host restart (code); compaction (tools are not compacted); a retired one-shot session (the next has the same list); redelivery (not an event) |
| `delegate` `for` and `develop` (+222 characters of JSON, owner-private conversations only) | as above | as above, owner-private conversations | by a release | as above | as above |
| `task` description | unchanged | | | | |
| `delegate` result `for` (14–25 characters) | `RoleTools.tool_delegate`, from the stored task's `whose` | CB, the turn that delegated | never | when the session's history is compacted (the summary keeps what she kept) | restart: the tool call's recorded result is replayed, not recomputed; redelivery: the same task id gives the same words; a retired one-shot session: the result turn repeats whose it is |
| `task_state_from_program` | unchanged: no field added; it lists the conversation's own tasks, which are now `whose`'s | CB, every turn with tasks | | | |
| the result turn's text (+10–30 characters) | `TaskService.feedback` when the result is handed back, from the task's `whose` and `standing` at that moment; stored with the input | CB, the `task_feedback` turn (one per result; the short one too) | never: a full re-hand reuses its event id and stored input; the short one is its own event | with the turn's history at compaction | restart and Host restart: the stored input is replayed; redelivery: deduplicated by its event id; compaction: kept in the summary as she kept it |
| a plan's firing text (+10–25 characters) | `Schedule._deliver_locked` per occurrence, from the plan's `whose` and `standing`; stored with the input | CB, the `scheduled` turn | never | as above | as above; a plan made before the install has no `whose` and fires with §2.5's reading |
| the visit's text | unchanged; the visit turn no longer has `delegate` usable (the list is the conversation's, unchanged) | | | | |
| `OWN_PUBLIC` (62) | the refusal when she calls `delegate` in her own turn in a public conversation | CB, visits and her own plans' turns in public conversations, only when she tries | by a release | with the tool result | as any tool result |
| `DEVELOP_NOT_HERE` (79) | the refusal when `develop` is given where it is not earned | CB, owner-private turns that do not earn it, only when she tries | by a release | as above | as above |
| `action_capabilities_from_program` `delivery` (+14), `development` (+26 where earned) | `ContextBuilder.prepare` each turn, from the turn's `whose` | CB, every turn where `delegate` is available; sent whole only when its content changed, otherwise named unchanged (`context-delivery.js`) | when `whose`'s grants change between turns (an owner's turn and a heartbeat at home), as the development key does today | replaced by the next turn's | rebuilt every turn: restart, compaction (`restoreContext`), redelivery |
| `capability_refusal` (the development line, 57; `这件算%s的`) | the broker's refusal of a tool the task was not given | AB, only on that refusal | by a release | with the tool result | as any tool result |
| `PLAN_HOME` (27) | `tool_plan`'s result on an errand | CB, the errand turn | by a release | with the tool result | as any tool result |
| `errands.HOME_TASK`, `REFLECTION_TASK`, `wake_words.WAKE_WORDS` | unchanged | | | | |

### 4.2 Every stored field this adds or changes

| Field | Created | Used | Updated | Discarded | Survives restart and compaction |
|---|---|---|---|---|---|
| `episodes.whose` | `Coordinator.ingest` and `consult`, in the episode's first save | `delegate`, `message_action`, `Schedule.create`, `prepare`, the refusal's words | never; a resumed turn keeps it | with the episode (episodes are kept; erasure redacts them per scope, ADR-105) | yes: stored; a session compaction does not touch episodes |
| `tasks.whose`, `tasks.develop` | `delegate`, `message_action`, in the task's one save | `of_turn` for its result turn and its consults, its continuations, the audit, the words | never | with the task (kept; erased per scope) | yes |
| `plans.whose` | `Schedule.create`, in the plan's first save; rhythm plans have none (their kind decides) | `of_turn` at its firing, the plans list | never: update keeps it, as it keeps the zone (ADR-106) | with the plan (FIRED and CANCELLED rows stay) | yes |
| `plans.status = SUSPENDED` on a firing that fails for good | `_deliver_locked`, once | the plans list (`schedule_rules.project` shows it as paused) | by her `plan` update, as today | as any plan | yes |
| audit `task.whose` | with the task's save | structure counts (the landings' checks) | never | after 30 days (ADR-074) | yes |
| `plans.integration_profile` | no longer written; old rows keep it and their events carry it | | | | |

## 5. Failure modes

| Case | She sees | The person sees | The program records |
|---|---|---|---|
| The conversation of `whose` ends, or the person's admission ends (an ADR-107 departure) | the result turn still runs there, saying `（A已经离开这个群了）`; she decides whether to say anything; a plan's firing says the same | nothing: they are not there | the task and plan unchanged; the folder kept (ADR-107); the words in the stored input |
| The person is blocked (her switch, or the channel's list) | the same, `（A在这里被屏蔽了）`; under the channel's block the task's next tool calls are refused `WORKSPACE_NOT_AUTHORIZED` and its report says so | what she chooses to say | the refusals in the task's records |
| The person is admitted again | the mark is gone, so the words are | as anyone | the return (ADR-107) |
| The person is unknown to her | the label `People.speaker` gives any author | — | `whose` by id |
| A plan fires after its conversation is gone (no scene, the route revoked, the epoch changed) | nothing: there is no conversation to read it in, and nothing she could do there | nothing | the outcome on the plan; a repeating plan suspended once; never moved elsewhere |
| A group she left or that was disbanded | a result said there fails at the adapter and shows as undelivered | nothing | a failed delivery (no state for "left": not in this ADR) |
| The work serves two conversations | one task, one `whose`; the `delegate` result says where its result goes, so the second is her own act (an errand, a note) | each sees what she says there | the task, and the errand or note as its own record |
| She names the wrong owner (`你自己的` when an agent asked) | `结果回家里…` in the `delegate` result; at home `是你在…交出去的` | the agent sees nothing on its line until she says something there | `whose.chosen`, the audit row |
| She names no owner when the work was hers | the `delegate` result says whose it went to (`这件是A托你的`) | the asker gets a result turn's words if she speaks | the asker's `whose`; its grants are the asker's, never more |
| A crash between the task's write and the episode's update | on resume, the task is listed as already handed over (§3.8) | — | the task row, with `whose` in it |
| The same event delivered twice | one turn: the episode id comes from the event id; `whose` is recomputed identically from stored rows | — | `ingress.deduped` |
| A restart while a task runs, or while its result waits | running: paused, then continued on its person's words or the owner's (question 6); waiting: the watchdog hands it to `whose`'s conversation | — | the pause; the hand-back |
| Compaction of the session that held the hand-over | the result turn carries the title, the brief, her thought then, whose it is and the report; nothing depends on the compacted `delegate` result | — | — |
| An agent line she closed while its work is in flight | its result turns and plans still run there (a closed line passes over the agent's messages, not her own work), saying `（这条线你关着）`; her words go out if she speaks | her words, if any | unchanged |
| An errand from home | the task is home's, its result at home (ADR-066); a plan made there is home's, `PLAN_HOME` | the destination sees what she said on the errand | `whose` = the home turn's |
| A visit | `delegate` is not usable; `OWN_PUBLIC` if she tries; a plan made there is hers there and listed only in her own turns there | what she says on the visit | `whose` own |
| A result that mentions another conversation's content | a task reads only its own conversation (history, digest, pictures and files are fenced by its fields); her brief is her own words, like a note; only a development task reads the whole database, and `whose` makes those home's, so their reports are read only at home; outside home the report is cleaned (ADR-050) | — | — |
| A task that would serve a less trusted person than the turn that started it | cannot be made: naming is offered only at home and only toward home; inheritance keeps the same `whose`; a task's grants are its `whose`'s, never the turn's | — | — |
| `develop` forgotten | the action brain is refused `CAPABILITY_DENIED` with the reason; its report says so; she hands it over again with `develop` | — | the refusal |
| `develop` where it is not earned | `DEVELOP_NOT_HERE` at the call | — | the refusal |

**Quiet wrong answers today, each made visible or removed:**

1. A visit's task recorded as asked by the route's first member: it ran in their folder, they could steer it, and
   `OTHERS_TASK` told her they asked. Removed: no such task.
2. Plans made on a visit listed in that member's turns, and the member's plans listed on her visits. Removed: the list
   follows `whose.person_id` (§3.6).
3. On a visit she could steer or stop that member's own tasks as if they were the visit's. Removed: §3.7.
4. The development grant on work that is not development (the writing task above). Removed by the mark; a missing
   mark is a loud refusal.
5. Work done on a line for someone else, recorded as that line's. Visible: every `delegate` result says whose it is.
6. A repeating plan firing into a conversation that is gone, every time, unseen. Suspended once, recorded.
7. A result handed to someone who left or was blocked, read as if they were there. Visible: the standing words.
8. A chain begun before the install carrying its old answer. Visible in the audit (`inherited: unrecorded`), counted at
   L1.
9. A task handed over twice after a crash because the resume notice missed it. Removed (§3.8).

## 6. Tests

Only those that guard a fence or a failure that would be silent and costly. All unit tests run on the in-memory adapter
(`world` and `store` in `tests/conftest.py`); none reaches a server.

| Test (new module `tests/test_whose.py` unless named) | Guards |
|---|---|
| `test_whose_by_turn_kind`: every row of §2.2, including an errand, an outside note, a trusted note, a visit, a plan made before the install, a task made before the install | the invariant itself: a wrong row is a wrong grant or a result in the wrong conversation, silently |
| `test_development_only_where_whose_earns_it_and_she_marked_it`: the owner at home, in his DM, on a line he joins; an agent on its line; a peer line's speaker; a home group's other member; a public member; `own`; `standing`; `develop` on and off | the authorization fence |
| `test_a_task_she_calls_hers_belongs_home`: `delegate` from an agent-line turn with `for` gives home's scene, scope, epoch, person and folder, home's session (a stub resolver), an empty input; its result is queued at home; the executor's, the hand-back's and the consult's reads of its input give nothing of the line | privacy across conversations and the routing |
| `test_a_result_turn_hands_its_whose_on`: a task's result turn delegates again and the new task has the first one's `whose` and grants; from a task made before the install, `words` by its requester and the audit's `inherited: unrecorded` | the chain, old records |
| `test_her_own_turn_in_a_group_hands_nothing_over`: a visit and a turn her visit-made plan opens have no usable `delegate`, `ask` to the action brain is refused, the words are `OWN_PUBLIC` | the placeholder never becomes an asker |
| `test_a_task_written_before_the_crash_is_listed_on_resume`: the coordinator's `crash('after_task_persist')`, then the resumed turn's notice | the crash gap |
| `test_a_plan_lives_where_its_whose_is` (L3): from an errand, at home; from an outside note, at the origin; with `line`, in the line as hers; its firing's turn has the plan's `whose`; a visit's plan is listed only in her own turns there | follow-up plans, the list |
| `test_a_plan_that_cannot_fire_is_suspended_once` (L3): the route revoked: suspended, the outcome kept, nothing sent elsewhere | no re-routing |

Changed: `tests/test_specs_by_place.py` (the two fields only where the class is owner-private),
`tests/test_refusal_words.py` (the new code's words), `tests/test_home_groups.py` (a home group's member no longer
earns development, under question 3's recommendation).

No new static check. No new integration test: no index, no adapter promise and no query form is added beyond a
nested equality the store contract already covers (the plans view's `whose.by`, which the builder confirms in
`integration/store_contract.py` and `tests/test_store_contract.py` before relying on it). `pytest integration` runs
at every landing as AGENTS.md requires.

## 7. Landings, in order

Each landing: targeted tests while building, then the full suite, `pytest integration`, the personal-data scan
(`tools/check_staged_secrets.py --personal --all`), the push gate, a fast-forward, the planned restart while she is
idle, a check that the running code is the commit's (`loaded.commit`), one report. Then one message to her from the
lead, and her check by content. Nothing reaches a real model endpoint in any test.

**L1: record `whose`, change nothing she reads or can do.** `whose.py` (the decision and the table, its words unused);
`episodes.whose`, `tasks.whose`, `plans.whose` written; the audit row. Task and plan fields stay exactly as today.
Tests: the first and the fourth. *On the real system,* after install, by structure only (no content), for two days
or 100 new tasks, whichever comes first: tasks and plans by turn kind, `whose.by`, the class of `whose`'s conversation
and of the turn's; how many tasks were `own` in a public conversation (what L2 stops), how many would lose the
development grant under questions 2 and 3, how many chains begun before the install are still open. This is also the
trace of the owner's "random group" case: every group task whose `whose` is not a person there.

**L2: tasks follow `whose`.** §2.3, §2.4, §3.3 to §3.5, §3.7, §3.8, question 6. Tests: all but the two plan tests.
*On the real system,* two days by structure: the development grant only where `whose` earns it and `develop` was
given (or `standing`); no task `own` in a public conversation; every `你自己的` task's result episode in the local chat;
no task whose input lies outside its own conversation; agent-line tasks a day and their development rate, beside the
lead's numbers for 10-27 and 10-28 (for the owner's reading, not a gate).

**L3: plans follow `whose`.** §3.6, questions 5 and 7. Tests: the two plan tests. *On the real system:* plans by
`whose.by`; every plan made on an errand stored at home; in a sample of group turns, the plans their context listed
against those plans' `whose`; suspended plans with their outcomes.

Her reading: the texts in §4.1, finished, at a frozen commit, before L2 is built (L3's two texts with them).

Under the other answer to a question: question 1 (B) adds a folder kind (`<data>/channels/auto-<hash of the route and
her>`, made on first need, erased with the conversation) and lets `own` in a public conversation hand over, with
`_own_task` comparing `whose` instead of the person; question 2 (B) drops `develop` and its words; question 3 (B)
keeps today's earners in `earns_development`; question 4 (B) drops `for`; question 5 (B) keeps an errand's plan in the
destination as `own` there; question 6 (B) keeps today's PAUSED rule; question 7 (B) keeps the plan event's
integration rule by hand.

## 8. What she carries

- **Every turn:** nothing new in her context. `action_capabilities_from_program` grows by 14 characters (`delivery`)
  and, where earned, 26 (`development`); the block is sent whole only when it changes.
- **Every request (the tool list, a cached prefix):** `delegate` grows by 22 characters everywhere, and by 222 more in
  owner-private conversations (`for` and `develop`, as JSON). Measured on `ac620ad17d40` with the drafted texts: 363 →
  607 characters at home, 363 → 385 elsewhere.
- **Per event:** 14–25 characters in each `delegate` result; 10–30 in each result turn; 10–25 in each plan's firing.
- **Only on a mistake:** `OWN_PUBLIC` (62), `DEVELOP_NOT_HERE` (79); for the action brain, the development line (57).

## 9. Not in this design

- A group she has left has no state; giving it one is its own ADR (ADR-107 has no rule for it).
- A fair task queue across conversations (ADR-050).
- A Web view of `whose` in the thread (a new UI field needs the owner's approval).
- The publication activation turn stays a self-development turn at home (`host._complete_activations`): it reports her
  own change going live, not the task's result.
- Who may update or cancel a plan inside one conversation (`tool_plan` fences by conversation, not person): unchanged.
