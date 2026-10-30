# ADR-111: whose work a task is, designed to the end

The README has the ask, the owner's rule and answers, the decisions and the defects found. This page has the survey
with its commands, the record and how it is decided, the interfaces, the life cycle of every text and stored field,
the failure modes, the defects with their evidence, the tests, the landings and the review.

**In scope:** whose work a task is, recorded once and followed by its grants, its result turn, its follow-up plans and
what she reads; requests from outside default to the home line, the Web chat. Everything else works as it does today.

Placeholders follow the test fixtures (`tests/fixtures/world.json`): people `A`, `B`, `C`, conversations `dm-a`, `g1`,
`g2`; the Web chat is `local-dm` with its person `local-user` (the owner); an agent line is `agent:<route>`.

## 1. Survey

### 1.1 Commands

All run on `ac620ad17d40` (2026-10-30, from the checkout root); the reviewer re-ran them and got the same. `main` moved
on to `99a69f3` the same day; `git diff --stat ac620ad 99a69f3 -- src packages` touches sticker and face wording only,
none of the paths below.

```bash
grep -rn "task_records.save(self.store, {'_id'" src/asuna --include=*.py          # where a new task is written: 2
grep -rn "plan_records.save(self.store, {'_id'" src/asuna --include=*.py          # where a new plan is written: 3
grep -rn "development_granted(" src/asuna --include=*.py | grep -v "def "          # 2 callers
grep -rn "event_profile(" src/asuna --include=*.py | grep -v "def "               # 6 callers
grep -rn "requester_id" src/asuna --include=*.py | grep -v "^src/asuna/records/\|catalog.py"   # 27 lines
grep -rn "offer_internal(\|offer_self_development(" src/asuna --include=*.py      # internal turns
grep -n "def targets" -A20 src/asuna/notes.py                                     # where a note may go
grep -rn "home_turn\|errands.carried\|_as_place\|outside_class" src/asuna --include=*.py
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

### 1.2 Every path that creates a task

Two writes make a new task row: `Coordinator.delegate` and `Coordinator.message_action` (a finished task continued).
Everything else reaches one of them.

| Path | Code | Its conversation and person today | Whose it is (this design) |
|---|---|---|---|
| `delegate` in a turn someone's line opened | `RoleTools.tool_delegate` → `Coordinator.delegate` | the turn's; the opener | `words`: the opener; in a group she may name another person in the turn; at home she may name the outside place the work is for |
| `ask` with `to` 行动脑; `ideas` review `adopt` | `RoleTools.tool_ask_ask` → `delegate`; adopt leads to `delegate` | as above | the turn's |
| `task` `message` on a finished task | `RoleTools.tool_task_message` → `Coordinator.message_action` | the turn's; its grants must equal the task's | the continued task's |
| a result turn (`task_feedback`) | `TaskService.feedback` opens it; she may `delegate` in it | the task's; the development grant from the task | the task's |
| `consult` | `Coordinator.consult` | the task's | the task's (no `delegate` there) |
| an errand turn | `errands.carried(event)`; `delegate` uses `errands.home_turn` | home's (ADR-066) | the home turn's |
| a self-development turn | `Chat.offer_self_development` | the Web chat, the owner | `standing` |
| her plan firing (`scheduled`) | `Schedule._deliver_locked` → `Chat.receive` | the plan's scene and person; development in any owner-private conversation | the plan's |
| a trusted note of hers, home to home | `Schedule.note` → `offer_internal('note', …)` | the receiving conversation; its route's person; development granted | `own` |
| a note from outside, at home | as above | `delegate` refused (ADR-088 §4.2) | the writing turn's own place (for its plans) |
| a visit | `Schedule.visit`, `Schedule.note` → `offer_internal('visit', …)` | the group; the route's first member (defect 1) | `own` (the owner's answer 4: as today) |
| a heartbeat, the settlement | `Schedule._presence`, `_settlement` | the Web chat, the owner | `own` |

### 1.3 Every path that creates or fires a plan

| Path | Code | The conversation it stores | This design |
|---|---|---|---|
| `plan` create | `RoleTools.tool_plan` → `Schedule.create(ep, spec, where)` | the turn's; `where` = a note's origin (ADR-088) or a peer line (`line`) | unchanged; the plan also records the turn's `whose` |
| `plan` update, cancel | `Schedule.update`, `Schedule.cancel` | the same row | unchanged; `whose` kept |
| rhythm and self-development plans | `Schedule._rhythm_plan`, `_ensure_development_plan` | the Web chat | unchanged |
| firing | `Schedule._deliver_locked` | authorizes `plan.scene_id` with `plan.person_id` and sends a `scheduled` event there | unchanged; the turn's `whose` is the plan's (§2.2) |

### 1.4 How a result comes back

1. `Chat._tasks` runs the task in `workspace_folder(task.scene_id, task.requester_id)`, then `Chat.hand_back(task)`
   queues the result in `task.scene_id`'s queue for `task.requester_id`.
2. `TaskService.feedback` builds the event again on every attempt (the task's conversation and person, its session, the
   result, the brief, her thought then, the original input read within the task's scope and epoch).
   `Coordinator.ingest` stores the input before it prepares the turn; a stored input whose text or integration profile
   differs from a rebuilt one is refused `INPUT_IDENTITY_OR_CONTENT_CONFLICT` (`ingress.py`).
3. `require_current_feedback` fences the turn by the task's state, revision, conversation, person, scope and epoch.
4. The watchdog (`handover`, `Chat.sweep`) hands a lost result back again the same way.
5. `publish.py` finds where her words go by walking back to the first input (through `errands.home_turn`).
6. `task_state_from_program` (`records.tasks.recent_with_inputs`) lists every task of the conversation, open first.
7. `task` `page` reads any of her tasks at home, and elsewhere only the conversation's own.

### 1.5 Who reads the task's fields

The 44 functions read the fields as one of: the conversation whose data the task may read (history, digest,
pictures, files, the epoch fence); whose folder, class and tools; where its result is said; who may steer it; which list
shows it; the session it runs in; the input it answers; the grants of the turn that made it. All of them already read
"the task's conversation and person" as "where it runs and for whom". This design keeps those fields meaning that, so
every reader stays as it is, except:

| Reader | Why it changes |
|---|---|
| `grants.development_granted`, its callers `Coordinator._grants` and `ContextBuilder.prepare` | the development grant comes from `whose` (§2.4) |
| `Coordinator.message_action` | a continuation keeps its task's `whose` and development grant |
| `Executor._run_claimed` (`raw_input_refs[0]`, not fenced) | a task that runs on the Web chat for work begun on a line must not show the line's words as its request (§3.5) |
| `Coordinator.consult` (its `belongs` check, persona and context from the hand-over turn; it raises when the input is fenced out) | the same case (§3.5) |
| `TaskService.feedback`, `Schedule._deliver_locked` via `ContextBuilder.prepare` | the words (§3.6) |

### 1.6 Earlier ADRs on this ground

- **ADR-011** §6.1–6.2: the development tools go with the owner's own delegations and her self-improvement and their
  results; never anyone else's request. Kept, made exact by `whose` (§2.4).
- **ADR-066**: a task begun on an errand is home's. Kept.
- **ADR-018**: a note never grants anything; a result turn inherits from its task. Kept.
- **ADR-017**: a group's task reports to that group. Kept (the owner's answer 1).
- **ADR-088**: a turn opened by a note from outside acts with its origin's authority, and so does everything it
  creates; `delegate` is refused there. Kept.
- **ADR-050**: the home lines keep home rights. Its development part is narrowed by the brief's rule and the owner's
  answer 3 (her sister's line); the rest is kept.
- **ADR-075**: the tier belongs to the task and its continuations. Kept.
- **ADR-108 D5**: a program-woken turn shows no speaker; the authorizing person stays on the episode. Kept.
- **ADR-106**: a plan keeps the zone it was made in; a plan keeps the `whose` it was made with in the same way.

## 2. The invariant and the record

**A task records whose work it is: who asked, and where. The program decides that from stored state wherever it can,
and every result, plan and task that follows carries the same answer. Work runs where it was asked, as today; work for
someone outside that she takes on in one of her home conversations runs on the home line, the Web chat. The
development grant follows the record.**

### 2.1 The record

```text
whose = {
  'by':        'words' | 'standing' | 'own' | 'outside',
  'scene_id':  where it was asked (own: where she was; outside: the outside conversation she named),
  'person_id': words: the person whose words asked; standing: the owner; own: the person the turn is authorized as,
               as today; outside: none,
  'chosen':    True when she named it (`for`),
  'version':   WHOSE_VERSION,
}
```

Kept whole on **episodes** (written in the episode's first save), **tasks** and **plans** (in their one save). It is
written beside the fields every reader uses, never instead of them.

### 2.2 Who asked: `whose.of_turn(store, ep, event)`

One function in a new module `src/asuna/whose.py`. It reads stored rows only and calls no model, so a restarted worker
and a redelivered event compute the same answer. It runs in `Coordinator.ingest` before `ContextBuilder.prepare`, from
the event (`errands.carried(event)` for an errand, since `ep['errand']` is set only after `prepare`).

| The turn | Its `whose` |
|---|---|
| on an errand | the home turn's `whose`, when it names that home conversation; otherwise `own` there (an errand a turn opened by a note from outside sent, on the owner's own line: its task stays home's, as today, and earns nothing) |
| `external` | `words`: the person whose line opened the turn |
| `task_feedback`, `consult` | the task's `whose` |
| `scheduled` | the plan's `whose` (§3.7: a plan records a `whose` only where it lives, so her `line` plans and a plan made on an errand are `own` where they fire); an old plan's read the same way (§2.6) |
| `note` or `visit` opened by a note from outside, in an owner-private conversation (`notes.outside_class`) | the writing turn's `whose`, computed without the errand row; never one that names an owner-private conversation, and never for a note that is gone: then none, and the turn hands nothing over and plans nothing (as ADR-088 already refuses) |
| `note` (trusted), `visit`, `presence`, `settlement` | `own` |
| `self_development` | `standing` |
| any kind added later | `own` |

A walk through stored rows (an old row, §2.6) stops after 64 steps, a guard against a broken chain rather than a limit
on a real one (a chain of results begun before the install is walked once a hop), and a turn it needs that is missing or erased
(an erasure keeps none of a turn's inputs, `records/view.py` `REDACTION_KEEPS`) answers `own` there.

### 2.3 Where it runs

As today: the conversation and person of the turn that hands it over (home's on an errand, ADR-066), and a
continuation where its task runs. Two answers change it, both hers (§2.5):

- **Work for someone outside, named in a home conversation** (`for`: an outside place): the task runs on the Web chat,
  for the owner (its `requester_id`, as every Web chat task), with home's folder, and its result turn is there. Its
  results, plans and further tasks stay there, since they carry its `whose`. From the Web chat itself only the record
  and the grants change.
- **Another person's request in a group** (`for`: a person in her turn; a home group too): the task is that person's,
  in the group, as any of theirs (their folder, they may steer it), with their line in the turn as its input: their
  first line to her waiting behind the one that opened it, as `people_from_program` found them, never a later one; only
  when she names them in that call, so a result turn of their task hands over its own input.

Plans live and fire where they do today.

### 2.4 Grants

`grants.for_whose(store, whose)` replaces `development_granted` at its two callers (`Coordinator._grants` for a new
task and a continuation, the capabilities block of her turn).

| Grant | Given when |
|---|---|
| development tools (`development_*`, `persona_job*`) | `earns_development(whose)`, self-development enabled, the sandbox available |
| integration profile | as today (the authority turn's input, `integration.event_profile`); none when `whose.by == 'outside'` |
| everything else (`sandbox_run`, credentials, the folder, workspace tools) | as today (`sandbox_run` and credentials by the authority turn's class, the folder by the conversation the task runs in); the same answer for every task in range |

`earns_development(whose)`: `standing`; `words` where the person is the owner (canonical, `scene_links`) in an
owner-private conversation; `words` on an agent line (`integration.agent_home_scene`) by that line's own agent. Not her
sister's line, not a home group's other members, not `own` (her heartbeat plans and notes), never `outside`.

A task's grants are written on it when it is made and never recomputed. A task's `whose`, as its result turn, its
consults and its continuations read it (`of_task`), carries `earns: False` when the task stored no development grant,
for an old row and a new one alike: none of them earns more than the task did (a result turn kept its task's grant
before ADR-111 too), and what they hand over or plan inherits the same. A continuation keeps its task's development
grant (`earns_development` of that `whose`, so never more than the task stored), never the turn's; today's check that a turn may add words to a task
with the development grant only if it has it too stays, reading `earns_development` of the turn's `whose`. Today's
integration check compares the task's profile with the one a task from this turn would get: for a task whose `whose.by`
is `outside` that is none, whatever the turn's event carries (the owner's own lines on the Web chat carry `owner`,
`Chat.submit`), so the owner can add words to and continue outside work on the Web chat.

### 2.5 Her choice

`delegate` takes `for`, shown by conversation (`placed_spec`, ADR-087 §4.3):

- **In owner-private conversations:** the place of an outside conversation (a group or a DM) from
  `note_places_from_program`, mapped by the program (`notes.targets`) to `{by: outside, scene_id, chosen}`. Not written:
  the program's answer. A place that is not an outside one (a home conversation, or a home group, which
  `places.errand_targets` lists among the outside places) is refused `FOR_UNKNOWN_PLACE`.
- **In groups** (the owner's answer 5): the label of another person whose line is in this turn
  (`people_from_program`), mapped to `{by: words, person_id, chosen}`. Not written, or the opener's own label: the
  opener. A label not in the turn is refused `FOR_UNKNOWN_PERSON`. Only a turn someone's line opened has
  `people_from_program`.
- **In a home group** (owner-private and a group): both, a person's label in her turn first, else an outside place; a
  value that is neither is refused `FOR_UNKNOWN_HERE`. So the owner's request in a turn someone else opened there is his,
  with his grant.
- **On an errand:** refused `FOR_ON_ERRAND`; its task is home's (ADR-066), as today.
- **Elsewhere** (someone else's DM): no `for`.

### 2.6 Old records

There is no history conversion (docs/DEVELOPMENT.md). Nothing rewrites a stored row.

- A **task** without `whose` reads it from `of_turn` of the turn that made it (`task.episode_id`; episodes are kept). A
  new task that inherits from an old one never gets more than the old one stored: its development grant is at most the
  old task's `development_grant`. Its audit row says `inherited: unrecorded`.
- A **plan** without `whose` reads it from `of_turn` of `plan.source_episode_id`, by §2.2's `scheduled` row.
- An **episode** without `whose` (a turn in flight across the install) gets it from `of_turn` when it is read.

## 3. Interfaces

### 3.1 `src/asuna/whose.py` (new)

- `of_turn(store, ep, event) -> whose | None` (§2.2); `of(store, ep)`: `ep['whose']`, else `of_turn`;
  `of_task(store, task)`, `of_plan(store, plan)`: the stored record, else §2.6's reading.
- `earns_development(store, whose) -> bool` (§2.4).
- `standing(store, whose) -> 'here' | 'left' | 'blocked' | 'closed'`: `left` when the person's grant on the group's
  route carries ADR-107's `ended_at`, `blocked` when the channel lists them in `blocked_senders` or her block switch
  holds them (`switches.blocked`), `closed` when the conversation is a line she has closed (`lines.is_closed`). Read
  when a turn is prepared, never stored.
- The words (versioned, `WHOSE_VERSION = 1`; a change to any of them bumps it), all addressing her as 你:

```python
TASK = {'words': '这件是%s托你的', 'standing': '这件是你自我改进时交的', 'own': '这件是你自己的事',
        'outside': '这件是%s那边托的'}
