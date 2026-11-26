# ADR-120: Bringing stored things back into the work

Status: **Decided** 2026-11-25 (the owner: one access table with three origins, each outside conversation its own
files, home everything, the table a setting shown as that table on the settings page; design big sis; her reading of
§9 done 2026-11-25, agent line 0668: landing 1 signed with her wording of its three sentences). Laid down 2026-11-09
from her request (agent line 0035, 2026-11-05: nine dated incidents with their idea ids, gathered into one class at
big sis's ask); ADR-124 (image routes, her request of 2026-11-10) merged in on 2026-11-11 at the owner's word, as §7.
Repro material: her 2026-11-02 four-part bundle, which she has kept.

Landing 3 (installed 2026-11-25, see §8) also fixes a fault found while building it: since `8685b0e09` (2026-11-10,
ADR-119 F4) `received_files` imported `media_life._moment`, which that commit removed, so every received-file read that
reached its answer, every `let_go`, and a `kept` list or over-quota `keep` holding a kept file raised ImportError. Her
records: 3 `received_file` calls from 11-10 to 11-25, all failed (last 11-20); 12 before, 6 of them answered. No fault
was reported. Fixed in `ea37a39b6e19` (`received_files` reads stored times with `clock.moment` itself); her 0693 asked
for it to be recorded here. With the default table `offer_file` by id never meets 「这个文件不归这个对话发。」 (a file a
task may read there is one it may send there); that sentence appears only when the owner narrows a send row.

Landing 2 installed 2026-11-25 20:52 (`632f729aa8ed`): own files per conversation, sends by origin, all 14 rows on the
settings table, table refusals in her review; her reading of its 16 texts (agent line 0684) and one change
(`received_file`'s home sentence, 0685). At install 11 of 24 outside groups had drawings of their own (382 in all);
the other 13 list none until she draws there or home carries one in. Landing 1 installed 2026-11-25 18:38 (`ae4b97ae3e35`): the table, origins on tasks and turns, the eight rows of
`access.IN_EFFECT`, the settings table; her §9 sentence for work from outside without 「换个做法」 (agent line 0669). Her
same-day case (0672): she reads table refusals apart from the guard's and the classifier's on the spot, but her
refusal review (`recall` `refusals`) does not list them; landing 2 adds them.

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
| `own_files` | this conversation's files (§4): read, save into them (web downloads included, from landing 4), list | ✓ | ✓ | ✓ | everywhere |
| `all_files` | every conversation's files by id, with no scope or age check while the bytes exist | ✓ | ✓ | ✗ | home and home from outside |
| `list_files` | list or search other conversations' files | ✓ | ✓ | ✗ | home and home from outside |
| `disk` | files on the computer outside her data (a disk path to `read_image`) | ✓ | ✗ | ✗ | home only |
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

The Host sandbox confines writes only, so `commands` also carries the owner's network, the database address and his
ssh and git keys; widening `commands` widens those with it.

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

- **What they are** (`own_files.py`, one function every fence asks). The stored rows whose `scope_key` is that
  conversation (received there, made there by her or its tasks, downloaded or saved there), and those **sent or
  carried there**: a row gains that conversation in `shared_scopes` (one set-add, no copy of the bytes, written outside
  the row's revision and kept by every write of it) when an outbound message carrying it is written for that
  conversation (`Coordinator.queue_reply`, before the row, so the byte endpoint always finds it so), and at pick time
  when an errand or a visit picks it for that place, by the picking turn, only where that turn's origin may send it
  there (`own_files.carry`: a visit runs as an outside turn, so without the share a picture home sent out would be
  refused there). An edit of a picture that came from a conversation is that conversation's (it goes back there); the
  conversations the owner linked to it (`context_links`) count as its own, as today; stickers stay `global-safe`,
  everyone's. A turn's own conversation is where it is, and for a home turn a note from outside opened, where the note
  came from; a task's is its binding. A task's `/task` folder (per place and person, `grants.py:47-52`) is its working
  folder inside those files: what it saves there it registers into them.
- **Outside sees only its own.** By id or by name within its own files; an id from elsewhere gets the same answer as
  an id that does not exist (§9), so nothing tells it that a file exists elsewhere.
- **Home sees all.** Any stored row by id, no scope, age or "is it hers" check while the bytes exist (`all_files`,
  home and home from outside by default). "No age check" is for stored files: a message's attachment ref (`att-…`) of
  any conversation is reachable for 7 days, as its pulled copy lives (`media_life.PULLED_DAYS`; past it there are
  usually no bytes), so a miss never scans a conversation's whole history.
- **What `list_files` decides now:** which home lists show other conversations' items. Where the turn's origin may use
  it, a home conversation lists as before (the owner's chat its own and linked pictures and her pictures from
  anywhere; a home group her pictures from anywhere and every conversation's files; her local chat her pictures from
  anywhere to look at); where it may not (a home turn a note from outside opened), only its own conversation's.
  Listing by conversation name is landing 3's (§8 item 3).
- **Sends** (`own_files.send_refused`). Into a home conversation is no crossing: whatever the work may read. Into an
  outside one: any file with `send_any` (home), any file into the conversation the work is for with `send_to_asker`
  (home from outside), that conversation's own with `send_own` (everywhere); else 「这个文件不归这个对话发。」
  (`ACCESS_DENIED_SEND`). The byte endpoints serve only the message's conversation's own files. An errand takes a
  picture or a file and a visit a picture by the same rule (it replaced "her 50 newest drawings only").
- **The 2026-11-24 case closes here.** A group's sendable pictures become its own files plus what home sent there; a
  picture drawn at home stands on no group's list until she sends it there (an errand or a visit that carries it),
  after which it is that group's. A picture someone sent in a group is that group's own: sendable there, not listed.
- **Pictures and files sent before this landing** were shared by a one-off backfill run between her Host's stop and
  the new worker's start, 2026-11-25 20:52 (every outbound line carrying a picture or a file shares it into its
  conversation): 857 lines, 463 of them stickers (left out), 376 file and conversation pairs, 304 already that
  conversation's own, 72 shared; its dry run gave the same. The tool was deleted after the install (it is in
  `632f729aa8ed`).
- **Lifetimes do not change** (`media_life.POLICY`: her drawings kept, pulled copies 7 days, task files and received
  files by their own days). A new source prefix (a download, a frame) adds its row there. An erasure of a conversation
  (ADR-105) erases its own rows and removes its scope from other rows' `shared_scopes`.

## 5. The four directions on the table

| # | Direction | How | Resources |
|---|---|---|---|
| D1 | A stored thing's body by id | `received_file` (both brains) takes a `blob-` id as `ref` (kinds `image`, `file`, `received_file`), through `own_files.stored`: outside another conversation's id answers as a missing one (`RECEIVED_FILE_NOT_FOUND: 这个对话里没有这个文件。`) and is recorded (`all_files`). `do=read`: a received file, or a task's file that is text within 1 MiB, in pages as today; anything else said for what it is (kind, type, size), a picture with `read_image`, and how to copy it. `do=copy` (the action brain): any kind into `/task/stored/` with the existing copy (name cleaning, the deny-execute folder, copy tracking; `drop_copies` now takes the copies of all three kinds). `read_file` reads the copy; `read_image` of a `/task` path is the `disk` row (home only), so outside a picture is read by its id. | `own_files` or `all_files` |
| D2 | A public URL's bytes into `/task` | `web_fetch` (the core registers DSH's tool with one more argument, `fetch.js` `registerWebFetch`) gains `save`, a file name or `true`: a body of any type is read as bytes on the same line as a page (`SlimFetch.download`: the same two providers, the task's scope, the same refusal of a local address), at most 20 MiB (over it, declared or read, refused and nothing kept), and handed to the worker with the call (`ToolBroker.call`'s `body`, base64 in the one worker line, never in its record). The worker (`downloads.py`) writes it to `/task/downloads/<name>` (the name made safe as a received copy's, ` (2)` for a name that exists), reads its type from the bytes and registers it in the task's conversation (source `download:`, kept as a task file is): a picture as an `image` row, anything else a `file` row, neither listed until `offer_file` offers it by id. She reads 「存好了：…」 with its id, its path and the sha256. Without `save` nothing changes, and a body that is not text is told it can be saved. | `own_files`, `internet` (or `local_network`) |
| D3 | An old picture or file onto this turn's list | `offer_file` takes `artifact_id` (a stored id) in place of `path` (`outbound_files.offer_stored`): readable as D1, sendable into the task's conversation (`own_files.send_refused`, else 「这个文件不归这个对话发。」), then shared into it. A picture (kind `image`) goes on the picture list, a task's file on the file list as it is, a received file is registered as a file of the task (its sender kept). The turn about the task lists what the task offered first on both blocks, whatever its age (`outbound_files.offered_by`, from the task's done `offer_file` calls, passed as `picked` with a going-out's pick). At home the list is a convenience, not a gate: a home turn's `speak` picture and file parts take any id it may read and send there; outside, the list gate stays as it was. | `send_own`, `send_to_asker` or `send_any` |
| D4 | A viewed frame as a picture | `read_image` (both brains) takes `at` (seconds, a number of 0 or more) with a video's `att-` ref: the video is pulled again by its ref as for the grid (its 32 MB, the ref's 7 days, the origin's reach), and the video child cuts that one frame by the seek a grid's cell uses (`media_children.video_frame`: the moment on a cell's label gives that cell's frame), at its own size up to 1920 px on its long edge, as a JPEG. It is stored as a picture of the turn's or task's own conversation through the picture registration, source `frame:<ref>:<ms>` (`media_life.POLICY`: as a pulled copy, 7 days unless a message names it); the same `at` on the same ref there reads that row back, with no second download. She sees the frame and 「截好了：视频第 <at> 秒这一帧（<w>×<h>），记在<the conversation>」 with its id and how to send it from where she is: a task by `offer_file`'s `artifact_id`, a home turn by `speak`'s picture; elsewhere the frame is not on the turn's list (it is the conversation's own, not listed, as a picture someone sent there), so a task offers it (D3). `at` past the end, on anything but a video, and a video that can no longer be pulled are said in words; the grid is never the answer to `at`, and without `at` nothing changes. | `own_files` (the ref read by `own_files` or `all_files`), then a send row |

