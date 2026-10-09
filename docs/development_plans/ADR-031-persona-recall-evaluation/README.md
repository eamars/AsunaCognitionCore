# ADR-031: evaluation of automatic recall for her persona sections

Status: **Concluded 2026-10-09: retrieval by the incoming turn is rejected for her persona sections; A then B.** See §6
for the benchmark that settled it. The owner asked for a careful evaluation before any
build because the earlier Kazusa design of this kind ("prewarm") was patched repeatedly and never worked well, and a
bad design could pollute Xiaoman. Xiaoman holds the decision on how her own pool is organised; this document is the
evidence for that decision and for the owner's review.

## 1. The problem

Her persona and voice documents render into every turn's system prompt. Measured 2026-10-09:

| Part | Sections | Tokens (estimate) |
|---|---|---|
| Shared core text | — | ~505 |
| Always loaded, public | 6 | ~3,040 |
| Always loaded, owner-private | 6 | ~2,515 |
| **Total always loaded** | 12 | **6,069 of a 6,144 limit** |
| On demand (read only through `recall`) | 14 | ~7,471 |

- Two always-loaded sections serve one kind of turn each: outings (~1,669 tokens) and the old-home reports (~991).
- On-demand content is effectively dormant: since 10-05 she called `recall` in 21 of 1,253 turns (1.7%).

The wish: keep only what must act instantly loaded, move the rest out, and still have it present when it matters.

## 2. What went wrong with Kazusa's prewarm (diagnosis, 2026-10-09)

Prewarm retrieved shared memory before every first cycle and injected up to five rows. It was never measured: no hit
rate exists in any of the four checkouts, plans, test artifacts or the local database. The evidence-backed failures:

1. **A polluted store** was injected unfiltered: a 07-02 audit found 99 of 202 active shared rows flawed.
2. **It was silently unwired for two weeks** while its tests stayed green.
3. **It searched with the wrong text:** the bot's own @mention dominated the query, and the turn was duplicated.
4. **A model-written query** dropped its required field on short input.
5. **Authority was mislabelled:** guidance rules were injected as plain facts.
6. **There was no per-item relevance check** (one whole-set verdict) and no signal of whether an item was used.
7. **A chat line was judged as if it were a question** (inferred from code).
8. ~~The score threshold was calibrated on a different corpus.~~ Corrected by the benchmark (§6): the prewarm path had
   no score threshold at all; the defect was that nothing gated items.

Its authors' own conclusions: no retrieval-first again, and only widen after real audits show repeated failures.

## 3. How automatic recall would pollute her here

These follow from how this runtime carries a turn's content forward, not from a guess about a model:

- **Injected text persists.** Anything placed in a turn's messages stays in the DSH session history. It is carried
  into compaction summaries and into the carried summary of ADR-028, so one wrong injection outlives its turn.
- **It feeds back into memory.** What she reads in a turn shapes her `think` text and replies. Those become chat
  chunks, monologue units and summaries, which recall and summaries read later. A wrong or stale section can
  re-enter her memory as her own experience. That is a loop: injected → said → remembered → retrieved.
- **Authority blurs.** A section placed in front of her reads as current instruction. A stale rule is reasserted
  each time it is matched, and she has no way to tell a program's reminder from her own decision.
- **Visibility can leak.** A private section matched in a group turn is a privacy failure with an audience.
- **It is hard to measure.** "She needed it" has no ground truth in her data; Kazusa never established one. Without
  one, a shadow run can count matches, but cannot say whether a match was right.

## 4. Options

**A. Load each section only in the turns it serves (deterministic).**
- How: each section is tagged with the turn kinds and scene classes it is for. The render includes it there and
  nowhere else.
- Benefits: no retrieval, nothing injected that is not in today's always-loaded text, nothing missed silently. The
  two single-purpose sections alone free about 2,600 tokens in other turns.
- Risk: a rule wrongly scoped is absent where it is needed. Mitigations: she writes the split list (the outing
  section mixes in parts home turns need), and each turn kind's render is listable for review.

**B. A visible index of what is on demand (a menu, not content).**
- How: each turn shows one short line per on-demand section: title, what it governs, when to read it, the date
  written and whether it was corrected. She reads a section with `recall` when a line applies.
- Cost: about 14 lines, roughly 30 tokens each.
- Benefits: content enters a turn only when she chooses it, so nothing is injected she did not ask for. It answers
  the actual gap: dormant sections are forgotten, not unreachable.
