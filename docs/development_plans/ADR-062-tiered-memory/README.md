# ADR-062: Tiered memory: down by default, kept up by use, details fade into gist

Status: **Proposed 2026-10-13** (the owner's finding and direction; the design by Claude, building on Claude's earlier
proposal and the owner's). For Xiaoman's review: the words, the capacities and the lapse times are hers to set; the
one-time rewrite of her own texts is hers to do. Nothing here is built.

*Her review:* ____ (her signature). This draft contains no paraphrase of her words; when her answers come, they are
added under "Her review" as Claude's paraphrase for her to sign or correct, as ADR-060 does.

## 1. Context: every store of hers only grows

Measured 2026-10-13 on her live database (counts, lengths and dates only; no content read):

| Store | How it is kept | What happened in 9 days |
|---|---|---|
| `current_self` (`update_self`, whole body, 4,000-character cap) | in every turn of every conversation (3,403 JSON characters median) | 549 → 4,000 characters by day 2; 3,500–4,000 since. 16 items for a week while dated references in it went 0 → 16: details are packed in, nothing leaves. 46 revisions, 3 ever shorter by more than 200 characters. The cap refuses ("…太长了…精简后再调用") |
| `character_core` | in every turn | never written: nothing has ever graduated |
| Persona document | `inject=always` sections in every system prompt (7,327 characters), `on_demand` sections only by `recall` | 1 → 45 sections, 293 → 37,004 characters; 0 sections ever removed; 29 tucked to `on_demand` (29,677 characters), of which **2 were ever read back** in 48 `recall` calls over four days |
| `work_log` | one document, `append_section` (190 of 242 revisions), `inject=on_demand` everywhere | 192 sections, 410,790 bytes, growing 76 KB a day: **about 8 days from the layer's 1 MiB revision cap**; every revision stores the whole document again: 47.3 MB of copies. Read back by `recall`: 0 sections |
| Her two "ledgers" | created with `append_section`, so their `kind` is `working`, not `ledger` | `ledgers_from_program` has been empty all along: they never reach a turn |
| Group notes (13) | in that group's turns, 2,400-character show limit | growing by append; tucked sections 1–4 each; the nightly tidy's 8 settlement turns made 5 tuck-aways, 1 rewrite that got longer, 0 removals |
| Memory units (chat chunks 24,942; dialogue summaries 5,269; her thoughts 3,190; promoted memories 6) | retrieval per turn (6 slots) with the forgetting formula | 87% never selected into a turn; 1,400 selected three times or more. Promotion: 6 memories in 9 days, none since 10-07 (quota 2 a night) |
| Ideas (69 open, 12 deferred), stickers (42 of 60), private words | each has a drop verb | level |
| Understanding (12 "here" records, 1 person record), 4,000 characters each | with the person's turns | small so far; same shape as `current_self` |

Two things are structural, not habits:

1. **The only ways down are refusal and compression.** Every store has a cap and a verb to add; none has a lapse. When
   a cap is hit she is told to shorten, so she compresses details into the same space. "Tucked away" (`on_demand`)
   is the one demotion, and a tucked section is read back almost never (2 of 29): with retrieval not covering her own
   documents, `on_demand` is loss with a polite name.
2. **Nothing is measured by use.** Memory units have `salience.last_ref_at` and a forgetting formula
   (0.5^(days/30) × 0.5^(messages/1500), `retrieval._forget`); her documents, self and notes have no use mark at all,
   so nothing can tell a rule she applies daily from one she wrote once.

What already exists and is right: the revision ledger (nothing is deleted; ADR-009), the per-scope index with
visibility (ADR-017), the forgetting formula and step-back for summarised chunks, the dialogue summaries (program gist
of lines), DSH compaction (gist of a conversation, written by her own compaction prompt), her nightly settlement with
`promote_memory`, ADR-043's rule that what comes back comes back in her words, ADR-056's folding and ADR-038's fixed
tool list. This ADR adds a life cycle on top of them; it replaces nothing that works.

### 1.1 Retrieval-coverage pilot (read-only, 2026-10-13)

The risk in any "down by default" design is that a demoted item is never found again. Replayed against her real turns:
300 distinct query texts of the week (406 turns: 278 home, 128 public; by kind 252 talk, 89 heartbeat, 38 task
results, 14 plans, 7 self-improvement, 6 visits), with the stored vector ranks and scores of what each turn really
selected, and the same embedding route embedding the 29 tucked sections, the 16 always sections and the 16 items of
her `current_self` (one needed the indexer's 400-character opening fallback; the embedding model refuses long
sections whole).

| Items | In the turn's 24 vector candidates, ever / in ≥5% of eligible turns | Would have made the 6 selected, ever / in ≥5% | Median share of turns it would be selected in | Best score (median, p90) |
|---|---|---|---|---|
| 29 tucked persona sections | 25 / 4 | 23 / 1 | 0.4% | 0.837, 0.876 |
| 16 always sections | 15 / 4 | 14 / 2 | 1.2% | 0.843, 0.878 |
| 16 `current_self` items | 15 / 2 | 14 / 0 | 1.2% | 0.828, 0.856 |

The cut a selected memory had to pass was 0.804 (median). So: the existing retrieval does reach her own items when a
turn is about them (best scores sit above the cut), and does not flood ordinary turns (0.4–1.2% each, 317 of 406
turns would have admitted none). Two cautions it also shows: visit turns, whose query is a short program text, would
have admitted about 10 items each (the relative cut collapses when few memories match), so a demoted tier needs an
absolute floor, not only a rank; and a section of 1,000–2,800 characters is embedded by its opening 400 characters,
so long sections are found by their first idea only. Items of one idea each retrieve better than sections of many;
this decides the unit size below. Other readings of the week: 1,942 distinct queries in 2,254 turns (heartbeats share
9 texts, so their memories are driven by the heartbeat text, not by anything live); the top 20 memories carry 11% of
selections; 4% of turns select exactly the set of the previous turn in the same conversation.

Scripts: `scratchpad/memory062/m1_inventory.py`, `m2_coverage.py`, `m3_sizes.py` (counts only; Claude's session).

## 2. The ideas on the table

- **The owner's:** prompt her to keep less important things in a searchable store, let her reflection keep how to
  find them so she does not feel the loss, better wording, and tiers by time with retirement. His frame: a system
  failure needing an architectural answer, not a wording fix.
- **Claude's:** flip the default. Tier 0 (every prompt) is item-structured and capped by item count; overflow
  demotes the least recently confirmed item automatically, with one notice, no refusal and no compressing. Tier 1 is
  the searchable index, surfaced by per-turn retrieval. Tier 2 is cold after weeks without recall, still recallable,
  never deleted. Her acts: confirm, pin a few, bring back. Demotion by use, not age. The owner called this close to
  how a person's memory works and asked for one step further.

This ADR takes that step in four places: the unit of memory becomes one idea everywhere (not a body or a long
section), each item carries two strengths read as words (how recently she confirmed it; how recently it was used),
details are made to fade into gist on a schedule she cannot skip forever, and recall is the act that keeps a memory
up, with the interval between confirmations growing each time (spacing), so what she keeps confirming costs her less
each time and what she stops confirming goes down by itself.

## 3. Grounding: what the sciences and the field say, and what is adopted

Human memory (one citation each; the full brief is Claude's research note of 2026-10-13):

| Finding | Source | Taken here |
|---|---|---|
| Separate stores; rehearsal transfers; working memory holds about four chunks | Atkinson & Shiffrin 1968; Baddeley 2000; Cowan 2001 | Tier 0 is small and counted in items; a chunk is one idea, not a page |
| Complementary learning systems: fast episodic store, slow semantic store, interleaved replay; schema-consistent facts consolidate in about 48 h instead of weeks | McClelland, McNaughton & O'Reilly 1995; Kumaran et al. 2016; Tse et al. 2007 | Episodes (lines, summaries, journal rows) and her semantic layer (self, persona, notes) stay separate stores; the night pass moves a few things between them; a new fact that fits an existing item is merged into it rather than added beside it |
| Sleep consolidates selectively: what is tagged as needed later | Diekelmann & Born 2010; Wilhelm et al. 2011 | The night list is short and chosen by rule (about to lapse, used before, open commitments), never "everything" |
| Forgetting curve; spacing: re-touch at 10–30% of the horizon you need it for | Murre & Dros 2015; Cepeda et al. 2008 | A confirmation extends an item's stay and the next check comes before it lapses; intervals double |
| ACT-R base-level activation: availability follows recency and frequency of use, not age | Anderson & Schooler 1991 | Tiers are decided by last use and last confirmation (the existing `_forget` already is this shape); creation date decides nothing |
| Two strengths: storage strength never falls, retrieval strength decays with disuse; retrieving is the strongest learning event | Bjork & Bjork 1992; Roediger & Karpicke 2006 | Every item keeps "last confirmed" and "last used"; an item used often but not confirmed is offered for confirmation before it drops (high storage, low retrieval: the cheapest save) |
| Reconsolidation: a recalled memory is labile and is updated when there is a prediction error | Nader et al. 2000; Sevenster et al. 2013 (human behavioural versions are contested) | A recalled item does not jump back to tier 0 by itself; it is rewritten when she rewrites it. Her rewrite after a recall is the reconsolidation, and it counts as a confirmation |
| Fuzzy trace: verbatim and gist are two traces; verbatim fades first; forgetting detail improves generalisation | Brainerd & Reyna 2002; Richards & Frankland 2017 | The gist step: a verbatim item that leaves tier 0 gets a gist in her words; the verbatim goes cold at once, still readable |
| Schema: recall is reconstruction; schema-consistent input assimilates, inconsistent input is kept as a flagged episode | Bartlett 1932; Ghosh & Gilboa 2014 | `character_core` is the schema layer; it is written by graduation from things that stayed true, not by a cap |
| Retrieval-induced forgetting and the testing effect | Anderson, Bjork & Bjork 1994 | Being surfaced in a turn counts as use; an item recalled on purpose counts more |
| Autobiographical memory: periods → general events → specifics; self-defining memories are the stable core | Conway & Pleydell-Pearce 2000 | The journal rolls up: rows → a day's gist → a week's; `character_core` holds the self-defining few |

AI agent memory (what each contributes; adopt or reject): see §3.1.

### 3.1 Agent memory systems

Each checked against its paper or docs (Claude's field brief, 2026-10-13); what it contributes, and what this design
takes or leaves:

| System | Mechanism | Taken | Left, and why |
|---|---|---|---|
| MemGPT / Letta (Packer et al. 2023) | fixed-size editable memory blocks in the prompt, recall and archival stores outside, a "memory pressure" warning at ~70% of the window, the model pages with tool calls | capped, labelled blocks the model edits by explicit operations; pressure as a program event (here: the count cap and the lapse) | paging as the only way down: she does not page (48 recalls in four days). Block rewrites in the prompt head every turn would break the cache prefix; here rewrites happen on her writes and at night |
| Generative Agents (Park et al. 2023) | one memory stream; retrieval = recency (0.995^hours since last retrieval) + importance (LLM-rated 1–10 once) + relevance; reflection when summed importance passes 150 | use-based recency (retrieval resets the clock), and a bounded consolidation that cites its sources | LLM-rated importance and additive scores (a number per item that the model would see or write toward; AGENTS.md); the night list is chosen by observed use and age, not by a rating |
| MemoryBank (Zhong et al. 2023) | Ebbinghaus strength R = e^(−t/S), S += 1 on each recall; daily summaries → portrait | one strength that grows with each use, decay computed by the program | time counted from learning rather than from last use; tiers that do not talk to the decay. Here the same freshness decides the place |
| A-MEM (Xu et al. 2025) | Zettelkasten notes with keywords, context line and links written at encoding; neighbours rewritten when a new note arrives | the heading as the retrieval key, written once at encoding (sections and journal rows already have one); near-duplicate pairs offered for merging | one model call per neighbour per insert on a local model |
| Mem0 (Chhikara et al. 2025) | extract facts, then a closed decision per fact: ADD / UPDATE / DELETE / NOOP; graph variant invalidates rather than deletes | the closed categorical set at write and at night (带着 / 放手 / 改写 / 进 core / 合并), program-applied and audited | an extraction call on every exchange in the hot path |
| Zep / Graphiti (Rasmussen et al. 2025) | temporal knowledge graph; bi-temporal edges (valid / invalid, created / expired); a contradiction closes the old edge instead of deleting it | validity by revision: the ledger already keeps the superseded text with its dates, and `detail_of` keeps the verbatim behind a gist, so "what I thought last month" stays answerable | the graph machinery; a persona's items are few and her words, not triples |
| HippoRAG 2 (Gutiérrez et al. 2025) | knowledge graph plus personalised PageRank; node specificity down-weights entities that appear everywhere; no forgetting | specificity is already in the lexical path (corpus-wide terms dropped) | PageRank over a growing chat corpus with no notion of time |
| LangMem (LangChain 2025) | semantic / episodic / procedural stores; hot-path tool vs background manager; a profile updated in place vs a collection | the hot-path / background split (indexing and the night list are background; her writes are the hot path) and profile-vs-collection (随身 is the profile in the cached prefix; 手边 the collection in the tail) | procedural memory that rewrites the system prompt in production |
| Reflexion, Voyager (2023) | a bounded buffer of self-reflections; a skills library kept only after verification | a skill is kept when verified: her skills, not this ADR | — |
| MemoryOS (Kang et al. 2025), H-MEM, HiAgent | short / mid / long tiers; heat = visits + interactions + e^(−Δt); promotion when heat passes a threshold, eviction of the coldest; a finished subgoal's log replaced by one summary with the log retrievable | tiers by heat (use), the coldest down first, the summary with the detail still readable | FIFO capacities and heat numbers; here the words and the ledger |
| Sleep-time compute (Lin et al., Letta 2025); LightMem (2025) | offline rethinking of memory between queries; deferred add / update / merge queues; pays when queries are predictable | the night pass as the place for every costly step; nothing scored per turn | — |
| RAPTOR (2024), MemTree (2024), recursive summarisation (Wang et al. 2023) | summary trees over leaves; recursive summaries lose about 4% of details and invent about 3% per hundred samples | the honest cost of gist-only, which is why the verbatim stays 收着 behind every gist | summaries written by the program over her words (ADR-043 rule 1) |
| LOCOMO, LongMemEval, MemBench (2024–2025) | temporal reasoning and knowledge updates are the weakest abilities everywhere; session summaries raise recall but not answers; several agent memories collapse near 100k tokens while plain retrieval holds; time-aware keys help | retrieval stays the backbone; every item carries clock times and comes back with `when`; a gist never replaces the verbatim | — |
| ChatGPT and Claude memory as deployed (2025) | memory as a user-readable list and summary, per-item delete, suppress without deleting, incognito | memory visible and editable: the memory side panel, `things_from_program`, every move audited | deletion |

Where the field is weak, this ADR takes a position: nothing published forgets *detail* automatically (summaries do,
and lose facts unmeasured); nothing monitors retrieval coverage in production; everything scores per turn with a
model call; and no system keeps a cache-stable prompt head while memory changes. The gist step with the verbatim
kept, the coverage measurements in §7, consolidation only at night, and the place words in a folding block are the
answers proposed here.

## 4. The model

### 4.1 One item, three places, two strengths

Everything she keeps is an **item**: one idea, one place, in her words. A persona section is an item; so is each
entry of `current_self`, each ledger section, each group-notes section, each journal row, each promoted memory, each
idea. The program never rewrites an item's text; it keeps three facts beside it:

- **where it lives** (the tier), one of three words from a versioned table (`TIERS_VERSION`), proposed:
  - 随身 (carried): in every turn where it is readable. Capped by count.
  - 手边 (at hand): in the index; comes up by itself when a turn is about it; found by `recall`.
  - 收着 (put away): out of automatic results; `recall` by a word or its heading still brings it; never deleted.
- **when she last confirmed it** (wrote it, rewrote it, or chose to keep it when asked);
- **when it was last used** (surfaced into a turn, or read by `recall`; the existing `salience.last_ref_at`).

She reads these only as words (AGENTS.md): age words `刚写的 / 这几天 / 上周 / 上个月 / 更早` (under 1, 7, 14, 45 days;
`AGE_WORDS`), use words `常用 / 偶尔用 / 很久没用` (from the same freshness the forgetting formula already computes:
above 0.5 / above 0.1 / below). No number reaches her.

### 4.2 The cycle

```
 encoding ──► 随身 ──lapse──► 手边 ──no use──► 收着
   (her write;        ▲  │ gist step         │ recall by word
    program marks     │  ▼ (night)           ▼ (explicit)
    time + scope)   confirm / rewrite ◄── surfaced in a turn (use)
                    (her act = reconsolidation; interval doubles)
 consolidation (night): lines → summary (program) → her gist / notes / promote → self items → character_core
```

1. **Encoding.** She writes as today (`write_document`, `understand_person`, `promote_memory`, `ideas`, journal
   rows). The program stamps scope and visibility from the turn (unchanged), `added`, `confirmed = added`, and the
   starting place: a persona or ledger section she marks 带着 starts 随身; everything else starts 手边. A journal row
   starts 手边 and is never 随身.
2. **Staying up is her act, with spacing.** A 随身 item has a stay: 14 days from its last confirmation at first; each
   confirmation doubles it (28, 56, capped at 56). When the stay runs out the item lapses to 手边 by itself. No
   refusal, no shortening. The turn after a lapse says so once, at the tail, with a clock time (ADR-056), and how to
   bring it back.
3. **Capacity by count.** 随身 holds at most N items per store (proposed: `self` 12, persona 16, each ledger 10, each
   group's notes 6; her numbers). Adding a 13th does not refuse: the item with the oldest confirmation lapses, and
   the write's result names it. This is the flip: today the oldest stays and the newest is refused.
4. **Detail fades into gist (the forced step).** When an item lapses, the next night lists it if it is long (over
   240 characters) or carries dated specifics. She writes its gist (one or two sentences, ≤ 160 characters) with the
   existing `replace_section`; the program keeps the verbatim as the gist's source (`detail_of`), moves the verbatim
   to 收着 at once, and the gist stays 手边. If she passes it over on two nights, the verbatim goes 收着 without a gist:
   the detail is out of her default view either way. A short item (≤ 160 characters) is already gist and skips this.
   Nothing is deleted; `recall` reads the verbatim through the gist's `detail_of` or by a word.
5. **Use keeps 手边 alive.** 手边 items sit in the same index as her memories (one per idea; owner-private items in
   her owner-private scope, public ones in `global-safe`, a group's notes in that group's scene scope), under the
   same forgetting formula. Below `step_back_below` (0.1: about 100 days unused, sooner in a busy conversation) an
   item is 收着. Being surfaced into a turn is use (already recorded); a `recall` that returns it is use.
6. **Surfacing.** Per-turn retrieval reserves up to two of its six slots for her own items (so her own words are never
   crowded out by 25,000 chat chunks and never crowd them out), admitted only above an absolute floor (to be set from
   the pilot; the week's data puts it near 0.83) in addition to the rank. Each comes with its heading, its age word
   and its place word, and a `doc:…#sid` ref she can rewrite from.
7. **Recall and reconsolidation.** A surfaced or recalled item does not return to 随身 by itself (that would churn
   every prompt and defeat the cache for a thing that may have been incidental). It comes back up when she rewrites it
   or says 带着 on it; that rewrite is the reconsolidation, dated now, and starts a new stay. Her rule from ADR-043
   stands: what comes back is her text, never a summary of it.
8. **Night consolidation (settlement, ADR-049 quiet time, ADR-058 self evaluation).** One short list, at most 5 items
   a night, chosen by rule and told in words why each is there:
   - 快掉下去了: a 随身 item two days from lapsing that was used in the last month (Bjork: high storage, low retrieval;
     the cheapest save). Her choices: 带着 (confirm; stay doubles), 放手 (let it lapse now), 改写 (rewrite).
   - 写一句意思: a lapsed verbatim item waiting for its gist (step 4).
   - 一个月都成立: a `self` item confirmed through three stays unchanged. Her choices: 进 core (one sentence into
     `character_core`), 还在变 (stays), 放手.
   - 合并: two items the index finds near-duplicate (cosine above a high threshold, same store): she merges or keeps
     both. Schema-consistent assimilation, in her words.
   - 回头看: at most one 收着 item a week, chosen at random among those with uses in their history: a chance to bring
     back what the index would otherwise never show her again (Richards & Frankland's transience is useful, but a
     person also stumbles on old things).
   The list replaces `notes_review_from_program` (7,740 characters when it fires) and its "tidy three notes a night"
   framing, which measured as compression, not retirement.
9. **Graduation.** `character_core` is written only from the 一个月都成立 list, as one sentence per item, capped at 12
   items; a core item lapses like any other but with a 56-day stay from the start. This is the schema layer: what stays
   true of her across weeks, not what she thinks this week.
10. **Back to encoding.** Every rewrite is a new revision in the ledger as today; the old text stays as history and
    `recall` reads it. Nothing in this cycle deletes.

### 4.3 What she is told, and when

Fixed text, once per conversation (system prompt, ADR-056 rule 1; about 650 characters, persona-agnostic), in the
place where the memory rules already are. Proposed wording kind (final words are hers):

> 你的东西有三个地方：随身的每回合都在；手边的平时不在眼前，谈到相关的事会自己浮上来，recall 一句话也能找到；收着的只有
> recall 找得到。放下不是丢：从随身放到手边、从手边放到收着，程序只换地方，不改一个字，什么都在。随身的位置有限，
> 一件东西随身一阵子没再确认，就自己放到手边，程序会告诉你一次；你写一遍或说一声「带着」，它就回来，并且下次能留更久。
> 长的细节会退成一句意思，细节还在，由意思那条带着。像人一样：细节淡下去，意思留下来；留下什么由你写，什么时候退由用不用决定。

Per turn, one block `things_from_program` (tier 0, stable; folds under ADR-056 when unchanged):

- counts by store and place in words (随身 几条 / 手边 十几条 / 收着 几十条), when she last tidied (clock time);
- `moved`: what the program moved since the last turn in this conversation, once, with the clock time, the heading,
  the reason word (随身满了 / 一阵子没确认 / 很久没用) and the one line that brings it back. Never a countdown.

In the memories block, a surfaced item of hers reads like a memory with three more words: its store, its place word,
its age word (`「标题」· persona · 手边 · 上周`). A recall result lists headings of 手边 and 收着 items that matched,
beyond the bodies it returns, so she can see what exists without reading it all.

At night, the list of §4.2 step 8, each item with its body and the choices as words; her answer is a categorical
choice the program maps to a move (`keep` on the existing write tool, §5).

What she is never told: numbers, scores, freshness values, item counts as digits beyond the count words, or that the
program "forgot" something: it moved it.

### 4.4 Per store

| Store | Unit | Starts | 随身 cap | Lapse / use | Gist step | Notes |
|---|---|---|---|---|---|---|
| `current_self` → document `self` | one item per section | 随身 | 12 | stay 14 → 28 → 56 days; cap overflow lapses the oldest confirmation | yes | her one-time rewrite of today's body into items; `update_self` retires (§5) |
| `character_core` → document `core` | one sentence per section | 随身, by graduation only | 12 | stay 56 days | no (already gist) | first entries come from the 一个月都成立 list |
| Persona document | section (as now) | her choice on write; existing `always` = 随身 | 16 | as `self`; `on_demand` sections become 手边 (indexed) at once: the 29 tucked ones become findable | yes | `inject` field keeps working and maps to places (`always` = 随身, `on_demand` = 手边, `never` = 收着) |
| Voice | section | 随身 | 6 | stay 56 days | no | small; the voice is schema-like |
| Ledgers (kind `ledger`) | section | 随身 | 10 each | as `self`; `correction` = a rewrite of the corrected item for confirmation purposes | yes | phase 0 fixes the kind of her two existing ones |
| Group notes | section, that group's scene scope | 随身 in that group | 6 per group | stay 28 days (groups move slower); use = surfaced in that group | yes, listed on a `write_notes` visit or at night | public visibility, read only in that group, unchanged |
| Journal (`work_log`) | row | 手边 | 0 (never carried) | use only; rows roll up: each night her gist of the day (≤ 400 characters) is a row of its own; rows over 30 days without use are 收着 | the day gist is the gist step | phase 0 moves it to rows |
| Understanding: person layer and here layer | body as now (phase 3: items) | 随身 with that person | — | later | later | same shape as `self`; small today |
| Memory units: chunks, dialogue summaries | as now | 手边 (chunks step back once summarised) | — | existing formula | summaries are the program's gist | unchanged |
| Her thoughts (`monologue`) | as now | 手边 | — | existing formula (her ADR-043 rule 3: no fast-fading lane) | none | unchanged; recalled with `when` and `then` |
| Promoted memories (`promote_memory`) | fact/appraisal/signal | 手边 | — | existing formula; her rewrite is a confirmation | no | unchanged tool; the public→home path of ADR-017 |
| Ideas | one idea | — | — | an open idea unread for 30 days is listed as 很久没动 in self-improvement with 还要 / 放弃 | no | already has drop; only the age word is new |
| Stickers | shelf | — | 60 | the weekly review gains last-used words | no | unchanged mechanism |
| Private words, credentials, affect ledger, plans, watches | — | — | — | out of scope: a safety list never decays; the vault is blind; the ledger has half-lives; plans and watches end by themselves | — | |
| Dialogue summaries, DSH compaction summaries | — | — | — | out of scope here: the program's gist of conversations already exists; a compaction summary stays with its session (ADR-028) | — | |

Visibility and scope travel with the item through every move: the tier is a third field beside `visibility` and
`scope_key`, never a scope. An owner-private item in 手边 is indexed in her owner-private scope and surfaces only in
owner-private turns; a group's notes index in that group's scope. `recall` in a public turn cannot reach a 收着
owner-private item any more than it can reach a 随身 one today (`read_sections` already refuses). The ADR-017 paths
are untouched: nothing here moves text between home and outside.

## 5. Tools and operations: options on what exists

No new tool. The character brain is at 20,881 of 20,900 characters of tool text (32 tools).

| Change | Where | Characters |
|---|---|---|
| `write_document` gains `keep` (带着 / 手边 / 收着; "where this item lives") and, on the first append that creates a document, `kind` (`ledger` / `journal` / `working`) | option fields | about +190 |
| `write_document` docs `self` and `core` (the two self descriptions as documents of kind `self`) | description names them | about +40 |
| `update_self` retires: `write_document(doc='self', …)` does the same with sections; the old name keeps working as an alias for a while (ADR-055's rule) | tool removed from the list | −388 |
| `recall` returns matching headings of 手边 and 收着 items beside bodies; `recall(sections=[{doc:'self'}])` with no `sid` lists a document's headings | result shape; one sentence in the description | about +60 |
| Her night choices (带着 / 放手 / 改写 / 进 core / 合并) are `write_document` calls: `keep` for the first two, `replace_section` for the third, `append_section` to `core` for the fourth, a `replace_section` plus `keep=收着` on the other for the fifth | no new option | 0 |

Net about −100 characters: the character brain's budget stays at 20,900 (the test's count drops to 31 tools). The
action brain has no memory tool and gains none; `asuna.dbread` reads the same collections. Per-turn lines:
`things_from_program` about 220 characters when it changes, about 40 folded; a `moved` line about 110 characters,
once per move; `current_self` shrinks from 3,403 to at most about 2,400 JSON characters (12 items × 200) in every
turn of every conversation; the night list is at most 5 items with bodies (about 2,500 characters) and replaces
`notes_review_from_program` (7,740 when it fires). The system prompt grows by about 650 characters once per
conversation. Prompt cache: nothing per turn changes except what changed (ADR-038, ADR-056); the memories block already
changes every turn.

## 6. Automatic mechanisms and their triggers

| Mechanism | Trigger | Program does | Tells her |
|---|---|---|---|
| Lapse | a 随身 item's stay runs out (checked when its store is read for a turn) | tier → 手边; index it | `moved` line, once, in the next turn of each conversation that read it |
| Overflow | a write that would make a store's 随身 count exceed its cap | the item with the oldest confirmation lapses | the write's result names it |
| Cooling | a 手边 item's freshness under `step_back_below` | tier → 收着 | nothing per item; the count words in `things_from_program` change |
| Gist listing | the night after a long or dated item lapsed | adds it to the night list | the list, with 写一句意思 |
| Gist done | her `replace_section` of a listed item with a body ≤ 160 characters | keeps the old body as a 收着 revision linked by `detail_of`; the new body is 手边 | the write's result |
| Gist skipped twice | the item was listed on two nights and not rewritten | the verbatim goes 收着 unchanged | the next night's list says it went |
| Edge save | a 随身 item two days from lapse with a use in the last 30 days | adds it to the night list as 快掉下去了 | the list |
| Graduation offer | a `self` item confirmed through three stays unchanged | adds it to the list as 一个月都成立 | the list |
| Near-duplicate | two items in one store with cosine above a high threshold (set in the pilot) | adds the pair as 合并 | the list |
| Stumble | once a week, one 收着 item with past uses, at random | adds it as 回头看 | the list |
| Use | an item surfaced into a turn or returned by `recall` | `salience.last_ref_at` (exists) | nothing |
| Confirmation | any write of hers on the item, or `keep=带着` | `confirmed_at = now`; stay doubles | the write's result |

Every move is one audit line (`memory.moved`: item, from, to, reason) and visible in the memory side panel, so the
owner and she can see the record. Tables (`TIERS_VERSION`): tier words, age words, use words, stays, caps, the gist
length, the floor, and the list sizes.

## 7. Phases, measurements, rollback

**Phase 0, this week (urgent, no design change on her side):**
- **Built 2026-10-13 (2590c104, the owner's call):** `work_log` is a running record (`documents.JOURNALS`), one row
  per entry (`journal_entries`), each change kept beside its entry (`journal_revisions`), written and read by the same
  calls as before; the document's sections move into rows once at its first read after the restart, and its old
  revisions stay as history. It stops the 1 MiB wall and the copies. Indexing the rows at 手边 is phase 1/2.
- Ledgers reach her: `write_document` takes `kind` on creation; she re-creates her two ledgers as `ledger` (or the
  owner sets the kind on the two documents once; his call). `ledgers_from_program` then shows them.
- Nothing else changes. Measure: `ledgers_from_program` present at home; journal bytes per day; no refusal.

**Phase 0b, delivery prerequisites (from the context-growth survey of 2026-10-13):** her conversations grow 6–9×
faster per turn than her sister's plain DSH session (local chat about 28k characters a turn against 3.3k; 12.5
compactions a day against 1), 70% of it the per-turn notice. The cycle above relies on per-turn delivery being
deterministic and visibility lasting longer than a few turns (`things_from_program`, `moved` lines and surfaced items
must fold when unchanged), so these come first:
- **Folding nested lists**: a list inside a block (`recent_experience_from_program` tasks, `affect_from_program`
  reasons) never folds (`context-delivery.js` `listOf` sees only a top-level array or `items`); fold every object list
  by block and field path.
- **The ceiling trims what is sent, not what is prepared**: `trim_turn` halves the longest texts of the whole prepared
  context (48k) before the Host removes what she still sees, so her self text is cut in 14 of 23 sends and each cut
  differs, which defeats folding; apply the ceiling to the composed notice, or cut only at fixed per-block limits.
- **A fully folded block sends nothing**: today it still sends its wrapper; name it unchanged instead.
- **Visibility beyond a fixed window** (the owner's decision): copies older than the 32k-token reuse window are sent
  again though still on the surface, about every 4–5 turns (about 2k characters a turn locally); count visibility from
  the last compaction checkpoint instead, or keep the window.
Independent fixes found by the same survey (lines piling up in idle groups, task results carrying their report
twice, group continuity and memories repeating lines still visible, a per-minute clock in the places block, the
document refs resent each turn) are made outside this ADR.

**Phase 1, pilot (one week, shadow):** index her items (persona sections, `current_self` items as split today,
journal rows, group notes) into the memory index with a `shadow` flag that retrieval records but does not deliver.
Measure per item: would-be surfacings per day by turn kind, the floor that keeps crowding at or under one own item
per turn on average and none in heartbeats, near-duplicate pairs found, and `recall` hits by heading. Decide the
floor and the two reserved slots from this; the ADR is amended with the numbers.

**Phase 2, the cycle on `self`, persona, ledgers and group notes:** places, stays, caps, lapse and overflow,
`keep`, the `things_from_program` block, delivery of own items, the night list replacing the notes review,
graduation into `core`. Her one-time rewrite of `current_self` into items (hers; the old body stays as history) and
her first `keep` choices on persona sections (today's `always` sections start 随身 with a fresh stay; nothing lapses
on day one). `update_self` aliased.

**Phase 3, after two weeks of readings:** understanding layers as items; the idea age word; sticker last-used words;
retire the alias; her own weekly reading in self evaluation (ADR-058): moves, saves, gists written, items brought
back, in words from records.

**Measure before, during, after** (a script run daily, counts only):
- store sizes per tier and per store; 随身 characters per turn by conversation kind (goal: `self` ≤ 2,400, persona
  always unchanged or lower, total home notice down by at least the `self` saving);
- refusals for length on her stores (goal: zero after phase 2; today 17 budget refusals on the persona document,
  and `SELF_STATE_TOO_LARGE` on `current_self`);
- moves per day by reason; how many lapsed items she brought back within a week (the "regret rate"; a high rate means
  stays are too short); gists written vs skipped twice;
- recall hit rate of 手边 and 收着 items: of the items that moved down, how many were surfaced or recalled again within
  30 days (the pilot predicts about 1% of turns each; a demoted item never seen again in 60 days despite its topic
  coming up is the failure to watch);
- her own readings: once a week, her words on what she missed and what she was glad to lose (not graded).

**Rollback criteria**, each mechanism behind its own switch in the tables: refusals for a missing `keep` or a wrong
`sid` rising after phase 2 (ADR-056's rule); the regret rate above a third; her readings saying she lost track of
things she needs; the home notice not shrinking. Rolling back keeps every item and every revision; only the
automatic moves stop and `inject` reads as before.

## 8. Alternatives considered

| Alternative | Trade-off | Verdict |
|---|---|---|
| **The owner's: a searchable store for the less important, pointers kept in her reflection, tiers by time** | The searchable store is right and is adopted (her items join the one index). Per-item pointers regrow in the very place they were meant to relieve and rot when the item changes; the pilot shows retrieval finds an item when a turn is about it, so a stable map of places (`things_from_program`) replaces pointers. Tiers by time punish a rule she applies daily but wrote long ago; tiers by use and confirmation do not | adopted in part |
| **Claude's earlier proposal** (items, count caps, auto-demotion by last confirmation, searchable tier 1, cold tier 2, confirm/pin/bring back) | Right direction; it lacked the gist step (detail never faded, it only moved), two strengths (use was not separate from confirmation), spacing (every confirmation cost the same), a path into `character_core`, and the journal | extended into this ADR |
| **Explicit paging only** (MemGPT-style: she pages things in and out herself, the program only warns) | She does not page: 48 recalls in four days, 0 reads of her work log, 2 of 29 tucked sections. A system that depends on her remembering to look is the system we measured | rejected as the sole mechanism; `recall` stays as the deliberate path |
| **LLM-rated importance per item** (Generative Agents) | A score per write or per turn costs a model call and would reach her as a number or shape her writing toward "important"; AGENTS.md forbids raw scores, and importance self-rated by a model is the least stable signal in the literature | rejected; use and confirmation are observed, not rated |
| **Program-written summaries of her text** (consolidation by the program) | Her rule (ADR-043): a reason comes back in her words; a summary is always more presentable than what she thought. The program may list, move and link; only she rewrites | rejected |
| **Deletion or expiry** | ADR-009: no delete; the owner wants fresh learning, not policing. Cold is enough: out of default view, in the record | rejected |
| **A bigger tier 0** (raise the caps, widen the budget) | Every character in tier 0 is read in every turn of every conversation; the window is not the limit, attention and the cache are. Cowan's four chunks is a reminder that a person carries little and finds the rest | rejected |
| **Time-boxed tiers** (anything older than N days goes down) | Age is the wrong clock: it demotes the rule she uses daily and keeps yesterday's detail | rejected; age words are shown, age decides nothing |

## 9. Open questions

**For her** (the design touches her texts and habits; it waits for her agreement):
1. The three place words and the age and use words.
2. The caps (12 / 16 / 10 / 6) and the first stay (14 days) and its doubling; whether group notes should move slower.
3. The gist step: 160 characters; two nights before the detail goes 收着 without a gist; whether a lapsed item should
   be listed at all if it is short.
4. `current_self` as a document of items she writes with `write_document` instead of one body with `update_self`:
   does it fit how she writes herself? Would she rather keep one body and have the program split it by lines?
5. Graduation: three unchanged stays before the offer; `character_core` at 12 sentences; her own first sentences.
6. Whether a surfaced item should ever come back to 随身 by itself (the proposal says no: only by her rewrite or 带着).
7. Whether her thoughts should enter the gist step (her ADR-043 rule 3 says no fast lane; the proposal leaves them).
8. What the weekly reading in self evaluation should show of her memory.

**For the owner:**
1. Phase 0: who sets the kind of her two existing ledgers (journal rows: decided and built).
2. The reserved slots (two of six) and the absolute floor: set from the pilot, or fixed now.
3. `promote_memory`'s quota (2 a night) stays; the promoted memories join the tiers at 手边.
4. Retiring `update_self` (one less tool) against keeping her habit.
5. Whether the pilot's shadow index may run on the live profile (it writes index rows, no delivery) or should wait for
   a copy of her database.

## 10. References

Cognitive science: Atkinson & Shiffrin 1968 (Psychol. Learn. Motiv.); Baddeley 2000 (TICS); Cowan 2001 (BBS);
McClelland, McNaughton & O'Reilly 1995 (Psychol. Rev.); Kumaran, Hassabis & McClelland 2016 (TICS); Tse et al. 2007
(Science); Diekelmann & Born 2010 (Nat. Rev. Neurosci.); Wilhelm et al. 2011 (J. Neurosci.); Murre & Dros 2015 (PLOS
ONE); Cepeda et al. 2008 (Psychol. Sci.); Anderson & Schooler 1991 (Psychol. Sci.); Anderson & Lebiere 1998; Bjork &
Bjork 1992; Roediger & Karpicke 2006 (Psychol. Sci.); Anderson, Bjork & Bjork 1994 (JEP:LMC); Nader, Schafe & LeDoux
2000 (Nature); Sevenster, Beckers & Kindt 2013 (Science); Lee 2009 (TINS); Brainerd & Reyna 2002 (Curr. Dir.);
Richards & Frankland 2017 (Neuron); Bartlett 1932; Ghosh & Gilboa 2014 (Neuropsychologia); Craik & Lockhart 1972;
Rogers, Kuiper & Kirker 1977; Conway & Pleydell-Pearce 2000 (Psychol. Rev.).

Agent memory: Packer et al. 2023, MemGPT, arXiv 2310.08560; Park et al. 2023, Generative Agents, arXiv 2304.03442;
Zhong et al. 2023, MemoryBank, arXiv 2305.10250; Xu et al. 2025, A-MEM, arXiv 2502.12110; Chhikara et al. 2025, Mem0,
arXiv 2504.19413; Rasmussen et al. 2025, Zep, arXiv 2501.13956; Gutiérrez et al. 2024/2025, HippoRAG, arXiv
2405.14831 and 2502.14802; LangChain 2025, LangMem conceptual guide; Shinn et al. 2023, Reflexion, arXiv 2303.11366;
Wang et al. 2023, Voyager, arXiv 2305.16291; Kang et al. 2025, MemoryOS, arXiv 2506.06326; H-MEM 2025, arXiv
2507.22925; Hu et al. 2024, HiAgent, arXiv 2408.09559; Lin et al. 2025, Sleep-time Compute, arXiv 2504.13171;
LightMem 2025, arXiv 2510.18866; Tan et al. 2025, RMM, arXiv 2503.08026; Sarthi et al. 2024, RAPTOR, arXiv
2401.18059; Rezazadeh et al. 2024, MemTree, arXiv 2410.14052; Wang et al. 2023, recursive summarisation, arXiv
2308.15022; Maharana et al. 2024, LOCOMO, arXiv 2402.17753; Wu et al. 2025, LongMemEval, arXiv 2410.10813; Tan et
al. 2025, MemBench, arXiv 2506.21605; OpenAI Memory FAQ; Anthropic, Memory (2025).

Project: ADR-009 (ledger, no delete, forgetting formula), ADR-014 (limits, nightly tidy), ADR-017 (home/public),
ADR-025 (two layers), ADR-028 (carried summary), ADR-032 (places), ADR-038 (fixed tool lists), ADR-042 (what the night
changed), ADR-043 (reasons in her words), ADR-049 (quiet-time condensing), ADR-056 (per-turn characters), ADR-058
(heartbeat dice), ADR-060 (plain names), ADR-061 (asking for help).
