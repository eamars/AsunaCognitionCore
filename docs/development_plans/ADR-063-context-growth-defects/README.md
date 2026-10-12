# ADR-063: Context growth defects: what makes her conversations grow faster than they should

Status: **Accepted 2026-10-13** (owner: fix every defect in priority order, the prerequisites of ADR-062 included;
ADR-062 does not start until each item here is fixed or documented). Items that change what she decided go to her
first (D1 part 1).

## Context

The owner saw her context grow much faster per turn than her sister's (a plain DSH session) and asked for a survey of
recent turns in every kind of conversation. Measured 2026-10-13 (turns after ADR-056 went live, 2026-10-12 08:21 UTC;
her sister read live, read-only):

| Conversation | Characters added per turn | Compactions a day |
|---|---|---|
| Her sister, plain DSH | 3,290 | 1.0 |
| Local chat | 27,976 (notice 19,620) | 12.5 |
| Agent line | 19,152 | 6.4 |
| DSH peer line | 18,996 | 4.6 |
| Busiest QQ group | 11,861–15,686 | 1.2 |
| A quiet QQ group | lines only, 821,739 characters on the surface | never compacted |

Of the local chat's excess over her sister (about 24.7k characters a turn): about 3.1k are the defects below, up to
2k the fixed reuse window (D2), about 4.3k her larger reasoning and tool calls (by design), and about 14k blocks sent
by design (plans, relationship, self, stickers, notes, memories), which is ADR-062's ground. Scripts and outputs:
Claude's scratchpad `growth/`.

## Defects, in the order they are fixed

| # | Defect | Evidence | Cause | Fix | Relation |
|---|---|---|---|---|---|
| D1 | **Lines pile up in groups and their compaction fails** | the quiet group's surface 821k characters, 4,113 nodes, never compacted; two groups' turns ended `CONTEXT_WINDOW_EXCEEDED` on 10-12; 9 group compactions refused by a provider's usage filter; 8 aborted ("session surface changed during summarization") | a headed conversation appends every line (`navigation.js` recordChannelInput); DSH compacts only inside her turns; ADR-049 condenses only a group she marked (twice ever); lines appended while a compaction runs change the surface under it; a refused summary request has no other route | (2) hold lines while a compaction runs, as lines are held while her tool call waits (`pairing.js`); (3) a compaction refused by a provider: deferred (owner 2026-10-13: provider refusals are their own matter, later; the local model refuses none); (1) a size floor: a conversation past a set size is condensed at its group's next quiet spell (ADR-049's quiet tiers and local night) without her mark, her mark still condensing earlier: her agreement given 2026-10-13 with three conditions (notes first, told every time, groups only; floor half the compaction threshold; ADR-049's last section) | gaps in ADR-028 (it recovers an overflowing turn, not a failing or absent compaction) and ADR-049 |
| D12 | **A held line is lost on a stop** | found reviewing D1 (2) | a line held while her tool call waits or a compaction runs lives only in memory, and its receipt is acknowledged to the worker as it is held; a stop before its release leaves it out of the conversation for good (Mongo keeps it) | acknowledge a receipt only once its line is in the conversation (on release), if the worker redelivers unacknowledged receipts | fixed after D1, before D3 (owner) |
| D3 | **A task result carries its report twice and every tool record's id** | 12 local results of 10–15k characters: `facts[].text` repeats `text`, `evidence_refs` up to 450 ids; in `event`, always sent | `tasks.py` builds `facts` with the whole report and all ids; `bounded_result` pages `text` but passes `facts` | `bounded_result` leaves `facts` out of what she is shown (Mongo keeps it) | independent |
| D5 | **Group continuity resends lines still visible** | 85–97% of `current_speaker_tail` and `related_messages` rows already on the surface | `composeContext` filters only `delivered_history` against visible rows | drop rows whose id is visible (citations are checked against the prepared context, not the notice) | independent |
| D6 | **The places block changes every minute** | 11 sends of 5.5k, all different | `their_time` ("那边现在 HH:MM", `places.py`) | give a group's offset from her clock once, not its current time | prerequisite-friendly |
| D8 | **The document references are resent each turn** | 80% of each `ref_index` identical to the last | `ref_index` mixes this turn's ids with every document section id | this turn's ids stay; document references move to a block of their own that folds | prerequisite-friendly |
| D10 | **Recalled memories repeat lines still visible** | chunks whose every source line is on the surface | `exclude_sources` covers only the last 12 history rows | the Host drops such a memory using the visible rows | independent |
| D9 | **A fully folded block still sends its wrapper** | about 0.2k a turn | `context-delivery.js` sends `{items: [], same_as_before}` | a block with nothing kept and an unchanged rest is named unchanged | **ADR-062 prerequisite** |
| D4 | **Lists inside a block never fold** | `recent_experience_from_program` 69.5k sent, 46.9k foldable; `affect_from_program.reasons` | `listOf` sees only a top-level array or `items` | fold every object list by block and field path | **ADR-062 prerequisite** |
| D7 | **The ceiling trims what is prepared, not what is sent** | 36 of 49 local turns trimmed while the median notice is 19.6k; her self text cut in 14 of 23 sends, each cut different | `trim_turn` halves the longest texts of the whole prepared context (48k) before the Host removes what she still sees | apply the ceiling to the composed notice, or cut only at fixed per-block limits | **ADR-062 prerequisite** |
| D2 | **Copies older than the reuse window are resent** | about every 4–5 turns; 4.2k a turn locally, 2.0k on the agent line | `REUSE_WINDOW_TOKENS` 32,768 counts only the newest stretch | count visibility from the last compaction checkpoint (what DSH keeps verbatim), composing after any compaction in the step | **ADR-062 prerequisite**; the owner's go (2026-10-13: "prerequisites need to be done") |
| D11 | **Small repeats** | `rhythm.local_time` repeats `clock.now_local`; one group surface holds two system prompts from a model switch | duplicate field; a reopen after the model switch | drop the field; nothing for the second prompt (it leaves with the next compaction) | independent |

