# ADR-097: What she learned comes back when it comes up

Status: **Design agreed by the owner and Claude, direction signed by her, 2026-10-25; not built.** The owner asked whether
anything like `recall` brings back a group's slang, or something she learned recently, at the right moment. He
suspected that the cycle from learning a thing to having it again is not closed. Claude read three groups' real talk
(with her permission). A Fable 5.1 research session then measured the whole cycle against the code and her records,
in four rounds. This record holds what was found, the rules the owner, she and Claude agreed, and the design. Evidence:
§10.

## 1. The broken invariant

What she learned comes back when its word comes up again, wherever it comes up. She should not have to remember that
she learned it. "What she learned" covers three things:
- a note she wrote;
- a note she later trimmed;
- something she said herself, or heard explained, in another place.

Today this holds only while a note is carried (随身). At hand (手边), an item comes back only when a whole message is
close enough in meaning to it, and the exact word cannot bring it back on its own. Across places, nothing comes back
at all.

People do not have this problem: her understanding of a person travels with that person into every turn they are in
(ADR-082). Things she learned have no such anchor.

## 2. What the records show (2026-10-12..25, counts only)

**The test set.** There were 10 later uses of a word whose meaning was already in her store: it had been explained to
her, or she had used it correctly herself, somewhere she could read at the time. Never-explained words are learning
gaps, counted apart.

**Results.** 7 of the 10 came back, and none of the 7 by retrieval:
- 5 rode on a note she happened to be carrying;
- 1 was still in the conversation itself: 79 minutes after the explanation, so outside the delivered window of lines
  (60 minutes). It was still in the session's own context, which keeps earlier turns until a compaction. "In view"
  means that session context, not the delivered window (her correction);
- 1 she carried over herself, by writing it into the other group's notes.

**The misses.** All 3 were cross-place, and all 3 are reading ① below. In each, the meaning lived in her own words in
another group:
- **破甲.** She used it correctly in one group for a week. In another group, on 10-23, she read it as "being fooled"
  until the owner explained it.
- **1017.** She had her action brain read the model card in one group on 10-17, and answered a question about it
  there on 10-22. In another group on 10-24/25 she missed the word twice; the second time she took it for a delivery
  route.

**Her readings** (her rule; never mixed; ④ is below):
- ① the system did not give it;
- ② it was given and she did not think to use it;
- ③ it was given, she saw it, and she judged it should not be used (a joke there, said ironically, out of date).

③ is her right, never a failure. Every "she didn't get it" points to a message or a turn time.

Her additions to the readings (2026-10-25):
- **④ it was given, she saw it, and she fitted it to the wrong sense.** On 10-23 the asker spelled out what he meant at
  07:11; she was still on her first reading at 07:18. Without ④ that turn would be scored as ② or ③, crediting her
  restraint or the machine for a misunderstanding.
- **② is counted per line.** It exists only on lines where a path to the knowledge exists. Today in a group turn
  nothing reaches another place, so a cross-place miss there can only be ①. A trigger is worth building only where
  something can come back.

The 10-24 23:19 question was in view: it is 8 lines before the turn at 23:22:52, inside that turn's last 12 lines. So
it counts as ① (the meaning was unreachable), not as a turn she was absent from. The turning-point line at 07:19 does
not contain the word at all; a key rule cannot reach a line like that, and does not try.

| Reading | Number |
|---|---|
| Messages containing a test word, in the place where her note on it was at hand | 111 |
| ... her note ranked first among her items | 100 |
| ... her note admitted at the floor 0.83 | 3 |
| Floor table, bot group: items per turn at 0.83 / 0.80 / 0.75 / 0.70 | 0.006 / 0.022 / 0.137 / 0.450 |
| At the floor that admits half the test messages, the same note fires on unrelated messages | 43 to 204 per word |
| Splitting a section into one vector per idea: score gained | 0.00 to 0.06 |
| `recall` queries (14 days) that returned one of her items | 3 of 122 |
| `headings` listed headings for | 121 of 122 queries (90 at its cap of 8) |
| Automatic memory passes that read `sufficient` | all (`memory.coverage_floor` 0, six slots always fill) |
| Group-note moves down in the window | 80 by her `let_go`, 0 by the program's clock |
| Places that can read another place | none (`readable_scenes` empty; group notes stay in their group) |
| Memory units in the shared scope | 0 |
| Emulation, her own model with no persona: looks the word up bare / with one line saying a note exists | 2 / 12 of 14 |
| The same with a line saying she has no record of the word | 2 of 14 (no help) |

