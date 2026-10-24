# ADR-095: Channel lanes — one slow message never holds another conversation

Status: **Accepted** in direction by the owner on 2026-10-23 evening, after a talk through Claude's notes: the
decisions in §5.2 (files don't hold chat), §5.3 (the transcriber in a child process; §5.3.1, voice and video as
independent children with their own settings and failure states), §5.4 (a single message never
clogs; reported so she can fix it), §5.6 (persistent faults only, as a digest, facts and pointers) and §5.8 (a
contract for every adapter) are his; the rest is Claude's. Not built; §7 is the order.

## 1. Why

On 10-22 the QQ outbound clogged. The fix made the Host's outbox fair per conversation (efccaef9, 74c9c55e), but
the adapter still executed one item at a time. On 10-23 a file upload (ADR-092) and voice settling (ADR-093) were put
on those same single threads, and the NapCat README even said "the outbox waits while a file is sent". The owner:
"a repeated mistake... haste development without system thinking." The class was fixed per instance and never
written down.

## 2. The invariant

**A slow, failing or hung message delays only its own conversation, and only work of its own kind.** Order is a
property of a conversation, never of the process. Every channel adapter keeps it; NapCat is built first.

What it means, as rules:

1. Isolation by conversation, in both directions.
2. Isolation by kind of work: chat (seconds) is never behind bulk (files) or heavy media.
3. Order within a conversation, in both directions, including across retries.
4. Inbound is at-least-once and idempotent at the Host (kept).
5. Outbound is at-most-once for anything a person sees: doubt is UNKNOWN, never a blind resend (kept).
6. Every wait has a deadline and an owner: who waits, how long, what happens after.
7. Nothing optional holds a line: an extra that fails or runs out of time is marked and the line goes on.
8. A stuck thing is detected and its lane recovered without a restart.
9. A single message never clogs: one that can't get through is set aside, and its conversation goes on.
10. State is visible: per lane and per conversation, how many wait, the oldest one's age, what is in flight and for
    how long.

## 3. What exists and stays

- The WebSocket reader classifies, writes the spool (fsync) and returns; it never calls anything.
- Inbound dedupe (local and at the Host by event id); catch-up after a reconnect.
- Outbound attempt ids; no answer is `unknown` and never resent; `recover_sending` at Host start; late answers settle;
  receipts spooled and replayed; read-back verification as observation.
- The Host's outbox order: fair across conversations by their oldest queued line, ordered within one, paced parts
  hold only their conversation, parts after a failed part cancelled.
- Side jobs on their own threads: catch-up, members, picture keys, mutes, home notices, health.
- Host ingest (`Channels.receive`) under the controller's ingress lock: database work only, no call off the machine.
  It stays serial and short; this design doesn't touch it.

## 4. What breaks the invariant today

**Inbound: one submitter thread for every conversation.** Per line, in order: peer lookup (3 s, when a profile needs
a refresh; each mention 3 s), merged-forward fetch (8 s), her role in the group, each voice (fetch 10 s, transcription
30 s), the post (12 s, once more if refused). Also: a line that gets `retry` lets the next line of the same
conversation overtake it.

**Outbound: one loop claims one item and finishes it before the next.** Per item: replaying spooled receipts (12 s
each when the Host is away), a picture fetch (30 s), the send (15 s), verification (a 0.8 s sleep, `get_msg` 5 s,
maybe 1.5 s and 5 s more), the receipt (three tries, 2 s and 5 s apart), a file (about 30 minutes at 50 MiB).

**Host: the transcriber and the video decoder** run native code in the Host's process. The transcriber holds a lock
around it, so a hang there fails every later voice until a restart; a video decode that hangs holds the thread of the
`read_image` call that asked for it, with no deadline.

## 5. Design

### 5.1 Inbound (adapter)

1. **Receive** — unchanged.
2. **Dispatch** — reads the spool and groups it by conversation (route). At most one line per conversation is in
   progress; a pool of workers (8, `INBOUND_LANES`) serves conversations, the oldest waiting conversation first.