### Progress

| # | Commit | What changed | Measured effect |
|---|---|---|---|
| D1 (1) | 77512efa | the condense plan looks at every group she is routed to; at a quiet spell after new lines the Host measures the conversation (`conversation_size`: DSH's meter, floor half the preset's compaction threshold); past it a notes visit (intent `condense`) first, condensing at the next quiet spell after it ran; groups only; the first turn there after any condensing is told (no one-day window); an oversized summary request is made in steps (`compaction.js` `inSteps`) | after her restart: the 821k group's first condense, sizes of groups past the floor |
| D12 | f4360acb | the worker projects every unacknowledged receipt again at each start (`navigation.ready`), each on its own; `recordChannelInput` answers `held` and the Host acknowledges a held line only after `release` wrote it and the conversation was flushed (`CognitionCore.written`) | none to measure: a stop while a line is held |
| D3 | 1203b5cb | `bounded_result` leaves `facts` (the report again with every tool record id) out of what she is shown; the stored result keeps it | after her restart: task-result notice sizes |
| D5 | ac8f6dc1 | `composeContext` drops a `group_continuity_from_program` line whose id is visible (her own line while its turn is), counts it in `repeated_from_program.history_rows` and carries the sent ones; citations check the prepared context, unchanged | after her restart: group notice sizes |
| D6 | f4ecc9a9 | a group row in `places_from_program` says how its clock stands to hers (`their_clock`, `places.clock_gap`: changes only with a zone or a daylight-saving switch) instead of `their_time`; `place_timezone` list still gives the time there | after her restart: places items folded |
| D8 | a3c5d2b6 | `ref_index` holds this turn's two ids; document section refs go to `doc_refs_from_program` (block guide explains it once; `context.refs` still counts them); the `feel` ref description is unchanged (no tool-budget cost) | after her restart: ref_index sizes |
| D10 | 3bc6703e | the Host leaves out a recalled memory (not a thought of hers) whose `source_event_ids` are all visible rows, the same rows `delivered_history` is filtered by; chosen over a wider `exclude_sources`, which can only guess what the surface shows | after her restart: memories resent |
| D9 | 184df050 | a folded send records the whole block's digest (`carried.lists`); the identical block again with every item visible is named in `unchanged_from_program` | after her restart: empty wrappers gone |
| D4 | 70a0e7b4 | `composeContext` folds every object list in a block's fields, at any depth, by its path (`block.field…`, `fold`), waiting items always sent; the block guide's `same_as_before` line says a list may be inside a block | after her restart: recent_experience and affect sizes |
| D7 | e83f8757 | the prepared context is kept whole; the worker hands the ceiling's table to the Host (`context_budget.ceiling`), which applies it to the composed notice (`trimTurn`: same row order, then halving the longest text) and drops what it cut from what is carried; under the ceiling nothing is cut; a context sent whole is trimmed by the worker on its way out (option 1 of the row: one rule, applied where the notice is known) | after her restart: trimmed turns and self-text cuts |
| D2 | 2ae6063f, 1ef70c6b | invariant (owner 2026-10-13): nothing the latest notice called unchanged may be missing from the surface when the model reads the next request; a fixed window or the retained tail does not hold it (a pressure compaction later in the turn keeps only the tail measured then). A copy counts as visible anywhere on the surface (after the last checkpoint); the Host keeps the turn's notice, and at each step's start, after DSH's own pre-step compaction, if a compaction committed since the notice was composed, what of its context the surface (with that step's claimed messages) no longer shows goes out as a follow-up notice (`restoreContext`, `restored_from_program`, explained once in the block guide). The first commit (reach sized by the retained tail) is superseded. Left open: a context-overflow compaction retries its request without a pre-step, so that one retried request can miss copies until the next step restores them | after her restart: resends beyond the old window, restore notices after compactions |
| D11 | aea4e43c | `rhythm_from_program.local_time` is left out when it equals `clock_from_program.now_local`; the second system prompt on one group surface is left for that conversation's next compaction | none to measure |
| D1 (2) | b34c122b | a line arriving while its conversation has a `compaction/start` without its `compaction/end` is held (`pairing.js` `compactionOpen`) and joins as the compaction ends, committed or failed (`releaseAfterCompaction`); a start older than the log's last `session/end-seed` (opened again after the process stopped mid-compaction) holds nothing, as in DSH's compaction lock. A held line lives in memory only and is acknowledged to the worker when held: a stop before its release leaves it out of the conversation (Mongo keeps it) | after her restart: aborted compactions in the day audit |

Not a defect: her sister's host answers `session/page` without authentication on the LAN. That is by design (owner
2026-10-13: a local server, no login wanted).

## How it is worked

One fix at a time in this order, each with its test, the full suites green, merged to main; her restart installs each
small batch as soon as she is free (owner: do not wait). Each item's row here gets its commit and its measured
effect after it is live. The survey script is re-run after the last one; ADR-062 starts only when every row is fixed
or documented here.