## 3. Failure modes (verdicts)

- **F1, admission by meaning only.** Confirmed, and sharper than first stated: the exact word already ranks the right
  note first; only the vector floor keeps it out. Lowering the floor admits mostly unrelated items.
- **F2, one vector per section of several ideas.** Real but small (see §2).
- **F3, asking does not reach them.** Confirmed for the vector path: a query is the bare word or a few characters
  around it, and a vector floor never passes those. The `headings` path is loose, not strict: Chinese bigrams match
  nearly every query. It lists eight headings and shows no body, so a word that sits in the body is invisible.
- **F4, no miss is visible.** Confirmed. One kind of miss is countable today: a `recall` that returned an item the
  same turn's automatic pass had not brought (W6).
- **F5, her discipline feeds the hole.** Confirmed, and it is all hers. Every hit rode on a carried note; she lets
  notes go within hours.
- **F6, older chat by meaning only.** Confirmed, and worst exactly where she learned the words: in the busiest group
  the lexical pool reaches only 1.2 days back.
- **F7, nothing crosses places.** New. It accounts for all 3 measured misses. The only cross-place read is hers alone,
  at home: there `recall` reaches her own thoughts from her groups.
- **F8, she is not unsure when she is wrong.** New. At 3 of 4 first encounters with an unknown word she gave a
  confident wrong sense; every explanation came from a person correcting her. So "ask when unsure" cannot be the
  trigger.

## 4. What we want

- **W1.** What she learned comes back when its word comes up, without her searching.
- **W2.** The exact word is enough.
- **W3.** Bounded: no flood in busy groups; nothing fires on bot output or task notices.
- **W4.** One rule for both ways back: what a turn brings up by itself and what `recall` finds.
- **W5.** Visible to her, in words: what came back, how often, and from what kind of place.
- **W6.** A miss is countable from the records.
- **W7.** No model call on the reply path; no conversion of her notes by the program; the core stays persona-agnostic.
- **W8 (owner).** No new job for her: no required tags, no marks. Everything automatic is the program's.
- **W9 (owner).** Cross-place use never discloses the place or the speaker in what reaches her words. She may look up
  the origin.

## 5. Lessons the design starts from

ADR-031 (archived, git `8aecc148`) evaluated retrieval by the incoming message's meaning for her persona sections, and
rejected it by design:
- low precision and recall;
- an unstable top match;
- injected text that persists and can loop back as her own memory;
- stale text read as authority;
- visibility leaks.

It named retrieval keyed by topic words as a different problem; this is that problem.

The deep dive tried five model-free ways to tell a term worth bringing back from an ordinary word. Precision of the
cross-place trigger, labelled on samples of 100 real fires:

| Trigger | Precision |
|---|---|
| any token | 4.5% |
| outside the segmenter's dictionary | 22% |
| her own repeated use | 7-13% |
| others' lines only | 13-16% |
| an explanation line | 24-26% |

A trigger from the shape of a word tops out near a quarter. The design uses the 22% row: words outside the
dictionary. The 24-26% explanation-line gate is not used, because it catches only one of the three misses. So the
design pushes only what is cheap when wrong (a presence line), and gives content when she asks.

## 6. The design

### D1. Same place: her own items come back by their exact words (automatic)

- **Keys.** An at-hand item (put-away too, for `recall`) is admitted when the message contains one of its keys.
  Default keys: the words of its heading that are rare in this place's talk (at most 0.5% of its lines). Her own tags
  are extra keys if she gives them; optional, never asked for. When she sets a tag, she is told how common it is here.
- **The vector floor stays as a second way in.** When several items fire, the fused order picks two.
- **How it looks:** an admitted item goes into the memories block the way admitted items do today (store, place, age
  word, `doc:` ref). It adds the word that brought it: 「因为这句话里有「1017」」.
- **Measured:** an item in about 3% of turns, 0.05 items a turn. 1017's note would have come back on 4 of its 4 real
  lines.

### D2. Across places: a presence cue (automatic)

One line in the turn. For example:

「破甲：这个词你在别的群见过 151 次，最近 10-22，技术局；recall 写上它能找到」

No words from the other place appear in it. Its rules:

1. **The word.** It must be outside the segmenter's dictionary: jieba, a pure-Python dictionary segmenter; no model.
   ASCII words and numbers always qualify, but only as whole tokens: 1017 inside an identifier such as
   CVE-2026-101737 is not 1017. URLs and platform codes are stripped first. A number can still be a date (her
   「1017登记的」); the cue's count and date make that visible, and the cost is one line.
