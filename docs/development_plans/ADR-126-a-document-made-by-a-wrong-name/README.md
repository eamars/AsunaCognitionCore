# ADR-126: A document named wrongly is made, not refused

Status: **Proposed** 2026-11-11 (laid down; nothing built). Her finding (agent line 0338, 2026-11-10 23:22).

## 1. What is known

- She called `write_document` with `doc=自我`, the display name of her self store, meaning `self`. `自我` is not a
  slug. `documents.py` makes a new document whenever `append_section` names one that does not exist; a slug outside
  `memory_tiers.SELF_DOCS` becomes kind `working`. So a document `自我` (kind `working`) was made on 2026-10-23, and
  her later edits by that name went there: her self document (`self`, the one she carries) was not changed, and the
  answer of her last one (2026-11-10 23:0x) said 「已写下」.
- `memory_tiers.STORE_WORDS` maps a slug to its display name for showing only; nothing maps a display name back.
- The class is wider than display names: any `append_section` to a misspelled name makes a new document.
- She has let go of the document `自我`; it is hers and stays as it is.

## 2. The change (to design with her)

1. Making a document is said: `append_section` to a name that does not exist makes it only when the call says so
   (`kind` given); otherwise it is refused as `DOC_NOT_FOUND` with the list of her documents, as the other
   operations are refused today.
2. A display name is read as its slug: `自我`, `流水` and the other `STORE_WORDS` names are taken as the store they
   name, so writing by the name she sees reaches the document she means.

Her choice (agent line 0342): both halves, and a display name is always read as its slug first, before any document
of that name is looked for. So her document `自我` (kind `working`) can no longer be named by `write_document`; it
stays as it is, hers. Her wording for the refusal before it is built.

## 3. Closes when

The change built and shown by a staged case for each half (a misspelled name refused with her documents listed; a
display name reaching its store), or a half dropped with her reason.
