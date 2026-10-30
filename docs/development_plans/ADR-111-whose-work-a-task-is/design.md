# ADR-111: whose work a task is, designed to the end

The README has the ask, the owner's rule and decisions, and the lead's decisions. This page has the survey with its
commands, the record and the two functions that decide it, the interfaces, the life cycle of every text and stored
field, the failure modes, the tests, the landings and the review.

Placeholders follow the test fixtures (`tests/fixtures/world.json`): people `A`, `B`, `C`, conversations `dm-a`, `g1`,
`g2`; the Web chat (the home line) is `local-dm` with its person `local-user` (the owner); an agent line is
`agent:<route>`.

## 1. Survey

### 1.1 Commands

All run on `ac620ad17d40` (2026-10-30, from the checkout root). Counts are from their output; the reviewer re-ran them
and got the same.

```bash
grep -rn "task_records.save(self.store, {'_id'" src/asuna --include=*.py          # where a new task is written: 2
grep -rn "plan_records.save(self.store, {'_id'" src/asuna --include=*.py          # where a new plan is written: 3
grep -rn "development_granted(" src/asuna --include=*.py | grep -v "def "          # 2 callers
grep -rn "event_profile(" src/asuna --include=*.py | grep -v "def "               # 6 callers
grep -rn "requester_id" src/asuna --include=*.py | grep -v "^src/asuna/records/\|catalog.py"   # 27 lines
grep -rn "offer_internal(\|offer_self_development(" src/asuna --include=*.py      # internal turns
grep -rn "ended_at" src/asuna/*.py                                                # ADR-107's end of admission
grep -rn "home_turn\|errands.carried\|_as_place\|outside_class" src/asuna --include=*.py
grep -n "workspace\|rmtree" src/asuna/privacy.py                                  # erasure deletes no task folder
python3 readers.py                                                                # below
```

`readers.py` walks `src/asuna` (outside `records/` and the catalog) with `ast` and prints, for every read of
`scene_id`, `scope_key`, `policy_epoch`, `requester_id`, `development_grant`, `integration_profile`,
`raw_input_refs` or `native_session_id` through a variable named like a row, the enclosing function:

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

Two writes make a new task row: `Coordinator.delegate` and `Coordinator.message_action` (a finished task continued,
`continues_task_id`). Everything else reaches one of them. "Runs" is §2.3's answer; "misc" is a task without `develop`.