## 6. The classifier sees what rides along

A crossing the classifier judges that carries stored pictures or files puts one program line into its question, right
after the kind of text: 「附带：N 张图、M 个文件」 (counts by kind, never a name, an id or a path; a kind with none is left
out, 「附带：2 张图」, and with nothing riding along there is no line). The judge then knows something goes with the
words. Text only is judged as before: the same question byte for byte, one request per crossing, the same verdicts
and modes. The line is in the question, after the fixed system text (the policy), so the cached prefix is unchanged;
the policy texts do not change. Only the classifier reads the line; her review shows the judged text, not the question.

What each crossing can carry (read from the code, main `76dc8ad33381`):

| Crossing | Judged (ADR-135 D9) | What rides along | Counted from |
|---|---|---|---|
| A note, into or out of home | yes | nothing: `note` takes text only | none |
| An idea written outside | yes | nothing | none |
| An errand | yes | one picture or file (`artifact_id`, kinds `image`, `file`), checked and shared there by the call (`own_files.carry`) before it is judged | the call's `artifact_id` |
| A task's result shown outside | yes | the pictures and files the task offered with `offer_file` (every revision), the ones its result turn lists first | `outbound_files.offered_by` |
| A visit | no | one picture | none: D9 does not read visits |

Only rows whose bytes are still stored are counted (`classifier.carried`). Stickers do not ride on these crossings
(they are sent by name in `speak`); a sticker's row (`global-safe`) named by an errand is not counted, being
everyone's. `classifier.asked` records the counts (`carried`). The operation key of a question is the hash of the
question, no longer of the text alone, so two crossings of one turn with the same words and different attachments are
two questions, each with its own session and receipt.

