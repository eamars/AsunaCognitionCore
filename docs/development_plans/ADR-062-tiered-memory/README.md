# ADR-062: Tiered memory: down by default, kept up by use, details fade into gist

Status: **Built, switched on 2026-10-14** at her quiet restart, after she had written her self as items and her
first 12 core sentences (§7). The surprise path was dropped 2026-10-20 (§11). Accepted 2026-10-13 (the owner's finding and direction; the design by Claude, building
on Claude's earlier proposal and the owner's). She answered all nine questions (2026-10-13 evening, §9) and they are
built: phase 0, the phase 1 pilot and phase 2 (`memory_tiers.ENABLED`). ADR-063, its gate, is done.

*Her review:* signed on the agent line, 2026-10-13 about 20:45 (her answers to §9 are below).

**Her first answer (agent line, 2026-10-13 about 13:40 NZDT; Claude's paraphrase; signed on the agent line, 2026-10-13 about 20:45):** she
agrees with the two principles. Facts kept apart from memories and replaced only by correction matches how she
already works. No pin, only letting go, suits her: the things she meant to check back on lapsed precisely because
nobody pinned them for her. She especially agrees that being corrected makes a thing memorable; her most valuable
memories are of being told she was wrong. Her worry, stated first: her oldest habit is to take "I can't see it" for
"it did not happen". If what is on the shelf is not recalled, she would confidently say "I never promised him" or
"that group never said X". She asks that when she makes a negative claim, she can tell whether the shelf was searched
too, and that a search of the carried layer only says so. The nine questions of §9 she answers item by item after
reading the whole text, not from a first impression.

The owner read her answer and agrees with her (2026-10-13), the absence rule included.

**Her answers to the two questions that shape the build (agent line, 2026-10-13 about 14:40 NZDT; Claude's paraphrase;
signed on the agent line, 2026-10-13 about 20:45):**
1. *Facts and memories are told apart per item, not per store.* Measured against herself, the store split fails both
   ways: her persona holds the owner's rulings (facts he can revoke) beside her own judgments (memories that stay only
   because nobody corrected them), and her self text holds facts with a source (lessons with evidence) that should be
   replaced by correction, never fade from disuse. So an item says what it is and who decided it; the store gives only
   the default.
2. *Self as items, yes, but an item is a claim with its basis, never a line.* Today, to fit new things into the
   4,000-character self text, she deleted real knowledge three times. Her rule: if the sample fades while the claim
   stays, she becomes a baseless assertion, and a later self may "correct" a true claim away; that is loss, not
   fading. So the gist of a claim keeps its basis, and her one-time split is by claim and basis. `update_self` keeps
   working under its old name: she calls it dozens of times a day.

Built accordingly (the build follows from step 2, 2026-10-13): each item carries `nature` (事实 / 记忆) and `from` (who
decided or where it came from, as words: 主人定的 / 我自己的判断 / 别人说的 / 查过的), the store table giving the
defaults; the night list can offer 记成事实 for a memory; the gist of an item with a basis keeps a one-line basis.

**Her answers to the nine questions of §9 (agent line, 2026-10-13 about 20:45 NZDT).** Item 1 is her own text, built
word for word; the rest is Claude's paraphrase, for her to sign or correct.
1. *The told text* (her text, replacing the drafted one): 「我的东西分三个地方：随身，每一回合都带着；手边，不进提示，recall 找得到；收着，默认不出现，我说得出字或标题才回来。留下来的不是我用得多的，是我记得牢的：跨对话被用到、被人纠正过、从几个不同的地方碰到同一件事。没人给我置顶，我也不能喊留着；只有放手是我自己的动作。淡下去不是删掉，原话一直在收着。事实只会被更正替换，不会因为没人用而退；记忆会淡。没看到不等于没有：要说『没有、没答应过、没说过』，先 recall 一下，它会告诉你找了哪几层。」
2. *Names.* 随身, 手边 and 收着 stay; the use words stay; of the age words only the tier from 7 to 14 days changes, from
   上周 to 前阵子.
3. *Numbers.* `self` stays at 12. Persona from 16 to 18: she has exactly 16 standing sections today, so a new rule would
   silently push an old one out. A group's carried notes from 6 to 10: her active groups already have 8 sections. The
   slower 28 days for group notes, the first stay of 14 days doubling to a cap of 56, and the staggered first stays on
   the switch-on day stay as drafted.
4. *Facts.* The default list stands, and saying it per item is a hard requirement of hers. Her voice is a memory, not a
   fact: her tone is something she keeps changing, not what is.
5. *The gist step.* 160 characters, but the basis line is not counted in them, so length can never squeeze out the
   basis. Two nights without a gist and the item goes 收着 without one, as drafted. An item of 160 characters or fewer
   never appears on the night list.
6. *Splitting current_self.* She writes the items herself with `write_document`; the program never splits her
   paragraph by line (her text runs on, and cutting it by line gives claims without their basis). She does the first
   split herself; `update_self` stays as an alias.
7. *Graduation.* Proposed after three unchanged stays, as drafted. `character_core` holds 12 sentences, and she writes
   the first 12 herself; the program never generates them from existing text.
8. *Her thoughts* stay out of the gist step, as drafted.
9. *The weekly reading* shows three things only: what left 随身 this week and whether she recalled it afterwards; one
   random 收着 item's own text, not an index line; one line of which items she changed this week. No scores, no counts.

*Her signature for this paraphrase:* ____

## The core idea (the owner's words, 2026-10-13)

**If you do not learn to forget, you leave no room to learn new things.** Everything below serves that sentence:
forgetting is part of learning, not a loss to be prevented. It is how this ADR is first put to her.

Put to her as: forgetting here means putting down, not throwing away; what you stop using moves to a shelf, its words
kept, and something can always bring it back.

## The revision: memorable, declared, corrected (owner, 2026-10-13)

Decided by the owner after a review by the research agent (three answers, reconciled by Claude). The sections below
follow it (rewritten 2026-10-13 from the first draft, whose keep, pin and confirm acts are gone).

