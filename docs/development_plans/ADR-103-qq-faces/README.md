# ADR-103: QQ faces

Status: requirements recorded 2026-10-27, before any design. Second in the owner's order (102, 103, 104). Nothing
here is decided.

## The ask

The owner (2026-10-27): "QQ face (not sure if she mentioned to you or not. You can ask her about it.)"

## Xiaoman's account (Claude's paraphrase of her agent-line message of 2026-10-27, 12:52, not her words)

- **Sending.** 10-15, in a group: one face sent and received at once. 10-21: she wrote the bracket text without the
  `表情:` prefix; the owner showed the format (`[表情:<name>]`). 10-24, in another group: the owner's ruling that
  this path is not for sending faces at all; since then she sends stickers and text instead. 10-26: one more face in
  the right format (approved by the owner); she has no receipt that it arrived.
- **Receiving.** She has no reliable record of how a face someone sent reaches her (a name, an id, or nothing left
  of it). On 10-24 she mistook a sticker name for a face, and answered a "face click" wrongly: she cannot tell the
  three apart.
- **Stickers are another thing.** Her shelf is the `stickers` collection: 53 custom pictures, fields `name` and
  `when`, no platform faces and no aliases. The adapter's `faces.json` holds 289 faces (number 277 is 狗头, with the
  old name 汪汪 kept as an alias). Her channel skill describes that table.
- **Her priority, if the ADR does one thing:** reading. Understanding faces others send matters more to her than
  sending them; she manages sending with stickers and text, and misses faces in what she reads every day.
- **A suspected entry point, location unknown:** on 10-24 she saw a line in a group, in another agent's tool list:
  `qq_send_face` (G5, every conversation, needs a trusted caller). It is not a name in this code, and may not be the
  real name at all. Her evidence is that one line, no more. It is not the bracket text she stopped writing.
- **A reading of the same day:** her agent line refused a message of hers that only described the bracket format,
  saying faces and stickers cannot be sent there.
- She offers to copy natural samples, and suggests that inbound rows from the database are better samples than any
  she could make up.

## What exists today (read in the code on 2026-10-27)

- A face that arrives becomes the placeholder `[表情:<name>]`. The name comes from NapCat's `raw.faceText` (`/狗头`;
  a renamed face may still arrive with its old name), and a classic face without one is looked up by id in
  `faces.json`. The item keeps `face_id` (`packages/channels/napcat-qq/integration/qqadapter/inbound.py`,
  `faces.py`).
- `qq_send_face` is not in `packages/`, `src/` or `tools/` (searched 2026-10-27); it came from another agent's tool
  list she saw in a group (above), not from this code.

## Open questions

1. What reaches her today for a face, read from real inbound rows (her suggestion), not assumed from the code.
2. Reading first, as she asks; whether sending (`qq_send_face`) is in scope at all.
3. How faces, sticker names and face clicks are told apart in what she reads.