Not built: a picture a task drew (`generate_image`, `render_svg`) and did not offer is not counted: it is that
conversation's own from the moment it is drawn and is listed as its pictures are, not carried by the result. Whether
the conversation's channel can send what rides along (a direct chat lists no files) is the send path's; the count is
what the crossing carried there. The outbound policy (`classify_outbound.md`, the owner's words) names the reminder line
and not this one.

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
| R3 | Repeatable picture slots | Only after the service is shown to have a ready edit route driven by several pictures | Dropped 2026-11-26 by the reading: no route declares a picture parameter that takes several pictures (each takes one, and R2 fills every declared one by name); a route that does is a new page. |

R3's two readings (2026-11-26, the service's workflow list, metadata only, nothing drawn), both stopping at what the
schema declares:
- Big sis's, 17:49 (local evidence `.runtime/private/adr120/r3-reading-1126.md`, 3.5 KB): 22 routes, all ready. 2 draw
  from text only; 16 take `input_image` only (one edit route requires it, 15 text-to-image or image-to-image routes
  take it optionally); 2 inpaint routes require `input_image` and `mask_image`; 2 face-reference routes require
  `face_image` and declare neither `input_image` nor a text-to-image mode. Every picture parameter is a single string.
- Hers (agent line 0712, 18:05), of the same listing (22 routes, 422,935 bytes, sha256
  `205628c20aa36c4cc230a742186d9ddc5ac394f596e6f950df67f517012a83ac`), the whole `parameter_schema` walked: no `array`
  type, no `items`, `maxItems` or `minItems`, no array default; the picture parameters are only `input_image` (18
  routes), `mask_image` (2) and `face_image` (2), each a single string. Routes with a required picture: 5 (the 2
  inpaint, `input_image` and `mask_image`; the 2 face-reference, `face_image` only; 1 edit, `input_image`).

