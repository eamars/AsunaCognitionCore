# ADR-105: What erasure leaves

Status: decided by the owner 2026-10-27; not built (it is built with ADR-102, whose received files are its first new
kind). This page is the canonical rule; ADR-102 and the picture and file code cite it, and none keeps its own version.

## Why

An operator's privacy erasure (`asuna` CLI `delete-memory`, `PrivacyService._erase`) deletes every stored byte of the
memory's conversation: `BlobStore.erase_scope(scope)` deletes each GridFS file whose `metadata.scope_key` is that
scope. It does not touch the `artifacts` rows, so each row still says `storage: gridfs` with a `gridfs_id` that points
at nothing. A reader then fails with GridFS's own error, or with a generic "not found", and she reads it as a file
that never had content (Xiaoman, her ADR-102 verdict of 2026-10-27: "账上还有引用，东西已经不在").

Counted on 2026-10-27, before this page was written: no erasure has run in this deployment (`audit_events` has no
`privacy.intent`), and no `artifacts` row misses its bytes (0 of 1,282). The hole is in the code's shape, not in the
data.

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

  > 这个文件被隐私清除删过（%s），字节已经不在了，拿不回来；不是文件没有内容。

  `%s` is when, on her clock. The places, from the code of 2026-10-27: `BlobStore.get` and `BlobStore.get_range`;
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
- **The sweep** (`media_life`) treats an erased row as having no bytes: nothing to delete, never an error.

## Failure modes

| What fails | What happens |
|---|---|
| The erasure stops between deleting bytes and marking rows | The rows are marked by scope when it runs again; until then a reader that finds a row without bytes answers with the storage error in words, not "not found" (`ARTIFACT_BYTES_MISSING`, a program fault). |
| A row is marked but a GridFS file of it survived | The mark wins: nothing reads bytes of an erased row; the next erasure of the scope deletes the file. |
| A reader written later forgets the mark | A test lists every `artifacts` lookup by id in `src/asuna` and fails for one that does not handle `erased`. |

## Not changed

What erasure deletes (bytes, memories, revisions) and who may run it.

## Tests

Erasing a scope marks each of its rows and no other scope's; each lookup place answers the sentence, the sending ones
each by a test of their own (`speak` with an erased file, with an erased picture, `attach_image`), in the call that
names it; offers leave erased rows out; a kept received file shows the sentence in `kept`; a copy is removed; the sweep passes an erased
row; the test that every lookup by id handles `erased`. Each mutation-checked.