- Risk: she may still not pull. That is measurable: the recall rate before and after, and her own review of misses.

**C. Automatic recall in shadow (records, feeds nothing).**
- How: deterministic matching of her index lines' trigger conditions against the turn (no model-written query).
  Four recorded outcomes: none / matched-not-relevant / matched-would-feed / error.
- Cost: a match per turn; no tokens in her context; nothing persists in her session.
- Limit: without a ground truth it measures match rates, not correctness. A usable ground truth would be her own
  labelling of a sample, or matches against sections she then recalled herself in the same turn.

**D. Automatic recall live.**
- Every risk in §3 applies.
- If it is ever built, where the content goes is a trade-off the benchmark measured (§6): message placement persists
  until compaction and partly into summaries; system-prompt placement breaks the prompt cache on every turn (group
  sessions run about 95% cached). It must be labelled as a program reminder, carry its source and
  age, and respect visibility.
- Gate: only if C shows a reliable, labelled signal, and A + B leave a measured gap.

## 5. Recommendation

- **Build A now.** It is decided by her and needs her split list.
- **Then B.** It is cheap, explicit and cannot inject unasked content, and it targets the measured problem (1.7%
  recall).
- **Run C only as an experiment with a defined ground truth,** agreed with her before it starts.
- **Do not plan D.** Revisit only if C and real audits show repeated misses that A + B do not prevent: Kazusa's
  authors' own threshold.

Xiaoman's acceptance conditions (2026-10-09) apply to every option that retrieves:
- no model-written queries;
- visibility respected;
- rules excluded by type;
- items carry source, date and a corrected flag;
- at most one or two items, each with the reason;
- she can see what was matched;
- a wiring test asserting the text reaches the request sent to the model;
- four distinguishable outcomes;
- a shadow gate of 200 turns or two weeks.

## 6. Benchmark and conclusion (2026-10-09)

The owner asked to conclude whether prewarm failed by design or by implementation. An independent agent sorted
Kazusa's failures (3 implementation, 4 design, 1 both) and benchmarked a clean build on her real turns, with every
implementation fault removed: the message as she received it (her own @ stripped), no model-written query,
deterministic vector search with a threshold calibrated on her data, per-item judgement, and an LLM reranker proxy as
an upper bound. Data: 1,311 character turns since 10-05; 248 stratified turns labelled offline (model labeller,
evaluation only; 80% agreement with a blind hand-labelled sample of 50).

- **Vector only** (deployed embedding model, section openings): at a cosine of 0.65 it matches 15% of turns with
  precision 0.50 and recall 0.28; at 0.70, precision 0.89 but recall 0.12. On turns where the needed section already
  existed: precision 0.24, recall 0.27. Short index lines are worse keys than section openings. A larger embedding
  model is no better.
- **Vector + reranker proxy:** precision 0.64 at recall 0.34 overall. On turns where the section already existed:
  precision 0.19, recall 0.30, no better than vector only. No real cross-encoder runs on the deployed servers.
- **Her own recalls:** for 4 of her 5 real section reads, the matcher ranked the section she chose 15th to 25th of 26.
- **Instability:** the gap between the top two matches is 0.02 at the median. Prepending her @ flips the top match
  in 13 of 40 turns.
- **Visibility:** in public turns the nearest section is owner-private in 35 of 37 matches.
- **Noise:** 23% of her turns are program-templated (heartbeats, hand-backs, plans), and match noise.

Conclusion: a flawed idea for her persona sections in this runtime, not only a badly built one. What she needs is
decided by the scene, the conversation's state, or a lesson being learned in that conversation, not by the words of
the incoming message. By scene alone, the two single-purpose sections cover 41 of the 68 labelled needs. Persistence
of injected content is real through the session and its summaries; the loop back into memory exists in mechanism but
was not observed (on-demand phrases appear in 1 of 1,923 monologues and none of 11,526 chunks).

Decision: build A (turn and scene scope; the outing section stays always loaded in groups, the old-home reports in
the sister line), then B (the visible index), with a recall-rate baseline of about 1.4% of turns. Instrument recall
reads and the owner's corrections now; they are the ground truth of real misses. Retrieval returns only if a
measured gap remains, and then only as a shadow over scene-scoped candidates, with a real reranker, on 200 turns
where the section already existed, gated at precision ≥ 0.6 and recall ≥ 0.5. Never unscoped vector-only with a
threshold. Not evaluated: retrieval of memories and facts keyed by topic words, which is a different problem.