## 8. Landings

One branch each from main, staged on an isolated stub profile, the full suite per landing; installed one at a time.

1. **The table.** `access.py` (origins, the 14 resources with their defaults, levels; `table`, `check`, `allowed`,
   `wider`, `origin_of_turn`, `origin_of_task`); a turn's origin from `guard.authority`, never wider than the task a
   turn is about (so the result turn of home-from-outside work is home from outside); a task's written once as
   `origin` in `delegate` (a continuation, or a task made in a turn about another task, never wider than that task; a
   row without it computed when read by the same rule from the turn that made it, or from its place when that turn is
   gone). The rows in effect (`IN_EFFECT`: `disk`, `commands`, `credentials`, `local_network`, `internet`,
   `integrations`, `development`, `drawing`) decide through `allowed` at grant time and at call time: `commands`
   (`_grants`, `ToolBroker.call`), `credentials` (`credentials.home_task`, the broker), `local_network`/`internet` (the
   task's network and the binding, from the current table), `disk` (`read_image`'s path for both brains),
   `integrations` and `development` (today's rules and the table), `drawing`. The dead guard row `_image_path` goes.
   The six file and send rows stay in `RESOURCES` with their defaults, are not drawn on the page, and a setting that
   names one is refused (`INVALID_ACCESS: <row> is not in effect yet`); landing 2 moves them into `IN_EFFECT` with
   their fences. §9's three refusal sentences; the setting `deployment.access`, checked at save and at start; the
   start report of wider rows (Host log, settings page); the settings section as the table of the rows in effect.
   Behaviour changes only in the middle column (no commands, credentials, local network or disk for home from
   outside) and in the dead guard row's removal.
2. **Own files.** `own_files.py`; `shared_scopes` (added when the outbound message row is written, and at pick time
   for a going-out; removed by an erasure; the backfill for what was sent before); the outside fences narrowed to own
   files, an outside read of another conversation's file answered exactly as a missing one and recorded apart; home's
   scope, age and "is it hers" checks removed for stored files (`all_files`; a message's attachment ref of any
   conversation for 7 days); the sends by origin and target, the errand's and visit's
   picture by the same rule; the two offer lists by conversation (closes the 2026-11-24 case). All 14 rows apply and
   are drawn on the settings page (`IN_EFFECT` goes: no row is left out). Every refusal by the table leaves one audit
   row `access.denied` (the plugin's two, a tool not given for the origin and a local address, through `guard.task`),
   and her refusal review lists them (her 0672, 0681), marked 「这里不许：<row>（<column>）」 in her words for the row
   (盘上的路径、跑命令、凭据、家里的网、公网、主人的集成、自我开发、画图、这个对话自己的文件、别的对话的文件、翻看别的
   对话的文件) and the column (家里、外面托、家里办、外面), every send 「这里不许：把这个文件发到这里（<column>）」, so a row
   the owner narrowed is seen at home before it is met again.
3. **D1 and D3.** Stored ids in `received_file` and `offer_file` (§5); `received_file` `do=list`: a conversation's
   stored files and pictures (not stickers), newest first, at most 20, each with its id, kind, name or type, size,
   when (her clock) and whether its bytes are still there; without `place` this conversation's own, with `place` a
   group by its name, resolved as `write_document`'s `group` (ADR-135 landing 9, the resolver moved to
   `places.group_named`; unknown and ambiguous names with those words, the field and the verb its own), only where the
   origin may use `list_files`. Elsewhere `place` is refused by the table (`ACCESS_DENIED_LIST_FILES: 这一步这里用不了。`,
   recorded), one answer whatever it names: the unknown-name sentence lists every group's name, which an outside turn
   is not told. Searching by name is not built: a list of 20 by id is the whole of it. Cost: the character brain's
   tools +215 characters declared (19,630 -> 19,845, inside its budget), the action brain's +567 (17,376 -> 17,943,
   budget raised). Found while building: from 2026-11-10 `received_files` imported a time reader ADR-119 F4 had
   removed (`media_life._moment`), so in the code every answer of a read received file, every `let_go`, and every
   `kept` list or over-quota `keep` with a kept file in it raised ImportError (read from the code, not from her
   records); fixed in its own commit with a test.
