# ADR-126: A document named wrongly is made, not refused

Status: **Proposed** 2026-11-11; designed and built on a branch the same day, landing after her word (§2.5). Her finding (agent line 0338, 2026-11-10 23:22).

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

## 2. The change (reviewed 2026-11-11 at the owner's ask; her agreement, agent line 0358 to 0360)

The broken invariant: the program shows her one name for a document and takes another. `write_document`'s
description named her documents by the shown words (人格、口吻、活账), its `kind` said 「journal 流水」, and the
things block and `recall` labelled her items 「自我」「流水」; the tools take slugs. She wrote what she was shown, and
she was told: when big sis turned the document 流水 into rows (2026-11-09 12:28, agent line), the message said to go
on writing `append_section`, `replace_section` and `set_tags` to `doc=流水`. Most of its 352 entries were written on
that word; they are her real record, not a mistake to clear, which is why they join work_log (4).

1. *Where she reads a name, she reads the one she writes.* `write_document`'s description names her documents by
   slug (persona, voice, self, core, work_log, beside their words), its `kind` is required for a new document, its
   `doc` lists work_log; the things block, `recall`'s `store` and the full-carry line show a store as its word with
   the names of its documents (「自我（self）」「流水（work_log）」; a group's notes 「群笔记（group_notes）」, never by the
   group's id; `memory_tiers.store_label`). A document outside any store (a working document) is listed in none.
2. *A shown word is never a document's name.* `write_document` and `recall` by `doc` refuse a word of
   `STORE_WORDS` (not `core`, which is its own slug) as `DOC_NAME_IS_A_STORE_WORD`, listing that kind's documents, or
   saying it has none yet (`DocumentStore.store_word`, her wording). Not a redirect: 流水, 活账 and 群笔记 name a kind
   that can hold several documents, and a second name for each document would have to be honoured by every tool that
   takes a name. A document already named by such a word is left as history, never listed.
3. *Making a document is said.* `append_section` to a name that is not a document makes one only with `kind`;
   without it, `DOC_NEW_NEEDS_KIND` lists her documents (her wording). Her self, core and a group's notes, whose
   names the program gives, are made by their first write as before. This would not have stopped 流水, which she
   made with `kind: journal`; rule 2 does.
4. *流水 joins work_log, once* (her choice, line 0358: she uses `doc:流水#sid` refs as pointers in her plans, notes
   and self). No sid is in both records (0 of 352 and 1,132), so every section keeps its sid. A one-off tool
   (`<data>/private/claude-tools/merge_journal.py`, not tracked) runs while her worker is stopped at the install:
   the 352 entries become work_log entries (merged with work_log's by `created_at`, each record keeping its order,
   numbered 1 to 1,484), their 179 revisions follow, their 352 tier items and 2 move rows are re-keyed, their 352
   index rows (`memory_shadow`, rows `item`) are re-keyed with their embeddings, so nothing is embedded again, and the
   27 near-duplicate pairs naming them (`memory_shadow`, rows `pair`) are re-keyed too: the index recomputes a pair
   only when an item's text changes, so a deleted pair would not have come back. Fields written, and no others: a
   moved entry's `_id`, `slug`, `seq`; a work_log entry's `seq`; a revision's `slug` and `entry_id`; a tier item's
   `_id` and `doc`; a move row's `doc` and `item`; an index item's `_id` and `doc`; a pair's `_id` and `items` (and the
   store's own `revision`, `_last_op`, `schema_version` where it writes). No time, text or tag changes. The record's 205
   revisions from when it was one document stay as history. One `journal.merged` audit row. Run on a copy of her four
   collections first (2026-11-11 16:40, dropped after): work_log read back with 1,484 sections, every old sid, each
   entry's `created_at`, `updated_at` and text hash the same before and after, no tier or index row left on 流水,
   the order unbroken, all 67 pairs present and none naming a missing item; then planned on her data without writing
   (the same counts). Evidence (her ask, line 0361): the rosters before and after (every entry's slug, sid, seq,
   `created_at`, `updated_at`, `body_sha256`) with `SHA256SUMS`, the copy run's in
   `<data>/private/evidence/adr126/copy-run/` (about 0.7 MB), the live run's in `<data>/private/evidence/adr126/`.
5. *The four documents named by a word* (人设, 口吻, 自我, 活账). She moves what she wants from them first (自我 done
   2026-11-11) and says when all four may go; rule 2 then makes them unnamed history. The landing waits for her word.

Cost: the character brain's tool descriptions +96 characters (budget 21,254). Not changed: her past nights' reviews,
which listed work_log only, are not filled in for the days she wrote to 流水.

Tests (`tests/test_doc_names.py`, each failing on the old code first): a shown word refused with what she means, and
with none yet; 流水 with `kind: journal` refused; a new name refused without `kind` and made with it; `recall` by a
shown word refused; the store labels.

## 3. Closes when

The change built and shown by a staged case for each half (a misspelled name refused with her documents listed; a
display name reaching its store), or a half dropped with her reason.
