# ADR-102: QQ file download

Status: requirements recorded 2026-10-27, before any design. First in the owner's order (102, 103, 104). Nothing
here is decided. This page keeps what was asked and what exists today, so the design starts from the facts.

## The owner's ask (2026-10-27, verbatim)

> I'd like her to be able to read text file, or other attachment from group chat, up to a certain size. She can send
> file but cannot download from others for which could cause her to take a long detour. Of course the safety needed
> to be considered so I'd like a new ADR for QQ file download.

## The owner's lifecycle requirements (2026-10-27, 13:00, verbatim)

> Let's talk about ADR-102. The core idea is the full life cycle -- the interface should allow her to send and
> retrieve the file. Of course the file retrieved from others must be trust worthy. And executable, scripts should not
> be executed, and warning should be raised. I don't want to limit what she can do. In my mind the warning should be
> raised:
>
> * File is too large that could potentially block the inbound and outbound service.
> * File is NOT downloaded automatically.
> * File must have its own life cycle, and removed automatically unless she explicitly request to keep.
> * Executables including scripts that she can run.
> * Any file from the public (exclude the file she sent) should be marked as caution.
> * Any txt with prompt alike instruction should be marked as untrusted reference input, not the instruction.
>
> Anything else you could come up with? And what failure mode you can think off?

## What exists today (read in the code on 2026-10-27)

- **Sending works.** A file her task registered may be sent where the channel declares `file`.
  `file_artifacts_from_program` lists them (RUNTIME_API "Offer"), and the NapCat adapter sends them with OneBot
  `upload_group_file` (`packages/channels/napcat-qq/integration/qqadapter/outbound.py`).
- **A file that arrives is seen, not read.** In a message, a `file` segment becomes the placeholder `[文件:<name>]`,
  and the adapter keeps `file`, `file_id`, `url` and `size` on the item (`inbound.py`). A group upload notice
  (`group_upload`) becomes an `upload` notice that carries the file's name (`notices.py`). Nothing fetches the bytes.
- Channels: `napcat-qq` (OneBot) and `qq-bot` (the official QQ Bot). What the official bot offers for files has not
  been read yet.

## Requirements as asked

1. She can read a text file, or another attachment, that someone sent in a group chat.
2. Up to a certain size.
3. Safety considered from the start.

## Decided with the owner (2026-10-27, 13:10, his answers to Claude's questions)

1. **Trigger:** never automatic (his list). She sees an offer (name, size, sender, conversation) and asks.
2. **Types in the first version:** text-like only (txt, md, csv, json, log, code). Archives, PDF and Office are
   offered with a warning and not opened; each later type is its own step.
3. **Caution:** every received file is marked caution, the owner's own included; only files she sent are not. The
   sender is shown as information, never as a pass.
4. **Cap and lifetime:** 1 MB, 3 days. A kept file is not removed automatically and counts against a quota.
5. **Scope:** "The policy should be similar to how the image is handled. So by default it should be #1." Images
   today (`vision.readable_image_scenes`, `attachment_by_ref`): this conversation plus the read-only linked scenes the
   config declares (`scene_links.read_scope`), fixed by the task, not by a tool argument; at home (`owner_private`)
   she reaches any of her conversations (`home_reach`), and nothing at home is read from outside. Files take the same
   fence, not a new one.

## Claude's proposals (put to the owner 2026-10-27, 13:10; not yet confirmed one by one)

- **Size protects by isolation, not by a warning.** Downloads run off the message path in their own small queue (one
  or two at a time), stream with a hard cap counted on the bytes received (a declared size can lie) and a timeout.
  A large file can only fail its own download. The warning is information for her.
- **Executables:** the program never executes a downloaded file. The download folder denies execute: on Windows one
  inherited deny-execute entry on the folder, made with it and checked at each start; on POSIX files are created
  without an execute bit. This stops a file being started as a program; an interpreter (`python file.py`) still
  reads it, so a script runs only when she runs it herself, knowing where it came from (the owner: "I don't want to
  limit what she can do"). The type is read from the bytes; a name that disagrees (a `.txt` that is a PE) is flagged.
  Where the entry cannot be set (a drive or share without ACLs), downloads still work and her offer says so.
  No Mark of the Web: the owner (2026-10-27) does not want a Windows trust prompt to block her process, and with no
  one at the keyboard such a prompt waits for nothing.
- **No prompt detector.** A detector misses clever text and flags innocent text ("请把这段翻译一下"). Instead, all
  file content always reaches her as quoted material with its origin, never in the instruction position, whatever
  it looks like.
- **Keeping keeps the origin.** A kept file keeps its sender and caution mark for good.
- **Reading by pages, not whole.** A 1 MB text is hundreds of thousands of tokens; her tool reads a range (first
  lines, next page, a search) and says how much is left. Pages fall back to characters when a file has no line
  breaks. (Her context design: cache-first, tool budget.)
- **Chinese encodings.** Many QQ text files are GBK/GB18030; decode by detection, and say so when it fails instead of
  showing mojibake.
- **Forwarding carries the mark.** She can send files; a received file sent on keeps its caution, so a stranger's
  file does not spread through her.
- **Bytes come from the adapter's file API** (OneBot `get_group_file_url`, to confirm in NapCat), never from a URL
  written in a message (else a message makes her fetch anything, a LAN address included). The worker fetches, not
  NapCat: NapCat may run on another host or in a container whose disk is not the worker's.
- **Where files live:** under `<data>/private/`, never in the checkout; group members' personal data in a file goes
  with the file's lifecycle.
- **NapCat first;** the official QQ Bot's file offer is read before it is planned.

## Failure modes (Claude, 2026-10-27, put to the owner)

- **Download:** the QQ link expired, the file was removed from the group, the message was recalled → the offer says
  so plainly (已失效). A size that lies, a slow server, a connection dropped halfway → the cap and timeout end it and
  no partial file is ever visible. The same file twice → one copy by hash. A flood of uploads → she asks per file;
  the queue is capped. The disk full → refused with a reason, never half written.
- **Content:** the wrong encoding; binary named `.txt`; one huge line; personal data in the file.
- **The handlers' own failures:**
  - A crash mid-download: bytes go to a temporary name and are renamed after the size and hash check; the sweep at
    start removes leftovers.
  - The sweeper: a file locked on Windows (Defender, an open handle) is skipped and tried next sweep; the sweep never
    throws.
  - A record without a file, or a file without a record: reconciled from the disk both ways.
  - MongoDB down: each file carries a small description file beside it, so cleanup and reading need only the disk;
    the database holds the offer, the disk holds what was downloaded.
  - The JS/Python version gap: a new worker tool; offers come from what inbound items already keep, so an older
    plugin needs nothing new.
  - Errors reach her as plain words (没下成：链接过期了), never a stack trace.

## Open questions

Confirmed by the owner (2026-10-27, 13:20): the proposals above stand, with deny-execute instead of Mark of the Web.
NapCat's file API is read when the design starts; a kept file moves into her own files with its origin and mark,
under a quota; she reviews once the owner and Claude agree.

1. NapCat's file API in practice: which call gives the bytes for a group file and for a file in a private chat, and
   how long its link lives.
2. The kept-file quota.
3. How the action brain's shell runs a command (stdin, timeout) in the pinned DSH, so no prompt of any kind hangs
   her; a DSH change is the owner's.