4. **D2.** `web_fetch` `save` (§5). The action brain's `web_fetch` is now the core's registration of DSH's tool (its
   schema, output text, cards and guidance kept; DSH's 30-second budget raised to 150 for a save's two minutes) with
   `save`, a string or a boolean: a name when she has one, `true` when the address's own will do. The bytes cross
   from the plugin to the worker in the one call that saves them, base64, as the existing byte paths cross (a persona
   job's snapshot, up to 8 MiB): at most 20 MiB, about 28 million characters, which the worker's reader thread reads
   and parses in about 64 ms (measured 2026-11-25 on this machine, 20 MiB of random bytes read from an in-memory
   stream, the pipe itself not timed); the decode and the writes
   run on the call's own thread. The table decides in the broker (`needs`: `save` needs `own_files`, the network as
   before), after the fetch: a save refused only by a narrowed `own_files` fetches its bytes and keeps nothing. A
   saved picture's bytes live as a task file's (`media_life.POLICY` `download:`); one a message names is kept, as every
   picture is (the sweep's task-file branch asks the same `named` rows the picture branches ask). Cost: the action
   brain's `web_fetch` as it is sent +175 characters (242 -> 417, measured on the two registrations). Not built: the
   `/task/downloads/` folder is a folder of the task like any other (no deny-execute entry, its files not removed with
   the stored bytes), and the address's `Content-Disposition` name is not read.
5. **D4.** `read_image`'s `at` (§5), in the one function both brains call (`vision.read_image_for_task` →
   `video_frame`). The frame is cut in the video child as a second job beside the grid (`media_worker`'s `frame` job,
   `animated.video_frame`; one try 60 s, 120 s in all, so a hung frame holds the video child's other jobs at most that
   long), never in the worker; out of a running Host (tests, tools) it is cut in the process. Storing it needs
   `own_files`, asked before the pull (`ACCESS_DENIED_OWN_FILES`, recorded, where the owner narrowed it). One copy per
   conversation, ref and moment: the source key is looked up in the turn's or task's scope before any pull. Its result
   says how to send it from where it was read (a task: `offer_file`; a home turn: `speak`'s picture; any other turn: a
   task's `offer_file` first, since an outside turn sends only what its list holds and a frame cut now is not on it).
   Cost: `at`'s field +104 characters declared in each brain (the character brain's tools 19,845 -> 19,949, inside its
   budget; the action brain's 17,943 -> 18,047, budget raised). Staged 2026-11-26 on the demo (`asuna_v2_demo_l5`,
   stub model, a 造的 3-second video of three colours from a local host): at home, a line on the demo's agent line
   carrying the video, her `read_image` at 1.5 gave the 320×240 frame of the second colour, cut in the video child and
   stored as the line's own picture (`frame:<ref>:1500`); her `speak` picture sent it and the line received it, its
   sha256 verified; the same moment again read the row back with no download (the video host's log); `at` 9, a link
   answering 404, `at` on a stored id and `at` -2 were each said in words. Outside, on a seeded group with no channel
   route (the code run on the demo's database, the video pulled over HTTP): a task's cut stored the frame as the
   group's, not on its list until the task offered it by `artifact_id`, then first on the list of the turn about the
   task and sendable there; another outside group asking for that video was answered as for a ref that names nothing,
   recorded. Not built: the time of the frame given when `at` falls between two frames (the frame at or after it, as a
   cell's) is not said; `at` takes no animated picture (refused as not a video); a video's pull refusals keep the grid's
   words, which say 图 (这张图没拉下来…); the outside talking side's sentence was read from the code, not staged live
   (the demo has no outside channel).
6. **R1 and R2** (R3 dropped by its reading, §7.2). `generate_image` takes `pictures`, `{name: ref or artifact_id}`,
   at most 4 and only with `workflow` (without one the service picks a text-to-image or a one-picture edit route,
   which takes no other picture): a workflow's other declared `*_image` parameters, required and optional alike
   (`integration_image.picture_slots`). Each is read as `source_image` is (`picture_to_edit`: `read_image`'s fence for
   the task's origin, `own_files`, `all_files` or `disk`, and its size cap; outside, another conversation's picture
   answers as a missing one), uploaded beside the source under the same name prefix, passed as that parameter and
   removed after the job (a queued job's are swept by a later call, as the source is). Refused before any upload: a
   name the workflow does not declare (`IMAGE_PICTURE_NOT_IN_WORKFLOW`, with the pictures it takes) and a required
   picture not given (`IMAGE_WORKFLOW_NEEDS_MORE_PICTURES`, kept with new words; it names `source_image` too when that
   is also missing). A workflow with no `input_image` and no text-to-image mode draws from the prompt and its pictures
   (the face-reference routes). A drawing made from someone else's picture goes back where the first such picture came
   from (the source first), as an edit of it does; her own mask or face picture leaves the drawing hers.
   `list_routes=yes` lists every ready workflow (the filter on `unsupplied` and on text-to-image or source gone):
   `pictures: {name: 'required' | 'optional'}` beside `source_image`, with the workflow's own description of the
   picture after a colon when it has one, and `needs: ['还要：<name>']` (§9) for an input the workflow requires that
   `generate_image` does not send (`integration_image.CARRIED`); on the service's listing of 2026-11-26 no route has
   one, so `needs` is shown on none. `IMAGE_WORKFLOW_TAKES_NO_SOURCE` now says which pictures the
   route takes (its old note said "draws only from text", false for a face-reference route). Cost: the action brain's
   tools +202 characters declared (18,047 -> 18,249 on top of landing 5, budget raised); the listing, measured on the service's own
   metadata (2026-11-26, `list_workflows` of main and of this landing on the same listing, nothing drawn),
   24,179 -> 29,840 characters (18 -> 22 routes; at an estimated four characters a token about 7,500 tokens, inside
   the 12,500 that DSH carries inline, `maxInlineTokens`), its note +80 (204 -> 284). Not built: the routes' other settings (her skill reads `mask_channel`, `grow_mask_by` and `denoise` on
   the inpaint routes and `input_fit` on face-reference): `options` still takes only `steps`, `cfg`, `sampler_name`
   and `scheduler`, so the service's defaults apply.
7. **§6**, the classifier's line. `classifier.question` takes the counts (`carried`) and puts 「附带：…」 after the kind
   line, before the program's reminder; `classifier.carried` counts the stored pictures and files a crossing names
   (stickers and rows without bytes left out); `after_call` passes an errand's `artifact_id`, `after_result` the ids
   its task offered (`offered_by`); `classifier.asked` keeps `carried`; the operation key hashes the question. Staged
   2026-11-26 on an isolated stub profile (database `asuna_v2_demo_l7`, every route on the stub, no model key, the classifier in
   `stop`; an outside group on the QQ kind with synthetic ids, its lines posted on the channel API as an adapter
   would, no adapter running): a member's task rendered a picture and offered it and a text file; the stub received
   「这段文字是：一件事的结果，要在外面给人看」 then 「附带：1 张图、1 个文件」; its flagged verdict stopped the result turn
   (`SUPPRESSED`, `CLASSIFIER_HELD`). A second task offered nothing: its question had no line, clear, its turn ran. One
   classifier request per result. The demo was removed after.

## 9. Her words (read by her 2026-11-25, agent line 0668)

Program words she sees, in her wording where she changed them. No part of her is named, no 他/她.

- A file from another conversation, asked for outside (the same answer as a missing one): 「这个对话里没有这个文件。」
- Commands, keys, the owner's network or a disk path in work for someone outside (her 0668: the subject fixed, so it
  is never read as an errand, which is home's; her 0669: no "换个做法", which would invite retrying the refused step
  another way, against her own rule; the sentence says which part is not done and that files still work):
  「这件是外面的人托的事：跑命令、用钥匙、连家里的网、读盘上的路径，都不在这件事里；文件照样能读、能用。」
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