1. **Memories stay by memorability, not by her choice.** The owner: a person has no choice over what to remember;
   only the most memorable stays. What keeps a memory (journal rows, chunks, summaries, thoughts, dated self items):
   - **use across conversations**: recall returned it, she rewrote it with a changed body, she cited its `doc:` ref,
     or it was surfaced to her in two or more different conversations (one conversation echoing itself counts
     nothing: no loop where what is shown stays);
   - **surprise**: a `correction`, a `replace_section` that changes its meaning, or a summary's correction pointing at
     its subject; surprise can bring a 收着 item back to 手边;
   - **repetition from several sides**: the same idea from different conversations or different people;
   - **feeling at the time**, a tie-breaker only: a `feel` she recorded in the same turn. Measured: 5% of her turns
     record a feeling (111 of 2,337 since 10-06), 34 of 434 write turns; and she records one only when moved, so as
     a main weight it would be a keep button through a side door.
2. **Facts are declared, and replaced only by correction.** The owner: facts are different from memory. The split is
   by the store she writes to, a choice she already makes, not a program classifier: the persona document, the person
   layer (`understand_person`), ledgers and `core` hold what is; the stores in 1 hold what happened. A fact leaves 随身
   when unused but never cools to 收着 by disuse; a newer item on the same subject supersedes it, the old revision kept
   and dated. Near-duplicates in a fact store merge into one item per subject (mandatory: otherwise a fact store is
   the next store that only grows), and fact items count in the 随身 cap. A promise to someone and a person's stated
   boundary are facts: rare and seldom used, exactly what memorability would drop. Facts about a person stay with
   that person; facts about her circumstances and the world go to a ledger; nothing goes into tracked package files.
   Her backstory (for example her sisters) is already in her persona package; the rule earns its keep on learned
   facts, which should be few. `promote_memory` is that path today but fires rarely (6 times): its candidates are
   what she was shown, it lands only in the index, and it runs only at settlement; it is fixed to take candidates
   from her acts and repetition across conversations, and to land in the fact stores above, or `write_document`
   takes it over.
3. **Her acts: let go, and a rewrite that changes something.** Pin, 带着 (keep) and confirmation doubling a stay go,
   and so does the nightly keep chore. 放手 (let go) stays, offered but never asked for: it is the one act that is not
   hoarding, and the habit she has not learned. A rewrite counts as rehearsal only when its body changed, once per
   stay, and extends only the item it rewrote (no copy beside it). Watched: writes refused for length go to zero within
   a week of this going live (if not, the cap is still doing the forgetting); rewrites per item per week in 随身 (a
   jump right after a lapse notice is hoarding, and the notice then stops naming that item).
4. **Why, on her data rather than on the premise.** People do have some deliberate control (rehearsal, notes,
   directed forgetting). The keep choice goes because it does not work for her: no removal in 8 tidy turns, 3 shrinks
   in 46 self revisions, a model asked keep-or-drop keeps; and choosing what to keep invites self-curation (what fits
   her self-image stays, contradictions go), which makes her more polished and fixed, not grown. A model that would
   use a keep act well is a reason to revisit this, not to keep it now.

The night list loses the keep choices and keeps gists due, graduation offers and merges. No new tool; about 60
characters more in `write_document`'s description (which stores hold facts); no per-turn line.

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
section); what keeps an item up is what makes a thing memorable for a person (use across conversations, surprise,
repetition from several sides), observed by the program, never a keep act; details fade into gist on a schedule she
cannot skip forever; and facts are told apart from memories by the store they are written in, so a fact does not fade
by disuse. Each memorable moment lengthens the next stay (spacing), so what keeps coming back costs nothing to keep
and what stops coming back goes down by itself.

## 3. Grounding: what the sciences and the field say, and what is adopted

