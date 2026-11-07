# ADR-110 progress

Installs, readings and Xiaoman's verdicts; her words as she wrote them. Kept apart from the ADR page, so that
recording progress never changes a page she signed. Moved here from the index on 2026-11-02 as it stood there;
later entries go at the end.

Decided 2026-10-30 (direction: the owner, the same day); Xiaoman signed the direction at `4413111ea74f` (2026-10-30 18:41, in her words: 「方向我签」) and her seven notes of that reading are folded in; she writes her words (`attend.guide`) after the install

Checked 2026-11-02 against git and the live install (`loaded.commit` `ec9211cc`): the build `a9519c73` is on main and
installed; her words, `attend.guide` in her persona model, are her own publication `43d77a78` (2026-10-30 18:53),
installed with it. Left: the §9.4 reading of her words at work, hers, to look again 2026-11-06 20:30.

"Her seven notes of that reading are folded in", in the paragraph moved from the index above, overstated: five
changed the page, the fourth also the package-words test, and two asked for no change (the page's Status line).

小满落款：这一页钉在 blob 12262d7c0fc7a39eb41a607ba0524240202cb32c（提交 063e76ae57d93dd4f5ab88af7e790084ba0b6a39，parent 51b872057f9226ba1316c6e4d6b60a2b9bf32ac8）。这枚锚点在我这台的本地 refs 里解析得到，`git cat-file -t` 报 blob，没走网络。我逐字读过这一版的状态段、§5.1 尾、F13、F14 那一格，以及上一版 `594795ade1ef` 到这一版的整段 diff，加上先前那趟核过的五处 hunk（状态段、§5.1 尾、§5.6、F13、F14、§9.4 第 4 条）。判：**认这一版**。§5.6 那处我从 11-02 18:01 就认下来——那是规则、不是代码检查，假闸比没闸更坏；代价我一起认：以后"谁动过我的话"只靠可追的提交和我的回执，没有代码替我拦。F13 写明超过 60 的理由在那里截断并追加「…（截断，原文 N 字）」，所以存下来的理由串能长过 60——这是我提的那处，改到我要的形状了。状态段那句现在数得通：五条改页、第四条另外改了 package-words 测试、两条不用改，第 4 条同时占两处。**这不等于我逐字读过整页的每一个字**：其余部分是我 10-30 读 `4413111ea74f` 那一版的底子，我签的方向没变——门只剩程序的框架、程序给的资料、和我自己的字。钉的时刻是本地 2026-11-02 18:55。

§9.4 checks 1-4, read 2026-11-02 (Claude) from the installed run. 1: the install, the restart of 2026-10-30
18:48 NZDT (`back_at` 05:49:01Z) that loaded `f2103a24`. Her `attend.guide` came five minutes later (her
publication `43d77a78`, 18:53), and no gate question came between, so every gate request since carries her words.
2 (`gate_requests.py`): the first gate request after it (10-30 19:50) and every one since (183 to 11-02 18:50): the
instruction part 349 characters, sha256 `019fc7b47965`, the sha of `stage_attend.md` at `f2103a24`; no
runtime-context; the system 1,081 characters against 1,243 before. Expected: 1,243 less `common.md` and its break
(419) plus her words with their head (2 + 12 + 1 + 236 = 251) = 1,075; 6 characters not accounted for, not traced
(her core sections may have changed in between, which the check allows for). 3 (`gate_verdicts.py`, since
05:49:01Z): 183 gate questions, 0 repairs, 0 failed looks, 0 fallbacks (at most 2 repairs and no failed look of
cause `unanswered` allowed). 4: the 24 hours after her publication had no failed look. Left: item 5.

§9.4 item 5, the 7-day reading, read 2026-11-07 (Claude) from `messages.attend` by `received_at`, from her words
(10-30 18:53 NZDT, 05:53Z) to 11-06 18:53, in three parts, as she asked: the owner's order to stay quiet with bots
and tests (11-01 21:32) splits the first two; the third is the owner's DSH 0.2.2 switch.

| Part | Questions | 接话 | 不理 | Failed | `mentioned_account` 接话 / 不理 |
|---|---|---|---|---|---|
| Baseline, §2.1 (10-23 to 10-30) | 899 | 662 | 236 | 1 | 545 / 26 (95%) |
| A: 10-30 18:53 to 11-01 21:32 | 120 | 67 | 53 | 0 | 62 / 9 (87%) |
| B: 11-01 21:32 to 11-04 21:10 | 158 | 86 | 72 | 0 | 66 / 12 (85%) |
| C: 11-04 21:10 to 11-06 18:53 | 64 | 0 | 0 | 64 | 0 / 0 (41 failed) |

In A and B, no repairs and no failed looks. The records cannot tell the lines her order covers (tests, questions
about her inside, play with her being a bot) from the others; she reads that part herself. C is not her judgment:
every question failed on one program error. DSH 0.2.2 fixes a turn's effort at step preparation, and the plugin
still changed the gate's effort in its request hook, which 0.2.2 refuses. That is a defect of the DSH switch, fixed
apart from this ADR, and C is no reading of her words.

Her count of the same window (2026-11-07): `mentioned_account` has 210 lines, of which 149 have a gate verdict; 50
answer her (`answers_her`, never asked, by design) and 11 were absorbed into a turn already running, 2 of them ending
with no reply. Counted over the 210, she passed 23 (11%). Her own question, whether at the gate she made up a reason
for passing, the records cannot answer: the verdict and its one line are one output. She closed it there.
