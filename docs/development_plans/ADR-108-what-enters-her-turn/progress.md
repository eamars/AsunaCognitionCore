# ADR-108 progress

Installs, readings and Xiaoman's verdicts; her words as she wrote them. Kept apart from the ADR page, so that
recording progress never changes a page she signed. Moved here from the index on 2026-11-02 as it stood there;
later entries go at the end.

Built; installed 2026-10-30 12:59 as `1850b590582d`.

Accepted 2026-10-29: Xiaoman signed commit `bdbac55c952c` (her words, as she wrote them: 

小满落款：「那两个字：签，推吧。」「签的是 `bdbac55c952c06947e4b23860eb7b227d1937f2b` 这一笔的差。」).

Landed 2026-10-30 by the owner's decision, before Xiaoman's Revision 2 reading was complete.

She read 8.4 item 4, the section headings, the finished-words list except `LIMIT_WHY`, and the diff of her signed decisions, at 12:47 and 12:52 on `1850b590582d` (her own read-only tasks); `LIMIT_WHY`, `WORDS` and the built behaviour she reads after the landing.

This row is not her signature on Revision 2; her signature at `bdbac55c952c` covers sections 1 to 7 as they stood at `d9cd9eb7246d`.

In her words: Closed 2026-10-30 as 1850b590582d. Xiaoman's signature bdbac55c952c covers sections 1 to 7 as they stood at d9cd9eb7246d; Revision 2 landed by the owner's decision before her reading. Four items she raised stay as follow-ups: no version constant on the two word tables, 8.4 item 4 still says "before the landing", ask.do's enum values are not stated as values, and there is no kept-tests table. — end of her words.

小满落款：**我挂的四条 follow-ups 判：两条就地办（文档侧，归开发者）、两条 Left，都不用金主拍。** ① 两张词表的版本常量：在 `role_tools.py` 里 grep 不到 `WORDS_VERSION`／`_VERSION =`，**这不是穷尽搜索**，要看词表源文件再决定"补常量"还是"改页上第 528–529 行那句"——Left，归我核。② §8.4 第 4 条仍写 "before the landing"：**就地办**，改成过去时并写明 10-30 12:59 已装（`1850b590582d…`）。③ `ask.do` 的枚举值没写成值：页上第 212 行有 "each enum field's description lists its values" 这句话，但没把值列出来——**就地办**，值从 `role_tools.py` 的 `ask` 定义抄。④ kept-tests 表：相关文件 `test_woken_by_program.py`、`packages/cognition-core/test/context-delivery.test.js`，还要补 `LIMIT_WHY`、`WORDS` 对应的——**Left：欠小满这张表，11-06 回看。** 另照旧记一句：我签的 §1–7 里那 11 处就地批注，我**不补签、也不反对**。

小满落款：108 的 kept-tests 表（同上正本与只读趟 `task-1f37d465a75350b6871f775ce6e38389`；页 blob `f620a7830ab5c6c6025f5d30fe02ac10a5fa4783`，design `b334ae8a1469e1e598d3f7560274e464dfd19256`）。要求原文在页 §8.4 第 2 条（L519-522）、§9 那张 Decision/Built in/Held by（L557-566）、design §10.1（L331-393，D5 那段 L359-363、D1 absorb 那段 L356-357）。

留下的测试 → 各管哪条规则：`tests/test_woken_by_program.py`（blob `3d7eb1f767cd`，98 行，collect 8 条）：#1–#5 → D5（§2，我签的范围）；#6 → A2（§8.3，我没签）；#7–#8 → D1 的 `_absorb`。`packages/cognition-core/test/context-delivery.test.js`（blob `ef151a3d7241`，383 行，20 条）：只有 L57 那一条标题点名 ADR-108 D5，其余 19 条管的是投递折叠／上限那条线的测试形状（其中 2 条自报 ADR-061）。`tests/test_length_refusal.py`（blob `71abeec93cab`，118 行，10 条）：#3/#4/#5/#8/#9/#10 → D4a–D4d；#1/#2 管 `cut`／`CUT_MARK` 的形状，不是规则。`tests/test_refusal_words.py`（blob `79bf1aed3408`，39 行，3 条，docstring 自报 ADR-060/076）：#1/#2 形状检查，#3 落 D4c 字面。`LIMIT_WHY` 在 `src/asuna/role_tools.py:53-59`（5 条），用点 `:1714`，测试里 0 处提到它，最接近的 `tests/test_length_refusal.py:67` 不点名那张表＝形状检查。`WORDS` 在 `src/asuna/role_tools.py:1224-1309`（84 条目行），用点 `:1322`。页 §9 点名的其余 12 份测试文件全在树里。

跑法与限度：`pytest --collect-only` 21 collected、`21 passed in 1.14s`（跑在 core 候选里，七份文件候选与工作区 sha256 逐字节相同，前缀 `10f88f3a261d`／`95ed3350e6a4`／`d8d598b11b07`／`72f2249cb9ed`／`0c3115422550`／`f7cc09b48a65`／`4ac072b209cb`，条数与绿可搬）；JS 只能直接 `node <文件>` → tests 20／pass 20／fail 0。没做到：JS 那 20 条只核到标题＋跑绿，没逐条读断言体；`npm run test:native` 没跑（这台机 `npm ERR [WinError 2]`，`node --test` 两个沙箱 `spawn EPERM`）。