3. **Prepare** — in that conversation's worker: peer and mentions, forward, her role, voices. Each step has its
   deadline (as today). A step that fails or runs out is marked on the line and the line goes on (rule 7); for a
   voice that is the existing reason on its media item.
4. **Deliver** — the same worker posts the line. Posts from several workers take turns at the Host's ingress lock.
   A `retry` holds that conversation until the line goes in; later lines there wait behind it (rule 3).

### 5.2 Outbound (Host and adapter)

1. **Host outbox** — unchanged order, plus: a conversation with a chat line in SENDING is held, so two chat lines of
   one conversation are never out at once (today only parts of one reply hold each other). A file in SENDING holds
   nothing but itself (3 below).
2. **Lanes** — the adapter claims for two lanes:
   - **chat**: text, stickers, pictures, reactions, actions; a pool (4), one conversation per worker at a time;
   - **bulk**: files; one worker, claiming files only.
   The claim names its lane; the Host hands a file only to the bulk lane and never to chat.
3. **Files don't hold chat**, even in their own conversation (owner): the parts of a reply before a file keep their
   order (the file part waits for them, as any part does); the file goes out when its upload finishes; nothing waits
   for it — not her later replies, and not the later parts of its own reply. In the Host's part rule a file part in
   flight therefore doesn't count as an earlier part still on its way. A file that fails cancels the parts after it
   that have not gone yet, as any failed part does (as built; the earlier draft said it cancels nothing).
4. **Execute** — in the worker: fetch, send, verify. Verification stays on the send path; in a per-conversation
   worker it costs only that conversation.
5. **Receipts** — their own queue and thread. The spool already exists; `report` enqueues, a receipt thread posts.
   A Host slow to take receipts no longer stops sends.

### 5.3 Shared resources

- **NapCat's API WebSocket**: calls are already multiplexed by echo id; a file is written in 4 MiB pieces, so chat
  calls get the socket between pieces.
- **QQ's pace**: if the platform needs one, it is a per-target pace in the lane, taken from QQ's documentation; never
  a global sleep.
- **The transcriber and the video decoder**: each in its own child process (§5.3.1).

### 5.3.1 Media children: voice and video (owner, 2026-10-23 night)

The owner: voice and video are treated the same, "they can be turned on or off independently. Any one broke should not
affect the other", and "the missing dependencies should NOT be treated as decoding failure. The failure mode needed to
be considered."

- **Two settings, one shape.** The cognition-core plugin's settings gain `voice` and `video`, each on or off, both on by
  default. They reach the Host in the worker's `initialize` call. A change takes effect when the plugin starts again.
- **On: one long-lived child per kind**, started with the Host and kept warm: the voice child loads the model (about
  310 MB, 0.8 s to load, measured 2026-10-23) and holds it; the video child loads its decoder. Each child takes one job
  at a time; voices queue only behind voices, videos only behind videos. **Off: no child**, nothing loaded.
- **Independent.** The two children share one supervisor's code (start, deadline, kill, reap, restart) and nothing
  else: no lock, no queue, no state. A voice child that will not start, hangs or dies changes nothing for videos, and
  the other way round.
- **A deadline per job**, from what the job is: a voice from its length (a base plus a share per second of audio), a
  video from its size. The Host waits up to the deadline; past it the child is killed and reaped and a fresh one is
  started at once (warm for the next job), and that job is tried once more. The adapter's wait for a voice answer is
  longer than two deadlines, so a retry never looks like a Host that is away.
- **No process outlives the Host**: on Windows each child sits in a job object that kills it when the Host goes; on
  every system the child exits when its input closes or the Host's pid is gone, even in the middle of a job. A child
  that has been killed is always waited for, so none is left over.
- **Stage times** of each job (queued, started, decoded, done) go into its evidence record (`voice.settled` and the
  video's), so a slow job shows where it was slow (two 3-second voices took 65 s right after a start, 2026-10-23,
  cause not on record).

**Failure modes.** Each has its own state and words; only a job's own failure is that job's failure:

| What happened | What it is | What she reads | Retried | Counted as |
|---|---|---|---|---|
| The setting is off | the owner's choice | voice: 「没转出文字：语音转写关着」; video: decoding is off | no | nothing |
| A package or model file is missing or not its pin, found at start | this machine's setup, not the job | voice: 「没转出文字：这台机器上的语音识别没装好」; video: the same for video | no | one Host log line and the Host's status, at start; not a fault per job |
| The child will not start (it exits or fails at load) | setup or the machine, not the job | as missing, with "没能启动" | the start: again at the next job, at most once a minute | one fault (lane `transcriber`/`video`, stage `start`) |
| The job runs past its deadline | the child or the machine | after the retry: 「没转出文字：识别超时了」 / video decoding timed out | once, in a fresh child | one fault per kill (stage `decode`, error `deadline`) |
| The child dies or answers garbage mid-job | the child | after the retry: 「没转出文字：识别程序出错了」 / the same for video | once, in a fresh child | one fault per death (error `exited` or `protocol`) |
| The bytes are not audio or video it can read (unknown container, empty, a decode error) | this job's own content | the reason, as today | no (it would fail the same) | nothing: an outcome, like a platform's `failed` |
| The Host stops mid-job | the Host | nothing yet | the adapter posts the voice again later (§5.4: the Host is away) | nothing |

Missing setup is told once, at start, where the owner looks (the Host log and status), and her lines say plainly that
the machine can't do it; it is never a count per voice and never looks like a voice that failed.

### 5.4 Set aside, never clog (rule 9)