| Path | Code | Its conversation and person today | Who asked (`whose`) and where it runs | Where the answer is in the code |
|---|---|---|---|---|
| `delegate` in a public conversation someone's line opened | `RoleTools.tool_delegate` → `Coordinator.delegate` | the turn's scene, scope, epoch; `requester_id` = the opener | `words`: the opener, or the person she names in a group (owner's decision 5); runs there | the input event's `person_id`; the turn's `people_from_program` |
| `delegate` in an agent line's turn opened by its agent or the owner | as above | that line | `words`: that person; development runs on the line, misc on the home line | the input event, `integration.agent_home_scene` |
| `delegate` in the Web chat, the owner's DM, her sister's line, a home group | as above | that conversation | `words`: the speaker; runs on the home line | the input event, `visibility.session_class` |
| `ask` with `to` 行动脑, `ideas` review `adopt` | `RoleTools.tool_ask_ask` → `delegate`; adopt leads to `delegate` | as above | the turn's | as above |
| `task` `message` on a finished task | `RoleTools.tool_task_message` → `Coordinator.message_action` | the **turn's** scene, scope, epoch and person; grants `_grants(ep)` must equal the task's | the continued task's; runs where it runs | the task row |
| a result turn (`task_feedback`) | `TaskService.feedback` opens it; she may `delegate` in it | the task's scene and requester; the development grant from the task | the task's `whose` | the input event's `task_id` |
| `consult` (the action brain asks her) | `Coordinator.consult` | the task's | the task's (no `delegate` in a consult turn) | the task row |
| an errand turn | `errands.carried(event)` at ingest; `delegate` uses `errands.home_turn` | home's (ADR-066) | the home turn's; runs on the home line | the event's `visit.from` |
| a self-development turn (offered, dice, night stage, publication) | `Chat.offer_self_development` | the Web chat, the owner | `standing`; runs on the home line, development by default | the episode kind |
| her plan firing (`scheduled`) | `Schedule._deliver_locked` → `Chat.receive` | the plan's scene and person; development in any owner-private conversation | the plan's `whose` | the event's `scheduled_plan_id` |
| a note of hers, trusted, home to home | `Schedule.note` → `offer_internal('note', …)` | the receiving conversation; its route's person; development granted | `own`; runs on the home line | the event's `note.id`, `notes.opening_for` |
| a note from outside, at home | as above | `delegate` refused (ADR-088 §4.2) | the writing turn's own place (for the plans it makes) | `notes.outside_class`, `note.from_episode` |
| a visit (her own, or a note of hers opening a group) | `Schedule.visit`, `Schedule.note` → `offer_internal('visit', …)` | the group; **the first member of the route by id** (`places.visitor`), their folder | `own`; runs in that group, in a folder of hers (owner's decision 4) | the episode kind and `visit.intent` |
| a heartbeat, the nightly settlement | `Schedule._presence`, `_settlement` | the Web chat, the owner | `own`; runs on the home line | the episode kind |

### 1.3 Every path that creates or fires a plan

| Path | Code | The conversation it stores today | This design |
|---|---|---|---|
| `plan` create | `RoleTools.tool_plan` → `Schedule.create(ep, spec, where)` | the turn's; `where` = a note's origin (ADR-088) or a peer line (`line`) | placed as misc (§2.3): the public conversation it belongs to, or the home line; `line` stays a plan of hers in that line |
| `plan` create on an errand | as above | the destination group, its visitor (ADR-066 row 1) | the home line |
| `plan` update, cancel | `Schedule.update`, `Schedule.cancel`, fenced by the turn's scene, **person** and epoch | the same row | fenced as §3.9 says (her own plans in a group apart from the visitor's) |
| rhythm plans (heartbeat, settlement, condensing) | `Schedule._rhythm_plan` via `_owner_private_target` | the Web chat, the owner | unchanged |
| self-development and night stages | `Schedule._ensure_development_plan` | the Web chat | unchanged |
| firing | `Schedule._deliver_locked` | authorizes `plan.scene_id` with `plan.person_id`, checks the epoch and the route's members, sends a `scheduled` event there; carries `integration_profile` only when it is `owner` (the 2026-10-11 rule) | unchanged where it fires; the turn's `whose` is the plan's (§2.2) |

### 1.4 How a result comes back

1. The executor finishes (`Chat._tasks` → `Executor.run` in the folder `workspace_folder(task.scene_id,
   task.requester_id)`), then `Chat.hand_back(task)` queues `{_feedback_task, scene_id: task.scene_id, person_id:
   task.requester_id}` in that conversation's queue (`SceneQueue`, keyed by scene).
2. `Chat._work` calls `TaskService.feedback`, which builds the event again on every attempt: `task.scene_id` /
   `task.requester_id`, its session `task.native_session_id` (else the handing-over turn's), its text the result
   sentence, its `trusted_context_events` the result (cleaned by `machine_words.clean` outside home), the brief, her
   thought then (`_why_then`), the original input (`raw_input_refs[0]`, read within the task's scope and epoch), the key
   tool records; `integration_profile` copied from the task. `Coordinator.ingest` stores the input (`persist_input`)
   before it prepares the turn and saves the episode after; a stored input whose text or integration profile differs
   from a rebuilt one is refused `INPUT_IDENTITY_OR_CONTENT_CONFLICT` (`ingress.py`).
3. `require_current_feedback` fences the turn: the task not cancelled, stale or paused, the same revision, the same
   scene, requester, scope and epoch, the scene's epoch unchanged.
4. The watchdog (`handover.lost`, `orphaned`, `Chat.sweep`) hands a lost result back again by cause, the same way.
5. `publish.py` finds where her words in a result turn go by walking back through `task_feedback` inputs to the first
   input (through `errands.home_turn`), and takes that input's channel, or the conversation's own route for a visit, a
   note or a plan's firing.
6. What she reads of tasks in a turn: `task_state_from_program`, from `records.tasks.recent_with_inputs(scene, scope,
   epoch)`: every task of the conversation (not by person), sorted by the newest time one of its inputs was received
   (those without one last), the open ones first, then three finished; each with `handover.status_words`, a report-pages
   note and the action brain's latest progress notes.
7. Paging: `task` `page` (`RoleTools.tool_task_page`) reads any of her tasks at home, and elsewhere only the tasks of
   the conversation it is in.

### 1.5 Who reads the task's fields, and what each assumes

| Reads the fields as | Readers | This design |
|---|---|---|
| the conversation whose data the task may read | `history_query.query_for_task`, `discussion_digest.digest_for_task`, `vision` (`read_image_for_task`, `readable_image_scenes`, `scene_attachments`, `attachment_by_ref`, `task_attachment_context`, `stored_image`, `path_image`, `picture_to_edit`, `local_upload_bytes`, `media_source_url`), `received_files.received_from`, `ToolBroker.call` (artifacts' scope), `TaskService.valid` and `stale_reason` (the epoch fence), `cancel`, `pause_for_restart`, `Executor._run_claimed` (the execution binding) | follows the place: a task moved to the home line reads the Web chat's history and pictures, not the line's |
| whose folder, class and tools | `Chat._tasks` (`workspace_folder`), `ToolBroker.bind`, `Executor._run_workspace` (grant, class, the action brain's persona and notes), `ToolBroker.call` (`allowed_capabilities`, `development_grant`, `integration_profile`, and a `workspace_grant` re-check), `NativeDevelopmentBridge.call` (`development_grant` and the owner-private class), `credentials.home_task` | the four folder reads go through one `grants.task_grant(config, task)` (§3.8); the grant fields are written from `whose` and the place (§2.4) |
| where the result is said | `Chat.hand_back`, `TaskService.feedback`, `require_current_feedback`, the watchdog, `publish.py`'s walk | follows; `publish.py` needs nothing new because a task never moves to another platform conversation |
| who may steer or stop it | `RoleTools._own_task` (same scene, `requester_id` = the turn's person, same epoch), `Coordinator.message_action` (the grants check and the PAUSED rule), `TaskService.cancel` (`person_id` = `requester_id`), `Chat.stop` | the fence compares the person each is for there (`whose.here`, §3.7); the grants check reads `whose`; the PAUSED rule changes (§3.4) |
| which list shows it | `records.tasks.recent_with_inputs` (by scene; sorted by its inputs' times), `places.elsewhere`, `self_review.block`, `queue_words`, `place_words`, `capability_refusal` | follows the place; `capability_refusal`'s "这件是%s交的" becomes "这件算%s的" |
| the session it is drawn in and its result runs in | `NativeWorker.parent_session`, `TaskService.feedback`, `message_action`, `Coordinator.consult` (also the hand-over turn's persona and `character_context`), `NativeLane` stage binding (`native_worker.py`, from the task since ADR-066) | the session of the conversation it runs in (§3.3); consult takes persona and context from that session's row (§3.5) |
| the input it answers | `Executor._run_claimed` (`raw_input_refs[0]`, **not fenced**), `TaskService.feedback` and `_short_event` (fenced), `Coordinator.consult` (fenced, raises `CONSULT_SOURCE_MISSING`), `host._recover_tasks` (two walks to the first input to decide whether to pause), `records.tasks.recent_with_inputs` (sorting), `message_action` | `raw_input_refs` keeps its meaning and is never empty; the executor's read gets the fence; consult accepts a fenced miss (§3.5) |
| the turn that handed it over | `Coordinator.consult`'s `belongs` check, `tasks._why_then`, the waiting turn, `delegation_depth` | the `belongs` check is replaced by the task's own fields; the rest stays the hand-over's record (ADR-066) |
| the grants of a turn | `grants.development_granted` (kind + class), `integration.event_profile` (the turn's input), `Coordinator._grants`, `ContextBuilder.prepare`'s capabilities block | replaced by `grants.for_whose` (§2.4) |

Plans' fields are read by `Schedule._deliver_locked` (authorize, epoch, route), `Schedule.update` and `cancel` (fenced
by scene, person and epoch), `records.plans.of_conversation` (the plans list, by the turn's person),
`RoleTools.tool_plan` (its own update and cancel lookups, by conversation), `schedule_rules.project` (the words).

### 1.6 Earlier ADRs on this ground

- **ADR-011** §6.1–6.2: the development tools go with the owner's own delegations and her self-improvement turns and
  their results; never anyone else's request. Kept and made exact (§2.4); the code had widened it to every
  owner-private turn kind.
- **ADR-066**: a task begun on an errand is home's; the errand turn stays the record of the hand-over; every reader that
  grants or authorizes goes through `errands.home_turn`. Kept; generalized by the home line. Its row 1 (a plan begun on
  an errand resolves to the destination) is changed: the home line.
- **ADR-018**: a note never grants anything; `task_feedback` inherits from its task; delegation depth stops a loop at 6.
  Kept.
- **ADR-017**: a group's task reports to that group. Kept (the owner's decision 1).
- **ADR-088**: a home turn opened by a note from outside acts with its origin's authority, and so does everything it
  creates. Kept as one row of §2.2, which stops there.
- **ADR-050**: the home lines keep home rights. Its development part is changed by the owner's decision 3; the
  hand-back cleaning by the class the report is shown in is kept.
- **ADR-075**: the tier belongs to the task and its continuations. Kept; a continuation also keeps its place.
- **ADR-107**: an admission ends as a mark on the grant; folders stay. Kept; read to say so (§3.6).
- **ADR-108 D5**: a program-woken turn shows no speaker; the authorizing person stays on the episode. Kept.
- **ADR-106**: a plan keeps the zone it was made in. The same shape: a plan keeps the `whose` it was made with.

## 2. The rule, the record and the two functions

**Work is done where it belongs, and the program decides where.** A public conversation's work runs in it, for whoever
there asked, and her own work on a visit runs there too; development asked for on an agent's line runs on that line;
everything else runs on the home line, the Web chat. The development tools go only with development work that the
owner, an agent on its own line, or her self-development asked for.

### 2.1 The record

```text
whose = {
  'by':        'words' | 'standing' | 'own',
  'scene_id':  where it was asked (or, for her own, where she was),
  'person_id': words: the person whose words asked; standing: the owner; own: the owner in the Web chat, none
               anywhere else,
  'chosen':    True when she named the person (a group's `for`) or the line (a plan's `line`),
  'version':   WHOSE_VERSION,
}
```

Kept whole on **episodes** (written in the episode's first save), **tasks** (in the task's one save: a task may run
somewhere other than where it was asked) and **plans** (from L3). The episode's own `person_id` stays the person the
turn is authorized as (ADR-108 D5), the visitor included.

Why a record and not a derivation each time (ADR-088 derived its class each time): the answer is read long after the
turn, across a chain (a result turn three steps after the first ask, a plan firing next week), and every step would
otherwise re-walk notes, plans, tasks and home turns that may be gone by then.

### 2.2 Who asked: `whose.of_turn(store, ep, event)`

One function in a new module `src/asuna/whose.py`. It reads stored rows only and calls no model, so a restarted worker
and a redelivered event compute the same answer. It runs in `Coordinator.ingest` before `ContextBuilder.prepare`, from
the event (`errands.carried(event)` for an errand, since `ep['errand']` is set only after `prepare`).

| The turn | Its `whose` |
|---|---|
| on an errand (`errands.carried(event)`) | the home turn's `whose`, when it names that home conversation; otherwise `own` there (a home turn acting for a note from outside sent it, on the owner's own line, ADR-066; it still carries the outside step, so it earns nothing) |
| `external` (a person's line) | `words`: the person whose line opened the turn, in this conversation |
| `task_feedback`, `consult` | the task's `whose` |
| `scheduled` | the plan's `whose`; a public conversation never carries one that names an owner-private conversation (an old errand plan in a group): then `own` there |
| `note` or `visit` opened by a note from outside, in an owner-private conversation (`notes.outside_class`) | the writing turn's `whose`, computed **without** the errand row (a note written on an errand acts as that conversation); an onward note's writer is itself such a turn and gives its own. Never one that names an owner-private conversation, and never for a note that is gone: then **none**, and the turn hands nothing over and plans nothing |
| `note` (trusted), `visit` (her own, or opened by a note of hers), `presence`, `settlement` | `own`, in this conversation |
| `self_development` | `standing`, in the Web chat |
| any kind added later | `own`, in this conversation (no grant until a decision gives one) |

Inheritance never crosses a less trusted step: an outside note stops it (its turn takes the writer's own place, never
what the writer carried, never a home conversation), and an errand carries home only what lives at home. A walk through
stored rows (an old row, §2.6) stops after eight steps, and a turn it needs that is missing or erased (an erasure keeps
none of a turn's inputs, `records/view.py` `REDACTION_KEEPS`) answers `own` there, earning nothing.

### 2.3 Where it runs: `whose.place(store, whose, develop)`

The second function, the only place that decides where a task runs and for whom there.

| `whose` | `develop` | Runs in | `requester_id` (authorizes its turns) | Folder | For (`whose.here`, §3.7) |
|---|---|---|---|---|---|
| `words`, in a public conversation (a group, someone else's DM) | — (cannot be earned) | that conversation | the asker | the asker's (`workspace_grant`) | the asker |
| `own`, in a public conversation (her visit; a turn her own plan there opens) | — | that conversation | the person its turns are authorized as (the visitor) | hers there (§3.8) | none |
| `words` on an agent line (its agent, or the owner joining it) | true | that line | the asker | `workspace_grant(line, asker)`, as today | the asker |
| anything else: misc on an agent line, everything in the Web chat, the owner's DM, her sister's line, a home group; `standing`; her own work in any owner-private conversation | any | **the home line, the Web chat** | the owner | home's | the owner |
| none (§2.2) | — | nowhere: the turn hands nothing over | | | |

A **plan** is placed as misc (`develop` false): in the public conversation of its `whose`, or on the home line. The
agent line hosts no new plans. A plan she made with `line` stays a plan of hers in that peer line (the owner,
2026-10-06): it is a time to speak there, not work. A task begun in that plan's turn is placed by the table.

### 2.4 Grants: `grants.for_whose(store, whose, place, develop)`

One function replaces `development_granted` and the event's integration profile wherever a task's grants are decided:
`Coordinator._grants` (a new task, a continuation), `message_action`'s check, and the capabilities block of her turn.

| Grant | Given when |
|---|---|
| development tools (`development_*`, `persona_job*`) | `earns_development(whose)` and (`develop` or `whose.by == 'standing'`), self-development enabled, the sandbox available |
| integration profile | the same condition; then `owner` when `owner_profile(scene, person)` holds, `agent_home` for an agent's own task on its line, `owner` for `standing` when the Web chat is the integration's binding (as `Chat.offer_self_development` decides today); else none |
| `sandbox_run`, stored credentials | the conversation it runs in is owner-private for its requester (`visibility.session_class`) |
| the folder | §2.3 |
| everything else (workspace tools, pictures, SVG, her word list) | as today |

`earns_development(whose)`: `standing`; `words` where the person is the owner (canonical, `scene_links`) in an
owner-private conversation; `words` on an agent line by that line's own agent. Nothing else (owner's decision 3).

A task's grants are written on it when it is made and never recomputed: every runtime reader keeps reading the stored
fields. A continuation runs where its task runs, with its task's grants.

### 2.5 Her two choices

- **`develop`** (true when the work changes or runs her own machinery: code, skills, packages, adapters). It is the one
  thing the rule needs that only she knows. Shown in owner-private conversations; refused `DEVELOP_NOT_HERE` where the
  turn's `whose` does not earn it; in a self-development turn (`standing`) a task counts as marked. On an agent line it
  also decides where the task runs: marked, on the line; not, on the home line.
- **`for`, in a group** (the owner's decision 5): the label of another person whose line is in this turn
  (`people_from_program`); the task becomes theirs (`words`, `chosen`). Without it, the opener's. A label not in the
  turn is refused `FOR_UNKNOWN` with the list. Only a turn someone's line opened has `people_from_program`, so on a
  visit, an errand or a result turn every label is refused.

### 2.6 Old records

There is no history conversion (docs/DEVELOPMENT.md). Nothing rewrites a stored task, plan or episode; an old task
stays where it is and runs out there; what is begun from it is placed by §2.3.

- A **task** without `whose` reads it from `of_turn` of the turn that made it (`task.episode_id`; episodes are kept),
  with the person none when that is `own` outside the Web chat. A task without `develop` (every task written before L2,
  L1's included) reads it as its stored `development_grant`. A new task inheriting from an old one gets at most the
  development and integration grants the old one stored; its audit row says `inherited: unrecorded`.
- A **plan** without `whose` reads it from `of_turn` of `plan.source_episode_id`, by §2.2's `scheduled` row: an
  errand's old plan keeps firing in its destination as her own there, a visit's old plan as her own in that group, an
  old agent-line plan on that line. Its stored `integration_profile` still goes on its event.
- An **episode** without `whose` (a turn in flight across the install) gets it from `of_turn` when it is read.

## 3. Interfaces

### 3.1 `src/asuna/whose.py` (new)

- `of_turn(store, ep, event) -> whose | None`: §2.2. `of(store, ep)`: `ep['whose']`, else `of_turn`.
  `of_task(store, task)`, `of_plan(store, plan)`: the stored record, else §2.6's reading.
- `place(store, whose, develop) -> {scene_id, scope_key, policy_epoch, requester_id, folder, here} | None`: §2.3.
- `here(store, whose, scene_id) -> person id | None`: the person a task or turn is for in that conversation: the asker
  in a public conversation or on an agent line, none for her own there, the owner on the home line.
- `standing(store, whose) -> 'here' | 'left' | 'blocked' | 'closed'`: `left` when the person's grant on the group's
  route carries ADR-107's `ended_at`, `blocked` when the channel lists them in `blocked_senders` or her block switch
  holds them (`switches.blocked`), `closed` when the conversation is a line she has closed (`lines.is_closed`). Read
  when a turn is prepared, never stored.
- The words (versioned, `WHOSE_VERSION = 1`; a change to any of them bumps it), all addressing her as 你:

```python
TASK = {'words': '这件是%s托你的', 'standing': '这件是你自我改进时交的', 'own': '这件是你自己的事'}
PLAN = {'words': '这条计划为的是%s托你的事', 'standing': '这条计划是你自我改进时定的', 'own': '这条计划是你自己的事'}
RESULT_HERE = '结果回到这里'
RESULT_HOME = '结果回家里，这边的上下文不跟过去'
LINE_DEV_ONLY = '这条线只做它托的开发'
HANDED = '是你在%s交出去的'
STANDING = {'left': '（%s已经离开这个群了）', 'blocked': '（%s在这里被屏蔽了）', 'closed': '（这条线你关着）'}
BRIEF_ONLY = '新开一份上下文：它只看得到这次的 brief。'
PLAN_HOME = '建在家里：到点在家里跑。'
DEVELOP_NOT_HERE = 'develop 只给主人或 agent 在自己的线上托的事、或自我改进时交的事；这一回合不是，去掉 develop 再交。'
FOR_UNKNOWN = '「%s」不是这一回合里的人：for 照抄 people_from_program 里的标签，或者不写（就是叫起这一回合的那位）。'
```

  `%s` is the person's label as she reads it in that conversation (`People.speaker`), or the place's title
  (`People.scene_title`); never an id. The two refusals are `Refused` with their codes kept in the record (ADR-108
  D4b) and shown as written.

### 3.2 Episodes

`Coordinator.ingest` computes `whose.of_turn` once, before `ContextBuilder.prepare` (which is given it, and computes it
itself when called without, as `recall` calls it), and writes it on the episode in the same save, for both the gated
(`ATTENDING`) and the prepared episode. `Coordinator.consult` writes the task's on the consult episode;
`Coordinator._attend` passes the stored one to `prepare`.

### 3.3 `Coordinator.delegate`

```text
whose  = whose.of(store, ep); none → refused with ADR-088's words (OUTSIDE_NEEDS_HOME), as today
         a group label in `for` → words(that person, here, chosen), FOR_UNKNOWN when not in the turn
refuse DEVELOP_NOT_HERE when develop and not earns_development(whose)
place  = whose.place(store, whose, develop)
scene  = scene_records.authorize(place.scene_id, place.requester_id)
development, integration, names = grants.for_whose(store, whose, place, develop)
session = the turn's own when the task runs in the turn's conversation (home's live one for an errand or a reflection,
          as `_task_session` does today); otherwise the session the resolver gives that conversation's own turn
raw    = ['in-' + the authority turn] as today (never empty: `host._recover_tasks`, `feedback` and the task list's sort
          need it); for a person she named in a group, that person's newest line this turn had in view
task   = {... as today ..., scene_id/scope_key/policy_epoch/requester_id from place, whose, develop (when true),
          development_grant, integration_profile, allowed_capabilities, native_session_id}
audit  'task.whose' {by, chosen, develop, development_grant, integration_profile, the class and kind of the conversation
          it runs in and of the turn's, inherited: 'unrecorded' when §2.6 applied}
```

The task is written in one save; the episode's `task_ids` update after it stays as it is (a resumed turn merges
`task_records.of_episode`, `Coordinator._run_turn`).

The `delegate` result gains `for`: `TASK[by]` (with the label), then `LINE_DEV_ONLY` when misc leaves an agent line,
then `RESULT_HERE` or `RESULT_HOME`; its `action_brain` reads `BRIEF_ONLY` when the input lies outside the task's
conversation; its `note` keeps `HOME_TASK` on an errand and `REFLECTION_TASK` in a reflection.

The spec (`role_tools.TOOLS['delegate']`): the description gains
`在哪儿做由程序定：群里托的在群里，agent 线只做它托的开发，别的都回家里；交出时会说。`; `develop` (boolean,
`要它动你自己（代码、技能、包、适配器）时写 true；只有主人、agent 在自己的线上托的、或自我改进时才有。在 agent 线上不写，这件就回家里做`)
in owner-private conversations; `for` (`这件是谁托的：不写＝叫起这一回合的那位；是这回合里另一个人托的，照抄 people_from_program 里 ta 的标签`)
in public groups; each placed by `placed_spec` (ADR-087 §4.3).

### 3.4 Continuations

`Coordinator.message_action` (a finished task continued): the new row runs where the task runs (its scene, scope,
requester), keeps its `whose` and `develop`, and gets `for_whose(task.whose, task's place, task.develop)`, never the
turn's grants. The turn may continue it when `_own_task` found it (§3.7) and the turn reaches the task's grants: a task
with the development grant takes words only from a turn whose `whose` earns it, one with an integration profile only
from a turn whose `whose` would get the same profile. Today's reverse refusal (an owner's turn may not add words to a
narrow task) goes, because a continuation no longer takes the turn's grants. A `PAUSED` task continues on an
`external` turn whose `whose.here` there is the task's: on the home line the owner, as today; on an agent line its agent
(today it never can, since only the owner in the Web chat may, and `task` finds only the turn's own conversation's
tasks).

### 3.5 Consult and the executor

- `Coordinator.consult`: the `belongs` equality goes; the consult is authorized by the task's own fields, runs in the
  task's session and takes its persona and `character_context` from that session's row (as the stage binding in
  `native_worker.py` does); an input outside the task's conversation gives `original_input: null` instead of
  `CONSULT_SOURCE_MISSING`.
- `Executor._run_claimed`: the input is read within the task's scope and epoch, as `feedback` and `consult` read it.
  A task's input is then never a line of another conversation in anything a model reads.

### 3.6 The result turn and the capabilities block

- The words are not put into the stored event: `feedback` rebuilds the event on every attempt and `ingress.py` refuses
  a stored input whose text differs, so a word that changes (a departure, the install itself) would fail every full
  hand-back. `ContextBuilder.prepare` adds them, when the turn is prepared (once per episode; a resumed turn reuses its
  stored context): the result item of a `task_feedback` turn (and of the short hand-back) gains `for`: `TASK[by]`,
  `HANDED` when the task was handed over in another conversation, `STANDING[...]` when the person can no longer be
  reached. The stored event, its text and its `integration_profile` stay byte for byte as today.
- A result whose conversation no longer exists is suppressed, like one whose epoch changed (today `feedback` fails on
  the missing scene).
- `action_capabilities_from_program`: `development` present when `earns_development(whose)`, with
  `要它动你自己，delegate 写 develop。`; `integration` from `whose`; `delivery` reads
  `程序自动执行委托，结果作为独立事件回到这件事做的地方（交出时会说在哪）；等待时仍可聊天。`.
- `capability_refusal` (the action brain's): the development line of `GIVEN_TO` reads
  `只给交的时候写了 develop 的任务：主人或 agent 在自己的线上托的、或自我改进时交的（自我开发要开着）`, and the place
  phrase reads `这件算%s的`.

### 3.7 Steering: the same fence, with the person the work is for there

`_own_task` keeps its fence (same conversation, same person, same epoch) and compares `whose.here` of the task with
that of the turn instead of the task's `requester_id` with the episode's `person_id`; `task` `stop` passes the same to
`TaskService.cancel`. On the home line both are the owner, so every home turn steers every home task, as today. On an
agent line the agent steers its own tasks; her own note's turn there steers none. In a group a member steers their own
tasks, and her own turns there (a visit, her plan's firing, her task's result) steer hers; her visit no longer steers
the first member's tasks, and every member's task answers `OTHERS_TASK` with the member who really asked.

### 3.8 Her folder in a group, and one folder rule

`grants.task_grant(config, task)` is the one answer to "which folder and read-only paths": for a task of hers in a
public conversation (`whose.by == 'own'` there), `grants.her_folder(config, scene_id)`; otherwise
`workspace_grant(task.scene_id, task.requester_id)`, as today. `Chat._tasks`, `ToolBroker.bind`,
`Executor._run_workspace` and `ToolBroker.call`'s re-check read it. Her folder is
`<data>/channels/her-<first 32 hex of sha(scene id)>`, checked against the other channel folders like a member's
(`host._checked_workspace`), made on first need (`grants.workspace_folder`), and kept like a member's folder: erasure
deletes no task folder (`privacy.py`), and a folder stays when an admission ends (ADR-107).

### 3.9 Plans (L3)

- **The catalog** declares `whose` (a nullable object: rhythm plans have none) and `whose.by` (text) for `plans`,
  since only declared fields may be named in a condition (`store/catalog.py`).
- `Schedule.create`: the target is `whose.place(whose, develop=False)` (an errand turn's is the home line; an
  outside-note turn's is the writing turn's own place, which `RoleTools._as_place` gives today; a turn with none plans
  nothing); `line` makes it `{by: own, scene_id: the line, chosen: True}` in that line. The row carries `whose`; its
  `person_id` is the place's `requester_id`. It no longer writes `integration_profile`. `RoleTools.tool_plan` stops
  computing `where` for outside notes; when the plan is placed on the home line from another conversation its result
  says `PLAN_HOME`.
- `Schedule.update` and `cancel` keep their fence by scene, person and epoch, and in a public conversation add the same
  split as the list: her own turns there change only her own plans (`whose.by` `own`), a member's turns only theirs.
  `tool_plan`'s `there` (the scene, person and epoch the fences use) is taken from the plan whenever the plan's scene is
  not the turn's (a plan an errand turn just made at home, one an outside-note turn made in the origin). A plan made
  again after it fired (`PLAN_MOVED_FIRED`) carries the old plan's `whose`.
- `Schedule._deliver_locked` is unchanged; the scheduled turn's `whose` is the plan's (§2.2), and `prepare` adds `for`:
  `PLAN[by]` and `STANDING[...]` to the plan block it builds for a `scheduled` turn. A firing that fails is recorded as
  today and never moved.
- The plans list (`records.plans.of_conversation`): by the turn's person as today; in a public conversation, her own
  turns list the plans whose `whose.by` is `own`, and a member's turns that member's plans that are not (an old plan,
  without `whose`, counts as not). On the home line every plan's person is the owner, so the list is what it is today.
  The view states `Exists` on `whose` for the new rows, so the None rule (`records/view.py`) cannot match an old row by
  a missing field; the contract already covers nested `Exists` (`integration/store_contract.py` W17), and the view gets
  its unit test.

## 4. Life cycles

### 4.1 Every text she reads about a task or a plan

Brains: CB the character brain, AB the action brain, RG the relevance gate (which reads none of these).

| Text | Created | Used | Updated | Discarded | Survives |
|---|---|---|---|---|---|
| `delegate` description (+45 characters) | `role_tools.TOOLS` at import; placed per conversation (`placed_spec`) | CB, in the tool list of every request in every conversation that lists `delegate` | by a release only | never while the tool exists | worker and Host restart (code); compaction (tools are not compacted); a retired one-shot session (the next has the same list); redelivery (not an event) |
| `delegate` `develop` (owner-private conversations), `for` (public groups) | as above | as above | by a release | as above | as above |
| `task` description | unchanged | | | | |
| `delegate` result `for` (about 15–46 characters, with the label) and `BRIEF_ONLY` (23, only when the input is elsewhere) | `RoleTools.tool_delegate`, from the stored task | CB, the turn that delegated | never | when the session's history is compacted (the summary keeps what she kept) | restart: the tool call's recorded result is replayed, not recomputed; redelivery: the same task id gives the same words; a retired one-shot session: the result turn says it again |
| `task_state_from_program` | unchanged: it lists the tasks that run in this conversation | CB, every turn with tasks | | | |
| the result item's `for` in a result turn (10–40 characters) | `ContextBuilder.prepare`, when the `task_feedback` turn is prepared, from the task's `whose`, the person's label and `standing` then; kept in the episode's stored context, never in the event | CB, that turn (one per result; the short one too) | never: a resumed turn reuses its stored context | with the turn's history at compaction | restart: the stored context is reused; redelivery: the stored event is unchanged, so the identity check passes; compaction: kept in the summary as she kept it |
| a plan block's `for` in a plan's firing (10–25 characters) | `ContextBuilder.prepare`, in the plan block it builds for a `scheduled` turn, from the plan's `whose` and `standing` | CB, the `scheduled` turn | never, as above | as above | as above; a plan made before L3 reads §2.6's answer |
| the stored result text, the stored plan text, the visit's text | unchanged byte for byte | | | | |
| `DEVELOP_NOT_HERE` (61), `FOR_UNKNOWN` (64 + the label) | the refusals of `develop` where it is not earned, and of a label not in the turn | CB, only when she tries | by a release | with the tool result | as any tool result |
| `action_capabilities_from_program` `delivery` (+12), `development` (+26 where earned) | `ContextBuilder.prepare` each turn, from the turn's `whose` | CB, every turn where `delegate` is available; sent whole only when its content changed, otherwise named unchanged (`context-delivery.js`) | when the turn's `whose` earns differently from the last (an owner's turn and a heartbeat at home), as the development key does today | replaced by the next turn's | rebuilt every turn |
| `capability_refusal` (the development line, 57; `这件算%s的`) | the broker's refusal of a tool the task was not given | AB, only on that refusal | by a release | with the tool result | as any tool result |
| `PLAN_HOME` (12) | `tool_plan`'s result when the plan is placed on the home line from another conversation (L3) | CB, that turn | by a release | with the tool result | as any tool result |
| `errands.HOME_TASK`, `REFLECTION_TASK`, `wake_words.WAKE_WORDS`, `NOT_NOW['delegate']` | unchanged | | | | |

### 4.2 Every stored field this adds or changes

| Field | Created | Used | Updated | Discarded | Survives restart and compaction |
|---|---|---|---|---|---|
| `episodes.whose` | `Coordinator.ingest` and `consult`, in the episode's first save | `delegate`, `message_action`, `Schedule.create`, `prepare`, the steering fence | never; a resumed turn keeps it | with the episode (kept; erasure redacts per scope, ADR-105) | yes; a session compaction does not touch episodes |
| `tasks.whose`, `tasks.develop` | `delegate`, `message_action`, in the task's one save | `of_turn` for its result turn and its consults, its continuations, the steering fence, the words | never | with the task (kept; erased per scope) | yes |
| `plans.whose` (from L3) | `Schedule.create`, in the plan's first save; rhythm plans have none | `of_turn` at its firing, the plans list and the fences | never: update keeps it (as it keeps the zone, ADR-106); a plan made again after it fired copies it | with the plan (FIRED and CANCELLED rows stay) | yes |
| her folder in a group | `grants.workspace_folder`, when a task of hers there first needs it | her tasks in that group | by her tasks | as a member's folder: not by erasure, not when an admission ends | yes (a folder on disk) |
| audit `task.whose` | with the task's save | structure counts (the landings' checks) | never | after 30 days (ADR-074) | yes |
| `plans.integration_profile` | no longer written; old rows keep it and their events carry it | | | | |

## 5. Failure modes

| Case | She sees | The person sees | The program records |
|---|---|---|---|
| She forgets `develop` on development work an agent asked for | the task goes to the home line (`这条线只做它托的开发` in the `delegate` result); the action brain is refused `CAPABILITY_DENIED`, says so, and the report comes home; from that result turn she hands it over again with `develop`, and it goes back to the agent's line (the result turn carries the agent's `whose`) | the agent waits one round | the refusal, two tasks |
| `develop` where it is not earned | `DEVELOP_NOT_HERE` at the call | — | the refusal and its code |
| An agent asks for misc work on its line | the task runs on the home line; its result turn there says `是你在…交出去的`; whether to tell the agent is hers | nothing on the line until she says something there | the task at home, the asker in `whose` |
| The owner asks in his platform DM | the task runs on the home line and reports there (owner's decision 2) | the result in the Web chat | the task at home |
| The conversation of `whose` ends, or the person's admission ends (an ADR-107 departure) | the result turn still runs there, its result item saying `（A已经离开这个群了）`; she decides whether to say anything; a plan's firing says the same | nothing: they are not there | the task and plan unchanged; the folder kept |
| The person is blocked (her switch, or the channel's list) | the same, `（A在这里被屏蔽了）`; under the channel's block the task's next tool calls are refused `WORKSPACE_NOT_AUTHORIZED` and its report says so | what she chooses to say | the refusals |
| The person is admitted again, or is unknown | the mark is gone, so the words are; an unknown author has the label `People.speaker` gives | — | — |
| A plan fires after its conversation is gone (no scene, the route revoked, the epoch changed) | nothing: there is no conversation to read it in | nothing | the outcome on the plan, as today; never moved |
| A group she left or that was disbanded | a result said there fails at the adapter and shows as undelivered | nothing | a failed delivery (not in this ADR) |
| The work serves two conversations | one task, one place; the `delegate` result says where its result goes, so the second is her own act (an errand, a note) | each sees what she says there | the task, and the errand or note |
| She names the wrong person in a group, or none when B asked | the `delegate` result says whose it went to | the right person can't follow it up | `chosen` in the audit; correctable with a new task |
| A crash between the task's write and the episode's update | on resume the task is listed as already handed over (`_run_turn` merges `of_episode`, as today) | — | the task row |
| The same event delivered twice | one turn: the episode id comes from the event id, and the existing episode returns with the `whose` it stored; a rebuilt result or plan event is byte for byte the stored one | — | `ingress.deduped` |
| A restart while a task runs, or while its result waits | running: paused, then continued on its person's words where it runs (§3.4); waiting: the watchdog hands it back where it runs | — | the pause; the hand-back |
| Compaction of the session that held the hand-over | the result turn carries the title, the brief, her thought then, whose it is and the report | — | — |
| An agent line she closed while its work is in flight | its development tasks' result turns still run there (a closed line passes over the agent's messages, not her own work), saying `（这条线你关着）`; her words go out if she speaks | her words, if any | unchanged |
| An errand from home | the task is home's (ADR-066); a plan made there is the home line's, `PLAN_HOME` | the destination sees what she said | `whose` = the home turn's |
| A note written on an errand, read at home | its turn acts as the errand's conversation (`own` there), never as home's: its plans live there and earn nothing | — | `whose` own there |
| A note from outside sent on into a home group, or one that is gone | its turn acts for no one: it hands nothing over and plans nothing | — | `whose` none |
| Her visit | as today: the task runs in that group, now in her own folder and steered only by her own turns there; a plan made there is hers there | what she says there | `whose` own |
| A result that mentions another conversation's content | a task reads only the conversation it runs in (history, digest, pictures and files are fenced by its fields; its input is read within it); a misc task from an agent line runs on the home line, both home; her brief is her own words, like a note; a development task reads the whole database, and only the owner's, an agent's on its own line or her self-development work gets it, so its report is read on a home line; outside home the report is cleaned (ADR-050) | — | — |
| A task that would get more than its asker earns | a public asker's task runs in their conversation with its limits; `for` names only a person in the same turn; inheritance keeps the same `whose` or stops at an outside note; a task's grants are its `whose`'s and its place's, never the turn's | — | — |

**Quiet wrong answers today, each made visible or removed:**

1. Misc work done on a line just because the line had the development grant. Removed: the place is the program's.
2. The development grant on work that is not development (the writing task above). Removed by the mark; a missing
   mark is a loud refusal.
3. A visit's task in the first member's folder, steerable by them, with `OTHERS_TASK` telling her they asked; her visit
   steering that member's tasks. Removed: her folder, the `here` fence.
4. Plans made on a visit listed in and changeable by that member's turns, and the member's on her visits. Removed: the
   split in public conversations.
5. B's request answered in A's turn recorded as A's. Correctable with `for`, visible in the `delegate` result.
6. A result handed to someone who left or was blocked, read as if they were there. Visible: the standing words.
7. A chain begun before the install carrying its old answer. Bounded by the old grants, visible in the audit, counted
   at L1.

## 6. Tests

Only those that guard a fence or a failure that would be silent and costly. All unit tests run on the in-memory adapter
(`world` and `store` in `tests/conftest.py`); none reaches a server.

| Test (new module `tests/test_whose.py` unless named) | Guards |
|---|---|
| `test_whose_by_turn_kind`: every row of §2.2, including an errand, an outside note, an outside note written on an errand, an onward outside note into a home group, an errand sent from an outside-note turn, a gone note, an erased turn, a trusted note, a visit, a plan and a task made before the install | the record: a wrong row is a wrong grant or a wrong place, silently |
| `test_where_a_task_runs`: every row of §2.3: a group member's ask; her visit; the agent's development and misc on its line; the owner joining the line; the owner in the Web chat, in his DM, in a home group; her sister's line; a heartbeat; self-development; none | the owner's rule |
| `test_development_only_where_whose_earns_it_and_she_marked_it`: the earners and non-earners of §2.4, `develop` on and off, `standing`; an old task's continuation capped at its stored grant | the authorization fence |
| `test_misc_from_a_line_runs_home`: a misc task from an agent-line turn has the Web chat's scene, scope, epoch, person, folder and session (a stub resolver); its result is queued there; the executor's, the hand-back's and the consult's reads of its input give nothing of the line; a development task from the same turn stays on the line | privacy across conversations and the routing |
| `test_a_result_turn_hands_its_whose_on`: a result turn delegates again and the new task has the first one's `whose`, place and grants; a forgotten `develop` corrected from the home result turn goes back to the line | the chain |
| `test_her_visit_works_in_her_own_folder`: a visit's task runs in `her_folder`, not the visitor's; on the visit `task` `stop` of a member's task answers `OTHERS_TASK`; a member cannot steer her task | the placeholder never owns or steers |
| `test_a_group_task_is_the_person_she_names`: `for` with a label in the turn gives that person's folder, steering and their own line as the input; a label not in the turn is refused | the person boundary inside a group |
| `test_a_plan_is_placed_as_misc` (L3): from an errand, on the home line; from an agent line, on the home line; from an outside note, at the origin; with `line`, in the line; its firing's turn has the plan's `whose`; in a group, her own plans and a member's are listed and changed apart; an old errand plan fires in its destination as her own | follow-up plans, the list, the fences, old plans |
| `records.plans` view (L3, beside `tests/test_store_contract.py`): new rows by `whose.by`, old rows by `person_id`, never an old row through a missing field | the None rule |

Changed: `tests/test_specs_by_place.py` (`develop` in owner-private conversations, `for` in public groups),
`tests/test_home_groups.py` (a home group's other member earns no development, and work handed over there runs on the
home line).

No new static check. No new integration test: no index and no adapter promise is added, and the nested `Exists` the
plans view uses is already in `integration/store_contract.py`. `pytest integration` runs at every landing.

## 7. Landings, in order

Each landing: targeted tests while building, then the full suite, `pytest integration`, the personal-data scan
(`tools/check_staged_secrets.py --personal --all`), the push gate, a fast-forward, the planned restart while she is
idle, a check that the running code is the commit's (`loaded.commit`), one report to the owner. Nothing reaches a real
model endpoint in any test. **No message to her about this ADR until L3 is installed and checked (the owner's rule);
then one message, and her reading of the whole page.**

**L1: record `whose`, change nothing she reads or can do.** `whose.py` (both functions and the table, its words
unused); `episodes.whose` and `tasks.whose` written; for a plan only the audit records the `whose` it would get (a plan
that recorded home's `whose` while it still lived in a group would hand home's authority to that group's turn once L2
reads it). Task and plan fields stay exactly as today. Tests: the first two. *On the real system,* after install, by
structure only (no content), for two days or 100 new tasks, whichever comes first: tasks and plans by turn kind,
`whose.by`, the kind and class of the conversation `whose` names and of the one §2.3 would place it in; how many tasks
L2 would move to the home line, from which kind of conversation; how many would lose the development grant; how many
visit tasks there are; how many chains begun before the install are still open. This is also the trace of the owner's
"random group" case: every group task whose `whose` is not a person there.

**L2: tasks follow the rule.** §2.3 to §2.5, §3.3 to §3.8. Tests: all but the two plan tests. *On the real system,*
two days by structure: no misc task on an agent line, her sister's line, the owner's DM or a home group (all on the home
line); the development grant only where `whose` earns it and `develop` was given (or `standing`); visit tasks in her
folders; no model-facing read of an input outside its task's conversation (the executor's facts, the result items);
agent-line tasks a day and their development rate, beside the lead's numbers for 10-27 and 10-28 (for the owner's
reading, not a gate).

**L3: plans follow the rule.** §3.9. Tests: the two plan tests. *On the real system:* plans by `whose.by` and by the
kind of conversation they fire in; none new on an agent line; every plan made on an errand on the home line; in a
sample of group turns, the plans their context listed against those plans' `whose`.

## 8. What she carries

- **Every turn:** nothing new in her context. `action_capabilities_from_program` grows by 12 characters (`delivery`)
  and, where earned, 26 (`development`); the block is sent whole only when it changes.
- **Every request (the tool list, a cached prefix):** `delegate` grows by 45 characters in someone else's chat, by
  109 more in a public group (`for`) and by 127 more in owner-private conversations (`develop`), as JSON. Measured with
  the drafted texts on `ac620ad17d40`: 363 → 408, 517 and 535 characters.
- **Per event:** about 15–46 characters in each `delegate` result (with the label); 10–40 in each result turn's item;
  10–25 in each plan's firing.
- **Only on a mistake:** `DEVELOP_NOT_HERE` (61), `FOR_UNKNOWN` (64 and the label); for the action brain, the
  development line (57).

## 9. Not in this design

- A group she has left has no state; giving it one is its own ADR (ADR-107 has no rule for it).
- A fair task queue across conversations (ADR-050).
- A Web view of where a task runs (a new UI field needs the owner's approval).
- The publication activation turn stays a self-development turn at home (`host._complete_activations`).
- A repeating plan that keeps failing to fire records its outcome at every occurrence, as today.

## 10. The review

### 10.1 The first draft (`d7e7decd7126`), 14 findings

The reviewer re-ran the survey's counts and got the same. Each finding was checked against the code before it was
taken.

| # | Finding | Severity | Done |
|---|---|---|---|
| 1 | The errand row and the outside-note row combined: a note written home on an errand inherited home's authority back into home; an errand sent from an outside-note turn landed its task in the origin group | blocker | Inheritance stops at an outside note (the writing turn's own place, without the errand row); an errand carries home's `whose` only when it lives at home (§2.2) |
| 2 | An empty `raw_input_refs` crashes `feedback`, `_short_event` and the recovery walk, and drops the task from the list's sort | blocker | `raw_input_refs` keeps its meaning and is never empty; every model-facing read is fenced instead; `BRIEF_ONLY` (§3.3, §3.5) |
| 3 | The result and plan texts change between rebuilds and break `ingress.py`'s identity check | major | Also found by the lead: the words are added at preparation; the stored event is unchanged (§3.6) |
| 4 | `own` on home lines kept the placeholder and broke in home groups | major | Her own work in owner-private conversations runs on the home line (§2.3) |
| 5 | Reading old records as `words` widened grants and kept the visit placeholder; L1 tasks would lose their grant on continuation | major | Old rows read `whose` from the turn that made them; a missing `develop` is the stored grant; nothing inherits more (§2.6) |
| 6 | Plans recorded at L1 but still living in a group would hand home's authority to that group's turn | major | L1 writes no `plans.whose`; a public conversation never carries a home `whose` (§2.2, §7) |
| 7 | Plan update and cancel fenced by the placeholder; `there` and moved plans ignored the plan's `whose` | major | §3.9 |
| 8 | The plans-list query named an undeclared field; a None fence finds nothing | major | Catalog entries; the view with `Exists`; its unit test (§3.9, §6) |
| 9 | "Suspended once" does not hold and is not needed | major | Dropped (§9) |
| 10 | The `external` row records who opened the turn, not who asked | major | Said as the opener; `for` in groups (owner's decision 5) |
| 11 | The crash gap is already closed (`_run_turn` merges `of_episode`) | minor | Dropped; the failure row cites the merge |
| 12 | Consult took the hand-over turn's persona and context | minor | From the task's session row (§3.5) |
| 13 | Duplicate state on tasks; `STANDING` stored; `chosen` only for the audit | minor | Standing read at preparation. Tasks again keep the whole `whose`, since a task can now run somewhere other than where it was asked |
| 14 | Wording and counts (eight items) | minor | Corrected |

### 10.2 The re-check of the fixes (`affd95133a06`), 8 items

| | Item | Done |
|---|---|---|
| A | An outside note sent on into a home group fell back to `own` at home | The outside row never names a home conversation; with nothing left, the turn has no `whose` (§2.2) |
| B | An errand turn could not change the home plan it made; her own group plans could not be found by the fences | `there` from the plan's scene; the public-conversation split in the fences (§3.9) |
| C | `own` on a line had the line's speaker as its person | `own` has a person only in the Web chat (§2.1) |
| D | A task L1 recorded for a visit or a line kept the placeholder in its result turn | The old-row reading gives no person to `own` outside the Web chat (§2.6) |
| E | An erased turn has none of the inputs `of_turn` needs | `own` there, earning nothing (§2.2) |
| F | `IsNull` matches only a stored null; rhythm plans have no `whose` | The view keys on `whose.by` with `Exists`; `whose` declared nullable (§3.9) |
| G | A task she names for B kept A's line as its input | B's newest line in the turn (§3.3) |
| H | The result item's words were said to be recomputed at each preparation | Computed once, kept in the episode's context (§3.6, §4.1) |

### 10.3 The redesign to the owner's rule (`see the commit that adds this line`)

To be filled with the same reviewer's reading of this version.
