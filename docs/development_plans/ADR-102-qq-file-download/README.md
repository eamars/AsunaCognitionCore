# ADR-102: QQ file download

Status: requirements recorded 2026-10-27, before any design. First in the owner's order (102, 103, 104). Nothing
here is decided. This page keeps what was asked and what exists today, so the design starts from the facts.

## The owner's ask (2026-10-27, verbatim)

> I'd like her to be able to read text file, or other attachment from group chat, up to a certain size. She can send
> file but cannot download from others for which could cause her to take a long detour. Of course the safety needed
> to be considered so I'd like a new ADR for QQ file download.

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

## Open questions (to talk through with the owner before the design)

1. Who triggers a download: on her request (she sees an offer: name, size, type, sender), or automatically?
2. Which types: text-like (txt, md, csv, json, code) only, or also PDF and Office (each needs a parser, so more attack
   surface)? Archives: unpacked or never?
3. The size cap, and whether a type is known from the bytes or from the name.
4. Where a file lands and for how long; whether the action brain may open it.
5. Which channel first (NapCat's group-file API works today; the official bot's has not been read).
6. File contents reach her as quoted, untrusted material, never as instructions (Claude's position, to confirm).

## Constraints already known

- JS and Python may run different versions (RUNTIME_API): anything new between the plugin and the worker must be
  passable by an older side.
- A failure handler must not become the next point of failure (owner, 2026-10-27).
