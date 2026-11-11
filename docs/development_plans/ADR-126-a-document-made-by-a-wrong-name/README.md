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

- Her count (agent line 0355, 2026-11-11, structure only): four `working` documents carry a display name of
  `STORE_WORDS` (`人设`, `口吻`, `自我`, `活账`). The journal has the same slip on its own path: `journal_entries`
  holds two slugs, `work_log` (1,131 rows) and `流水` (350 rows, still written on 2026-11-11). None of the four
  documents is in `memory_tiers`, so `recall` does not find their text (she searched one principle written there on
  2026-11-05: not found).
- `kind=working` does not mark them: `voice` is `working` too and is carried by its name (`carried.IDENTITY`). What
  marks them is a name equal to a display name, with no `memory_tiers` rows.
- Many of her documents have Chinese names on purpose; only the seven display names are read as slugs.

## 2. The change (to design with her)

1. Making a document is said: `append_section` to a name that does not exist makes it only when the call says so
   (`kind` given); otherwise it is refused as `DOC_NOT_FOUND` with the list of her documents, as the other
   operations are refused today.
2. A display name is read as its slug: `自我`, `流水` and the other `STORE_WORDS` names are taken as the store they
   name, so writing by the name she sees reaches the document she means.

Her choice (agent line 0342): both halves, and a display name is always read as its slug first, before any document
of that name is looked for. So her document `自我` (kind `working`) can no longer be named by `write_document`; it
stays as it is, hers. Her wording for the refusal before it is built.

3. The journal path: `流水` read as `work_log` for new entries; whether the 350 rows under `流水` move, and how
   carrying picks journal entries (by slug or by store), is read in the design first.
4. The documents already made this way (her ask, line 0354): once a display name reads as its slug, her document
   `自我` can no longer be written, and must not stay silently, since `recall` can still bring its text back. She
   reads its four sections and moves into her self what she wants, by hand; the program never guesses. Then it
   leaves her store by a designed path (whether one exists for a `working` document is read in the design). She is
   moving what she wants from all four (自我 done 2026-11-11); none leaves before she says it is moved. The change
   covers every one, not only `自我`.

## 3. Closes when

The change built and shown by a staged case for each half (a misspelled name refused with her documents listed; a
display name reaching its store), or a half dropped with her reason.
