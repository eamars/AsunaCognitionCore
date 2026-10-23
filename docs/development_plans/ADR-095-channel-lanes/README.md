# ADR-095: Channel lanes — one slow message never holds another conversation

Status: **Accepted** in direction by the owner on 2026-10-23 evening, after a talk through Claude's notes: the
decisions in §5.2 (files don't hold chat), §5.3 (the transcriber in a child process), §5.4 (a single message never
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

**Host: the transcriber** holds a lock around native code in the Host's process; a hang there fails every later
voice until a restart.

## 5. Design

### 5.1 Inbound (adapter)

1. **Receive** — unchanged.
2. **Dispatch** — reads the spool and groups it by conversation (route). At most one line per conversation is in
   progress; a pool of workers (4) serves conversations, the oldest waiting conversation first.
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
   flight therefore doesn't count as an earlier part still on its way; a file that fails still cancels nothing after
   it (files stand alone).
4. **Execute** — in the worker: fetch, send, verify. Verification stays on the send path; in a per-conversation
   worker it costs only that conversation.
5. **Receipts** — their own queue and thread. The spool already exists; `report` enqueues, a receipt thread posts.
   A Host slow to take receipts no longer stops sends.

### 5.3 Shared resources

- **NapCat's API WebSocket**: calls are already multiplexed by echo id; a file is written in 4 MiB pieces, so chat
  calls get the socket between pieces.
- **QQ's pace**: if the platform needs one, it is a per-target pace in the lane, taken from QQ's documentation; never
  a global sleep.
- **The transcriber**: one long-lived child process that holds the model (owner). The Host waits for it with the
  voice's deadline; on a miss it kills the child, reaps it, and starts a new one at the next voice. On Windows the
  child sits in a job object that kills it when the Host goes, so no process outlives the Host or piles up.

### 5.4 Set aside, never clog (rule 9)

- A refusal that can never succeed (the Host's 4xx, a shape the platform rejects) is set aside at once.
- A failure of this item (its fetch, its send, its post) is retried with backoff; after 5 tries it is set aside.
- A failure of a shared dependency (the Host unreachable, NapCat disconnected, the network) **never counts against an
  item**: everything waits durably until it is back. Only the item's own failures count.
- Set aside means: moved to the dead-letter record with its reason and tries (`inbound_failed`, `inbound_rejected`,
  `receipts_rejected` exist), counted as a fault (5.6), and its conversation goes on. Outbound: the receipt is
  `failed`, as today, so her line shows it didn't go. Inbound: there is no mark in her conversation — the Host is
  what refused the line, so a stand-in would be refused too, and preparing never sets a line aside (its extras are
  optional, rule 7). An inbound gap becomes visible through the fault digest (5.6), when it persists.

### 5.5 Watchdog (rule 8)

Each worker records its item and when it started. A watchdog thread checks every few seconds: an item past its
budget (the sum of its steps' deadlines plus a margin) is marked stuck, its worker is abandoned and replaced, and the
item goes the way of 5.4. A Python thread can't be killed, so every call keeps its own socket timeout; the watchdog
covers what slipped past one.

### 5.6 Faults she should know about: persistent, not random (owner)

The owner: "I don't want her to be flooded with random fault like network errors. And issues don't needed to be
solved at real time."

- Every lane fault is counted under a **signature**: channel, lane, stage, error class — never the message. Faults
  are: a set-aside message (in or out), a worker the watchdog replaced, a killed transcriber child.
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
9. A transcriber child that hangs: killed and reaped at its deadline; the next voice gets a new child; no process left.
10. A burst of network errors in one hour: counted, not reported; the same signature on two days: in the digest once.

Every review brief for I/O work asks: what does a slow, hung or failing item do to every other conversation?

## 7. Build order (each its own review and restart)

1. The fault counts and the endpoint (no behaviour change): the place every later step reports to.
2. Inbound dispatch and per-conversation workers, with tests 1, 3, 4, 6.
3. Outbound lanes, the Host's SENDING hold and the receipt thread, with tests 2, 5, 7, 8.
4. The transcriber child, with test 9.
5. The watchdog and visible state.
6. The digest in her night stage, with test 10 — talked through with her before it reaches her.

## 8. Rejected

- **Shorter timeouts.** They limit how long one item takes; they don't keep the delay inside its conversation.
- **One poster for all deliveries.** Not needed: the Host already serializes ingest under its lock, briefly.
- **Real-time fault reports to her.** Random faults would flood her; issues don't need solving in real time (owner).
- **Holding a conversation on a poison item.** A single message must never clog (owner).

## 9. Cost

- Code: the adapter's two loops become dispatchers with worker pools, a receipt thread and a watchdog; the Host gains
  a claim lane, the SENDING hold, a faults endpoint and store, the transcriber child, and the digest block.
- Her context: one block in her night stage, only on nights with a persistent signature; no new tool.
- Risk: the adapter's loops are its most tested code. Every guarantee in §3 gets a test before the change.