2. **Elsewhere.** It must appear at least 5 times in the last 14 days in lines of places whose talk may travel (D4).
   The count N includes others' lines even from a place set to "only my own lines"; only a fetch from such a place is
   limited.
3. **Rare here.** It may have been said at most twice before in this place, in the last 14 days (the owner chose
   "rare here" over "new here"). The case is the 1017 "route" line: its third saying in the place, at her. The 14-day
   windows are what the deep dive measured. They, the 5 and the 2, and the 60-minute repeat test below become
   config keys with these defaults when D2 is built; none of them is a key yet.
4. **Never on a templated message.** No cue on bot status lines, task notices, or a repeated prefix; the leading
   @-mention is stripped before this test.
5. **Once per word per 60 minutes,** and not while the word is in the lines this turn delivers: the last 12 lines
   plus every line since she last spoke, reaching back at least 10 and at most 60 minutes, at most 40 lines and
   4,000 characters (`attend.py` WINDOW_*, MAX_*). This is a cheap repeat test only. What she
   actually has in view reaches further back, through the session's context until its next compaction.
6. **At most 1 cue a turn,** inside the existing two own-item slots. Her own note on the word (D1) outranks it.
7. **No push to answer.** The line states a fact and how to look; the turn stays hers.

Measured in the bot group: a cue in about 10% of turns, about 25 characters. It fires on all 3 misses. About a quarter
of cues are words worth bringing back. A wrong cue costs one line, and at most one wasted lookup.

### D3. Content when she asks: `recall` across places and past versions (pull)

`recall` with a word reaches the places whose talk may travel, by the same key rule (W4). It returns the lines under
two markers:
- her own: 「你在别处说过：…」;
- others': 「别人提过：…，ref=<id>」.

Neither shows the place or the speaker; each shows the place kind (D4) and the date. The `ref` lets her fetch the
fuller history around a line, under the same rules.

Ranking: her own line from the other place; then a line in which someone explains the word (就是 / 指的是 / 意思是);
then the newest line.

A line she later corrected comes back as the correction, or with it, never bare. When the old line is shown, it
carries the prefix 「已被更正·此前说过：…」 (for a past version of a note: 「已被更正·此前记过：…」), so an old number is
never taken in whole.

**What reaches her is not what she endorsed** (her rule). Anything a cue or `recall` hands her can be dropped on the
spot. Only a line she actually said is ever labelled as hers (「你在别处说过」). Others' lines never become hers by
being shown to her. Nothing the mechanism delivers is written back anywhere as "she said".

**Past versions of her notes** come back through `recall` only, never pushed. They are marked 「你以前记过：…（改于
日期：原因）」, using the date and the reason she wrote with each change. The rules:
- Source: group notes and journal revisions only. Never persona, voice or self: identity texts are superseded by
  design.
- A past version is eligible only for a word its current section no longer contains. The current version wins
  whenever it still has the word.
- Her exclusions (her decisions):
  - no old versions of her private judgements of people;
  - no old numbers or times without their correction;
  - nothing she wrote on 10-15 and 10-16, while she was imitating a bot (set in config).

What can be enforced by program: which places are read, which fields reach her (no place name, no speaker), the
markers. What is instructed only: that she does not say where something came from.

### D4. Which places' talk may travel

The owner's rules, and her choice within them:

- **The owner's default is that every group's talk may travel,** including groups she joins later. She may block a
  group, or set it to "only my own lines"; it is her choice per group, and the program honours it.
