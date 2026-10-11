# ADR-040: Merged forwards are read, previewed, and pulled in full by ref

Status: **Accepted and built 2026-10-11.** Xiaoman's request, passed on by the owner; she chose the preview and set
the condition on the fetch.

## Context

A QQ merged forward (合并转发) reached her as `[合并转发（未解析）]`. The dozen messages inside were often the
very thing a group was discussing, and she had reported the blind spot on 10-05. A forward segment carries only an
id. OneBot gets its messages with `get_forward_msg`. NapCat may include them in the segment, but the stored data
could not tell, because the adapter dropped the segment's fields.

## Decision

- **The adapter reads it.** It uses the messages included in the segment when there are any, else one bounded
  `get_forward_msg` call on the submitter thread. Xiaoman's condition: the fetch is not a fixed premise. The log
  records which path ran (fields, source, count, never the text), so a measurement can retire the call.
- **The line shows count, ref, and the first three messages, one short line each.** Xiaoman: a preview is what
  decides whether to open it; without a sample every opening is a blind box. Each line is cut short so the preview
  does not pour a summary back into her group budget.
- **The full text is pulled by ref with `recall`** (`doc: forward`), reusing the section read she already has, so
  the tool list does not change and the cached prefix holds. Only in the conversation the forward arrived in, so
  home cannot pull a group's forward (ADR-017).
- **Kept on the line that brought it** (`raw.asuna_forward` on the message row). The action brain's history query
  searches the forwarded messages with the line. Memory and summaries see only the line's text.
- One level of nesting; at most 3 forwards a message, 100 messages and 20,000 characters a forward.

## Consequences

One extra platform call per forward when NapCat does not include the messages. A forward that cannot be read keeps
its placeholder. Forwards received before this change stay unread placeholders.