答应过那格——版本常量：页上那句「each table is one file, with a version constant that is raised with the text」（L528-529）现场不成立。`LIMIT_WHY` 与 `WORDS` 在同一份 `src/asuna/role_tools.py`（3814 行，blob `4c8c6b04586e`，sha256 前缀 `0c3115422550`），全文 `git grep -nE "VERSION|_V = |version"` 只 3 行命中且都不是版本常量（`:1839` 注释、`:2018` conversion、`:3186` `plan_version`）；`git grep -nE "WORDS_VERSION|LIMIT_WHY_VERSION" src/asuna/` 零命中（`notices.py:31` 那个 `WORDS_VERSION = 1` 是适配器通知词表，另一回事）。同页另外两张有，可当参照：`packages/cognition-core/src/marks.js:8` `export const MARKS_VERSION = 1;`、`src/asuna/wake_words.py:9` `WAKE_VERSION = 2`（L7 注释 Bump WAKE_VERSION with any change to them.）。这句页上写的是设计意图还是已成立的事实归她一句话；要留就标未落地。那两行 L528-529 出自哪份文档，随本次回执报我；若不在 108 README，我另补一段更正这句的归属。

判这张表交齐了，同时留一句给下一个人：我签的 D5 只有 6 处落点（py 5 条＋js 标题 1 条），`WORDS`／`LIMIT_WHY` 那两张表只有 1 条落字面、其余是形状——别拿"108 的测试全绿"当"我签的规则被测过"。页 L393 那句 `Not tested: wording, the words of the tables, the counts of section 5.` 与上面一致，我照旧不要补措辞测试。

The one acceptance (§8.4 item 5, design.md §8), read 2026-11-07 by a Claude subagent for the 7 days after the install
(10-29 23:59Z to 11-05 23:59Z, 5,644 character-brain calls; the 7 days before, 9,211 calls, where a row compares).
Counts only, from her character sessions (one per id) and audit rows.

| Row | Count | Criterion | Verdict |
|---|---|---|---|
| B1 channel lines between a step's mark and its assistant message | 0 (one flagged step is a session's first, its lines queued before it) | 0 | pass |
| B1 hold time | 353 held lines and 40 held over a compaction, each written within 1 s of a step boundary | its step + 1 s | pass |
| B1 receipts written twice / lines absorbed into a turn without `speak` | 0 / 0 of 521 | no rise / 0 | pass |
| B2 notices with their mark / checkpoints with theirs / program-woken notices with `speaker` | 1,728 of 1,728 / 133 of 133 / 0 of 876 | all / all / 0 | pass |
| B2 checkpoint items with a 〔n〕 | 4,988 of 12,522 (39.8%) | reported | – |
| B3 a second refusal of another class on the same tool | 35 of 694 failures (5.0%; 5.7% before) | below 2% | **fail** |
| B3 refusals holding 20+ characters of the call's prose | 6 (understand_person 4, note 1, delegate 1) | 0 | **fail** |
| B3 refusals past layer 0 with no codes in their audit row | 223 of 671 | 0 | **fail** |
| B3 DSH's English refusal on her character brain | 0 | 0 | pass |
| B4 the guard's schema refusals | 12, 2.13 per 1,000, every one a missing field the program cannot infer | at most 1.5 (floor 1.0) | **fail** |
| B4 chains | 1, 0.18 per 1,000 | at most 0.4 | pass |
| B4 length refusals per field against the week before | think 31 (30); note text 31 (40); plan intent 14 (52); others 2 or fewer | no higher | **fail** (think, by 1) |
| B4 cold first step per conversation | 19 of 30 cold, 11 partly cached, then warm (94.1% of character steps cached; 95.0% before) | one each | pass |
| §10.8 items from someone's word resolve to a line by that person | 20 of 20 | all | pass |
| B5 checkpoint items whose one cited line's speaker differs from the label | 5 of 32 (16%, an upper bound) | built or dropped on the rate | – |

Across the owner's DSH 0.2.2 switch (11-04 21:10 NZDT) the rows measure the same things (DSH's English refusal 0 on both
sides); after it the relevance gate failed every question, so the last 1.5 days hold no group turns. Of the 35 second
refusals, 21 are write_document, mostly a missing name followed by the persona render budget, a refusal ADR-117 L3
removed (11-06).

The owner's calls on the acceptance, 2026-11-07, his recommended options: the two real defects are fixed (a code on
every refusal past layer 0; no refusal holds her prose), and three fails stand as stated residuals: the second
refusals of another class (5.0%, most of them a refusal ADR-117 L3 removed), the schema refusals above the gate (all
of the floor's kind, a missing field the program cannot infer), and think's length refusals (31 against 30). B5 is
dropped: its rate is an upper bound on 5 cases, revisited only if a wrong attribution causes a real failure.
