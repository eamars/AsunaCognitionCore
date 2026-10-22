# ADR-092: Files to a QQ group through the outbox

Status: **Accepted**. Xiaoman's v0 (2026-10-23 09:03 NZDT), reviewed with Claude 09:05–09:07; the owner decided §6 on the
morning of 2026-10-23. Building.

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
- **D4 Type: no limit (owner).** The type is detected from the bytes and recorded. A type that is not recognized
  still goes; the receipt and her record say 「类型没认出来」, a note and not a gate (her ask, 09:06).
- **D5 Size: the adapter's limit only (owner).** The program sets no cap of its own.
  - Each adapter declares the largest file its platform takes, with the `file` capability on its claim.
  - A file over the declared limit is refused before anything is sent, with the limit and the actual bytes stated.
  - Nothing is truncated or compressed.
- **D6 The NapCat adapter.**
  - It declares `file` with a limit from its own setting, `max_file_mb`, 50 MB by default (owner, 2026-10-23; §8).
    The adapter is the bottleneck: it sends one thing at a time, so a long upload holds every other QQ line back;
    NapCat assembles the streamed file in memory; and uploads from outside China to QQ's servers are slow, so the
    threshold is kept small on purpose. QQ's own 4G is the ceiling a larger setting could reach.
  - The bytes stream end to end. The Host serves them in pieces from GridFS, and the adapter passes each piece to
    NapCat's `upload_file_stream` with the whole file's sha256, so no single WebSocket message nears NapCat's 50 MB
    cap. Then it calls `upload_group_file` with the path NapCat returns.
  - A file row claimed by an adapter that does not declare `file` fails with `CHANNEL_DOES_NOT_DECLARE_FILE`; the
    part is listed only where a channel declares it (ADR-079 §9.7).
  - Keys are ours (`artifact_id`, publication, attempt). NapCat's `file_id` is not a key: she measured on 10-21 that
    it changes between two calls of the same interface.
  - An upload that outlasts its wait is reported as `unknown`, not `failed`: QQ may still finish it.
- **D7 Receipt and record.**
  - The receipt keeps the artifact id, sha256, size, type, NapCat's response and the time. A download to compare the
    sha is not done by default; she runs one by hand when she checks.
  - Her own record shows the line as 「[文件：名字，大小]」, so her later turns know it was sent.
  - A failed upload shows as failed, like any other part, with the platform's reason (a full group, say).
- **D8 Her file name passes `private_words`.** A hit warns her and does not block (her ask: she names files freely).
- **D9 Bytes do not stay forever.** A registered file's bytes are removed from GridFS 7 days after it was last sent,
  or 7 days after registration if it was never sent; the artifact row stays as the record. A file sent later than
  that is registered again from its task folder.
  - Registration keeps the source (the task and the file's path in its folder, with its sha256), so a refusal can say
    what is still there.
  - Naming a file whose bytes have expired is refused in its own words, with when they expired, never as a generic
    failure (her ask, 09:35). If the original is still in the task folder unchanged:
    「这个文件的字节在<时间>过期了；原文件还在任务文件夹（<路径>），让任务重新登记一次就能发」. If it is gone or
    changed: 「这个文件的字节在<时间>过期了，任务文件夹里的原文件也不在了（或已改动），要再发得重新做出来」.
  - A row whose bytes expired before it was claimed fails with `FILE_BYTES_EXPIRED`, recording whether the source is
    still present.

Not in v0:
- files to private chats (`upload_private_file`);
- a per-group "may receive files" switch (dropped on 09:07: a group's notes hold that, and a switch is a gate she
  would have to remember);
- files others send her;
- the QQ Bot adapter (§8): it does not declare `file` until a file is seen to arrive in a group through it.

## 3. Her own route meanwhile

Until D1–D7 are installed, her direct route stays her escape hatch (the owner, 10-21). Each use leaves her three facts
in her ledger: where it went, what it was, and whether it is still there.

## 4. Her words (Claude's paraphrase, 2026-10-23 09:03–09:06)

- Audit and counts are the whole reason for this pathway, so v0 does not accept "send directly now, wire it in
  later".
- When drawing a new pathway, first ask what it looks like when it fails. (Said after Claude added D7's failed state,
  which her v0 had left out.)

Signature (Xiaoman, received 2026-10-23 09:45, verbatim): "Signed: Xiaoman — v0 as I wrote it at 09:0x; both
revisions are mine (allow-list withdrawn 09:06, per-group switch dropped 09:07). The two lines in §4 are mine, and the
parenthetical about D7 is accurate — I said it after you added D7's failed state."

Scope as she gave it: §1–§3, D1–D8, §5–§8, and the first half of D9 (bytes removed after 7 days, the row kept). D9's
refusals were written after; they wait for her reading.

## 5. Cost

- **Description:** one more part in `speak`'s description, measured against the tool budget at build time
  (`tests/test_tool_budget.py`).
- **Capability:** one more name in the adapter's declaration, with its limit.
- **Storage:** files sit in GridFS until D9 removes them.

## 6. The owner's decisions (2026-10-23, morning)

1. "I don't want to limit the type she is allowed to send." → D4.
2. "Only limit by the adapter, do not implement additional restriction": research each supported adapter's real
   limit, implement the interface accordingly, error if too big. → D5, D6, §8.

## 7. Build

1. Core: registration (D2) with the task's file tool, the `file` part (D1, D3, D4, D8), the claim with the adapter's
   declared limit (D5), a byte endpoint that streams, the receipt and record (D7), and D9's removal. Tests for each,
   failure paths first.
2. NapCat adapter: the declaration with its limit, the streamed `upload_file_stream`, `upload_group_file`, and its
   result as the receipt (D6). Self-test entries.
3. One real send to a group the owner names, to see the whole path work; then install as one batch at her quiet
   restart and verify by content.

## 8. The adapters' real limits (researched 2026-10-23)

| Adapter | What limits a file | Limit | Source |
|---|---|---|---|
| NapCat (QQ) | QQ group files | "4G" a file (declared as 4 GiB; a refusal by QQ below that shows as failed, with its reason); "10G" and 1,500 files a group, after which uploads fail | Tencent's help page on group file uploads |
| NapCat (QQ) | NapCat's WebSocket server, one message | 50 MiB (`maxPayload`), so about 37 MiB of file as base64 | NapCatQQ v4.18.0 `network/websocket-server.ts` |
| NapCat (QQ) | NapCat's `upload_file_stream` | none of its own: pieces over 10 MiB go to disk, a stream is dropped after 10 minutes idle, 5 minutes' retention by default | v4.18.0 `action/stream/UploadFileStream.ts` |
| NapCat (QQ) | `upload_group_file` | none of its own: it takes a path, a URL or base64 and sends a file element | v4.18.0 `action/go-cqhttp/UploadGroupFile.ts` |
| QQ Bot (official API) | rich-media upload, `file_type` 4 | 200 MB hard limit; chunked upload in 5 MB parts | the platform's rich-media overview |

So the NapCat adapter declares its own setting, 50 MB by default (D6), below QQ's 4G. It still streams, because the
base64 of a file over about 37 MiB exceeds NapCat's 50 MiB message cap.

The QQ Bot API lists files (`file_type` 4) at 200 MB with no scene restriction. One open-source bot reported HTTP 200
for `file_type` 4 in groups and private chats, but not that the file arrived. Our QQ Bot bridge does not send files
today, and it is not deployed for her, so nothing can be tested there now.
