# ADR-107: who may talk to her, designed to the end

Written 2026-10-29 from a read of [README.md](README.md) against main `196b6f6bbeaa`, with the owner's two answers of
the same day (decisions 5 and 6), reviewed by a fresh reviewer against the code (section 2), and built on branch
`claude/happy-meitner-vrg19f` (section 10 says what was run and what is left). Every count below was read from command
output on that commit. Where this page and the README differ on a detail, this page is the later one.

## 1. What the README's plan did not say

The README's direction stands: the core decides, once; a channel package forwards and acts on the answer; open is the
default for new deployments only. These are the places where the code said something the plan had not, with what the
design does about each.

Counts (main `196b6f6bbeaa`, `git grep -c` on that tree):

- The NapCat adapter holds **70 lines** of admission decisions outside its self-test: `config.py` 48, `catchup.py` 5,
  `inbound.py` 5, `notices.py` 4, `outbound.py` 3, `members.py` 2, `service.py` 2, `mutes.py` 1 (pattern
  `route_for_sender|route_for_group|route_for_target|route_by_id|is_group_member|accepts_sender|is_allowed_private|
  \.blocked_senders|\.blocked_groups|\.allowed_groups|\.allowed_private|\.admission|\.routes\b|catchup_routes`). Its
  self-test names the same on 58 lines (114 with the words `admission`, `allowed_`, `blocked_`).
- The core reads the mode or a block list on **22 lines in 8 files** (`channel_admission` 3, `channels` 3, `grants` 4,
  `group_members` 1, `host` 3, `native_settings` 2, `native_worker` 3, `places` 3; pattern
  `get('admission')|['admission']|blocked_senders|blocked_groups` over `src/asuna/*.py`).
- **No unit test called `admit`, `restore_admissions` or `prepare_admission`**. The core's decider was untested; the
  only tests of the policy were the adapter's self-test (`pass=409 fail=0 skip=3` offline at that commit), which
  tested the copy this ADR removes.

