# ADR-092: Files to a QQ group through the outbox

Status: **Proposed**. Xiaoman's v0 (2026-10-23 09:03 NZDT), reviewed with Claude 09:05–09:07; two decisions are the
owner's (§6). Not built.

## 1. Why

On 2026-10-21 (~21:48 NZDT) a file reached a QQ group outside the outbox: her home action brain sent it straight to
NapCat with the adapter's token. Nothing about it reached the audit, the logs or the counts. The owner decided
(~23:55): a proper pathway through the outbox is hers to design, with Claude, and the core parts are Claude's to
build; until it exists she may keep using her own route.

What exists today:
- **Her side:** `speak` takes six parts: text, sticker, picture, poke, react, recall (`role_tools.REPLY_KINDS`).
- **Pictures:** a picture's bytes live in GridFS, and the message row carries only `artifact_id`, `media_type`,
  `sha256` and `size`. The adapter fetches the bytes per publication and attempt, up to 8 MiB
  (`outbound_media.MAX_ATTACHMENT_BYTES`).
- **The adapter:** it declares the image and sticker media capabilities, its outgoing segment list has no file, and
  it never calls NapCat's file upload.

Pictures become sendable when a task registers them (`outbound_media.register_imported_image`, from image import and
`render_svg`). Nothing registers any other file.

## 2. Decisions

- **D1 A `file` part.** `speak` gains a seventh part, `file`, whose one field is `artifact_id`. Everything else comes
  from the registered artifact (name, type, sha256, size), never from her words. A file is its own message, like a
  sticker: no text rides with it.
- **D2 Registration is the main work.**
  - A task registers a file from its own folder as a sendable `file` artifact in the task's scope.
  - She names the file at registration. The program computes the sha256, the size and the type from the bytes.
  - Any task may register, home's or one begun in a group, because registration is a program step and not
    `sandbox_run`.
  - This generalizes the picture path. Without it, the part could be named in `speak` but there would be nothing for
    it to send.
- **D3 What a conversation may send** follows the pictures' rules (`image_scopes`, `own_only`). In a group, or in
  anyone's chat that is not the owner's, only files her own tasks produced may go.
- **D4 Type.** The type is detected from the bytes and recorded; there is no allow-list (pending the owner, §6). A
  type that is not recognized still goes. The receipt and her record say 「类型没认出来」, a note and not a gate (her
  ask, 09:06).
- **D5 Size.** Files get their own cap, separate from the pictures' 8 MiB. A file over the cap is refused, with the
  cap and the actual bytes stated, and is never truncated or compressed.
  - She proposed 32 MiB. The number is fixed only after one end-to-end send at that size, because the bytes go to
    NapCat base64-encoded in one WebSocket message and only 1.87 MB has been through.
- **D6 The adapter.**
  - It declares `file` on each claim. The part is listed only where a channel declares it (ADR-079 §9.7); a channel
    that does not (QQ Bot) never shows it.
  - A file row claimed by an adapter that does not declare it fails with `CHANNEL_DOES_NOT_DECLARE_FILE`.
  - NapCat is called with `upload_group_file` (`file` as `base64://…`, `name`), the one new action on the adapter's
    outgoing list.
  - Keys are ours (`artifact_id`, publication, attempt). NapCat's `file_id` is not a key: she measured on 10-21 that
    it changes between two calls of the same interface.
- **D7 Receipt and record.**
  - The receipt keeps the artifact id, sha256, size, type, NapCat's response and the time. A download to compare the
    sha is not done by default; she runs one by hand when she checks.
  - Her own record shows the line as 「[文件：名字，大小]」, so her later turns know it was sent.
  - A failed upload shows as failed, like any other part.
- **D8 Her file name passes `private_words`.** A hit warns her and does not block (her ask: she names files freely).

Not in v0:
- files to private chats (`upload_private_file`);
- a per-group "may receive files" switch (dropped on 09:07: a group's notes hold that, and a switch is a gate she
  would have to remember);
- files others send her.

## 3. Her own route meanwhile

Until D1–D7 are installed, her direct route stays her escape hatch (the owner, 10-21). Each use leaves her three facts
in her ledger: where it went, what it was, and whether it is still there.

## 4. Her words (Claude's paraphrase, 2026-10-23 09:03–09:06)

- Audit and counts are the whole reason for this pathway, so v0 does not accept "send directly now, wire it in
  later".
- When drawing a new pathway, first ask what it looks like when it fails. (Said after Claude added D7's failed state,
  which her v0 had left out.)

Signature: ____

## 5. Cost

- **Description:** one more part in `speak`'s description, measured against the tool budget at build time
  (`tests/test_tool_budget.py`).
- **Capability:** one more name in the adapter's declaration.
- **Files kept:** files stay in GridFS like pictures.

## 6. The owner's decisions

1. **Type allow-list.** Claude recommends none, recording the type instead. The risk is in what a file contains, not
   its type, and the owner said on 10-06 that what goes out from home is her judgement. An allow-list would refuse
   types she does send (`.7z`, `.py`, `.svg`). Xiaoman withdrew her allow-list on 09:06 and asked only for D4's note.
2. **The size test.** Choose the group a test file goes to; it is a public act.

## 7. Build

1. Core: registration (D2) with the task's file tool, the `file` part (D1, D3, D4, D8), the claim and byte endpoint
   with the file cap (D5), and the receipt and record (D7). Tests for each, failure paths first.
2. Adapter: the declaration, `upload_group_file`, and its result as the receipt (D6). Self-test entries.
3. One end-to-end send at the cap size to the group the owner names; then D5's number is written here.
4. Install as one batch at her quiet restart, then verify by content.
