# ADR-120: Bringing stored things back into the work

Status: **Decided** 2026-11-25 (the owner: one access table with three origins, each outside conversation its own
files, home everything, the table a setting shown as that table on the settings page; design big sis; her reading of
§9 done 2026-11-25, agent line 0668: landing 1 signed with her wording of its three sentences). Laid down 2026-11-09
from her request (agent line 0035, 2026-11-05: nine dated incidents with their idea ids, gathered into one class at
big sis's ask); ADR-124 (image routes, her request of 2026-11-10) merged in on 2026-11-11 at the owner's word, as §7.
Repro material: her 2026-11-02 four-part bundle, which she has kept.

## 1. The gap

The program keeps "what is stored" and "what this turn can use or send" as two worlds, with no way across for her or
the action brain. It is one gap, in four directions:

1. **A stored thing's body by its id.** `read_file` does not take a blob id, `read_image` takes only images,
   `received_file` takes only this turn's `att-…` refs, and `web_fetch` takes no `file://`. From a task, the DATA path
   is `PATH_DENIED`. Seen 10-26, 11-02 and 11-04 (the last two relayed by her home turn).
2. **A public URL's bytes into `/task`.** `web_fetch` refuses `image/*` (`unsupported content type`), and no tool
   writes fetched bytes into `/task`. Seen 10-15, 10-19 and 10-24.
3. **An old image product onto this turn's sendable list.** `offer_file` takes only `/task` paths; a blob id, a store
   path and a disk path are each refused. Once she redrew a picture instead, which meant a second generation and
   different pixels. Seen 10-27 and 10-31.
4. **A viewed frame into a picture she can send.** A video reaches her as timed still grids, and a frame cannot
   become a picture she sends. Seen 10-21, with two more readings since.

Not in this ADR (her line): the two image-generation recipe items, which are their own bundle.

## 2. What the code does today (survey 2026-11-25, main `d16ba12280f9`)

Evidence: `.runtime/private/adr120/survey-1125.md` (local, 6 KB). Still live: from 11-09 to 11-25 her tool records
carry `IMAGE_PATH_HOME_ONLY` 128 times in 69 sessions, `IMAGE_WORKFLOW_NEEDS_MORE_PICTURES` 49 in 33, `unsupported
content type` 14 in 8, `RECEIVED_FILE_NOT_FOUND` 5 in 5 (program codes counted, no text read); 8 of the 9 incidents'
ideas are deferred, waiting on this page.

- **Ids.** A stored thing is a row of `artifacts` (kinds `image`, `file`, `received_file`), named to her as
  `blob-<32 hex>`; a message's picture, video, sticker or file is `att-<12 hex>`; history shows only a sha256. **Every
  such row already carries the conversation it was made in** (`scope_key`, all ~2,100 rows; stickers are
  `global-safe`).
- **Per direction**, all four still open: `read_file` (Asuna's, UTF-8 up to 32 KiB, `/task` only) refuses a blob id and
  any DATA path; `read_image` takes `att-` refs (7 days; at home from all conversations), `blob-` ids of kind image in
  scope, hers, or offered this turn, and paths at home only (`vision.py:703-713`); `received_file` takes `att-` refs
  only and reads text up to 1 MiB, its `do=copy` writes into `/task/received/`; `web_fetch` reads text, HTML, JSON and
  XML only (`WEB_UNSUPPORTED_CONTENT_TYPE`, `vendor/web-fetch-http-rc2.js:379-383`). Speak's `picture` takes only the
  ids on `image_artifacts_from_program`. A video becomes one still grid (stored, 7 days); no single frame is stored.
- **What a group may send.** In a group or someone else's chat that list is her newest drawings **from anywhere**,
  home included (`outbound_media.offer`, "a picture she made goes wherever a picture may go"), and the file list is
  every file any task registered, from every conversation (`outbound_files.offer`, no scope filter). This is how a
  picture drawn at home stood on a group's list on 2026-11-24 for no reason.
- **The trust line is decided in about ten places**, each by a slightly different question (the room, the requester,
  the owner's private class): `coordinator._grants`; the per-call class in `tasks.py:940-963`; four fences in
  `vision.py`; `received_files.reach`; `outbound_media` and `outbound_files`; the ADR-135 guard; the network line in
  `fetch.js`; `local_roots.PUBLIC_HANDS`; `credentials.home_task`. None asks whose the work is.
- **Work for someone outside taken on at home runs as home.** Such a task is written in her local chat with the owner
  as requester (`coordinator.py:706-712`), so it gets the shell, which runs as the owner's own user with his ssh and
  git keys (`tasks.py:371`), the owner's local network, and the credentials (`credentials.home_task` asks the same
  question). Only the owner's integrations are withheld (`whose.by == 'outside'`).
- **Found after ADR-135's close:** `guard._image_path` checks `args['path']`, but `read_image` takes only `ref` (a path
  arrives as a ref), so the rule never fires; the real fence, `vision.py:703-713`, does. Nothing is exposed; the rule
  goes in landing 1.

## 3. Decision: one access table

### 3.1 Three origins

Every task and every one of her turns has one origin (the middle one in her words: 「外面托、家里办」), fixed when it is created and stored on it (a task's
`origin`; a turn's is the one `RoleTools._cls` already works out), so a restart, a continuation or a result turn
reads the same one and nothing widens it later.

| Origin | Which work |
|---|---|
| **home** | A turn in a home conversation (her local chat, a home group, an agent's line), and the work it starts, whoever it is for at home: the owner's words, an agent's, her own (`own`, `standing`). An errand turn, which acts with home's authority (ADR-066). |
| **home from outside** | Work she decides on in a home turn of her own **for someone outside** (`whose.by == 'outside'`): the task and its result turn. |
| **outside** | A turn in an outside conversation and the work it starts. A home turn **opened by a note from outside** is outside too, with its note's conversation as its own (ADR-088 §4.2, ADR-135 B1/B3): an instruction from outside is never home's decision. |

The owner's reason for the middle column (2026-11-25): what a person outside passes in is judged by the classifier on
its way home, and what home sends out is judged on its way out, so the most dangerous path is checked at both ends;
her home is trusted to do right without instruction from outside; commands are dangerous, files less so.

### 3.2 Resources and the default table

Each row is one resource; each tool names the resources it needs (§3.4). In every row the allowed origins run from
home outwards, so a row's setting is one of four levels: **home only**, **home and home from outside**,
**everywhere**, or **nowhere**. The default is the table agreed with the owner on 2026-11-25:

| Resource | Covers | home | home from outside | outside | Default level |
|---|---|---|---|---|---|
| `own_files` | this conversation's files (§4): read, save into them (web downloads included), list | ✓ | ✓ | ✓ | everywhere |
| `all_files` | every conversation's files by id, with no scope or age check while the bytes exist | ✓ | ✓ | ✗ | home and home from outside |
| `list_files` | list or search other conversations' files | ✓ | ✓ | ✗ | home and home from outside |
| `disk` | files on the computer outside her data (a disk path to `read_image`, `read_file`) | ✓ | ✗ | ✗ | home only |
| `commands` | `sandbox_run` (the owner's own user, his ssh and git keys) | ✓ | ✗ | ✗ | home only |
| `credentials` | the credentials a command may carry | ✓ | ✗ | ✗ | home only |
| `local_network` | `web_fetch` and commands reaching the owner's own network (scope `any`) | ✓ | ✗ | ✗ | home only |
| `internet` | `web_fetch`, `web_search` on the public internet (scope `public`) | ✓ | ✓ | ✓ | everywhere |
| `integrations` | the owner's integration tools, by profile where earned (`integration.event_profile`) | where earned | ✗ | ✗ | home only |
| `development` | self-development tools where earned (`grants.for_whose`) | where earned | ✗ | ✗ | home only |
| `drawing` | `generate_image`, `render_svg`, her private-words list | ✓ | ✓ | ✓ | everywhere |
| `send_any` | send any stored file or picture to any conversation she may speak in | ✓ | ✗ | ✗ | home only |
| `send_to_asker` | send any stored file or picture to the conversation the work is for | ✓ | ✓ | ✗ | home and home from outside |
| `send_own` | send this conversation's own files there | ✓ | ✓ | ✓ | everywhere |

`disk` is its own row because a file on the computer can be a key (`~/.ssh`): with it under `all_files`, work for
someone outside could read a key it may not use. `integrations` and `development` take only home only or nowhere:
outside home there is no rule saying who earns them, so a wider level is refused when the setting is saved.

### 3.3 The setting and its page

The setting is `deployment.access`, one entry per resource whose level differs from the default:

```yaml
access:              # resource: home | home_from_outside | everywhere | none; a resource left out has its default
  commands: none     # example: no commands anywhere
```

- **Who sets it: the owner**, on the settings page (below) or in the profile's settings file. It is not one of her
  settings and no tool of hers writes it: a setting she could widen from a turn steered from outside would undo the
  table.
- **The page: the table itself.** The settings page Asuna already adds to DSH gets a section 「访问权限」/ "Access"
  drawn as §3.2's table (owner, 2026-11-25: "the table makes much more sense"): one row per resource with its words
  (§9), the three origins as columns, a tick box in each cell, ticked where the default allows. Ticking a cell ticks
  the cells to its left, unticking one unticks the cells to its right, so a row always holds one of the four levels and
  a table that contradicts itself (outside yes, home no) cannot be entered; `integrations` and `development` show their
  two outer cells as not available. A row away from its default is marked as changed, a row wider than its default
  also as wider (「比默认宽」/ "Wider"). The section is one field of DSH's own form (`deployment.access`), so staging,
  save, discard and reset are DSH's; the grid is the one new component, approved by the owner on 2026-11-25.
- **Checked when saved and at start.** An unknown resource or level, or a level that row does not take, is refused
  when the page saves (`core.validateSettings`) and stops the Host at start with its name, never a silent grant.
- **Said at start.** The Host's start report names each resource set wider than its default, once per start; nothing
  pops up.
- **When it applies.** The worker reads the table when it starts; a change applies at the next start (the page's
  existing apply/restart path), then to every call, a task already running included. Each call looks the table up;
  only the origin is stored on the work.

### 3.4 One place in the code

A module `access.py` holds the origins, the resources, the default table and the levels: `origin(store, task_or_turn)`
and `allowed(config, origin, resource)`. Each fence listed in §2 becomes a call to it (the ADR-135 guard rows that
decide by place included; its dead `_image_path` row goes), each tool names its resources in one table beside its
definition, and `coordinator._grants` gives a task the tools whose resources its origin allows. The table and the
levels go into `RUNTIME_API.md` as present behaviour.

## 4. A conversation's own files

- **What they are.** The stored rows whose `scope_key` is that conversation (received there, made there by her or
  its tasks, downloaded or saved there), and those **sent there**: a row sent to another conversation gains that
  conversation in `shared_scopes` when the message is accepted (one set-add, no copy of the bytes). Stickers stay
  `global-safe`, everyone's as today. A task's `/task` folder (per place and person, `grants.py:47-52`) is its working
  folder inside those files: what it saves there it registers into them.
- **Outside sees only its own.** By id or by name within its own files; an id from elsewhere gets the same answer as
  an id that does not exist (§9), so nothing tells it that a file exists elsewhere.
- **Home sees all.** Any row by id, no scope, age or "is it hers" check while the bytes exist; listing by
  conversation name, as `write_document`'s `group` already does from home (ADR-135 landing 9).
- **The 2026-11-24 case closes here.** A group's sendable pictures become its own files plus what home sent there; a
  picture drawn at home stands on no group's list until she sends it there (an errand, a visit that carries it, or a
  home turn's `send_any`), after which it is that group's.
- **Lifetimes do not change** (`media_life.POLICY`: her drawings kept, pulled copies 7 days, task files and received
  files by their own days). A new source prefix (a download, a frame) adds its row there. An erasure of a conversation
  (ADR-105) erases its own rows and removes its scope from other rows' `shared_scopes`.

## 5. The four directions on the table

| # | Direction | How | Resources |
|---|---|---|---|
| D1 | A stored thing's body by id | `received_file` takes a `blob-` id too: text read as today (1 MiB), any kind copied into `/task/stored/` with `do=copy` (the existing copy: name cleaning, the deny-execute folder, copy tracking for erasure); `read_file` and `read_image` then read the copy. | `own_files` or `all_files` |
| D2 | A public URL's bytes into `/task` | `web_fetch` gains `save`: a body of any type is written to `/task/downloads/<name>` (up to 20 MB, the type from its bytes, sha256 returned), registered into this conversation's files; the network line stays `fetch.js`'s, now set by `internet`/`local_network`. | `own_files`, `internet` |
| D3 | An old picture or file onto this turn's list | `offer_file` takes a stored id as well as a `/task` path; a picture's type becomes a picture for speak's `picture`, anything else a file part. The block `image_artifacts_from_program` lists this conversation's newest own pictures plus anything offered this turn (`offer`'s existing `picked`). Home offers any id. | `send_own`, `send_to_asker` or `send_any` |
| D4 | A viewed frame as a picture | `read_image` of a video takes `at` (seconds): the video child cuts that one frame (`media_children`), stored as this conversation's picture (source prefix `frame:`, 7 days unless sent); the grid stays as it is. It is then offered like any picture (D3). | `own_files`, then a send row |

## 6. The classifier sees what rides along

A note, an errand or a result that carries a stored file or picture puts one program line into the classifier's
question: 「附带：N 张图、M 个文件」 (counts and kinds, never a name). The judge then knows something goes with the
words. Text only is judged, as today; the line costs no extra request.

## 7. The image routes (ADR-124, merged 2026-11-11)

Her request on the agent line (0215, 2026-11-10), from her idea `idea-ff702804`: three verdicts on `generate_image`,
the action brain's drawing tool.

### 7.1 What is known

- `integration_image.list_workflows` drops every ready route whose `parameter_schema.required` names a picture other
  than `input_image` (`unsupplied`: an inpaint mask and the like). The route is not in what `list_routes=yes` returns,
  and nothing says it was left out. Asking for it by name is refused with `IMAGE_WORKFLOW_NEEDS_MORE_PICTURES`, whose
  note says it is not in the list.
- `generate_image` takes one picture, `source_image`, uploaded as the route's `input_image`. No other picture reaches
  the service; the runner already carries several files (`integration._trusted_run(files=…)`).
- Her reading (2026-11-09, three orders): every one of the 18 routes she was shown takes one picture; an inpaint route
  was refused for the missing picture and did not appear in the list. To her a hidden route reads as "the service
  cannot do this", not "I did not give it something".

### 7.2 Her three verdicts and their design

| # | Item | Her verdict | Design |
|---|---|---|---|
| R1 | `list_routes` lists the filtered routes too, each with the pictures it still needs | Take it | Each such route is listed with 「还要：<slot>」 per missing slot (§9); with R2 built, a slot `pictures` can fill is no longer missing. |
| R2 | A required picture slot other than the source open | Take it | `generate_image` gains `pictures: {<slot>: <ref or id>}` for the route's other required `*_image` slots; each is resolved through `picture_to_edit` with the same table as `source_image` (D1's resources), size-capped as `source_image` is, uploaded beside it and forgotten after the job as it is (`integration_image.py:213-230`, `341-360`). A mask she draws with `render_svg` is a picture of this conversation like any other. |
| R3 | Repeatable picture slots | Only after the service is shown to have a ready edit route driven by several pictures | Read the service's workflow list (metadata only, no drawing) at the build's start; no such route: R3 is dropped with that reading as its reason. |

## 8. Landings

One branch each from main, staged on an isolated stub profile, the full suite per landing; installed one at a time.

1. **The table.** `access.py` (origins, the 14 resources with their defaults, levels; `table`, `check`, `allowed`,
   `wider`, `origin_of_turn`, `origin_of_task`); a turn's origin from `guard.authority`, a task's written once as
   `origin` in `delegate` (a continuation, or a task made in a turn about another task, never wider than that task; a
   row without it computed by the same rule when read). The non-file rows decide through `allowed` at grant time and
   at call time: `commands` (`_grants`, `ToolBroker.call`), `credentials` (`credentials.home_task`, the broker),
   `local_network`/`internet` (the task's network and the binding, from the current table), `disk` (`read_image`'s
   path for both brains), `integrations` and `development` (today's rules and the table), `drawing`. The dead guard
   row `_image_path` goes. The file and send rows are in the table, the setting and the page; their fences are landing
   2's. §9's three refusal sentences; the setting `deployment.access`, checked at save and at start; the start report
   of wider rows (Host log, settings page); the settings section as the table. Behaviour changes only in the middle
   column (no commands, credentials, local network or disk for home from outside) and in the dead guard row's removal.
2. **Own files.** `shared_scopes`, the outside fences narrowed to own files, home's checks removed, the two offer lists
   by conversation (closes the 2026-11-24 case).
3. **D1 and D3.** Stored ids in `received_file` and `offer_file`.
4. **D2.** `web_fetch` `save`.
5. **D4.** A frame at a time.
6. **R1 and R2** (R3 read first).
7. **§6**, the classifier's line.

## 9. Her words (read by her 2026-11-25, agent line 0668)

Program words she sees, in her wording where she changed them. No part of her is named, no 他/她.

- A file from another conversation, asked for outside (the same answer as a missing one): 「这个对话里没有这个文件。」
- Commands, keys, the owner's network or a disk path in work for someone outside (her 0668: the subject fixed, so it
  is never read as an errand, which is home's; and a way on, so the work goes on with files instead of stopping):
  「这件是外面的人托的事：跑命令、用钥匙、连家里的网、读盘上的路径，都不在这件事里；这一步换个做法，文件照样能读、能用。」
  Not her proposed 「要跑命令，回家里那一拍办」: a home turn of hers for the same person is home from outside again, and
  doing the outside person's command as her own home work is the step this row exists to stop.
- A disk path, outside (her 0668: the trigger is a path in hand, not "files on the computer"): 「盘上的路径只在家里能读。」
- A send this origin may not make (her 0668: not to be read as a failed delivery): 「这个文件不归这个对话发。」
- R1, a route that needs more: 「还要：%s」, %s the name of the one missing thing only (「第二张图」), no adjective (her 0668).
- D2's result: 「存好了：%s（%s，%s，记在%s）」 (name, size, type, the conversation it belongs to: her 0668, so an id
  another conversation cannot reach is not later reported as never saved).
- The settings table (the owner's page, both UI languages): one line per resource from §3.2's "Covers"; the column
  heads 「家里」「外面托、家里办」「外面」 / "Home", "Home from outside", "Outside" (her 0668: one Chinese name for the middle
  column that cannot be read as 差事, an errand); the marks 「改过」「比默认宽」 /
  "Changed", "Wider".

## 10. Closes when

Built and installed in the order of §8, each landing shown by a staged case on the stub profile the day it is built:
outside cannot read, list or send another conversation's file and gets §9's sentence; home reads and sends any;
home from outside reads any file and is refused commands, credentials, the owner's network and the disk; a setting
changed on the page applies at the next start and a wider row is named in the start report; an unknown level is
refused at save and at start; D1-D4 and R1-R2 each carry a file end to end; the classifier's question carries 「附带」.
At each install she runs her own case for that landing on her live system the same day (her 11-02 bundle for D1),
and the page records what she saw. R3 closes by its reading.

## 11. Settled

- One general path, not one tool per direction: the four directions are uses of the file rows (§5).
- Which lane may move what: the table (§3).
- Size limit for fetched bytes: 20 MB (D2); a fetched or cut thing is recorded as an artifact of this conversation.
- Not here: the owner's 11-05 report (an image delivered, its text not), a question about sending, read on its own.