PLAN = {'words': '这条计划为的是%s托你的事', 'standing': '这条计划是你自我改进时定的', 'own': '这条计划是你自己的事',
        'outside': '这条计划为的是%s那边托的事'}
RESULT_HERE = '结果回到这里'
RESULT_OUTSIDE = '结果回家里，这边的上下文不跟过去；要给那边，你自己去说'
HANDED = '是你在%s交出去的'
STANDING = {'left': '（%s已经离开这个群了）', 'blocked': '（%s在这里被屏蔽了）', 'closed': '（这条线你关着）'}
BRIEF_ONLY = '新开一份上下文：它只看得到这次的 brief。'
FOR_UNKNOWN_PLACE = ('「%s」不是外面的一处：for 照抄 note_places_from_program 里群或私聊的 place，'
                     '或者不写（就是这一回合叫你的那位）。')
FOR_UNKNOWN_PERSON = '「%s」不是这一回合里的人：for 照抄 people_from_program 里的标签，或者不写（就是叫起这一回合的那位）。'
FOR_UNKNOWN_HERE = ('「%s」不是这一回合里的人，也不是外面的一处：for 照抄 people_from_program 里的标签或'
                    ' note_places_from_program 里群或私聊的 place，或者不写（就是叫起这一回合的那位）。')