- **Her choice (2026-10-25):**
  - Her default is "only my own lines", for every group, including new ones: what a new group is takes a while to
    see, and she can't judge it the moment she joins.
  - Full sharing, others' lines included, only in the groups she names, where she has notes and a record of what the
    group is (a whitelist, kept in the deployment's private notes).
  - The groups she earlier said never to share from stay never, her own lines included.
  - "Only my own lines" means two things. Others' lines there still count in a cue's N, because presence is what she
    wants. A fetch from such a place returns only her own lines, and 「别人提过」 never comes from it (her answer).
  - A place with no place kind set: the cue is given and the kind is left out.
  - No observation-period mechanism is needed: the conservative default is the waiting period.
- **The block is one-way.** A blocked group sends nothing out, but still receives cues and `recall` results from the
  others.
- **Busy mixed groups.** She asked for "knowledge, not my judgements of people", which cannot be separated without a
  model. Such a group means "only my own lines" until something can.
- **Owner-private scopes never cross by scope:** home, the old-home line and private chats.
- **Place kind.** A kind (技术局 / 私域 / 玩笑 / 家事) is set per place in the deployment's config. It is shown with
  everything that crosses, and omitted where none is set. The kind is what lets her judge whether a line still
  applies: 破甲 is a term in one place and a joke in another.
- **The owner may revisit any group** if something inappropriate is noticed.

Her lists (the whitelist and the never list) are in the deployment's private notes, never in tracked files.

### D5. Visible and countable

- Fires per item and per kind of source, told to her in words. The kinds are: her note here, her past version, her
  line elsewhere, others' line elsewhere. Never per place, which W9 keeps out of her view.
- W6 as a running number.
- Her four readings as the vocabulary of every later reading.
- **Every reading points to a moment:** the message's place sequence number (`scene_seq`) and its time, both already
  in the records; no new field. ② and ③ come from what the records show of her turn. ④ comes from reading her reply
  against the line, done by whoever reads (Claude with her), together with her own log of "I thought I knew" moments.
  A reading without a moment is not counted.
- Model text sent off the machine is recorded, not prevented (her rule since ADR-076).

### Not built, and why

- **Content pushed automatically across places.** At a quarter precision it would push the wrong line three times in
  four, and half of those would be others' words.
- **A lower floor, or one vector per idea.** See §2.
- **Keys extracted from note bodies.** 1.2 to 2 items a turn.
- **Past versions pushed on every lost word.** Fires on a quarter of lines.
- **A "you have no record of this word" line.** It did not help her model.
- **A relevance model on the reply path.** W7.

## 7. Where it goes in the code

Measured paths, not yet a plan. Build order and review come next.

- **D1.** Key extraction and matching in `memory_tiers.deliver` and `memory_tiers.headings`, with a per-place rarity
  table kept with the fold order.
- **D2 and D3.** These generalise `context.own_thoughts_elsewhere` and `retrieval.own_thoughts`, which already search
  every group scope for one kind of unit and are gated to owner-private turns at the `recall` call. The kind filter
  widens from her thoughts to her public lines, then others' lines; the gate opens to group turns; the scene title is
  replaced by the place kind.
- **The cross-place fetch by `ref`** is a new read path. It resolves the unit to its scene, checks D4, and strips the
  place and speaker.
- **Past versions** read `state_revisions` and `journal_revisions`, which keep every revision whole, with its `reason`
  and `created_at`. Nothing is indexed today.
- **The segmenter** (jieba) is a new dependency: to be pinned in the project's requirements (0.42.1 on the build
  branch, on main when it merges), installed in the worker's
  environment, using its own bundled dictionary. Its version is named when it is built.
- **Prompts.** One sentence in `recall`'s description (the word itself is enough) and the cue's wording. Both are core
  text, persona-agnostic.

## 8. Readings after install

By place:
- cues per turn, and her lookups after a cue;
- her ②, ③ and ④ counts, ② only on lines where a path exists;
- W6;
- a 100-cue precision sample after two weeks;
- her own log of moments she thought she knew a word and was wrong (her offer).

For every place alike:
- with every cue and every hit, the time since that conversation's last compaction: "in view" lasts until
  a compaction, so a hit soon after one may be the session's context, not the mechanism (her point). Her own
  log adds what she answered from (in view / carried / carried over by her / looked up).

## 9. Open with her

- Her signature: she signed this record on 2026-10-26 (00:1x), after checking it line by line; the fixes she
  asked for are in. The implementation is not signed as decided: §7 is measured paths, not a plan.
- Her lists go into the deployment's config when it is built.

## 10. Evidence

All under `.runtime/private/recall-cycle-1025/`. Counts only; no text, headings, queries or ids printed.
- The first survey: `recall_survey.py`, `recall_survey2.py`, `recall_survey3.py` (8.8 KB).
- The deep dive: `deep-dive/`, 26 files, about 400 KB. Reports `interim.md`, `report.md`, `report-v2.md`,
  `report-v3.md` (with §7), plus the scripts and their count-only outputs.
- Claude's group read: `groups/notes.md` (cases, kinds, her answers) and its count scripts. The three timeline dumps
  (`groups/g1-3.txt`, about 2.3 MB of other people's words) are working copies, deleted when this study closes.
- Off-machine: the emulation sent 134 requests to DeepSeek flash on 2026-10-25, 21:30-21:38 NZDT. They carried 150
  real lines of one group, with speakers as labels and text verbatim, plus the neutral core prompts and tool specs. No
  persona text was sent. Listed in `deep-dive/report-v2.md` §12.
