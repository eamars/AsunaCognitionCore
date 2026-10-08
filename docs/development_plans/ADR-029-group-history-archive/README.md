# ADR-029: old group chat kept as archived messages; a platform message id names a message only with its time

Status: **Built, imported and activated; live lookup checked with a scope limitation** 2026-10-09. The owner set
the requirements and asked Claude to lead the method; Claude decided the method below. Part A's records are
imported and verified. The owner restarted the production profile; the installed history, ingress, context and
channel files match the checkout. Part A is a one-off import. Part B is a persistent fix to live ingress.

## 1. Context

Two earlier deployments on the same QQ bot account left group chat history in their own MongoDB databases: an
earlier one with Kazusa as the character (April to late July 2026) and a later one with another character (late July
to mid-September 2026). Neither character was Xiaoman, who runs on this deployment. A read-only discovery on
2026-10-09 (private evidence under the deployment's `<data>/private/`) found:

- About 720,000 rows in 24 numeric QQ groups: about 714,000 human lines and about 6,000 bot lines. Sixteen of the
  groups have a current scene; eight do not, and one of those holds about half of all rows. A few rows sit under
  non-numeric test identifiers; the rest of the two archives are private chats, debug traffic and other platforms.
- No overlap with the current database: its group history starts on October 4–6, and nothing covers September 18
  to October 4.
- No copied overlap between the two archives.
- About 101,000 rows have no text; most of their attachments are metadata only, and a few hundred carry bytes inline.
  `raw_wire_text` often differs from `body_text`.
- **QQ message ids are reused within the same group.** Within the archives, 21 rows reuse a group-and-id key, 17 of
  them with different content. Between the archives, nine keys are shared, all with different content, 12–85 days
  apart. One key also matches a current-database row 94 days later with a different sender and text.

The owner's requirements (2026-10-09):

1. The group chat is kept because it is useful for training future harnesses and models. Keep the human part; the
   Kazusa-era bot lines may be stripped.
2. Direct messages with the owner may be stripped.
3. The messages are for storage and explicit recall only. Nothing in Xiaoman's database other than `messages` is
   touched.
4. Claude leads the implementation method.

Live ingress identifies an inbound QQ line by its id alone. The adapter sets `event_id = str(message_id)`
(`packages/channels/napcat-qq/integration/qqadapter/inbound.py`), and the Host hashes
`(channel, account, scene, event_id)` into the row's identity (`src/asuna/channels.py`, `src/asuna/ingress.py`).
When an id comes back weeks later:

- **The adapter drops it.** In one adapter process, the line is dropped as `duplicate_local` if the old key is still
  among the last 512 in its in-memory list. A quiet group can go weeks without filling 512 keys.
- **The Host loses it.** `persist_input` finds the old row. With the same author and text (a short greeting), it
  answers `duplicate`, and the adapter removes the spool file: the line is lost without a trace. With different
  content it raises `INPUT_IDENTITY_OR_CONTENT_CONFLICT`, and the adapter moves the line to `inbound_rejected.jsonl`:
  lost, with a record.
- **Replies resolve to the wrong line.** `group_context` and `Context._reply_context` resolve a QQ reply by
  `find_one` on the bare id, with no order. With a reused id, a reply can resolve to a weeks-old line, or to an old
  line of hers, and wrongly wake her as `reply_to_character`.

The broken invariant is the same in all three: *a QQ message id identifies one message in a group forever.* It does
not. It identifies one only together with its send time.

## 2. Part A: the archive import (one-off)

### What is kept

- **A1 — Human lines only.** Group rows written by people in the 24 numeric groups, from both archives, over their
  whole span (April 18 to September 18). This includes blank rows that carry media metadata.
- **A2 — Bot lines stripped, from both eras.** Kazusa-era bot lines are stripped as the owner allowed. The
  later-era bot lines are stripped too: neither character was Xiaoman. Kept in her store, they would either read as
  her own words or need a third kind of speaker that recall and training data would have to explain. Stripping
  them also removes the pending and delivery-unknown rows, which therefore can never be sent. The source databases
  are not changed, so these lines stay available there.
- **A3 — Left out.** Private chats, debug and other-platform rows, and the rows under non-numeric test
  identifiers.

### Where it goes

- **A4 — Only `messages`.** No scene, identity, people label, memory unit, embedding, summary, blob, audit event
  or index is written. Rows are inserted directly in batches, not through `Store.put`, because `put` also writes
  `audit_events`. A private, local manifest file is the import's record.
- **A5 — Each group's archive is its own scene id, with no scene document.** The archive's scene id is `archive:`
  plus the scene id that admission gives that group (the QQ channel kind's `scene_id(account, 'group', group_id)` in `src/asuna/channel_kinds.py`). This is the
  current scene's id for the 16 matched groups, and the id the group would get if admitted for the other eight. Its
  `scope_key` is the live scene's (`scene:<id>`), so erasing a conversation also erases its archive. Its
  `policy_epoch` is the live scene's current one (1 for all 16 matched scenes; 1 for the unmatched groups).
  Every live reader selects rows by the live scene id, so none of them reads an archive row: recent history,
  catch-up, attention, chunking, summaries, proactive pacing, the outbox and recovery.
- **A6 — A direction of their own: `direction: 'archived'`.** Live code that counts people across scenes filters on
  `direction: 'inbound'`. For example, familiarity counts a person's inbound lines (`src/asuna/familiarity.py`), and
  without this, 700,000 imported lines would raise how well she "knows" people. Archived rows match none of those
  filters. They have no `delivery_state`, `host_managed`, `ingress_state`, `channel_id`, `platform_event_id`,
  `publication_key` or `event`, so no outbox, recovery, uniqueness or reply predicate can match them.
- **A7 — Order without touching live counters.** Each archive scene numbers its rows `scene_seq` 1..N, ordered by
  original time and then by source identity. That gives history paging its tie-breaker. No scene document exists to
  hold a counter, and live sequences are untouched.

### What a row holds

- **A8 — Identity.** `_id` is `archive-` plus a hash of (source database, collection, original `_id`). A rerun
  inserts nothing twice. A changed source row under an existing `_id` stops the import for review. Platform message
  ids are kept as data, never used as identity.
- **A9 — Author.** The person's existing `person_id`, found read-only in `identities` by platform account.
  Otherwise the platform's standard form (the channel kind's `person_id(account)`, `qq:<account>`), which a later admission of that person
  would produce anyway. The display name of the time is stored on the row as a name of that time; it never updates
  a profile.
- **A10 — Time.** `occurred_at` is the original timestamp in UTC. The original `received_at`, where one exists, is
  kept separately. `imported_at` and `import_run` record the import itself. No field is set to the import time under
  a live name.
- **A11 — Text and media.** `text` is `body_text` unchanged; a media-only row has empty text. The original row is
  kept under `legacy`, minus its embedding vector: `raw_wire_text`, mentions, reply context and attachment items
  (with any inline bytes, which are not decoded, validated or registered as blobs). Stored image descriptions stay
  inside `legacy` as descriptions, never as text. Old URLs are not fetched.
- **A12 — Replies.** Replies are kept as recorded and not resolved. Their targets may be stripped bot lines or
  reused ids, and recall and training both work from the stored reply context.

### Recall

- **A13 — The history tool reads the archive.** It is the one live code change in part A. When `history` reads a
  scene, it also reads that scene's `archive:` id, and the archive ids of its linked scenes, under the same epoch
  and link rules. In those ids, rows with `direction: 'archived'` count as people's lines. Searches need explicit
  dates, as anything older than 90 days already does.
- **A14 — Naming archive speakers.** A speaker is named the way the live scene already names that person, when the
  person is in its roster. Otherwise the history result uses the name stored on the row, and says it is the name
  they used then. Reading the archive never creates people entries.
- **A15 — Nothing else.** No memory units, embeddings or summaries are made from the archive, and no recall happens
  without an explicit `history` call. The eight unmatched groups are stored only: nothing reads them until such a
  group is admitted. Admission then gives it the scene id its archive already names.

### Running it

- **A16 — An ignored, private script.** The importer is a one-off script under the deployment's `<data>/private/`,
  not tracked code. Source database names and group lists are deployment details. Its steps:
  1. **Dry run.** It reads the sources and writes the manifest: rows kept and their counts by group, day and
     direction; rows left out by reason (bot line, private chat, test identifier, other platform); the source
     high-water marks; the archive scene id for each group. It writes nothing to MongoDB.
  2. **Pilot.** A bounded subset goes into a temporary test database under the repository's test rules (the database
     is dropped after its evidence is exported, on failure too). This checks the history tool against archived
     rows, speaker names, reruns, interruption and resume, and that familiarity and live readers ignore them.
  3. **Import.** It writes into the live database in batches. The Host does not need to stop: no live reader sees
     archived rows. Inserts are throttled so live traffic keeps its share of the disk.
