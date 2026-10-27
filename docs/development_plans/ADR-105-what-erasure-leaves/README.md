# ADR-105: What erasure leaves

Status: decided by the owner 2026-10-27. Built 2026-10-27 for every place that exists today (see Built); the
places of ADR-102's received files (`read`, `kept`, `copy`) are built with ADR-102. This page is the canonical rule; ADR-102 and the picture and file code cite it, and none keeps its own version.

## Why

An operator's privacy erasure (`asuna` CLI `delete-memory`, `PrivacyService._erase`) deletes every stored byte of the
memory's conversation: `BlobStore.erase_scope(scope)` deletes each GridFS file whose `metadata.scope_key` is that
scope. Then `PrivacyService._erase` replaces every `artifacts` row of the scope, as it does every episode, task and
message, with a stub that keeps only its identity (`state: INVALIDATED`, no `storage`, no name, no size). Every reader
looks a row up with `state: DONE`, so it answers with a generic "not found", and she reads it as a file that never had
content (Xiaoman, her ADR-102 verdict of 2026-10-27: "账上还有引用，东西已经不在").

*Corrected 2026-10-27, in the build.* This paragraph first said the erasure does not touch the `artifacts` rows and
that a reader fails on a `gridfs_id` pointing at nothing. Claude had read only `erase_scope`, not the rest of `_erase`;
the build's test of a real erasure found the stub. The problem is the same, and so is the rule; the build also keeps
the marked rows out of that stub (Built), since the owner's decision 2 is that the row keeps its name.

Counted on 2026-10-27 by Claude, read-only queries on the deployment's database, before this page was written: no
erasure has run in this deployment (`audit_events` has no `privacy.intent`), and no `artifacts` row misses its bytes
(0 of 1,282 `storage: gridfs` rows). The hole is in the code's shape, not in the data.

## Decisions (the owner, 2026-10-27, in the question tool)

1. **Bytes gone, a marked row.** Erasure stays conversation-wide, files she kept included: privacy wins. Each row
   whose bytes it deleted is marked, and whatever reads or sends it says so in words of its own.
2. **The row keeps the name.** Asked whether the mark may keep a file's name (a name can itself be personal), the
   owner, verbatim: "We don't help with keeping someone else's privacy if the file is already shared online, so I
   won't additional censorship or privacy protection for someone's careless act." The row keeps its name, size,
   sender and when, as it was. **This holds for every file whatever its source or place:** one someone posted in a
   group, one the owner sent her at home, one she made herself. The reason the owner gave is not a test of which
   files it covers; no kind of file gets its name hidden on the strength of it.
3. **Its own ADR,** this one, as the one place the rule is written.

## The rule

