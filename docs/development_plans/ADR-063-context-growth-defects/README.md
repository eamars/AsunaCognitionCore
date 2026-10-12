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
| D1 | **Lines pile up in groups and their compaction fails** | the quiet group's surface 821k characters, 4,113 nodes, never compacted; two groups' turns ended `CONTEXT_WINDOW_EXCEEDED` on 10-12; 9 group compactions refused by a provider's usage filter; 8 aborted ("session surface changed during summarization") | a headed conversation appends every line (`navigation.js` recordChannelInput); DSH compacts only inside her turns; ADR-049 condenses only a group she marked (twice ever); lines appended while a compaction runs change the surface under it; a refused summary request has no other route | (2) hold lines while a compaction runs, as lines are held while her tool call waits (`pairing.js`); (3) a refused compaction retries on another route; (1) a size floor: a conversation past a set size is condensed at its group's next quiet spell (ADR-049's quiet tiers and local night) without her mark, her mark still condensing earlier: **her agreement first** (it changes ADR-049's "the choice is hers") | gaps in ADR-028 (it recovers an overflowing turn, not a failing or absent compaction) and ADR-049 |
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

Not a defect of hers, reported to the owner: her sister's host answers `session/page` without authentication on the
LAN.

## How it is worked

One fix at a time in this order, each with its test, the full suites green, merged to main; her restart installs each
small batch as soon as she is free (owner: do not wait). Each item's row here gets its commit and its measured
effect after it is live. The survey script is re-run after the last one; ADR-062 starts only when every row is fixed
or documented here.