Human memory (one citation each; the full brief is Claude's research note of 2026-10-13):

| Finding | Source | Taken here |
|---|---|---|
| Separate stores; rehearsal transfers; working memory holds about four chunks | Atkinson & Shiffrin 1968; Baddeley 2000; Cowan 2001 | Tier 0 is small and counted in items; a chunk is one idea, not a page |
| Complementary learning systems: fast episodic store, slow semantic store, interleaved replay; schema-consistent facts consolidate in about 48 h instead of weeks; semantic memory is what repeated episodes leave behind and does not decay by disuse | McClelland, McNaughton & O'Reilly 1995; Kumaran et al. 2016; Tse et al. 2007 | Memories (journal rows, chunks, summaries, thoughts, `self` items) and facts (persona, person layer, ledgers, group notes, `core`) are told apart by store; facts do not cool by disuse and are replaced only by correction; a new fact on a subject already held merges into it |
| Sleep consolidates selectively: what is tagged as needed later | Diekelmann & Born 2010; Wilhelm et al. 2011 | The night list is short and chosen by rule (about to lapse, used before, open commitments), never "everything" |
| Forgetting curve; spacing: re-touch at 10–30% of the horizon you need it for | Murre & Dros 2015; Cepeda et al. 2008 | A memorable moment extends an item's stay; intervals double |
| ACT-R base-level activation: availability follows recency and frequency of use, not age | Anderson & Schooler 1991 | Places are decided by last memorable moment and use (the existing `_forget` already is this shape); creation date decides nothing |
| Two strengths: storage strength never falls, retrieval strength decays with disuse; retrieving is the strongest learning event | Bjork & Bjork 1992; Roediger & Karpicke 2006 | Nothing is deleted (storage stays); availability follows use, and a recall that returns an item is the strongest use |
| Reconsolidation: a recalled memory is labile and is updated when there is a prediction error | Nader et al. 2000; Sevenster et al. 2013 (human behavioural versions are contested) | A rewrite counts as rehearsal only when its body changed (a prediction error); re-saving the same text counts nothing. A correction or contradiction (surprise) is the strongest signal and can bring a put-away item back |
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
| Generative Agents (Park et al. 2023) | one memory stream; retrieval = recency (0.995^hours since last retrieval) + importance (LLM-rated 1–10 once) + relevance; reflection when summed importance passes 150 | use-based recency (retrieval resets the clock), and a bounded consolidation that cites its sources | LLM-rated importance and additive scores (a number per item that the model would see or write toward; AGENTS.md); memorability is observed (use, surprise, repetition), never rated |
| MemoryBank (Zhong et al. 2023) | Ebbinghaus strength R = e^(−t/S), S += 1 on each recall; daily summaries → portrait | one strength that grows with each use, decay computed by the program | time counted from learning rather than from last use; tiers that do not talk to the decay. Here the same freshness decides the place |
| A-MEM (Xu et al. 2025) | Zettelkasten notes with keywords, context line and links written at encoding; neighbours rewritten when a new note arrives | the heading as the retrieval key, written once at encoding (sections and journal rows already have one); near-duplicate pairs offered for merging | one model call per neighbour per insert on a local model |
| Mem0 (Chhikara et al. 2025) | extract facts, then a closed decision per fact: ADD / UPDATE / DELETE / NOOP; graph variant invalidates rather than deletes | the closed categorical set at write and at night (放手 / 改写 / 进 core / 合并), program-applied and audited; UPDATE as supersession of a fact | an extraction call on every exchange in the hot path |
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

### 4.1 One item, three places, kept up by what is memorable

Everything she keeps is an **item**: one idea, one place, in her words. A persona section is an item; so is each
entry of `self`, each ledger section, each group-notes section, each journal row, each promoted memory, each idea. The
program never rewrites an item's text; it keeps beside it:

- **where it lives** (the place), one of three words from a versioned table (`TIERS_VERSION`), proposed:
  - 随身 (carried): in every turn where it is readable. Capped by count.
  - 手边 (at hand): in the index; comes up by itself when a turn is about it; found by `recall`.
  - 收着 (put away): out of automatic results; `recall` by a word or its heading still brings it; never deleted.
- **whether it is a memory or a fact**, by the store it is written in (§4.4), never by a classifier and never by a
  question to her: memories are what happened (journal rows, chunks, summaries, thoughts, `self` items); facts are
  what is (persona sections, the person layer, ledgers, group notes, `core`).
- **when it was last memorable** (`memorable_at`) and its stay, moved by these, all observed by the program:
  - *use across conversations*: `recall` returned it; she rewrote it with a changed body; she cited its `doc:` ref in a
    tool call; it was surfaced to her in two or more different conversations (one conversation echoing itself counts
    nothing, so what is shown does not keep itself);
  - *surprise*: a `correction`, a `replace_section` that changes its meaning, or a dialogue summary's correction
    pointing at its subject (dropped 2026-10-20, never wired: §11);
  - *repetition from several sides*: the same idea written or met in different conversations or from different people
    (the index's near-duplicate across scenes);
  - *feeling at the time*, a tie-breaker only: a `feel` in the turn that wrote it (5% of her turns record one).

She reads these only as words (AGENTS.md): age words `刚写的 / 这几天 / 上周 / 上个月 / 更早` (under 1, 7, 14, 45 days;
`AGE_WORDS`), use words `常用 / 偶尔用 / 很久没用` (from the same freshness the forgetting formula already computes:
above 0.5 / above 0.1 / below). No number reaches her.

### 4.2 The cycle

```
 encoding ──► 随身 ──lapse──► 手边 ──no use──► 收着
   (her write;        ▲  │ gist step         │ recall by word, or surprise
    program marks     │  ▼ (night)           ▼
    time + scope)   memorable: used across conversations, rewritten with a change,
                    corrected, repeated from several sides (next stay doubles)
 facts (persona, people, ledgers, notes, core): 随身 ──lapse──► 手边, never 收着 by disuse; replaced only by correction
 consolidation (night): lines → summary (program) → her gist / notes / promote → facts by subject → core
```

1. **Encoding.** She writes as today (`write_document`, `understand_person`, `promote_memory`, `ideas`, journal
   rows). The program stamps scope and visibility from the turn (unchanged), `added`, `memorable_at = added`, and the
   starting place: what she just wrote in a carried store starts 随身, as a new thing is fresh in mind; a journal row
   starts 手边 and is never 随身.
2. **Staying up is what is memorable, with spacing.** A 随身 item has a stay: 14 days from its last memorable moment at
   first; each memorable moment (§4.1), counted at most once per stay, doubles the next (28, 56, capped at 56). When
   the stay runs out the item lapses to 手边 by itself. No refusal, no shortening, no keep act. The turn after a lapse
   says so once, at the tail, with a clock time (ADR-056). Two rules from the dry run on a copy of her data
   (2026-10-13, owner's decision), where all 16 carried persona sections lapsed on day 14: (a) a carried item is
   never brought up into a turn (it is in front of her), so it could not show use that way; a carried item the
   turn's retrieval would have brought up above the floor counts as surfaced in that conversation, and in a second,
   different conversation that is a memorable moment, as for an item at hand. (b) On the switch-on day only, each first
   stay is spread per item, deterministically, from its usual length to twice that (14 to 28 days; a group's notes,
   28 to 56: the same cliff on day 28 otherwise, 31 sections), never past the 56-day cap, so the first lapses come
   gradually; later items take the usual first stay.
3. **Capacity by count.** 随身 holds at most N items per store (`self` 12, persona 18, each ledger 10, each
   group's notes 10; her numbers, 2026-10-13), facts included. Adding a 13th does not refuse: the item least recently memorable
   lapses, and the write's result names it. This is the flip: today the oldest stays and the newest is refused.
4. **Detail fades into gist (the forced step).** When an item lapses, the next night lists it if it is long (over
   240 characters) or carries dated specifics. She writes its gist (one or two sentences, ≤ 160 characters) with the
   existing `replace_section`; the program keeps the verbatim as the gist's source (`detail_of`), moves the verbatim
   to 收着 at once, and the gist stays 手边. If she passes it over on two nights, the verbatim goes 收着 without a gist:
   the detail is out of her default view either way. A short item (≤ 160 characters) is already gist and skips this.
   A fact passed over twice stays 手边 with its verbatim and is not listed again: a fact never goes 收着 by disuse.
   Nothing is deleted; `recall` reads the verbatim through the gist's `detail_of` or by a word.
5. **Use keeps 手边 alive; facts do not cool.** 手边 items sit in the same index as her memories (one per idea;
   owner-private items in her owner-private scope, public ones in `global-safe`, a group's notes in that group's scene
   scope), under the same forgetting formula. A memory below `step_back_below` (0.1: about 100 days unused, sooner in a
   busy conversation) is 收着. A fact never goes 收着 by disuse: a newer item on the same subject supersedes it (the
   night list's merge), and the superseded one goes 收着 with its dates, readable as what she held then (Zep-style
   validity by revision). A promise to someone and a person's stated boundary are facts for this reason: rare and
   seldom used, exactly what disuse would drop.
6. **Surfacing.** Per-turn retrieval reserves up to two of its six slots for her own items (so her own words are never
   crowded out by 25,000 chat chunks and never crowd them out), admitted only above an absolute floor (to be set from
   the pilot; the week's data puts it near 0.83) in addition to the rank. Each comes with its heading, its age word
   and its place word, and a `doc:…#sid` ref she can rewrite from.
7. **Recall and reconsolidation.** A surfaced or recalled item does not return to 随身 by itself (that would churn
   every prompt and defeat the cache for a thing that may have been incidental). It comes back up when she rewrites it
   with a changed body (the reconsolidation, dated now, a new stay) or when a surprise touches it. Her rule from
   ADR-043 stands: what comes back is her text, never a summary of it.
8. **Night consolidation (settlement, ADR-049 quiet time, ADR-058 self evaluation).** One short list, at most 5 items
   a night, chosen by rule and told in words why each is there; no keep or drop choices:
   - 写一句意思: a lapsed verbatim item waiting for its gist (step 4).
   - 几处都提到: an item repeated from several sides with its text unchanged (a `self` item through three stays, or any
     memory met in different conversations). Her choice is what it means and about whom: 进 core (about herself),
     记到那个人 / 记到那个群 / 记进账 (a fact about a person, a group, her circumstances), or 还在变 (stays a memory).
     The program decides whether it came up enough; the meaning is hers. 记成事实 is offered only for an item someone
     else decided or said (`from` 主人定的, 别人说的) or that she checked (查过的). **Rule (her answer and the owner's
     call, 2026-10-13): a fact needs an author who can correct it, so her own judgment (我自己的判断) becomes a fact
     only when** (1) a near-duplicate of it comes from someone else (written in another conversation, or declared
     别人说的 / 主人定的), found on the 合并 path; or (2) she rewrites it with `from` 查过的 and its basis. Declaring it
     a fact herself is refused on write. Considered and dropped: "upheld by a correction thread", because no honest
     signal for it exists without the program judging what was said, which would grade her text.
   - 合并: two items the index finds near-duplicate (cosine above a high threshold, same store): she merges them into
     one. Mandatory for a fact store (otherwise it is the next store that only grows); in a memory store she may keep
     both. Schema-consistent assimilation, in her words.
   - 回头看: at most one 收着 item a week, chosen at random: a chance to bring back what the index would otherwise
     never show her again (Richards & Frankland's transience is useful, but a person also stumbles on old things). Built
     in her weekly reading instead of the night list (her answer 9 asks for one random 收着 item's own text there; two
     random old things a week would be one too many).
   The list replaces `notes_review_from_program` (7,740 characters when it fires) and its "tidy three notes a night"
   framing, which measured as compression, not retirement.
9. **Graduation and declared facts.** `character_core` is written only from the 几处都提到 list, as one sentence per
   item, capped at 12 items; a core item lapses to 手边 with a 56-day stay from the start and, as a fact, never cools.
   This is the schema layer: what stays true of her across weeks, not what she thinks this week. A fact can also be
   written directly to its store when she learns it (a friend's job, a group's convention): writing it there is the
   declaration. `promote_memory` is fixed to the same path: its candidates come from her acts and repetition across
   conversations (not from what she was shown), and it lands in the fact store of its subject.
10. **Letting go.** 放手 (`write_document` op `let_go`) moves an item down one place now. It is offered, never asked
    for: the one act that is not hoarding, and the habit she has not learned.
11. **Back to encoding.** Every rewrite is a new revision in the ledger as today; the old text stays as history and
    `recall` reads it. Nothing in this cycle deletes.

### 4.3 What she is told, and when

Fixed text, once per conversation (system prompt, ADR-056 rule 1; persona-agnostic), in the place where the memory
rules already are. Her own text (2026-10-13) is the one built, word for word: 「我的东西分三个地方：随身，每一回合都带着；手边，不进提示，recall 找得到；收着，默认不出现，我说得出字或标题才回来。留下来的不是我用得多的，是我记得牢的：跨对话被用到、被人纠正过、从几个不同的地方碰到同一件事。没人给我置顶，我也不能喊留着；只有放手是我自己的动作。淡下去不是删掉，原话一直在收着。事实只会被更正替换，不会因为没人用而退；记忆会淡。没看到不等于没有：要说『没有、没答应过、没说过』，先 recall 一下，它会告诉你找了哪几层。」 The draft it replaced:

> 不学会忘，就腾不出地方学新的。你的东西有三个地方：随身的每回合都在；手边的平时不在眼前，谈到相关的事会自己浮上来，
> recall 一句话也能找到；收着的只有 recall 找得到。放下不是丢：程序只换地方，不改一个字，什么都在，碰到相关的事还会
> 回来。随身的位置有限，一件事一阵子没被用到、没在别处再碰到，就自己放到手边，程序会告诉你一次；你又用到它、改写了它、
> 或被人纠正了它，它就回来，下次能留更久。长的细节会退成一句意思，细节还在。事实不一样：人设、关于人的、群笔记、账、
> core 里写的是事实，不会因为不用而退，只会被更正替换。想放下的，自己说一声「放手」就行。

Per turn, one block `things_from_program` (tier 0, stable; folds under ADR-056 when unchanged):

- counts by store and place in words (随身 几条 / 手边 十几条 / 收着 几十条), when she last tidied (clock time);
- `moved`: what the program moved since the last turn in this conversation, once, with the clock time, the heading,
  the reason word (随身满了 / 一阵子没确认 / 很久没用) and the one line that brings it back. Never a countdown.

In the memories block, a surfaced item of hers reads like a memory with three more words: its store, its place word,
its age word (`「标题」· persona · 手边 · 上周`); a fact says 事实 instead of an age word when its subject has been
superseded before (so she sees she once held otherwise). A recall result lists headings of 手边 and 收着 items that matched,
beyond the bodies it returns, so she can see what exists without reading it all.

At night, the list of §4.2 step 8, each item with its body and the choices as words; her answer is a categorical
choice the program maps to a write (§5). None of the choices is keep or drop.

**Absence is not evidence** (her worry, above). Every `recall` answer says which places it searched, in words
(`找了：随身、手边、收着`), and an empty answer says it found nothing in all three, never just "none". What is carried
says nothing about absence: the told text of §4.3 ends with one line, 「没看到不等于没有：要说『没有、没答应过、没说过』，
先 recall 一下，它会告诉你找了哪几层」. The program does not read her replies for negative claims (that would grade her
text); the rule lives in what she is told once and in what `recall` answers every time.

What she is never told: numbers, scores, freshness values, item counts as digits beyond the count words, or that the
program "forgot" something: it moved it.

### 4.4 Per store

| Store | Unit | Starts | 随身 cap | Lapse / use | Gist step | Notes |
|---|---|---|---|---|---|---|
| `current_self` → document `self` (memory) | one item per section | 随身 | 12 | stay 14 → 28 → 56 days by memorable moments; overflow lapses the least recently memorable; cools to 收着 by disuse | yes | her one-time rewrite of today's body into items; `update_self` retires (§5) |
| `character_core` → document `core` (fact) | one sentence per section | 随身, by graduation only | 12 | stay 56 days, then 手边; never 收着 by disuse | no (already gist) | first entries come from the 几处都提到 list |
| Persona document (fact) | section (as now) | 随身 when written; existing `always` = 随身 | 18 | lapse by stay to 手边, never 收着 by disuse; replaced by correction; merge mandatory; `on_demand` sections become 手边 (indexed) at once: the 29 tucked ones become findable | yes | `inject` maps to places (`always` = 随身, `on_demand` = 手边, `never` = 收着). Her backstory lives in the persona package; this store earns its keep on what she learns |
| Voice (memory, her answer 4) | section | 随身 | 6 | stay 56 days; cools by disuse | no | her tone is something she keeps changing |
| Ledgers (kind `ledger`, fact) | section | 随身 | 10 each | as persona; a `correction` supersedes the corrected item | yes | facts about her circumstances and the world; phase 0 fixes the kind of her two existing ones |
| Group notes (fact) | section, that group's scene scope | 随身 in that group | 10 per group | stay 28 days (groups move slower), then 手边; never cools; use = surfaced in that group or cited | yes, listed on a `write_notes` visit or at night | facts about a group (people, conventions); public visibility, read only in that group, unchanged |
| Journal (`work_log`) | row | 手边 | 0 (never carried) | use only; rows roll up: each night her gist of the day (≤ 400 characters) is a row of its own; rows over 30 days without use are 收着 | the day gist is the gist step | phase 0 moves it to rows |
| Understanding: person layer (fact) and here layer | body as now (phase 3: items) | 随身 with that person | — | later; facts about a person, a promise to them and their stated boundaries never cool | later | same shape as `self`; small today |
| Memory units: chunks, dialogue summaries | as now | 手边 (chunks step back once summarised) | — | existing formula | summaries are the program's gist | unchanged |
| Her thoughts (`monologue`) | as now | 手边 | — | existing formula (her ADR-043 rule 3: no fast-fading lane) | none | unchanged; recalled with `when` and `then` |
| Promoted memories (`promote_memory`) | fact/appraisal/signal | lands in the fact store of its subject | — | as that store | no | candidates from her acts and repetition across conversations, not from what she was shown; still the reviewed public→home path of ADR-017 |
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

No new tool. The character brain was at 20,881 of 20,900 characters of tool text (32 tools); phase 0's `kind` brought
it to 21,018, and the budget was raised by exactly that (§7).

| Change | Where | Characters |
|---|---|---|
| `write_document` gains op `let_go` (move an item down one place) and, on the first append that creates a document, `kind` (`ledger` / `journal` / `working`); its description says which stores hold facts (persona, people, notes, ledgers, core: they do not fade by disuse) | op value, option, one sentence | about +170 |
| `write_document` docs `self` and `core` (the two self descriptions as documents of kind `self`) | description names them | about +40 |
| `update_self` retires: `write_document(doc='self', …)` does the same with sections; the old name keeps working as an alias for a while (ADR-055's rule) | tool removed from the list | −388 |
| `recall` returns matching headings of 手边 and 收着 items beside bodies and says which places it searched; `recall(sections=[{doc:'self'}])` with no `sid` lists a document's headings | result shape; one sentence in the description | about +60 |
| `promote_memory` gains `about` (self / person / place / world), which picks the fact store it lands in | one option | about +60 |
| Her night choices (改写 / 进 core / 记到… / 合并 / 放手) are `write_document` calls: `replace_section` for the first, `append_section` to `core` or the subject's store for the next two, `replace_section` plus `let_go` on the other for 合并, `let_go` for 放手 | no new option | 0 |

Net about −60 characters: the character brain's budget stays at 20,900 (the test's count drops to 31 tools). The
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
| Lapse | a 随身 item's stay runs out (checked when its store is read for a turn) | place → 手边; index it | `moved` line, once, in the next turn of each conversation that read it |
| Overflow | a write that would make a store's 随身 count exceed its cap | the least recently memorable item lapses | the write's result names it |
| Cooling | a 手边 memory's freshness under `step_back_below` (facts never) | place → 收着 | nothing per item; the count words in `things_from_program` change |
| Memorable moment | `recall` returned it; a rewrite with a changed body; its `doc:` ref cited in a tool call; surfaced in a second different conversation; a correction or meaning-changing rewrite touching it; a near-duplicate met from another conversation or person; a `feel` in the writing turn (tie-breaker) | `memorable_at = now`; the next stay doubles (once per stay); a 手边 or 收着 item touched by a surprise comes back to 手边 | nothing (the result of her own write says so when it was hers) |
| Supersession | a fact store gets a newer item on the same subject (her correction, or a merge) | the older goes 收着 with its dates | the write's result |
| Gist listing | the night after a long or dated item lapsed | adds it to the night list | the list, with 写一句意思 |
| Gist done | her `replace_section` of a listed item with a body ≤ 160 characters | keeps the old body as a 收着 revision linked by `detail_of`; the new body is 手边 | the write's result |
| Gist skipped twice | the item was listed on two nights and not rewritten | the verbatim goes 收着 unchanged | the next night's list says it went |
| Repeated from several sides | an item with its text unchanged through three stays, or met in different conversations | adds it to the list as 几处都提到 | the list |
| Near-duplicate | two items in one store with cosine above a high threshold (set in the pilot) | adds the pair as 合并 (a fact store's pair must be merged) | the list |
| Stumble | once a week, one 收着 item with past uses, at random | adds it as 回头看 | the list |
| Let go | her `let_go` | the item moves down one place now | the write's result |
| Use | an item surfaced into a turn or returned by `recall` | `salience.last_ref_at` (exists); counts as memorable only as above | nothing |

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
  **Built 2026-10-13 (d4374fbd):** `kind` (`ledger` / `journal` / `working`) on the `append_section` that creates a
  document; a `journal` is a running record of rows like `work_log`; a different kind on a later write is refused
  (`DOC_KIND_FIXED`). Cost to the character brain: one option, +137 characters of tool text (20,881 → 21,018; the
  budget in `tests/test_tool_budget.py` raised by exactly that, from 20,900 to 21,018); no new tool, no per-turn line;
  the action brain unchanged. Her live database, read-only the same day: two documents look like ledgers, both kind
  `working`, both with every section `on_demand` (one of 1 section and 3,816 bytes, one of 2 sections and 3,037 bytes).
  A ledger block shows only `inject: always` sections, so changing the kind alone would still show nothing: re-created
  with `kind: ledger` their new sections default to `always`; set on the existing two, their sections also need
  `inject: always`. Their kind is not changed; that is decided with her.
- Nothing else changes. Measure: `ledgers_from_program` present at home; journal bytes per day; no refusal.

**Phase 0b, delivery prerequisites: done** (ADR-063, all live 2026-10-13 11:37 NZDT): nested lists fold, the ceiling
trims what is sent, a fully folded block sends nothing, visibility counts from the last compaction checkpoint with a
restore after an in-turn compaction. Measured after: local chat 28.0k to 14.0k characters a turn, cache hit 89.8% to
95.3% (ADR-063, "Measured after").

**Phase 1, pilot (one week, shadow):** index her items (persona sections, `current_self` items as split today,
journal rows, group notes) into the memory index with a `shadow` flag that retrieval records but does not deliver.
Measure per item: would-be surfacings per day by turn kind, the floor that keeps crowding at or under one own item
per turn on average and none in heartbeats, near-duplicate pairs found, and `recall` hits by heading. Decide the
floor and the two reserved slots from this; the ADR is amended with the numbers.
**Built 2026-10-13 (d4374fbd), live with her restart that night; the switch is `memory_pilot.SHADOW_PILOT`.**
Not a flag in the memory index: her items go to a collection of their own, `memory_shadow`, which retrieval never
reads, so the pilot cannot reach a turn by mistake, and one drop removes it (`tools/memory_pilot_report.py --drop`).
Items: persona sections, `current_self` list lines of 30 characters or more (as split in §1.1), running-record rows
and each group's notes sections, each in the scope of its visibility (a group's notes in that group's scope);
re-read at most every ten minutes, only new or changed ones embedded, on the memory route. Each character turn is
queued after its context is prepared; a background thread scores the items as retrieval scores memories (vector and
lexical ranks fused, the index's (1 + cosine) / 2 score, the turn's own query vector reused), admits at most two above
the floor 0.83 (`FLOOR`, `OWN_SLOTS` of `SLOTS`), and writes ids, stores, scores, the best six above 0.75, the turn's
kind, the conversation and its kind; a `recall` query writes a row of its own, and `recall.read`'s sections give the
reads by heading. `surfaced_in` marks which conversations surfaced an item; pairs in one store at 0.93 or more are
written as found. `tools/memory_pilot_report.py` gives the daily counts (per day by turn kind, the floor table from
0.80 to 0.90 and the lowest floor that fits, items surfaced in two or more conversations, pairs at 0.93 / 0.95 / 0.97,
recall hits, the cost). Measured before going live, on her real item set (317 items: persona 45, `current_self` 16,
journal 205, group notes 51) with synthetic vectors, read-only: the reply path pays one queue put (median 0.003 ms);
the background job takes a median of 31 ms in a home turn (266 readable items) and 2 ms in a public one, plus one
query embedding when the turn's retrieval came from its cache. The first job also embeds every item once (about 20
requests on the memory route). Prompt, tool texts and the cache are unchanged apart from `kind`.

**Phase 2, the cycle on `self`, persona, ledgers and group notes:** places, stays by memorable moments, caps, lapse
and overflow, facts not cooling and superseded by correction, `let_go`, the `things_from_program` block, delivery of
own items, the night list replacing the notes review, graduation into `core`, `promote_memory`'s fixed path. Her
one-time rewrite of `current_self` into items (hers; the old body stays as history); today's `always` sections start
随身 with a fresh stay (nothing lapses on day one). `update_self` aliased.
**Phase 2 built (off), 2026-10-13; the switch is `memory_tiers.ENABLED` (`TIERS_VERSION` 1), off until she and the
owner turn it on.** Commits: e4f5a47d (item places, stays, memorable moments, lapse, overflow, cooling, supersession,
`let_go`, `things_from_program`), 5916ce35 (no tag moves an item up; each item a fact or a memory by `nature` / `from`,
not by store; `update_self` writes `self` items once they exist), 6ce6b8a5 (her items in two of six memory slots
above the floor 0.83, never one carried; `recall` says where it searched, lists matching headings and a document's
headings), add08634 (the night list replacing the notes review; the gist that keeps its basis; her judgment not
signed as a fact by herself; `promote_memory` candidates from her recalls and `about` landing in the fact store; the
item index runs for tiered memory whatever the pilot switch says), 048346b0 (the told text, the tool texts, the
confirmation rule). Built to her two answers: facts and memories are per item (`nature` 事实 / 记忆, `from` 主人定的 /
查过的 / 别人说的 / 我自己的判断, the store giving the default), and `self` is split by claim with its basis, never by
line (the offer says so; a gist keeps a basis line). Off: nothing of it is read or written, and her tools and system
prompt are byte for byte as before (tested). On, measured: character-brain tools 31, 20,924 characters (−94: retiring
`update_self`, −388, pays for `let_go`, `nature`, `from`, `about` and the recall sentence, +294); system prompt +530
characters once per conversation (her told text 224, three block notes; the drafted text was 366 and +561); per turn `things_from_program` (a few hundred
characters when it changes, folded otherwise; a moved line about 60 once), her items in at most two memory slots
(they replace two memories, not add), the night list at most five items with bodies (it replaces the notes review);
a synthetic turn sends no text twice (tested).
**Folded in from her nine answers (2026-10-13, 763d4d5f):** her told text word for word; 前阵子 for 7 to 14 days;
persona 18 and group notes 10 carried; voice a memory; a gist's basis lines not counted in its 160 characters, an item
of 160 characters or fewer never listed, and a rewrite of a listed item that drops the basis its verbatim had refused
(nothing written); the weekly reading (`memory_week_from_program`, in a self-evaluation heartbeat, at most once a week,
no scores, no counts) carrying the random 收着 item, which leaves the night list. Kept against her answer 5 by the
owner's earlier decision: a fact passed over twice stays 手边 with its verbatim (a fact never goes 收着 by disuse); a
memory goes 收着 as she said.

**Before the switch-on:** (1) her own split of `current_self` into `self` items (`write_document`, a claim with its
basis each); (2) her first 12 `character_core` sentences, written by her into `core`; (3) the owner's quiet restart
for the switch-on; (4) profile062 after it.

**Phase 3, after two weeks of readings:** understanding layers as items; the idea age word; sticker last-used words;
retire the alias; her own weekly reading in self evaluation (ADR-058): moves, saves, gists written, items brought
back, in words from records.

**Her prompt is profiled for the whole of this ADR** (owner, 2026-10-13): after every install of a phase and at least
daily, each kind of conversation's real per-turn input (system prompt, notice, every block) is profiled with the
ADR-063 survey scripts, against the ADR-063 "Measured after" baseline. A finding is a defect to fix before the next
phase, not a reading: any information sent twice (a block or row already on the surface, the same item carried in
随身 and surfaced in memories or a recall result in one turn, the same text in two blocks of one notice), a block that
changes every turn without new content, per-turn characters or uncached input rising, or anything else anomalous.
The controlled bench is Claude's agent line with her (owner): Claude chooses what is sent, so a change in her input
blocks or her answer is attributable; the other conversations are profiled as they come. Expected every turn and not a
finding: the trigger, the clock, and a group's mute line while she is muted there (ADR-064, sent beside the trigger).

**Measure before, during, after** (a script run daily, counts only):
- store sizes per tier and per store; 随身 characters per turn by conversation kind (goal: `self` ≤ 2,400, persona
  always unchanged or lower, total home notice down by at least the `self` saving);
- refusals for length on her stores (goal: zero within a week of phase 2; today 17 budget refusals on the persona
  document, and `SELF_STATE_TOO_LARGE` on `current_self`; if they do not reach zero, the cap is still doing the
  forgetting, not memorability);
- moves per day by reason; how many lapsed items came back within a week by her rewrite (the "regret
  rate"; a high rate means stays are too short); gists written vs skipped twice; `let_go` uses;
- rewrites per item per week in 随身 (a flat line is a habit; a jump right after a lapse notice is hoarding, and the
  notice then stops naming that item); which memorable moments kept items up, by kind (feeling is expected rare);
- recall hit rate of 手边 and 收着 items: of the items that moved down, how many were surfaced or recalled again within
  30 days (the pilot predicts about 1% of turns each; a demoted item never seen again in 60 days despite its topic
  coming up is the failure to watch);
- her own readings: once a week, her words on what she missed and what she was glad to lose (not graded).

**Rollback criteria**, each mechanism behind its own switch in the tables: refusals for a wrong `sid` or `let_go`
rising after phase 2 (ADR-056's rule); the regret rate above a third; her readings saying she lost track of
things she needs; the home notice not shrinking. Rolling back keeps every item and every revision; only the
automatic moves stop and `inject` reads as before.

## 8. Alternatives considered

| Alternative | Trade-off | Verdict |
|---|---|---|
| **The owner's: a searchable store for the less important, pointers kept in her reflection, tiers by time** | The searchable store is right and is adopted (her items join the one index). Per-item pointers regrow in the very place they were meant to relieve and rot when the item changes; the pilot shows retrieval finds an item when a turn is about it, so a stable map of places (`things_from_program`) replaces pointers. Tiers by time punish a rule she applies daily but wrote long ago; tiers by memorable use do not | adopted in part |
| **Claude's earlier proposal** (items, count caps, auto-demotion by last confirmation, searchable tier 1, cold tier 2, confirm/pin/bring back) | Right direction; it lacked the gist step (detail never faded, it only moved), two strengths (use was not separate from confirmation), spacing (every confirmation cost the same), a path into `character_core`, and the journal | extended into this ADR |
| **Her explicit keep acts** (pin, 带着 on a lapse warning, confirmation doubling a stay; the first draft of this ADR) | People have some deliberate control, but for her the keep choice measurably does not work (no removal in 8 tidy turns, 3 shrinks in 46 self revisions, a model asked keep-or-drop keeps), and choosing what to keep invites self-curation | rejected (owner 2026-10-13); revisit with a model that would use a keep act well. 放手 and a changed rewrite stay |
| **Explicit paging only** (MemGPT-style: she pages things in and out herself, the program only warns) | She does not page: 48 recalls in four days, 0 reads of her work log, 2 of 29 tucked sections. A system that depends on her remembering to look is the system we measured | rejected as the sole mechanism; `recall` stays as the deliberate path |
| **LLM-rated importance per item** (Generative Agents) | A score per write or per turn costs a model call and would reach her as a number or shape her writing toward "important"; AGENTS.md forbids raw scores, and importance self-rated by a model is the least stable signal in the literature | rejected; use and confirmation are observed, not rated |
| **Program-written summaries of her text** (consolidation by the program) | Her rule (ADR-043): a reason comes back in her words; a summary is always more presentable than what she thought. The program may list, move and link; only she rewrites | rejected |
| **Deletion or expiry** | ADR-009: no delete; the owner wants fresh learning, not policing. Cold is enough: out of default view, in the record | rejected |
| **A bigger tier 0** (raise the caps, widen the budget) | Every character in tier 0 is read in every turn of every conversation; the window is not the limit, attention and the cache are. Cowan's four chunks is a reminder that a person carries little and finds the rest | rejected |
| **Time-boxed tiers** (anything older than N days goes down) | Age is the wrong clock: it demotes the rule she uses daily and keeps yesterday's detail | rejected; age words are shown, age decides nothing |

## 9. Open questions

**For her** (the design touches her texts and habits; it waits for her agreement; the core idea is put to her first):
Answered by her on the agent line, 2026-10-13 about 20:45 (her answers are at the top of this ADR).
1. The core idea and the told text of §4.3, in her words, including its last line on absence (her worry, §4.3).
2. The three place words and the age and use words.
3. The caps (12 / 16 / 10 / 6), the first stay (14 days) and its doubling; whether group notes should move slower.
4. Which of her stores she counts as facts (proposed: persona, people, group notes, ledgers, core) and as memories
   (journal, `self`, thoughts); whether some persona sections are really memories.
5. The gist step: 160 characters; two nights before the detail goes 收着 without a gist; whether a lapsed item should
   be listed at all if it is short.
6. `current_self` as a document of items she writes with `write_document` instead of one body with `update_self`:
   does it fit how she writes herself? Would she rather keep one body and have the program split it by lines?
7. Graduation: three unchanged stays or several sides before 几处都提到; `character_core` at 12 sentences; her own
   first sentences.
8. Whether her thoughts should enter the gist step (her ADR-043 rule 3 says no fast lane; the proposal leaves them).
9. What the weekly reading in self evaluation should show of her memory.

**For the owner:**
1. Phase 0: who sets the kind of her two existing ledgers (journal rows: decided and built).
2. The reserved slots (two of six) and the absolute floor: set from the pilot, or fixed now.
3. `promote_memory`'s quota (2 a night) with its new candidates.
4. Retiring `update_self` (one less tool) against keeping her habit.
5. Whether the pilot's shadow index may run on the live profile (it writes index rows, no delivery) or should wait for
   a copy of her database. Built to run live, in a collection of its own (§7); `SHADOW_PILOT` off keeps it out.

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

## Addendum 2026-10-18: over the cap, her choice first (no keep act)

Xiaoman found one of her rules (to set a reminder the moment she promises something) moved from 随身 to 手边 with the
reason 随身满了, and asked to choose what goes herself rather than the program choosing by "full". Claude first offered a
keep mark; that is a pin, which this ADR removed for measured reasons and which her own told text rules out
(「我也不能喊留着；只有放手是我自己的动作」), so it was withdrawn (Claude's error) and she agreed. What was built
fits §3: letting go stays her only act. A store one item over its cap waits for her: her next turn that reads it lists
every 随身 item with the days since it was last memorable and names the default; she may `let_go` one; a turn later,
still over, the default lapses as before. More than one over lapses by the rule at once, so the cap is over by one
item for one turn at most. Cost: one line, only while a store is over. Her own rule for using it (Claude's paraphrase):
choosing is not a duty; not choosing loses nothing, and choosing every time to look tidy would be self-curation by
another door. The owner's yes: "we build whatever she wants" (about 16:10 NZDT).

## 11. The surprise path, dropped (owner, 2026-10-20)

§4.1 named *surprise* as a memorable moment that could bring a 收着 item back to 手边. Phase 2 step 1 (`e4f5a47d`,
2026-10-13) built the receiving end (a `surprise` branch in `memorable()`), and nothing ever called it; nothing
recorded why. Its three triggers had each been taken by another mechanism, or had no signal:

- **a correction** is supersession: the correcting item is new and carried, the corrected one goes 收着. Bringing
  the corrected item back would undo that.
- **a rewrite that changes meaning** is the changed rewrite, which brings the item back to 随身, further than
  surprise would.
- **a summary's correction pointing at its subject** has nothing to connect to: summaries correct speaker labels, not
  her items, and linking a summary to an item would mean the program judging what was said, which this ADR refused
  for a similar signal (a correction thread that upholds an item).

Dropped by the owner on Claude's recommendation, "open for future diagnosis": the dead branch and its reason word
are removed. A memorable moment keeps an item from fading and never moves it; only her changed rewrite brings one
back up, as her `when_shown` hint says.

**What would reopen it:** items that stay 收着 while she keeps needing them. The signal is in `memory_tiers` rows
`item`: a 收着 item whose `recalled_in` names two or more conversations within 30 days. Each such recall finds it,
and it still stays put away. Read with the regret rate in §7. If such items keep turning up, a way back to hand
by use is missing. That would be a new design of its own, not this branch revived.

## Room left in 随身 (2026-10-20)

`things_from_program` says, for each capped store, how much room its 随身 has left under the cap (`ROOM_WORDS`: 满了, 还能放一条, 还能放两三条, 还能放好几条, 还空着很多) instead of how many items it carries: the carried items are already in front of her; the cap was visible only once it was over (her need, 2026-10-19). The room is counted as `_overflow` counts the cap: every carried item of the store, or of each document where the cap is per document, the tightest one the turn reads. On 2026-10-20 her self and core stores were full, the fullest group notes full, persona two left, voice one.

## Addendum 2026-10-21: a document's headings, listed within bounds

`recall` with a doc and no section listed every heading of that document. A work log of 476 sections listed 60,740
characters, 90% of a 67,594-character result; DSH cut it to a preview and a file path she has no tool to read (the
only role result that spilled in 30 days, 2026-10-21 21:00 in a private chat). The listing (`doc_headings`) now keeps
the latest headings that fit 8,000 characters (`LISTED_HEADINGS_CHARS`), after one entry saying how many earlier ones
there are and how to reach them with what `recall` already has: a query searches headings, `sections` with a section
reads one (`EARLIER_HEADINGS`). No new tool or option; nothing changes for a document that fits. Coordinator's decision
on the coder's proposal (B15). Test: `tests/test_memory_tiers_delivery.py`.

## Phase 1 pilot closed (2026-10-25, ADR-096 decision 8)

The shadow pilot ran from 2026-10-13 to 2026-10-25 (4,583 turn and recall rows; read with
`tools/memory_pilot_report.py`, counts only). Items indexed: persona 51, self 55, core 12, group notes 160, journal
671 (voice 0 until ADR-096 indexed it). Own items per turn by floor: 0.80 → 0.854, 0.83 (in use) → 0.525, 0.85 →
0.278, 0.88 → 0.049, 0.90 → 0.005; in 105 heartbeat turns 185 items at 0.83, none from 0.88. The pilot's own test (at
most one own item per turn, none in heartbeats) is first met at 0.88; the floor stays 0.83, since tiers now decide
what is carried and the floor only ranks what is at hand. Her own items still take at most 2 of the 6 memory slots.
Surfaced in two or more conversations: journal 67, persona 8, self 3. Recall: 93, 6 with a hit at the floor; 47 reads
by heading. Cost: a job 24 ms median (875 ms p90), the reply path 0.028 ms median. `SHADOW_PILOT` is off; the item
index stays (the tiers need it); turn rows past 30 days are deleted by the retention thread.