- **A17 — Backups and rollback.** The source databases are not modified, so they are the backup. Before the import,
  `messages` is dumped (it is small). Rollback is `delete_many({'import_run': <id>})`, and nothing else exists to
  undo.
- **A18 — Indexes.** The existing `(scene_id, scene_seq)` index serves archive paging. A history search over the
  largest archive is timed in the pilot. A `messages` index on `(scene_id, occurred_at)` is added only if that
  timing shows the need.

### Acceptance

- The manifest accounts for every source row as imported or as left out with a reason.
- A rerun inserts nothing.
- A `history` call with explicit dates, made directly against the live database, returns attributed, dated lines
  from the archive of a matched group and nothing from another group.
- Before and after the import, the same sample of people has the same familiarity level, and nothing new appears in
  episodes, tasks or outbound rows.
- Only `messages` changed.

## 3. Part B: a platform message id names a message only with its time (persistent)

- **B1 — Ingress identity includes the platform time.** The Host's event identity becomes a hash of
  `(channel, account, scene, event_id, occurred_at)` when the envelope carries `occurred_at`, and stays as before when
  it does not. `occurred_at` is the platform's send time. The QQ adapter takes it from the event's `time` in whole
  seconds, and a pushed line and the same line fetched by catch-up carry the same value, so redelivery is still
  answered `duplicate`. A reused id at a different time is a new line. The rule belongs to the Host and is the same
  for every channel: a channel whose ids never repeat loses nothing.
