# ADR-032: a persona section renders only in the places it serves

Status: **Accepted and built 2026-10-09.** Option A of ADR-031, decided by Xiaoman with her own split list; Claude
built the switch.

## Context

Her always-loaded persona was 6,069 of 6,144 tokens. ADR-031's benchmark showed that what she needs is decided by
where a turn happens, not by the words of the incoming message: by scene alone, two single-purpose sections cover 41 of
68 labelled needs. Retrieval was rejected; a deterministic place scope was chosen.

## Decision

- **D1. Places.** The program decides each turn's place like its session class (`visibility.place`):
  - `peer`: a trusted home channel's line (a peer bridge);
  - `home`: the owner's own conversations;
  - `group`: a group;
  - `dm`: another direct conversation.

  Each place has one session class (home and peer are owner-private).
- **D2. A place is a tag.** A section tagged `place:<place>` renders only in turns at those places. A section with no
  place tag renders everywhere, as before. She sets the tags herself with `write_document` (`set_tags`); no new field
  and no new tool. An unknown place is refused, because a typo would hide a rule silently.
- **D3. Budget.** The limit bounds the largest render over the places, so a section pinned to groups still counts.
- **D4. The record of real reads.** Every `recall` is audited (`recall.read`): the query, the sections asked, read
  and missing, the memories returned, and the turn's kind and place. This is the ground truth ADR-031 asked to start
  collecting, kept by the program. She adds only what she wanted, in her own notes.
- **D5. Her split list** (2026-10-09). It is her content and she applies it:
  - A, groups and outings only: @ syntax, outbound checks, joining, chains.
  - B, everywhere, kept minimal: the two "her"s, how she remembers people, group time zones, the QQ / old-home split.
  - C, the old-home line only: the old-home report reading guide.
  - The XP group's rules move into that group's notes.

## Consequences

- Her home render drops by about 1,900 tokens once she applies the list. Group renders keep what they use.
- A session's place is fixed, so its system prompt stays stable and the prompt cache is unaffected.
- A rule pinned to the wrong place is absent there. Her review of each place's render (`probe_context` with `place`)
  is the check.