| # | Finding | What the code says | What the design does |
|---|---|---|---|
| F1 | "Every event reaches the core" is priced as one LAN request. The real price is higher. | The adapter spools and fsyncs every accepted line, then **prepares it before posting** (`service._prepare`: profile lookups, voice fetch). The incident below is a lookup after admission. With the copy removed and nothing in front, a stranger's line in a group that is not admitted costs a spool write and platform lookups, to be refused at the end. | An **admission query** answered by the core, pure, with a time-to-live the core names (section 4.1). The lane asks before it prepares and reuses answers. |
| F2 | The core's decider had no tests of its own. | See the counts. | `tests/test_channel_admission.py` on a stand-in kind (section 9); it carries the cases the self-test held. |
| F3 | The deployment-wide mode applied to **every** channel, `agent` and `dsh` included. | `runtime_settings` set `channel['admission']` on each channel. An `auto-dm-<name>` route id posted with the channel token on an `agent` or `dsh` channel is admitted today under `automatic`; a refusal came only where the posted id named an existing route (`CHANNEL_GROUP_DENIED`), by accident. | A kind declares `OPEN_ADMISSION`; the core applies the mode only to kinds that declare it (4.3, 5.2). |
| F4 | Decision 2's pin has a precise place. | `compose(defaults, prior)` lets the saved row win but writes a default into a saved row that stores none; a running profile that reads `explicit` because it never stored a value would be opened at its next install. A new profile is **not** "a profile with no Asuna row": `dsh plugin add` has already put a bare row there. | The pin lives in the setup tool and its discriminator is "no saved `deployment`" (8.1). Every code fallback stays `explicit`. |
| F5 | Member lists and catch-up for "the conversations the core admitted" need a way to read them. | `group_members.routed_group` refuses a list for a group with no route; an automatic-mode adapter fetched a list for **every group the account is in** and was refused for each group nobody had spoken in. Catch-up named core route ids. | The same query, in batch and by route id, and `GET …/routes` (4.1, 4.2). Members and mutes act only on a group the core already holds a route for (`known`). |
| F6 | Ending an admission by removing the member breaks six readers. | `chat.py:445` raises `INPUT_ROUTE_STALE` for a queued line whose sender left the route; `prepare_navigation` and `places.visitor` take the **first** member of a route to speak for it; `scene_records.authorize` is called at 29 sites and fails for a person not in `scene['members']`; `_route_scene` bumps the **policy epoch** for a member no longer in the route, which retires the group's native session. | An end is a **mark on the grant** (`ended_at`), not a removal (5.3). Nothing about the scene, its epoch, the roster or the person changes. |
| F7 | A DM that stops being admitted loses its route, which is also how she writes to that person. | `route_for_scene` is the outbound's only lookup; a plan for that person fails (`SCHEDULE_ROUTE_REVOKED`). | Owner decision 5: DMs never end by silence. |
| F8 | `inbound_rejected.jsonl` is one of every journal that grows without bound. | `Journal.append`, the one writer, never rotated; `peers.py` appended `peer_changes.jsonl` with its own `open`. | Rotation for the class, both writers (6.7). With the query in front a stranger's refused line is no longer journaled at all. |
| F9 | "Fail closed with an older core" was a constraint, not a design. | An unknown path answers `404 UNKNOWN_CHANNEL_ENDPOINT`. | Section 7. |
| F10 | "The folder is made when a task first needs it" has more than one place. | `host.prepare_channels` and `prepare_admission` made it. Where it is used as a working directory: `chat.py` (the task queue), `native_worker.py` (a lane's `cwd`); `Sandbox.__init__` already makes a task's own folder. | `grants.workspace_folder`, called at those two (5.5). |
| F11 | The mark Xiaoman asked for has a carrier. | `persist_input` stores the whole `event` on the line; `people.transcript` already puts program words after the time (`（补接）`). | `event['admitted']`, shown once after the time of its line (5.4). |
| F12 | The README left the Ns and the state names open. | | Settled: no silence rule (decisions 5, 6); the stored words stay (7). |
| F13 | A stale sentence in README section 4 ("the rule to test is item 3 under `Before building`; this line is kept for history"). | | README rewritten. The version Xiaoman read stays at blob `f5a314f83cca`. |

### The incident, as a design input

38 "member does not exist" errors came from lookups for people who had just posted, after a start of NapCat. What the
platform says about membership is wrong right after a start. So an admission ends only on the platform's own leave
notice (decision 6); the core never reads a member list to admit or end anyone; the adapter's lookups run after the
verdict, never before it, and a failed lookup changes nothing about admission.

## 2. What the review changed

A fresh reviewer read the first version of this page against the code (read-only, told what to look for) and returned
20 findings, 3 of them blockers. All 20 were checked; each is handled in the sections named.

| Review finding | Handling |
|---|---|
| B1 A returning member cannot be re-admitted: `prepare_admission` checks the grant's own folder against the folders already collected and refuses it (`CHANNEL_WORKSPACE_OVERLAP`). | Found again by the contract test while building. A return skips the preparation (its scene, identity and folder are unchanged) and only clears the mark (5.3). |
| B2 The managed adapter would not come back after the install: the integration profile's fingerprint includes the derived `adapter_config`, and a Host start refuses a changed one (`PROFILE_CHANGED_RESTART_REQUIRES_EXPLICIT_START`). | Checked in `integration.py`. Landing 2 changes the derived settings, so it needs `integration_start` and a read of `restoration_error` (section 10). Landing 1 does not touch them. |
| B3 A departure racing an earlier line: a line spooled before the leave reaches the core after it and would undo the end. | `ended_at` is the platform's time of the leave; a line the platform dated at or before it is a member's line and leaves the mark (5.3). Caught-up lines are the same case. |
| S4 A refusal deletes the spooled line with no row, and nothing invalidates what was kept. | The answer carries the core's start (`epoch`); a change, or any answer of "away", drops everything kept; the endpoints answer 503 while settings are applied (4.1, 6.1). |
| S5 "`judge` says admitted exactly when `admit` succeeds" is false: `admit` also runs the preparation's bindings. | The property is scoped to the policy checks; the bindings stay `admit`'s and surface as a 4xx at the post (4.1, T1). |
| S6 `judge` runs in HTTP threads outside the fence. | It reads `list(routes.items())`, a copy, and the shared records are read with `.get` (5.1). |
| S7 Member lists and mutes would still fetch for a group the core only *will* admit. | They act on `known` only (6.3). |
| S8 The lane key change was incomplete (watch, seen set, catch-up). | All three use the conversation key; old spool files need no conversion because the key is derived from `group_id` or `sender_id` (6.2). |
| S9 Removing the adapter's target checks removes the only claim-time barrier for admin actions. | `group_admin.claim` checks the route and the block list when an action goes out (a stale one is marked `FAILED`); the adapter keeps its shape check (digits) (6.3). |
| S10 "No saved row" cannot discriminate a new profile. | Adopted: "no saved `deployment`" (8.1). |
| S11 Ten suites import adapter internals; real kinds' declarations and the mark's chain are untested; the persona's probes use `cfg.routes`. | Eight suites were ported (section 9). Tests added for the declarations, the chain and a stale line. `packages/personas/xiaoman/integration/probe_catchup.py` and the adapter skill pages are hers: told to her through the agent line (section 10). |
| S12 Departures must not share the home poster's thread and must come before the not-shown return. | Own class and thread, hook first in `on_notice`, raw `user_id` read; `event_id` goes to the audit row, `occurred_at` to `ended_at` (6.4). |
| S13 Define what a held or dropped notice does to the mark. | It uses the mark up; said in RUNTIME_API (5.4). |
| S14 Open to Closed drops the restored routes, which contradicts "DMs never end". | Stated as the owner's act: closing drops them at the next start, the rows stay, opening again restores them (RUNTIME_API, Admission). |
| S15 Error classes of the ask were unclassified. | 5xx and a transport failure and 403 `CHANNEL_AUTH_REQUIRED` are "away"; 404 is "unsupported"; any other 4xx is "rejected" (6.1). The bridge holds the event on 404 and on away (7). |
| S16 "Bounds every journal" was false (`peers.py`). | Both writers rotate (6.7). |
| S17 Landing 1 mixes a refactor with behaviour changes. | The extraction of `admit`'s checks was proven identical before anything else was added: 840 cases (both modes, block lists, route ids, listed and unlisted senders and groups) gave the same result from the old and the new function. The commits are ordered so (section 10). |
| N18–N20 counts, line numbers, blob, F3's wording, `DEVELOPMENT.md` and `tools/README.md`, an exit code for the pre-install check, "the core never parses ids", `known:false` carries a configured route's id. | Corrected in place; `--require-admission` exits 1; the core owns the `auto-…` scheme (4.1); `judge` returns the holding route's id. |

## 3. In plain words

A person writes to the account. The adapter, which knows only QQ, asks the core one question: "may this sender speak
in this conversation?" The core answers admitted, refused or blocked, and for how long the answer may be reused. If
admitted, the adapter does its platform work (looks the person up, fetches a voice) and posts the line; the core
decides again when it takes the line, and that decision is the one that counts. If refused, the adapter drops the line
and counts it. The adapter has no list of people, no list of groups, no block list, and no idea whether the deployment
is open or closed.

Open admits any DM, any group the account is in, and any member, on the first line, with no owner standing. Closed
admits only what the owner listed. Block lists win in both. A member who leaves a group is marked as having left; when
they write again they are admitted again and her context says so once.

## 4. Decisions

1 to 4 are the README's (2026-10-27). 5 and 6 are the owner's of 2026-10-29. 7 to 9 are this design's.

1. **The core decides, once.**
2. **Open is the default for new deployments only; a running deployment keeps what it reads.** The pin is in the setup tool (F4).
3. **Admission first;** moving routes and her per-conversation rules out of the core's settings is the next ADR.
4. **Admission gets its end, and a folder is made when a task needs it.**
5. **A DM never ends by silence.** She keeps the ability to write first to anyone who has written to her and to keep a plan for them; nothing is gained by ending a one-member conversation. (Owner.)
6. **A group member's admission ends only on the platform's leave notice.** No silence rule, no sweep, no second N. A notice the adapter missed leaves a member as they were, which costs nothing. (Owner.)
7. **The stored words stay `explicit` and `automatic`;** the settings card says Closed and Open. A rename would need a conversion of every saved profile and buys no behaviour.
8. **The setup tool writes `automatic` for a profile with no saved deployment, and `explicit` into one that has a deployment and stores none.** Every code fallback stays `explicit`.
9. **Open applies to the kinds that declare it** (`OPEN_ADMISSION`), never to a home line.

## 5. The core's public interface for a channel

Documented once in RUNTIME_API ([Admission](../../../RUNTIME_API.md#admission) and the three endpoints after it) and exercised by
`tests/test_channel_admission.py`. A package implements it without the core knowing its platform.

### 5.1 `POST /v1/channels/{channel_id}/admission`

Asks what the core would do with a sender or a conversation. **Pure:** it writes nothing and creates no route, folder,
identity or scene. Body limit 256 KiB; unknown fields are refused; a route key cannot reach it.

- `{account_id, asks: [...]}`, 1 to 200 asks; each has exactly one of `conversation` (`{type: dm|group, id}`) or
  `route_id`; `sender_id` only with a `conversation`, and it is a group ask's sender (a DM's sender is its `id`).
- Answer `{answers: [...], epoch}`, one per ask, in order: `admitted` (`route_id`, `conversation`, `known`,
  `ttl_seconds` 300 when known and 60 when open admission would admit it on its first event, under the id of the route
  that already holds the target if there is one), `refused` (`CHANNEL_IDENTITY_DENIED`, `CHANNEL_SENDER_INVALID`,
  `CHANNEL_GROUP_DENIED`, `CHANNEL_ROUTE_NOT_AUTHORIZED`) or `blocked` (`CHANNEL_BLOCKED`), each with `scope`
  (`sender` or `conversation`) and `ttl_seconds` 60.
- A wrong account is 403; a malformed ask is `INVALID_ADMISSION_ASK` (400); while settings are applied or the worker
  stops it is 503 (`HOST_RECONFIGURING`), so a refusal is never given from a half-applied configuration.
- The core owns the `auto-…` scheme and answers it; a package never builds one.
- It answers the **policy** (the account, ids, block lists, the route and member, the mode). The bindings the
  preparation checks (a scene id distinct from the others, folders that overlap, an identity bound to another account)
  stay `admit`'s own and surface as a 4xx at the post; they are listed in the code, not here.
- `epoch` names this start of the worker. Settings are applied by a new start, so a package that sees it change drops
  every answer it kept.

### 5.2 `GET /v1/channels/{channel_id}/routes`

`{routes: [{route_id, conversation}], epoch}`: every route, listed or admitted, that no block list stops. Catch-up reads
it for `"all"`.

### 5.3 `POST /v1/channels/{channel_id}/departures`

A person is no longer in a group. `{account_id, conversation: {type: "group", id}, sender_id, event_id?,
occurred_at?}`; unknown fields refused. Answer `{status: "ended"}` when an admitted member was marked, `{status:
"unchanged"}` otherwise (no route, a listed member, an unknown sender, a mark already there). It never creates
anything. A DM is `INVALID_DEPARTURE`.

### 5.4 What a kind declares

`OPEN_ADMISSION = True` (optional, default False; the shipped `qq` and `qqbot` set it, `agent` and `dsh` do not). The
existing names stand. The deployment's `channelAdmission` applies to a channel only when its kind declares it.

### 5.5 What a package sends, and what the core answers and keeps

- **Sends:** events as today (`route_id` from an admission answer, or a listed route's), admission asks, departures.
- **Answers:** a verdict it can act on and reuse within `ttl_seconds`; at an event, the existing statuses and codes.
- **Keeps:** the mode, block lists, the owner, routes, members and their ends, her per-conversation rules.
- **The package keeps** only what reaches its platform: addresses, tokens, media modes, member-list refresh, catch-up
  look-back. None of it is a core setting.

## 6. The core

### 6.1 `channel_admission.py`

One rule, two uses. `_checked` is the existing sequence (account, sender and group validity, block lists) and raises the
existing codes; `judge` turns the outcome into a verdict and reads only; `admit` is `_checked` followed by the writes it
made before, in the same order. `admit` returns `(route, mark)`. A grant made by `admit` is told from a listed one by
`admitted(grant)` (its folder name starts with `auto-`, the test `_in_this_data_folder` already used).

### 6.2 The mode

`mode(channel_id, channel)` is `automatic` only when the channel says so and its kind declares `OPEN_ADMISSION`;
otherwise `explicit`. `channels._receive`, `restore_admissions` and `host._route_scene` ask it. A start records
`channel.admission_closed_by_kind` for a platform kind that the deployment opens and that cannot be (a kind installed
beside a newer core): that is the one way a newer core could close a deployment unseen.

### 6.3 The end of an admission

`depart` runs under `ingress_lock` (a change to the route in the configuration; no network or process work). For an
admitted grant of a group route it sets `ended_at` (the platform's time of the leave, else the core's) in the
configuration and in the `channel_admission` artifact (revision-checked) and writes an audit row `channel.departed`. It
touches nothing else: not `scene['members']`, not the epoch, not the roster label, the identity, the lines or the folder.

`_member` treats a grant with `ended_at` as not a member for a line the platform dated after it. `admit` then clears the
mark and returns `returned`, without preparing anything again (its scene, identity and folder are unchanged). A line
dated at or before the end is a member's line: accepted, the mark kept.

### 6.4 What she reads

`event['admitted']` is `new` (the person has no label in that scene) or `returned` on the line that caused the
admission, nothing on any other. A notice that is held or dropped uses the mark up. `people.transcript` adds a phrase
after the time of that line from a versioned table (`ADMITTED_WORDS`, `ADMITTED_VERSION`): `new` 「第一次在这里说话」,
`returned` 「退群后又回来了」. No number, no date.

### 6.5 Folders

No folder is made at admission or at a start. `host.prepare_channels` and `prepare_admission` keep every check and drop
`mkdir`. `grants.workspace_folder` returns the granted path after `mkdir`, and `chat.py` (the task queue) and
`native_worker.py` (a lane's `cwd` where it is the person's folder) call it. `workspace_grant` stays a read.

### 6.6 Where she reads that the missing cap is deliberate (Xiaoman's ask 6)

One plain line in `stage_attend.md`, the gate's own prompt (where she decides whether to take a line): every admitted
line is asked of her once, the program sets no cap on them, deliberately, not forgotten; what to take and how much is her
judgement. It is 57 characters (`tests/test_tool_budget.py`: 445 to 502). Her prompt: it gets her reading and observation
time on real turns before the next step builds on it, and it lands on its own, last.

### 6.7 Admin actions

`group_admin.claim` checks, when an action goes out, that its conversation is still one the core serves and that no
block list stops it; a queued action that is not marked `FAILED` (`target_not_authorized`). The adapter no longer asks.

## 7. The NapCat adapter

### 7.1 One module that asks

`qqadapter/admission.py`: `Admission` with `cached` (no I/O, the reader thread), `ask`, `ask_many`, `ask_routes`,
`routes`, `forget`, `clear`. A bounded cache (4096), keyed by conversation and sender; an answer is kept for at most its
`ttl_seconds`; a conversation-scope refusal answers for every sender; one that admits answers for none. Three errors:
`AdmissionAway` (no answer, any 5xx, a reset, 403 `CHANNEL_AUTH_REQUIRED`; also drops everything kept),
`AdmissionUnsupported` (404 `UNKNOWN_CHANNEL_ENDPOINT`), `AdmissionRejected` (another 4xx). The timeout of one ask is
5 s, far inside `INBOUND_BASE` (120 s).

### 7.2 The inbound line

The reader thread keeps the platform checks that need no decision and consults `cached`: a refusal is dropped and
counted, a held admission fills in the route id, no answer spools the line without one. The spool key, the lane key, the
watch key and the seen set use the **conversation key** (`group:<id>`, `dm:<id>`), the same for a conversation's lines
whether or not their route is known, so order inside a conversation holds.

The lane (`_submit_one`) asks before it prepares: refused → the spool file is removed and counted, with no journal row;
admitted → the route id goes into the envelope and the spool file, the catch-up cursor is noted, then the line is
prepared and posted as before; away → it waits as for a host that is away, nothing dropped; unsupported → it waits, adds
a lane fault `inbound/admission/unsupported` and says so once a minute; rejected → counted like a host error and set
aside after the same number of tries. A 4xx at the post forgets the answer the line went on. Notices and catch-up rows
take the same path.

### 7.3 Platform work after the verdict

Member lists (`ask_many`, `known` only), mutes (the route check moves out of the reader thread: a cached refusal drops
the report, anything else is posted and the core refuses an unrouted group), home notices for a group (asked in the home
poster's thread: away goes through to its own retries, unsupported or rejected drops), catch-up (route names resolved
with `ask_routes`; `"all"` adds `GET …/routes`; away holds the run and it asks for itself again; the run notes the cursor
of every row it fed), outbound (the three target checks are gone; a shape check, digits, stays).

### 7.4 Leaves

`notices.departure` reads the raw `group_decrease` (`leave` or `kick` of someone other than the account) and
`Departures`, a class with its own thread, posts it: 5 tries, 5 s apart, then dropped and counted. `kick_me`, `disband`
and the account's own leave post nothing here.

### 7.5 What the adapter's configuration loses

`admission`, `blocked_senders`, `blocked_groups`, `allowed_private_user_ids`, `allowed_group_ids`, `routes`, `Route`,
`_cross_check`, `route_for_*`, `is_group_member`, `accepts_sender`, `is_allowed_private`. A leftover key from an older
deployment is ignored. The kind module's `adapter_config` derives only `napcat.account_id`. `group_routes` is gone from
`health.json` and the `STATUS` line.

### 7.6 Lanes, in the rules' own words

For a slow, a failing and a hung core: the asking lane waits, for its query timeout and then its own retry wait; only its
own conversation waits, and only its inbound work; a conversation with an answer held does not ask. The reader thread
never waits for the core. Members, catch-up, mutes, home notices and leaves each have a thread and skip a round or retry
by their own rule. What recovers a lane is its next try; what recovers an unsupported core is installing the matching one
(the fault row says so).

### 7.7 Journals

`Journal.append` and the peer-changes writer rotate a file at 8 MiB (`<name>.1`, the previous one removed). Every
journal is bounded, not only the rejected-inbound one.

## 8. The QQ Bot bridge and version skew

`bridge.js` asks the admission endpoint (the same cache rule, keyed by conversation and sender, dropped on an `epoch`
change or when the core does not answer) and puts the answer's `route_id` into the event at the flush. Its pending
items carry a non-wire note of the conversation. A refusal drops the line; a 404, a 5xx or a missing core holds it (the
line stays in `pending`, as it already did for a host restarting). It reads no route from the core's settings and builds
no `auto-…` id.

**Skew.** The core ships first and additively, so an old adapter against the new core works as before (its derived
settings are still written by the old kind module that ships with it). The adapters ship second. A new adapter against
an old core gets 404 from its first ask: it holds the lines, raises the lane fault, and posts nothing without a verdict.
An old adapter against a new core after the kind module changed cannot occur in one install (both are packed from one
commit and the integration runs the release selected at the start); if a publication of the adapter alone brought it
about, the old adapter would refuse to start with `adapter.routes missing` rather than run on half a policy.

## 9. Settings, tools, documents

### 9.1 `tools/setup_native_profile.py`

- A profile with no saved `deployment` (including one `dsh plugin add` has only given a bare row) gets
  `channelAdmission: automatic`; one with a deployment that stores none gets `explicit` written into it; a saved value
  is untouched; `--channel-admission` still chooses for a profile that has not saved one.
- `--print-admission` prints `stored automatic`, `stored explicit` or `absent`; `--require-admission <value>` also exits
  1 unless the profile has saved exactly that.

### 9.2 Settings card and documents

`client.js` labels (zh, en): `automatic` reads Open, `explicit` reads Closed; values, schema and fallbacks untouched.
RUNTIME_API (settings table, Admission, the three endpoints, the kind table), `DEVELOPMENT.md`, `RUN_ASUNA.md`,
`NATIVE_PLUGIN.md`, `tools/README.md`, the package READMEs, `docs/map` (regenerated). The adapter's own skill pages
(`skills/qq-napcat-adapter/SKILL.md`, `USAGE.md`) describe the old configuration in places; they are hers and are not
rewritten here.

## 10. Tests, what was run, landings

### 10.1 Tests that earn their place

- **`tests/test_channel_admission.py`** (new, in-memory store, a stand-in kind that is not QQ): closed and open; block
  lists in both; a home kind never open; the answer changes nothing and is the admission's on 60 generated asks; a
  departure marks only an admitted grant and leaves the scene, its epoch, the person and the roster as they were; a
  restored admission brings the mark back; a line dated before the leave does not undo it; the endpoints refuse what
  they do not know and a route key reaches none; the epoch; the routes read; the real kinds' declarations; an action
  queued for a group blocked since does not go out; the mark reaches the line she reads; no folder before a task.
- **`tests/test_profile_compose.py`**: the discriminator, the pin, the flag, the reads.
- **Adapter self-test** (`qqadapter/selftest.py`, a fixture core in `fixtures.py`): the policy cases replaced by the
  admission cases of 7.2 to 7.4, in both modes, with the three ways the core can fail, order across a conversation's
  known and unknown routes, the epoch, leaves, the journals.
- **Bridge test** (`test/bridge.test.js`): the route from the core, once per ttl; a refusal drops; an old or absent core
  holds; nothing of ours goes on the wire.
- **Ported:** `test_catchup`, `test_group_members`, `test_notices`, `test_own_mute`, `test_stickers`, `test_tool_budget`.
- Not written: a test per function, of the three program phrases' wording, that a cap is absent.

### 10.2 What was run

On the build (all numbers read from the run, 2026-10-29, in the cloud checkout, Linux):

- `pytest tests`: the same four failures as on the untouched tree (`test_integration` snapshot run, `test_no_server`,
  `test_refusal_probe`: no `config/local.json`, `test_sandbox_backend`: no confining sandbox in this container), nothing
  else.
- `npm run test:native`: the same failing tests as on the untouched tree (compaction ×4 cancelled, ADR-098 ×3 on a
  Windows path, ADR-065 ×1), plus the two new bridge tests passing.
- Adapter self-test offline: `pass=415 fail=0 skip=3` (from 409).
- The refactor proof: `admit` before and after on 840 cases, identical.
- Not run here: the MongoDB integration layer (no server), the live system, the running Host. Nothing is installed.

### 10.3 Landings

All three keep an old adapter working. Commits on the branch are ordered so each landing is a prefix.

**Landing 1, the core (additive).** Design and docs; the core (`channel_admission`, `channels`, `host`, `grants`, `chat`,
`native_worker` lane `cwd`, `people`, `group_admin`); the `OPEN_ADMISSION` lines of `napcat_qq` and `qq_bot`; the setup
tool; the card labels; their tests. It does not touch `adapter_config`, so the integration's fingerprint is unchanged.
*Before the install:* read her profile with `python tools/setup_native_profile.py --require-admission automatic` (exit 0
or stop); her reading of this page and of the two phrases in 6.4. The install restarts the worker only. Verify
`loaded.commit` and that the core files match the commit; the start's evidence has no `channel.admission_closed_by_kind`
for `qq`. *Her check by content:* a new group line is admitted as before; a DM likewise; a stranger's first line shows
「第一次在这里说话」.

**Landing 2, the adapters.** `qqadapter/*`, the kind module's `adapter_config`, the bridge, their tests and documents.
The integration profile's fingerprint changes (the derived settings shrink), so a plain Host start leaves
`PROFILE_CHANGED_RESTART_REQUIRES_EXPLICIT_START`: after the install run `integration_start` and read
`integration_status.restoration_error` (empty). Verify by content: the adapter's `STATUS` shows `admission_asked`, no
`ADMISSION_UNSUPPORTED`, `inbound_sent.jsonl` rows carry a route; a probe in the isolated demo profile (no real model)
shows a refused sender dropped before a lookup. Tell her, through the agent line, that her `probe_catchup.py` (it reads
`cfg.routes`) and the adapter skill pages describe the old configuration.

**Landing 3, her prompt** (the sentence of 6.6, with its budget) alone, after she has read it, then observed on real turns.

**Readings due.** One week after landing 2: `inbound_not_admitted` (closed deployments), `returned` marks, the size of
`inbound_rejected.jsonl`.

## 11. Not in this ADR

Moving routes and per-conversation rules out of the core's settings; the QQ Bot platform's own rules; any cap on
admitted people (deliberate, 6.6); any silence rule for a DM or a member (decisions 5 and 6); the platform's gates for
non-friend DMs (not measured); the adapter skill pages and her probes (hers).