- A refusal that can never succeed (the Host's 4xx, a shape the platform rejects) is set aside at once.
- A failure of this item (its fetch, its send, its post) is retried with backoff; after 5 tries it is set aside.
- A failure of a shared dependency (the Host unreachable, NapCat disconnected, the network) **never counts against an
  item**: everything waits durably until it is back. Only the item's own failures count.
- As built for inbound (step 2, after its review): the Host answers a state of the whole Host with 503 and its name
  (`HOST_RECONFIGURING`, `HOST_STOPPING`, `HOST_DATABASE_UNAVAILABLE`) and one request's own failure with 500
  (`HOST_REQUEST_FAILED`). No answer, a dropped connection, a 503 and `CHANNEL_AUTH_REQUIRED` are about the Host:
  they wait. A 503 the Host names and `CHANNEL_AUTH_REQUIRED` never count; no answer (and an unnamed 503, from an
  older Host) counts only when other lines went in since that line's previous try. A 500, another 5xx, or a try
  that raises in the adapter counts. Any 2xx settles the line. A line is prepared once and written back, so a retry
  posts it again without asking the platform again, except when a voice could not be handed to the Host (then the
  next try prepares it again).
- Set aside means: moved to the dead-letter record with its reason and tries (`inbound_failed`, `inbound_rejected`,
  `receipts_rejected` exist), counted as a fault (5.6), and its conversation goes on. Outbound: the receipt is
  `failed`, as today, so her line shows it didn't go. Inbound: there is no mark in her conversation — the Host is
  what refused the line, so a stand-in would be refused too, and preparing never sets a line aside (its extras are
  optional, rule 7). An inbound gap becomes visible through the fault digest (5.6), when it persists.

### 5.5 Watchdog (rule 8)

Each worker records its item and when it started. A watchdog thread checks every few seconds: an item past its
budget (the sum of its steps' deadlines plus a margin) is marked stuck — one log line, one fault — and its place in
the pool is freed, so the other conversations keep their workers. The item itself is held, not set aside or tried
again, while its thread lives: its conversation waits until the thread returns (owner, 2026-10-24). A Python thread
can't be killed, so a stuck thread may still finish; setting its item aside would let an inbound line arrive after
the lines behind it, or mark failed a line that QQ shows. Every call keeps its own socket timeout, so every step
already ends (2026-10-24: an inbound try within its post and 210 s per voice, a chat send within about 100 s, a file
within about 2 minutes per 4 MiB piece); the watchdog covers what slipped past one, which only a bug can be.
Budgets: an inbound try 60 s plus 210 s per voice, a chat send 150 s (below the Host's 300 s hold), a file 120 s per
piece plus 60 s, a receipt 15 s.

### 5.6 Faults she should know about: persistent, not random (owner)

The owner: "I don't want her to be flooded with random fault like network errors. And issues don't needed to be
solved at real time."

- Every lane fault is counted under a **signature**: channel, lane, stage, error class — never the message. Faults
  are: a set-aside message (in or out), a worker the watchdog replaced, a media child that was killed, died or
  would not start (§5.3.1).
- The adapter keeps its counts and posts them to the Host every few minutes (like members and picture keys), to a
  new `faults` endpoint; the Host keeps them by signature and hour.
- A signature is **persistent** when it shows up in at least 3 different hours spread over at least 6 hours, or on 2
  different days. A burst inside one hour that clears is a count, nothing more.
- A **shared-dependency outage** is the environment, not hers to fix: it is persistent only when it lasts 30 minutes
  without a break, or comes back on 2 different days.
- Persistent signatures reach her as a **digest in her night self-development** (a block in the stage's program
  context, ADR-021), at most once per signature per night: what, where, how often, since when, and the pointer to the
  dead-letter records. Facts and pointers only; she reads the messages with her own home tools if she needs them
  (ADR-017 unchanged). The same digest goes to the developer inbox, as `faults.py` does for failed turns.
- Thresholds are generous on purpose: when in doubt, a fault stays a count.

**Refinement for step 6 (owner agreed, 2026-10-24; designed against a week of real faults under napcat-qq 0.16.0,
about 10-31).** Four rules on top of the thresholds above, from the same counts, the dead-letter records and the
publication receipts (no new collection):

1. **Consequences, not attempts.** The digest is built from what ended badly for a message — set aside for good, a
   send left `unknown`, a voice never transcribed, an item stuck — not from error events. A shared-dependency outage
   makes lines wait and go in later (§5.4 never counts that against them), so a surge leaves no consequence and
   filters itself out. (The first entry in `lane_faults`, 10-24: two inbound lines the Host refused with
   `INPUT_IDENTITY_OR_CONTENT_CONFLICT` and set aside — a consequence, not noise; looked into on its own.)
2. **Shared causes collapse.** Many unrelated signatures rising in the same minutes across lanes are one cause in the
   environment (NapCat restarting, the network, the Host away): one environment event with its start and end, to
   the developer inbox only and only when long; never to her, who can't fix it.
3. **New after a change.** A signature never seen before that first appears after a publication or a restart is
   reported the next night even if seen once, with the change it followed — a regression is caught in a day, not
   after the persistence test. She publishes her own code, so this is the case she can act on fastest.
4. **To whoever can fix it.** A fault in her own packages (her channel or persona work) goes to her; one in the core
   or the environment (a Host refusal, a media child, an outage) to the developer inbox.

### 5.7 Visible state (rule 10)

The STATUS line and the health snapshot gain, per lane: depth, the oldest item's age, in-flight items and their ages;
per conversation: depth and the oldest item's age. Each line's journal entry carries its stage times (spooled,
prepared, delivered; claimed, sent, verified).

### 5.8 The contract

The rules of §2 become part of the channel package rules (docs/DEVELOPMENT.md, channel packages), with self-test
cases that any adapter can reuse (§6). NapCat is built first; the QQ Bot bridge follows when it is deployed for her.

## 6. Proof

Written before the code, on stubs (a NapCat that can hang or refuse, a Host that can be slow or away):

1. A voice fetch that hangs in conversation A: a text line in B is delivered; A's later lines wait for A.
2. A file upload that hangs in A: a reply in B goes out, and a reply in A goes out too.
3. One post to the Host times out: the next line of that conversation doesn't overtake it.
4. A poison line: set aside after its tries; its conversation continues; one fault counted under its signature.
5. A file part in the middle of a reply: the parts before it go first; the parts after it don't wait for its upload.
6. The Host away for a while: nothing is set aside; everything goes in, in order, when it is back.
7. The adapter killed mid-send: UNKNOWN, no duplicate.
8. The Host slow to take receipts: sends continue.
9. A voice child that hangs: killed and reaped at its deadline, the voice retried once in a fresh child, no process
   left; meanwhile a video is decoded as usual. The same with the kinds swapped. With a package missing: no child, the
   line says the machine can't, no fault is counted; with the setting off: the same, in its own words.
10. A burst of network errors in one hour: counted, not reported; the same signature on two days: in the digest once.

Every review brief for I/O work asks: what does a slow, hung or failing item do to every other conversation?

## 7. Build order (each its own review and restart)

Built in the order 2, 3, 1, 4, 5, 6 (Claude, 2026-10-23: the owner wanted the clog fixed the same day; a set-aside
line is in the adapter's journal meanwhile, so nothing waits on step 1).

1. The fault counts and the endpoint (no behaviour change): the place every later step reports to. **Built:** the
   Host's `lane_faults.py` (`receive`, `record`; collection `lane_faults`, one document per channel, signature and
   hour, its count raised with `$inc`) behind `POST /v1/channels/<id>/faults`; the adapter's `faults.py` (napcat-qq
   0.13.0) counts each set-aside line, refused or abandoned receipt and send exception where it happens, keeps the
   counts the host has not taken in `faults_pending.json`, and posts them every 5 minutes. Tests:
   `tests/test_lane_faults.py`; self-test `_check_faults`. Independent review: the project map lacked the module
   (fixed); signatures could carry the host's words (now names only, `CLASS_CHARS` at the host, the code alone at the
   adapter), which would also have split one fault class into many signatures; nothing removed the documents (now a
   TTL of `KEEP_DAYS` = 30 on `hour_at`, the hour's start as a date); a refused batch blocked the rest (now journaled
   and dropped); a damaged pending file could raise into a lane (now checked on load, `add` never raises); loose hours
   (now canonical, within the 30 days, at most an hour ahead); a post written row by row (now one `bulk_write`; counts
   are at least once). Not counted as lane faults, on purpose: an outbound send whose platform answer is `failed` or
   `unknown` — that is the platform's outcome, already on the line, not a fault of a lane.
2. Inbound dispatch and per-conversation workers, with tests 1, 3, 4, 6. **Built:** `service.py` `submit_pending`
   (groups the spool by route, at most `INBOUND_LANES` = 8 lanes, the conversation with the oldest line first),
   `_lane` (a conversation's lines in order; a line not in yet is tried again after `RETRY_WAITS` 2, 5, 15, 30, 60 s),
   `_submit_one` and `_host_away` (the answers as §5.4 says; `HOST_ERROR_TRIES` = 5 counted tries, then
   `inbound_failed.jsonl`; a line prepared once, `_prepare`/`_post`), `_lane_error` (an exception is a counted try
   with its backoff), each spool file read once by the dispatcher (`_spooled`; an OS error while reading waits for
   the next pass), lanes yield after `LANE_BATCH` = 20 and the conversation whose lane started longest ago goes first,
   no pass at shutdown (the spool waits for the next start); the Host's `whole_host_state` (503 versus 500);
   `HostApi` takes a dropped connection as no answer; the journal removes a file another thread has open a moment
   later; `peers.py` keeps an observation's changes per thread. Self-test `_check_lanes` (11 checks: a voice NapCat
   does not give holds only its conversation; order kept; B goes in while A waits and A's next line does not overtake;
   no answer or a 503 never sets aside; a key not taken waits; a 500 line set aside and its conversation goes on; a
   line not taken while others go in set aside; an exception counted, no hot loop; held settles; prepared once with
   peers on; a named 503 never counts; a voice the Host was away for is fetched again; a waiting conversation gets
   its turn after one batch). The first check fails on the single submitter. Independent review: one high (the
   Host's own 503 counted against a line) and five medium findings, fixed; a second verifier: three medium (a stale
   first-answer time, prepare-once keeping a voice's refusal, the batch not letting others in) and two low, fixed.
3. Outbound lanes, the Host's SENDING hold and the receipt thread, with tests 2, 5, 7, 8. **Built:** the Host's
   `claim` takes `lane` (`chat` default, `bulk` files; an adapter not declaring `file` meets file rows on chat and
   fails them as before), `_next` holds a conversation with a chat line `SENDING` claimed within
   `CHAT_LEASE_SECONDS` = 300 (past it the line holds nothing and stays `SENDING` for its receipt or the Host's
   recovery: no state change), and a file is no earlier part on its way. The adapter (napcat-qq 0.12.0): `_main_loop`
   claims while fewer than `CHAT_LANES` = 4 sends are out and gives each a thread (`_send`); `_bulk_loop` claims files;
   `_receipt_loop` posts spooled receipts; `Outbound.report` tries once and spools; a stop waits up to 20 s for the
   sends on their way. Tests: Host `test_a_file_holds_nothing_and_comes_on_the_bulk_lane_only`,
   `test_a_chat_line_out_holds_its_conversation_until_settled_or_its_lease_ends`; self-test `_check_outbound_lanes`
   (a file upload that does not finish holds no chat send, in its own conversation either; a send that does not finish
   holds only its conversation; a host not taking receipts holds no send). Independent review: one medium-high (a late
   platform answer posted its receipt on NapCat's reader thread, so a slow host could turn other sends `unknown`; now
   it is spooled, `report_later`), a regression (a failed file did not cancel the parts after it; the part rule now
   cancels on any earlier part not on its way and holds only on an earlier chat part on its way), admin actions out
   several at once (now one per channel, `group_admin.claim`), mixed versions (a claim naming no lane is one lane for
   everything; the answer names its lane and a new adapter on an older host goes back to one send at a time), the stop
   not waiting for the bulk lane (now it does), and receipts abandoned while the host was away (only error answers
   count now); all fixed with a check each. NapCat's one write lock (a 4 MiB file piece under it) stays: a shared
   dependency, waited on.
4. The media children (§5.3.1), with test 9: the shared supervisor, the voice and video children, the two plugin
   settings, the failure states and their words, the adapter's longer wait for a voice answer. **Built** (2026-10-24):
   `src/asuna/media_children.py` (`Child`: started on the base interpreter with `-P` and only the package root and
   site-packages on its path, frames on stdin/stdout, one job at a time; each call has a budget from when it was asked
   (`VOICE_BUDGET` 180 s, `VIDEO_BUDGET` 240 s) for the wait behind its kind, a start and the tries, each try ending at
   `VOICE_DEADLINE` 90 s / `VIDEO_DEADLINE` 120 s or the budget, the write included; a timeout or death killed, reaped
   and tried once more in a fresh child; a failed start tried again after `RESTART_WAIT` 60 s; `close` ends a hung
   job at once; a Windows job object; `video_snapshot`, `start_video` in the background), `src/asuna/media_worker.py`
   (the child: voice loads `SenseVoice` and does decode and transcription, video `animated.video_snapshot`; a program
   error answered apart from a content error, with its trace's tail; exits when the Host's pid is gone), `voice.Transcriber` (off, not set up, or the warm child; the
   state `not_transcribed` for the machine's own state; stage times in `voice.settled`), `vision.py` (the video goes
   through `media_children.video_snapshot`), plugin settings `voiceToText` and `videoDecoding` (`index.js`, passed in
   `initialize` as `media`), lane `video` in `lane_faults` (the Host counts a child's faults in a thread of its own, as
   channel `host`), adapter 0.15.1 (`POST_TIMEOUT` 200 s, above the 180 s budget). Tests: `tests/test_media_children.py`
   (real child processes: deadline, one retry, deaths, garbage, a program error, a child that stops reading, start
   failures and their wait, the budget behind a hung job, proof test 9 (one kind hung, the other answers), close
   during a hung job, a child started from a thread that ends, a Host killed hard in the middle of a job takes its
   child, the real video child), `tests/test_voice.py` (every state's words, off, not set up, the child's failures). Measured with
   the real model: the child is ready 1.2–2.0 s after start, a 2-second voice 0.2–0.3 s. Review (2026-10-24), fixed: a
   Linux parent-death signal set from the starting thread would have killed the child when that thread ended (now the
   worker watches the Host's pid); the queue behind a hung voice had no bound (now the budget); the video child
   started in the Host's start (now in the background); `close` waited for a hung job; the write had no deadline; a
   program error in the child read as the voice's content; no Host log line when video is not set up. Found by the
   full test run: a Host `sys.path` holding the package folder put `asuna/queue.py` in front of the standard library's
   `queue` in the child (now `-P` and only site-packages). Not built: stage times of a video (no evidence record
   there), a size-based deadline (fixed deadlines first).
5. The watchdog and visible state. Designed 2026-10-24 (owner chose "free the slot, hold the item", §5.5): the
   adapter's STATUS line gains one block (inbound lanes busy, the oldest waiting line's age, the longest in flight,
   chat sends busy, the bulk upload's age and size, receipts waiting); the health snapshot the full table per lane and
   per conversation; each line's journal entry its stage times; the watchdog marks and frees as §5.5 says. No Host
   change, no change to her context. Her asks (agent line, 15:2x): tell "places full, conversations queued" from
   "one conversation slow on its own"; name the oldest item's conversation and stage; seconds with units; `stuck` on
   the STATUS line itself; keys fixed, new ones only at the end. **Built** (napcat-qq 0.16.0): `qqadapter/watch.py`
   (`Watch`: `begin`/`stage`/`end` per worker thread, `check` marks once, `stuck.jsonl` rows `stuck` and `ended`;
   `inbound_budget`, `duration`), `outbound.file_budget` (the sum of a file's own deadlines), the service's
   `_inbound_busy`/`_chat_busy` (a stuck item's place is free; its conversation stays held by `_lanes` and the
   Host's chat hold), a bulk lane replaced by generation when its file is stuck (the old one ends after it),
   receipts marked only (no send waits for them), the pass in the health loop (`watchdog`), `lanes_state` in
   `health.json`, `lanes_status` at the end of STATUS, `stages` in `inbound_sent.jsonl` and `sends.jsonl`. Self-test
   `_check_watchdog` (9 checks: a full pool shows `queued`; a stuck inbound line frees its place, B goes in, A's next
   line waits and A is posted once in order; STATUS names the stuck; a stuck send frees its place and is sent once;
   a stuck file gets a new bulk lane; durations; the file budget). Each place-freeing undone makes its check fail.
   Independent review (2026-10-24), fixed: the Host's chat hold ends after its 300 s lease, so a later line of a
   stuck send's conversation could be claimed and overtake it (now a send waits for an earlier send of its
   conversation still on its way; check `watchdog_stuck_send_keeps_its_conversation_order`, red without the wait);
   a shared hang would have turned freed places into endless claims (now at most a pool's worth of stuck items give
   their places up, one replacement bulk lane at most); a line not yet read by the dispatcher had no conversation and
   could crash STATUS (now `-`, sorted by age, STATUS never raises); `begin` outside its `try` could leak a place or
   end the bulk lane (now inside, sizes coerced); nested forwards had no bound on their fetches (now
   `forward.MAX_FETCHES` = 6 per message, the inbound base 120 s); a lane whose line was stuck kept its place on
   return (now it ends after that line); with a Host that names no lanes nothing gives its place up and a file on
   the chat lane gets a file's budget; a failing log in the watchdog pass could skip the bulk replacement. 12 checks.
6. The digest in her night stage, with test 10 — talked through with her before it reaches her. With the refinement
   in §5.6 (owner, 2026-10-24); the design note after a week of faults under 0.16.0 (about 10-31).

## 8. Rejected

- **Shorter timeouts.** They limit how long one item takes; they don't keep the delay inside its conversation.
- **One poster for all deliveries.** Not needed: the Host already serializes ingest under its lock, briefly.
- **Real-time fault reports to her.** Random faults would flood her; issues don't need solving in real time (owner).
- **Holding a conversation on a poison item.** A single message must never clog (owner).

## 9. Cost

- Code: the adapter's two loops become dispatchers with worker pools, a receipt thread and a watchdog; the Host gains
  a claim lane, the SENDING hold, a faults endpoint and store, two media children and their settings, and the digest
  block.
- Memory: the voice child holds about 310 MB while voice is on (measured 2026-10-23).
- Her context: one block in her night stage, only on nights with a persistent signature; no new tool.
- Risk: the adapter's loops are its most tested code. Every guarantee in §3 gets a test before the change.