```

  `%s` is a person's label as she reads it there (`People.speaker`) or a place's title (`People.scene_title`); never an
  id. The two refusals are `Refused` with their codes kept in the record (ADR-108 D4b).

### 3.2 Episodes

`Coordinator.ingest` computes `whose.of_turn` once, before `ContextBuilder.prepare` (which is given it, and computes it
itself when called without, as `recall` calls it), and writes it in the episode's first save, gated (`ATTENDING`) or
prepared. `Coordinator.consult` writes the task's on the consult episode.

### 3.3 `Coordinator.delegate`

```text
resumed = the task this call made, if any: returned as it is, nothing decided again
whose  = whose.of(store, ep); none → refused with ADR-088's words, as today
for    = home form → {outside, the place's scene, chosen}, or FOR_UNKNOWN_PLACE
         group form → {words, that person, chosen}, or FOR_UNKNOWN_PERSON; the opener → the turn's own
         home group → the group form, else the home form, or FOR_UNKNOWN_HERE
         on an errand → FOR_ON_ERRAND
where  = the Web chat, the owner, when whose.by == 'outside' and the turn is in a home conversation;
         otherwise as today (the turn's; home's on an errand); the named person's in a group
development = for_whose(whose); integration as today, none for outside; capabilities as today
session = as today when the task runs in the turn's conversation; otherwise the Web chat's live session from the
          resolver, with a proto of that scene alone (its own character_context, no task_id, no context), since a
          session is bound to one scene (`NativeWorker.bind_session`)
raw    = as today; for a person she named in this call, that person's line in the turn (`whose.line_in_turn`)
task   = {... as today, with `where` ..., whose}
audit  'task.whose' {by, chosen, development_grant, the kind and class of where it runs and of the turn's,
          inherited: 'unrecorded' when §2.6 applied}
```

The `delegate` result gains `for`: `TASK[by]` with its label or place, then `RESULT_HERE`, or `RESULT_OUTSIDE` when the
task runs on the Web chat from another conversation; its `action_brain` reads `BRIEF_ONLY` there.

The spec: in owner-private conversations the description gains `外面（群、别人的私聊）托的事在家里做：for 写那边的 place，结果回家里。`
and `for` reads `这件是外面哪一处托的（群或私聊）：照抄 note_places_from_program 里那边的 place；不写＝这一回合叫你的那位托的`;
in public groups `for` reads `这件是谁托的：不写＝叫起这一回合的那位；是这回合里另一个人托的，照抄 people_from_program 里 ta 的标签`;
in a home group the description is the home one and `for` reads
`这件是谁托的：不写＝叫起这一回合的那位；是这回合里另一个人托的，照抄 people_from_program 里 ta 的标签；外面（群或私聊）托的，照抄 note_places_from_program 里那边的 place`.

### 3.4 Continuations

`Coordinator.message_action`: the new row runs where the task runs, keeps its `whose`, and takes the development grant
from it (§2.4). Everything else as today.

### 3.5 A task that runs on the Web chat for work begun on a line

Only this case runs a task in a conversation other than the turn's (an errand's already does, ADR-066, and keeps
its own paths). For it:

- `Executor._run_claimed` reads the input within the task's scope and epoch, as `feedback` and `consult` already do, so
  the action brain gets her brief and not the line's words as the request.
- `Coordinator.consult` is authorized by the task's own fields (the `belongs` equality would refuse it), runs in the
  task's session with its persona and `character_context` from that session's row, and gives `original_input: null`
  when the input is fenced out instead of raising `CONSULT_SOURCE_MISSING`.

### 3.6 What she reads

- The result item of a `task_feedback` turn (and of the short hand-back) gains `for`: `TASK[by]`, `HANDED` when the task
  was handed over in another conversation, `STANDING[...]` when its person can no longer be reached there. A plan's
  firing gains `PLAN[by]` and `STANDING[...]` in the plan block `prepare` builds for a `scheduled` turn. Both are added
  by `ContextBuilder.prepare` when the turn is prepared (once per episode; a resumed turn reuses its stored context),
  never written into the stored event, which `feedback` rebuilds on every attempt and `ingress.py` compares byte for
  byte.
- `action_capabilities_from_program`: `development` present when `earns_development` of the turn's `whose`, and never
  in a consult turn, whose tasks get none (`Coordinator._grants`); `delivery`
  in owner-private conversations reads `程序自动执行委托，结果作为独立事件返回当前场景（外面托的写 for，结果回家里）；等待时仍可聊天。`.
- `capability_refusal` (the action brain's): the development line of `GIVEN_TO` reads
  `只给主人在自己的对话里、agent 在自己的线上交的任务，和自我改进时交的（自我开发要开着）`.

### 3.7 Plans

`Schedule.create` stores the plan where it does today and records a `whose` on it: the turn's when the plan lives in
the conversation that `whose` names, or the `whose` is `outside` (its work lives on the Web chat); otherwise `own` where
it lives. So her `line` plans (made at home, firing on a peer line) and a plan made on an errand (firing in the
destination, a home group included) are her own where they fire and earn nothing there, and a plan made in the result
turn of outside work on the Web chat fires there with the outside `whose`, so the work's follow-ups stay home. A new
wording of a plan (`ScheduleService.update` with an intent) records the changing turn's `whose` the same way, since what
the plan asks is then that turn's; a new time alone keeps it. Nothing else of plans changes.

## 4. Life cycles

### 4.1 Every text she reads about a task or a plan

Brains: CB the character brain, AB the action brain, RG the relevance gate (which reads none of these).

| Text | Created | Used | Updated | Discarded | Survives |
|---|---|---|---|---|---|
| `delegate` description (+40) and `for`, home form (owner-private conversations: +156 characters of JSON in all) | `role_tools.TOOLS` at import; placed per conversation (`placed_spec`) | CB, in the tool list of every request there | by a release only | never while the tool exists | restarts (code); compaction (tools are not compacted); a retired one-shot session (the next has the same list); redelivery (not an event) |
| `delegate` `for`, group form (public groups: +109) | as above | CB, groups | by a release | as above | as above |
| `delegate` `for`, home group form (home groups: +199 in all) | as above | CB, home groups | by a release | as above | as above |
| `task` description, `task_state_from_program`, the stored result text, the stored plan text, the visit's text, `errands.HOME_TASK`, `wake_words.WAKE_WORDS` | unchanged | | | | |
| `delegate` result `for` (15–43 characters with the label or place), `BRIEF_ONLY` (23, only for work moved to the Web chat) | `RoleTools.tool_delegate`, from the stored task | CB, the turn that delegated | never | at compaction (the summary keeps what she kept) | restart: the recorded tool result is replayed, not recomputed; redelivery: the same task id gives the same words |
| the result item's `for` (10–40) | `ContextBuilder.prepare`, when the `task_feedback` turn is prepared, from the task's `whose`, a label and `standing` then; kept in the episode's stored context, never in the event | CB, that turn (one per result) | never: a resumed turn reuses its stored context | at compaction | restart: the stored context is reused; redelivery: the stored event is unchanged, so the identity check passes |
| a plan block's `for` (10–25) | `ContextBuilder.prepare`, in the plan block of a `scheduled` turn | CB, that turn | never | at compaction | as above |
| `FOR_UNKNOWN_PLACE` (75), `FOR_UNKNOWN_PERSON` (64), `FOR_UNKNOWN_HERE` (112), each with the value she wrote; `FOR_ON_ERRAND` (20) | the refusal of a value not on the list | CB, only when she tries | by a release | with the tool result | as any tool result |
| `action_capabilities_from_program` `delivery` (+17, owner-private conversations) | `ContextBuilder.prepare` each turn | CB, every turn where `delegate` is available; sent whole only when it changes, otherwise named unchanged (`context-delivery.js`) | by a release | replaced by the next turn's | rebuilt every turn |
| `capability_refusal`'s development line (46) | the broker's refusal of a development tool | AB, only on that refusal | by a release | with the tool result | as any tool result |

### 4.2 Every stored field this adds

| Field | Created | Used | Updated | Discarded | Survives restart and compaction |
|---|---|---|---|---|---|
| `episodes.whose` | `Coordinator.ingest`, `consult`, in the first save | `delegate`, `message_action`, `Schedule.create`, `prepare` | never; a resumed turn keeps it | with the episode (kept; erasure redacts per scope, ADR-105) | yes |
| `tasks.whose` | `delegate`, `message_action`, in the task's one save | its result turn and consults, its continuations, the words | never | with the task | yes |
| `plans.whose` | `ScheduleService.create`, in the plan's first save | its firing's turn, the words | by `update` with a new wording (the changing turn's, §3.7); a new time keeps it | with the plan | yes |
| audit `task.whose` | with the task's save | the landings' structure counts | never | after 30 days (ADR-074) | yes |

## 5. Failure modes

| Case | She sees | The person sees | The program records |
|---|---|---|---|
| The conversation of `whose` ends, or the person's admission ends (an ADR-107 departure) | the result turn still runs where the task runs, its item saying `（A已经离开这个群了）`; a plan's firing the same | nothing: they are not there | the task and plan unchanged |
| The person is blocked, admitted again, or unknown | `（A在这里被屏蔽了）` while blocked; nothing once back; an unknown author has the label `People.speaker` gives | — | — |
| A plan fires after its conversation is gone | nothing: no conversation to read it in | nothing | the outcome on the plan, as today (defect 4) |
| The work serves two conversations | one task, one `whose`; the `delegate` result says where the result goes, so the other is her own act (an errand, a note) | each sees what she says there | the task, and the errand or note |
| She names no outside place for outside work on a line | the `delegate` result says `这件是A托你的；结果回到这里` (the line's agent): the slip is in front of her | — | the agent's `whose` and its grant (the case this ADR started from, now visible every time) |
| She names the wrong place, or the wrong person in a group | the `delegate` result names the place or person | the right person can't follow it up | `chosen` in the audit |
| A crash between the task's write and the episode's update | on resume the task is listed as already handed over (`_run_turn` merges `task_records.of_episode`, as today) | — | the task row |
| The same event delivered twice | one turn (the episode id comes from the event id; the existing episode returns with its `whose`); a rebuilt result or plan event is byte for byte the stored one | — | `ingress.deduped` |
| A restart while a task runs, or while its result waits | paused or handed back where it runs, as today | — | as today |
| Compaction of the session that held the hand-over | the result turn carries the title, the brief, her thought then, whose it is and the report | — | — |
| An agent line she closed while its work is in flight | its result turns still run there, saying `（这条线你关着）`; outside work named from it is already on the Web chat | her words, if any | unchanged |
| An errand from home, and a visit | as today: the errand's task is home's; the visit's task is in the group (defect 1) | as today | `whose` the home turn's; `own` |
| A result that mentions another conversation's content | a task reads the conversation it runs in; outside work moved to the Web chat reads the Web chat's history, as the same work on a line read the line's; its input is fenced to the Web chat (§3.5); her brief is her own words, like a note | — | — |
| A task that would get a grant beyond its asker | the development grant is `whose`'s, never the turn's; work for someone outside never has it nor integration; `for` names only an outside place or a person in the same turn | — | — |

## 6. Defects found, not in this ADR

1. **A visit's task belongs to the route's first member.** `places.visitor` (places.py) enters the group as the first
   member by id; `Coordinator.delegate` records that person as `requester_id`, so the task runs in their folder
   (`Chat._tasks`, `workspace_folder`; the stage binding in `native_worker.py`), they may steer it (`RoleTools._own_task`
   fences by `requester_id`), and `OTHERS_TASK` tells her they asked. Her visit may steer and stop that member's own
   tasks, and the plans list and the plan update and cancel fences (`records.plans.of_conversation`,
   `Schedule.update`, `Schedule.cancel`) go by that person, so plans made on a visit are theirs to see and change.
2. **A task paused on an agent line can never be continued.** `Coordinator.message_action` lets a `PAUSED` task go on
   only for the owner's own line in the Web chat, and `RoleTools._own_task` finds only the turn's own conversation's
   tasks.
3. **A plan made on an errand fires in the destination** (ADR-066 row 1), with an intent she wrote while holding home's
   authority, so home's words enter that conversation's session. This design keeps it from carrying home's grants
   there (§2.2's `scheduled` row); the text still goes.
4. **A repeating plan whose conversation is gone** records `SCENE_MEMBERSHIP_DENIED`, `SCHEDULE_ROUTE_REVOKED` or
   `SCHEDULE_POLICY_STALE` at every occurrence (`Schedule._deliver_locked` resets it to `ACTIVE`).
5. **A result whose conversation no longer exists crashes the hand-back:** `TaskService.feedback` reads
   `scene['policy_epoch']` of a scene `scene_records.get` returned as None.
6. **A group she has left or that was disbanded has no state** (ADR-107 has no rule for it); results said there fail at
   the adapter.
7. **A visit can enter a group as a member who has left.** `places.visitor` leaves out only blocked senders;
   `channels.route_members` still returns a grant whose admission ended (ADR-107 marks `ended_at`,
   `channel_admission.depart`), and the plan firing's route check (`SCHEDULE_ROUTE_REVOKED`) reads the same list.

## 7. Tests

Only those that guard a fence or a failure that would be silent and costly; unit tests on the in-memory adapter
(`world` and `store`, `tests/conftest.py`), none reaching a server.

| Test (new module `tests/test_whose.py`) | Guards |
|---|---|
| `test_whose_by_turn_kind`: every row of §2.2, including an errand, an outside note, a note written on an errand, a gone note, an erased turn, and a task and a plan made before the install; a result turn of a task that stored no grant earns none | the record: a wrong row is a wrong grant, silently |
| `test_development_only_where_whose_earns_it`: the owner in his conversations (a home group included), an agent on its line, `standing` earn it; a home group's other member, `own`, `outside`, a public member do not; through `Coordinator.message_action`, a continuation keeps exactly its task's grant (the owner's task made while self-development was off gets none when continued later from a turn with nothing to give), a turn without the grant cannot add words to work that has it, and the owner may continue outside work from his own line though it carries his integration grant (integration on, so the comparison is real) | the authorization fence |
| `test_outside_work_named_on_a_line_runs_home`: `Coordinator.delegate` with an outside place from an agent-line turn gives the Web chat's scene, scope, epoch, owner and session (a stub resolver) and no development or integration grant, while the agent's own task keeps both; a resumed call returns the same task with no session at hand; `Executor._run_claimed` reads nothing of the line as its input; `Coordinator.consult` answers it in the Web chat's session with no original input; `TaskService.feedback` hands its result back on the Web chat in the task's session, or in none, never the line's; `ScheduleService.create` in that result turn records the outside `whose`, a line plan made at home is `own` on the line, and `update` re-records a rewritten plan's `whose` but not a moved one's | the owner's rule, and privacy across conversations |
| `test_a_group_task_is_the_person_she_names`: through `RoleTools.tool_delegate`, `for` with a label in the turn gives that person's task with their line in the turn (not a later one) as input and the words for it; the opener's label is the turn's own; a label not in the turn, and any `for` on an errand, is refused; a result turn of their task hands over its own input; in a home group the owner's label gives his task with his grant, an outside place works as at home, and the home group itself is refused | the person inside a group |

Each fence was checked against its test: reverting any one of the 15 changes that make these fences (the executor's
read, the consult's and the hand-back's session, the result turn's cap, the continuation's integration comparison, a
plan's `whose` at create and update, the named person's input and its bound, the home group's person, outside work's
integration, the errand refusal, the resumed call, the opener, the grant by `whose`) fails one of these tests.

Changed: `tests/test_specs_by_place.py` (the forms of `for` by class and kind, the home group's included); `tests/test_home_groups.py`
only names the rule in its docstring, and a home group's other member earning no development grant is asserted in
`test_development_only_where_whose_earns_it`. No new static check and no new integration test: no index,
no query and no adapter promise is added. `pytest integration` runs at every landing.

## 8. Landings, in order

Each landing: targeted tests, the full suite, `pytest integration`, the personal-data scan
(`tools/check_staged_secrets.py --personal --all`), the push gate, a fast-forward, the planned restart while she is
idle, a check that the running code is the commit's (`loaded.commit`), one report to the owner. Nothing reaches a real
model endpoint in any test. **No message to her about this ADR until L2 is installed and checked (the owner's rule);
then one message, and her reading of the whole page.**

Built on `claude/elegant-goodall-2ip12g`, both points on main as of `f2103a24` (ADR-110 built), so each fast-forwards
it: **L1 installs at `e0f818e`** (`553e2f3`, the build review's record fixes `2d58e42` (§10.5), and that main; no L2
code), **L2 at the branch head** (`e1dd8b8`, the review's L2 fixes `5be549e`, the same main through `e0f818e`, and this
page). Neither is installed. If main moves before a landing, merge it into that point first and run the tests again.

Not checked where it was built (a cloud session: no private word list, no node packages, no MongoDB, no live Host),
so each landing runs them on the owner's machine: the personal-data scan of the added lines and messages, and
`tests/test_personal_words.py` with the list; the tests that skip without node and the DSH sandbox
(`tests/test_declared_specs_dsh.py`, the confined-command tests); `pytest integration` on a server; the restart and
the real-system checks below. Measured there: the full suite at the L2 point 836 passed, 30 skipped, 3 failed, the
same three that failed there on the unchanged base before the build (`test_no_server`'s unresolvable-address check,
two of `test_refusal_probe`'s that need DSH's own conversion).

**L1: record `whose`, change nothing she reads or can do.** `whose.py`; `episodes.whose`, `tasks.whose`, `plans.whose`
written; the audit row; nothing reads them yet. Tests: the first. *On the real system,* by structure only (no
content), for two days or 100 new tasks: tasks by turn kind and `whose.by`; how many would lose the development grant
under §2.4; how many chains begun before the install are still open.

**L2: everything else.** Tests: all. *On the real system,* two days by structure: the development grant only where
`whose` earns it; every task with `whose.by == 'outside'` on the Web chat with its result there; no model-facing read
of an input outside its task's conversation; agent-line tasks a day and their development rate beside the lead's
numbers for 10-27 and 10-28 (for the owner's reading, not a gate).

## 9. What she carries

- **Every turn:** nothing new in her context; `action_capabilities_from_program`'s `delivery` grows by 17 characters in
  owner-private conversations, and the block is sent whole only when it changes.
- **Every request (the tool list, a cached prefix):** `delegate` grows by 156 characters of JSON in owner-private
  conversations (363 → 519), by 199 in home groups (363 → 562) and by 109 in public groups (363 → 472); unchanged in
  someone else's DM.
- **Per event:** 15–43 characters in each `delegate` result; 10–40 in each result turn's item; 10–25 in each plan's
  firing.
- **Only on a mistake:** `FOR_UNKNOWN_PLACE` (75), `FOR_UNKNOWN_PERSON` (64), `FOR_UNKNOWN_HERE` (112),
  `FOR_ON_ERRAND` (20).

## 10. The review

A fresh reviewer read three earlier versions of this page against the code: the first draft (`d7e7decd7126`, 14
findings, 2 blockers), the fixes (`affd95133a06`, 8 items) and a wider version written to an over-reading of the
owner's rule (`4dca4dff7f1d`, 8 findings). The full tables are in those commits' design.md (`git show
0e6d1c17bcf8:docs/development_plans/ADR-111-whose-work-a-task-is/design.md`, §10). What bears on this version, and is in
it:

- inheritance stops at a note from outside and never names a home conversation; a note written on an errand acts as
  that conversation; a gone note or erased turn answers none or `own` (first draft 1, re-check A and E);
- `raw_input_refs` keeps its meaning and is never empty; the readers that show it to a model are fenced (first draft
  2);
- the words are added when the turn is prepared, never into the stored event, which `ingress.py` compares byte for
  byte (first draft 3);
- old rows read `whose` from the turn that made them and never inherit more than they stored (first draft 5);
- a public conversation never carries a `whose` that names another conversation (first draft 6);
- consult is authorized by the task's own fields, with persona and context from its session (first draft 12);
- the `external` row is the opener, and a group task can be named for another person, with that person's line as its
  input (first draft 10, re-check G, the owner's answer 5);
- a task's session is its own conversation's, from a proto of that scene alone (redesign 1 and 6);
- the crash gap was already closed (first draft 11).

Findings about the parts that are no longer here (her own folder on visits, steering on the home line, the read fence
of moved tasks, plans moved off lines, the plans list, `develop`) left with them; the visit placeholder they found is
defect 1.

### 10.4 This version (`155dc3b072f0`), 4 findings and one defect

| # | Finding | Severity | Done |
|---|---|---|---|
| 1 | The integration check in `message_action` compared an outside task (no profile) with the owner's Web chat line (`owner`), so the owner could not add words to or continue outside work | major | The check compares with the profile a task from this turn would get, none for `outside` (§2.4) |
| 2 | A plan recorded the turn's `whose` wherever it fired, so her `line` plans and a plan made on an errand into a home group kept the owner's development grant there | major | A plan records a `whose` only where it lives, else `own` (§3.7, §2.2) |
| 3 | The home form of `for` offered home groups as outside places | minor | Refused (§2.5) |
| 4 | `sandbox_run` and credentials follow the authority turn's class, not where the task runs | minor | Worded as today (§2.4) |
| — | A visit can enter as a member who has left | defect | §6 defect 7 |

The reviewer found clean: the agent-line → Web chat case end to end (place, folder, session proto, input fences,
publication, the feedback fence, the stage binding, no integration), the errand and outside-note rows, the words at
preparation, the old rows, and the claims about the code.

### 10.5 The build (`e1dd8b8`), 9 findings

A fresh reviewer read the built code (`94bd986..e1dd8b8`) against this page, with probes on the in-memory store. No
blocker: the fence held on the main paths, outside work had no development or integration grant, no outside note took
a home conversation's place, the stored events stayed byte for byte, and the fenced read broke no task that is not
moved.

| # | Finding | Kind | Done |
|---|---|---|---|
| 1 | A home group had only the home form of `for`: the owner's request in a turn someone else opened was that person's, with no grant, and could not be named his | design (the owner's answer 5 is for any group) | A home group takes both forms (§2.5, §3.3) |
| 2 | A continuation's grant was `earns_development` of its task's `whose`, not capped by what the task stored: an outside result turn continuing the owner's task made while self-development was off gave it the development tools | build | A task's `whose` as read carries `earns: False` when it stored no grant, new rows as old (§2.4); its result turn is capped the same way, as before ADR-111 |
| 3 | The tests did not drive the code they named: the executor's read, consult, the hand-back, `message_action`, `ScheduleService.create`, the session resolver and `tool_delegate` were never called, and the integration assertion was vacuous with integration off | tests | Rewritten to drive each path, integration on; each fence reverted fails a test (§7) |
| 4 | On an errand with `for`, `moved` compared with the errand turn's place, not home's, so the result said the action brain saw only the brief and the context stayed behind, though it ran home with home's input | build | `for` is refused on an errand (its task is home's, as today) and `moved` compares with an errand's home |
| 5 | A turn that earns nothing could rewrite the owner's plan, which then fired as his words with the grant | design | A new wording records the changing turn's `whose` (§3.7) |
| 6 | The named person's input was their newest line, possibly one after her turn; `chosen` was inherited, so a task in their result turn took that line again | build | Their line in the turn (`line_in_turn`), only when named in that call (§2.3) |
| 7 | A chain of results begun before the install deeper than eight hops would lose the owner's or an agent's grant | design | The walk stops at 64, a guard against a broken chain (§2.2) |
| 8 | The development line now shows in errand turns in public groups and in consult turns | design | Errand turns: as §3.6 specifies (their tasks have home's grant, which the line now says); consult turns: none, as their tasks get none |
| 9 | A resumed `delegate` for outside work asked for the Web chat's place and session before finding the task it had made, so a session not at hand failed a turn whose task existed | build | A resumed call returns its task first (§3.3) |

Not changed: the reply token a result carries on a platform (`platform_answers`) stays the line of the turn that handed
the task over, also for a person she named; what her line quotes is hers to choose (`publish._quote`).

The record fixes (2, 5, 6's function, 7, and `moved`) land with L1, since what L1 stores is what L2 reads.