- **B2 — Channels send a platform time or none.** `occurred_at` must be the platform's time for that message,
  never the time of sending it to the Host. The DSH peer bridge's `Date.now()` fallback is removed: without a
  platform time it omits the field.
- **B3 — The adapter's local duplicate check uses the same key.** `SeenLRU` keys become route, id and time.
- **B4 — A reply resolves to the newest matching line at or before it.** In `group_context` and
  `Context._reply_context`, a reply id resolves to the newest matching row whose time is not later than the replying
  line's, instead of an unordered `find_one`. Inbound rows are matched by `event.channel.platform_event_id`, which
  keeps the bare platform id. Outbound rows are matched by `platform_message_id` and ordered by `receipt_at`.
- **B5 — No compatibility path.** Rows accepted before the change keep the identity they were stored under. If a
  line accepted before deployment is fetched again by catch-up after it, it is accepted once more as a new line.
  That can happen only within catch-up's six-hour look-back right after the change, and only on routes where
  catch-up is on. This is accepted, not handled by code.
- **B6 — Tests.** These follow the repository rules: the `runtime_work` fixture, owned test databases dropped on
  failure too, and no real model.
  - The same id at two times becomes two lines; the same id at the same time is a duplicate.
  - A catch-up redelivery is a duplicate.
  - A reply resolves to the newest line at or before it.
  - The adapter self-test covers the LRU key.

## 4. Consequences

- About 714,000 archived rows enter `messages`, which holds about 11,000 today. Live readers do not see them
  (A5, A6). `messages` grows to the order of a gigabyte. Only `history` reads the archive.
- What Xiaoman is and whom she knows does not change. The archive is something she can look up, not something she
  remembers.
- The training use reads archived rows by `direction: 'archived'` and `import_run`, with the original payload under
  `legacy`.
- From part B on, a reused QQ id is a new line, and the adapter journals no longer show reused-id rejections.

## 5. Not decided here

- Whether a summary or embedding pass over the archive is ever wanted. It would need its own decision and
  real-model authorization.
- Media bytes beyond the few hundred inline items. They are not in the archives.

## 6. Implementation and evidence (2026-10-09)

The one-off importer and its frozen manifest live under `<data>/private/adr029-group-history-archive/`.
The superseded proposal and discovery scripts were removed; their five evidence files are retained in that
directory's `discovery/`. Deployment identifiers and original content remain private.