- **Marking.** `erase_scope` marks every `artifacts` row of the scope whose bytes it deleted: `storage: 'erased'`,
  `erased_at`, `deletion_id` (the erasure's id, as in the audit), and drops `gridfs_id`. It marks rows by the scope of
  the row, not only by the GridFS files it found, so a row whose bytes were already gone is marked too. Nothing else of
  the row changes.
- **Offers.** Every list that offers stored media already reads `storage: 'gridfs'` only, so an erased row leaves
  every offer by itself (the pictures of a turn, the files she may send, her received files).
- **Looked up by id, read or sent.** Every place that finds one row by its id and finds it erased answers with one
  sentence, never a generic "not found" or a storage error:

  > 这%s被隐私清除删过（%s），字节已经不在了，拿不回来；不是没有内容。

  The first `%s` names the thing by its kind, as she reads it: 张图 for a picture, 个文件 for a file (one she sent,
  or one she received). The second is when, on her clock. This is "the ADR-105 sentence" other pages cite. The places, from the code of 2026-10-27: `BlobStore.get` and `BlobStore.get_range`;
  `vision.stored_image` and `vision.local_upload_bytes` (`read_image` of a stored picture); `outbound_media.accept_artifact`
  and `outbound_media.serve` (a picture attached to `speak`); `outbound_files.check`, `claim_failure` and `serve_piece`
  (a file sent with `speak`); `received_files` (ADR-102: `read`, `kept`, `copy`). A claim already on its way when the
  erasure ran fails with the same words as its `failure_detail`.
- **Said when she names it, not after.** Sending is where this is easiest to miss: the sentence comes in the very call
  that names the erased file (`speak`'s `file` or picture, `attach_image`), so she never sees a part accepted and then
  a delivery that fails. A file a task registers again from its folder is new bytes, not the erased row; one whose
  folder copy is gone gets the folder's own words.
- **In RUNTIME_API with the build.** The reference she reads at every turn carries both sentences once they are true:
  what was erased says it was erased, never that there is nothing; a ref found by scanning messages lives 7 days, a
  kept file's does not end (ADR-102). RUNTIME_API shows only what is, so they land with the code, not before.
- **Kept received files** (ADR-102) are erased with the rest; `kept` lists them with the sentence, until she lets
  them go.
- **Copies on disk.** A received file's copy in a task folder (ADR-102 `copy`) is recorded on its row and removed with
  the row's bytes, erasure included.
- **Stickers are outside this path.** Her shelf and the sticker pool are stored in `global-safe`, and a conversation
  erasure refuses that scope (`GLOBAL_ERASURE_REQUIRES_ALL_SCENE_MIGRATION`), so no sticker is erased by it. If an
  erasure of `global-safe` is ever built, the shelf and the pool list an erased sticker with the same sentence and
  sending it answers with it.
- **`storage` has three values now** (`gridfs`, `removed`, `erased`), so every reader of it is named here, from the
  code of 2026-10-27: the lookups and offers above read `gridfs` only; `BlobStore.put_once` deduplicates against
  `gridfs` rows only, so the same bytes arriving after an erasure are stored anew, never matched to the erased row;
  `media_life.sweep` reads `gridfs` rows only, so an erased row is never swept and never an error;
  `outbound_files.removed` tests `removed` only, so an erased file is not said to have expired. A reader added later
  is held by the structural test below.

## Failure modes

| What fails | What happens |
|---|---|
| The erasure stops between deleting bytes and marking rows | The rows are marked by scope when it runs again; until then a reader that finds a row without bytes answers with the storage error in words, not "not found" (`ARTIFACT_BYTES_MISSING`, a program fault). |
| A row is marked but a GridFS file of it survived | The mark wins: nothing reads bytes of an erased row; the next erasure of the scope deletes the file. |
| A reader written later forgets the mark | A test lists every `artifacts` lookup by id in `src/asuna` and fails for one that does not handle `erased`. |

## Not changed

What erasure deletes (bytes, memories, revisions) and who may run it.

## Built (2026-10-27)

- `blobs.py`: `ERASED`, `ERASED_WORDS`, `erased`, `erased_words`, `refuse_erased`. `erase_scope(scope, deletion)`
  deletes the scope's GridFS files, then marks every row of the scope whose storage is `gridfs` or `removed`. The
  bytes go first, so a stop between the two leaves no byte behind; running it again marks what is left. A `removed` row
  is marked too: its bytes are gone either way, and for ADR-102's received files `removed` means "fetched again from
  the link", which an erasure must stop. `BlobStore.get` and `get_range` check the fence, then the mark, then read; a
  row whose GridFS file is missing answers `ARTIFACT_BYTES_MISSING` in words.
- `privacy.py`: `_erase` passes its `deletion_id` to `erase_scope` and leaves rows marked `erased` out of its stub
  (Why). Every other `artifacts` row of the scope is still replaced as before.
- Each place looks the row up without filtering on `storage`, checks its own fence, and only then says the sentence,
  so it never tells anyone that a row outside their fence exists: `vision.stored_image`, `vision.local_upload_bytes`,
  `outbound_media.accept_artifact` and `serve`, `outbound_files.check`, `claim_failure` (`FILE_ERASED`, its
  `failure_detail` the sentence; `FAILED_CODES` carries it to her record) and `serve_piece`.
- **Said when she names it** also for a picture this turn did not offer: `outbound_media.refuse_erased_named` runs
  the same fence (`_fence`) without reading bytes, for `speak`'s picture and `attach_image`.
- **One place this page did not list,** found by the structural test: `stickers.keep` of a picture she drew. Its
  lookup filtered on `gridfs`, so an erased drawing answered "不是你自己画好的图", which is false. It now says the
  sentence.
- RUNTIME_API: "Erased media", and the codes in the claim and the byte endpoint.
- `tests/test_erasure_marks.py`: 17 tests, the structural one included; 21 mutants, each turning its own test red.

## Tests

Erasing a scope marks each of its rows and no other scope's; each lookup place answers the sentence, the sending ones
each by a test of their own (`speak` with an erased file, with an erased picture, `attach_image`), in the call that
names it; offers leave erased rows out; a kept received file shows the sentence in `kept`; a copy is removed; the sweep passes an erased
row; the test that every lookup by id handles `erased`. Each mutation-checked.