- The dry run reconciled all 726,637 source rows: **714,182 human group records kept**, 12,455 excluded,
  across 24 approved numeric group identifiers. The source payload hashes were checked again before importing.
- The import inserted all 714,182 records. Command monitoring recorded only `insert` commands against the
  target `messages` collection. No production index was added. The pre-import `messages` dump has 10,898 rows
  and was decoded again to verify its count; its checksum is in the private manifest.
- A full production rerun found all 714,182 records already present, inserted none, and issued zero MongoDB
  write commands.
- Post-import verification read every imported payload back, verified all 714,182 hashes and original text/time
  values, and reconciled every group's counts by day. All forbidden live-routing fields were absent.
- Direct, non-semantic history calls against the live database returned attributed archive lines from all 16
  matched groups, with the scope checks intact. The eight unmatched groups remain stored without scene documents.
- The same sample of 30 people retained its familiarity levels. No outbound row was added during the measured
  interval. The already-running Host independently advanced some receipts, sessions, audit records and memory
  units; the command log establishes that the importer wrote none of them.
- A 2,000-record pilot proved interruption/resume, an unchanged rerun, rejection of a changed payload, scoped
  attribution and rollback. Its test database was dropped after evidence export. A 360,000-record synthetic
  archive took 1.4–2.0 seconds for full-page, matching and missing-term searches using existing indexes.
- An isolated native DSH profile with synthetic inference called the real Python history service and displayed
  its dated archive receipt through the shipped Web interface. The Web fixture database was dropped and its Host
  stopped; the screenshot and source receipt are retained privately. No real model endpoint was called by these
  probes, and the operator's independent model server was not stopped.
- Targeted Mongo/runtime checks passed, including archive pagination, transport-budget continuation, scope/epoch
  fences, read-only historical naming, media-only rows, stable familiarity, repeated platform IDs and reply time
  ordering. Native tests passed (100); the adapter's offline self-test passed (281 checks), including its new
  ID-and-time and catch-up cases. The summary and proactive offline checks passed (24 and 19 cases).
- The older flat-module discussion check passes 17/18 cases. Its remaining relative-import failure in
  `case_cursor_and_argument_fences` was reproduced with the unchanged `HEAD` history reader. The changed-file
  personal-data scan found no hits; the deployment's personal-word-list check is skipped because no list is
  configured, so that particular check remains unchecked.

The history change also fixes transport-budget continuation advancing from the newest delivered row: each stream
now continues after its oldest delivered row. Archive media payloads are excluded from the query projection while
remaining intact in storage. Reply attribution runs before recent-context timestamps are rendered, preserving the
catch-up marker until its original-time label has been produced.

Claude's audit ran the full Python suite. It showed that reply resolution dropped any candidate without a readable
time, which `test_host.py`'s scene-isolation fixture relies on. Such a line cannot be shown to be later than the
reply, so it now stays a candidate ranked below every dated one. No live row lacks those times. After the fix the
full suite passed (470), and the adapter self-test passed again (281).

The owner restarted the production profile manually and then explicitly requested a live lookup experiment.
The installed code was checked against the checkout before the experiment.

## 7. Live lookup experiment (2026-10-09)

Codex identified itself as a development agent, not the owner, in the existing local Web conversation and asked
for a dated human statement from one imported group. The answer was selected from the source beforehand and was
not supplied in the question. The character delegated a read-only lookup to the action brain.

The action brain recovered the exact statement, its original UTC timestamp and its archive message ID. All three
matched the original source record. It also kept uncertainty about the statement's intent separate from its
verbatim text. The result and screenshot are in the private `live-experiment/` evidence directory.

This was **not a successful ordinary history lookup from the local conversation**: `query_authorized_history`
correctly reported a scope containing the local conversation and its configured private-chat link, not the named
group. The action brain then used `development_database_read`, the read-only maintenance interface, to obtain the
archive. It took 32 tool calls and about two and a half minutes of action execution. No read link or permission was
changed for the experiment, and no group message was requested or sent by its task.

Thus the live archive and source fidelity are confirmed, while ordinary cross-group lookup from home remains
limited by the accepted scope design. A normal history-tool experiment would need that group's own authorized
context or an explicitly configured read link. The maintenance report also described the displayed `occurred_at`
as local storage time; the actual stored value is UTC and the tool formats it for reading. Its separately quoted
original UTC timestamp was correct.
