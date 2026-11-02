# ADR-064 progress

本页 2026-11-02 由小满新建，先只有她判页上 L828–837 那条 `stay_silent` 读数那一段。索引 `docs/development_plans/README.md:75` 那行的状态词与 Left 由 Claude 维护。

判词（小满，2026-11-02）：

页上那条读数（L836–837）是：「Reading: the same counter a week after install; the unexposed `stay_silent` refusals should be 0.」

**判：达标。但我把这一格记成"报警器不会响"，不是"测到的稳定"。**

读数本身（Claude 用 `host_refusals.py` 数会话日志，我的行动脑独立扫 4,910 个 `session.v4.jsonl.zstd` 复算，两路一致）：

- 装前 `10-22 00:00 → 01:41:53`：守卫那句「这个对话里没有 stay_silent 这个工具」的拒 **1 条**——10-22 00:19:32，QQ 群，`call_7d3f274d26fb44e4a7730534`。
- 装后 `10-22 01:41:53 → 11-03 00:00`：**0 条**。按页上"装上一周后"那个点（启动器台账算出是 10-29 01:41:53）也一样是 0，两种窗尾都成立。

**这个 0 不是测出来的。** 现装这一版里**没有任何一条线"既不带 `stay_silent` 又不带 `speak`"**：`stay_silent` 在 `EVERYWHERE`（`src/asuna/role_tools.py:942`），只在 `reply_parts` 为真的场合跟 `await_answer`、`attach_image` 一起摘掉并补上 `speak`（`:198 REPLY_REPLACES`、`:936`、`:1008`）；别名再把 `stay_silent → speak`（`:806-810`），宿主守卫看见清单里有 `speak` 就放行（`packages/cognition-core/src/index.js:1260`）。库里 `turn.started` 的 `payload.tools` 也对上：QQ 那一类 2,036 个回合是 `speak=是、stay_silent=否`，开发线 1,112 回合、家里 948 回合是 `stay_silent=是、speak=否`，**没有哪一格两个都没有**。所以这条读数结构上不会变红——它是"装对了就永远是 0"那种判据，不是"跑偏了会响"那种。

**真正撑住这条的凭据在行为那一格**（页上 C2 说的就是它）：装后 QQ 群里 `stay_silent` 被真调了 **14 次**（一个群 12 次、另外两个群各 1 次），库里恰好 **14 行** `payload.result.note` 是那句一次性提示「这里不调 speak 就是不说话，用不着 stay_silent；这回合到此结束。」，全库也只有这 14 行带着这句话。别名在跑、回合照样结束、提示只说一次——**我拿这一格当达标凭据，那个 0 只当旁证。** 管这件事的测试是 `tests/test_silence_where_speak.py`。

三格页上没写、我这里补齐（页我不动，那是你的历史）：

1. **装机时刻**：别名提交 `baa310de79e5791e2ac8a0fd1c647b42e9ec7b9f`（作者 2026-10-22 00:49:38，parent `8e1ece86…`）；第一次装上是启动器台账 `restart-20261021124153`，**停 01:41:53.011、起 01:42:23.610**，`loaded.commit = 031bd74e885e0de026ce6533c85a6975cc1245f6`（它的 parent 正是 `baa310de`）。页上"一周后"照这一刻算是 **10-29 01:41:53**；Claude 数到 11-03 00:00（12 天 22 小时），两个窗尾都是 0。
2. **数据源**：这条读数的分子**只活在 DSH 会话日志**里——`host_refusals.py` 头部写死了这件事，页上没说。点名一格：**宿主那道守卫的拒根本不写 `audit_events`**，拒发生在 `packages/cognition-core/src/index.js:1252-1266`，压根没走到 worker 侧那条 `role_tool` 审计（`src/asuna/role_tools.py:1602`）。实测：上面那次被拒的 `call_7d3f274d26fb44e4a7730534` 在库里 **0 行**，而同一回合 00:19:54 的 speak 行照常在。⇒ **这一格以后只能用日志复测，不能用库。** 日志这边眼下没有按龄删除规则（`asuna-role-` 不在 `tools/asuna-launch.mjs:386-388` 的 `RETIRED_PREFIXES` 里，实测能数到 10-11），但这只是"没找到删除规则＋实测还在"，**不是任何书面上的永久保留**。
3. **别把两个"0"混成一个**：页上那句只指守卫那一格。从库里看，装后 `stay_silent` 另有 **4 行 `payload.refused` 非空**——3 条是「这回合第 24 次工具调用，到了硬线（24）」、1 条是「先用 think 写下这回合的心里话」，都是别的成因。

**没测到的格子照实列**（不许并进"没有"）：QQ 那一类共 23 格（22 群 ＋ 1 私聊），装后只有 3 个群调过——**QQ 私聊 0 次、其余 19 个群 0 次**，这些格子说不了；`asuna-reflect-` 会话那 18 次调用只躺在归档目录里，`host_refusals.py` 只扫活存储，看不见它们。

两格顺手更正（都不影响达标）：Claude 那句"同一时段宿主拒了 15 次"里的 **15 是 `10-22 00:00 → 11-03` 整段的总数**，**装后那一窗是 14 条**（10-22 00:19:32 那条 `stay_silent` 落在装前）；那 15 条里还有三条没点名：`close` 1、`sleep` 1、`stickers` 1。`speak` 8 次与 `stay_side`／`stay_sight`／`write_docxg_2lp4` 各 1 次逐格对上。页上 L831–832 那句旧数（27 条、10-19 26 条）我这趟**没判**：未去重的行数与按 `callId` 去重的数对不上（10-19 全店原始 56 行 vs 去重 48 行），要不要复核归你。

我自己一笔：页上写的是"装上一周后"，那一拍谁都没挂钟，这一格从 10-29 拖到 11-02 才判——跟 054 同一次毛病、同一个修法（点头那一拍就挂钟）。

**我不借这一段宣布整份 064 做完**：页上 phase 2 那些（`speak` 的 text／sticker／poke／reaction）不在这段范围里；索引那行的状态词你按你的图例定，Left 那句「not written」现在可以销了。

小满落款：我认 ADR-064 这一版页，blob `4dcd5f0e17438c315e9f17f84d44d82aef636733`，提交 `aadd9661e1ff5e4072826e089de918b5527000e7`。认的是上面这一段判词和它引用的读数，**这不等于我逐字读过整页 881 行的每一个字**——我逐字读过的是 L828–837 那一段和索引 `README.md:75` 那一行，其余是没读的历史。

## Reading after a week (2026-11-02, done 22:0x)

### Readings (read 2026-11-02, Xiaoman)

**Windows.** After: 2026-10-26 21:38:03 → 2026-11-02 21:38:03 her clock (UTC 10-26 08:38:03 → 11-02 08:38:03),
7 d exactly. Before (the baseline the owner asked for, "改前七日"): 2026-10-19 21:38:03 → 2026-10-26 21:38:03 her
clock (UTC 10-19 08:38:03 → 10-26 08:38:03), 7 d exactly. The start is `ab156a75…`'s author date, which the owner set
as the window start at 2026-11-02 21:38; **the page's own "11-02 21:00" was written without a clock behind it** (it is
not "the change plus seven days", and nothing was scheduled at it), so this reading takes 21:38:03 as the tail and says
so here. The install came 27 min 13 s after the window start: launcher ledger `restart-20261026090516`, down 22:05:16,
back 22:06:16 her clock (09:05:16Z / 09:06:16Z), `loaded.commit 7650eac4…` (`7650eac41bac2a49eb62bb304cd75c9b8a84b244`;
the ledger stores the 8-char short form). `git merge-base --is-ancestor ab156a75 7650eac4` → 0; the install one before
it (`155d413c`, down 19:42:51) → 1. In the 27-minute sliver between window start and install there are **0**
`turn.rejected` rows, so nothing counted below was produced by the old wording. The wording itself has not been touched
since: `git log -S'如果这段是写给自己的' --since=2026-10-26 -- src/ packages/` → no commits; the string sits at
`src/asuna/coordinator.py:67` (`UNSENT_NOTE`).

**读数一 — narration pushed out (expected to fall).** The hand-back itself is `audit_events type='turn.rejected'` with
`payload.problem='unsent'` (`coordinator.py:302-318`). One note first, because it changes which grid can measure this:
the new sentence is **not** written to `role_tool.payload.refused` — in that grid the whole new wording appears in 0 rows
in either window (841 refused rows after / 988 before, classified by wording: 先 think 182/150, 撞硬线 7/4, 别的 652/833,
告知不强制 0/0; the single row containing 「在这里说话用 speak」 is a 10-22 00:41:49 `note` refusal whose *body* quotes
that sentence, not a hand-back). So the instructed `role_tool.refused` counter cannot see this change at all; the census
in `.runtime/private/handback-1026/` uses `turn.rejected`, and so does this reading.
A turn counts in the numerator when (a) she then spoke in that same turn (`episodes.reply.parts` non-empty — mechanically
impossible before the hand-back, since `unsent` is only raised when there is no reply yet), and (b) the pushed beat had
no new external input, counted exactly as `draft_newinput.py` does: inbound lines in that scene between the last message
at/before the hand-back and her first outbound line of the turn == 0.

* after: 121 hand-back turns (group 115, dm 6) → 2 ended speaking → **numerator 2** (both group). Per day (hand-back):
  10-26 5, 10-27 9, 10-28 18, 10-29 25, 10-30 20, 10-31 16, 11-01 16, 11-02 12. Rate 2/121 = **1.7%**.
* before: 132 hand-back turns (group 130, dm 2) → 54 ended speaking → **numerator 53** (group 51, dm 2; per day 10-20 5,
  10-21 9, 10-22 19, 10-23 4, 10-24 2, 10-25 6, 10-26 8). Rate 53/132 = **40.2%**. The one excluded turn (10-24 02:33:39)
  had 3 new inbound lines before she spoke.
* the 2 after-turns, full first lines (times her clock): 10-29 02:08:48 draft 「@[🍊 #56] 2^100000000 ≈ 3.68 × 10^…」 →
  said 「@[🍊 #56] 2的一亿次方约等于 3.6…」／「全贴出来能把这塘埋了，凌晨两点不开这个张…」／「[表情:斜眼笑] 这回发出去了吧」;
  11-01 22:04:09 draft 「笔记已经重写完，要紧的都并进了新版活账节，这回合不用说话。」 → said 「你十天没来，这期间塘里又进了好几条新鱼…报 400 的、贴 token 账的…」.
  Read by eye, both are lines addressed to a person, not bookkeeping narration — with the content step applied the
  after-window numerator is **0**. That step is my judgment, so it is kept beside the mechanical 2, not inside it.
* 12 samples of what the new wording did instead (hand-back given, words left in the turn, time + first 20 chars):
  10-26 22:14:44 「（该留的都落进笔记了：暴涨行情快照、#1…」; 10-26 22:23:32 「（查完了，该留的都在笔记里，没话要说。）…」;
  10-26 23:20:55 「旧条款那批不带出去丢人了——按初语新单（…」; 10-26 23:21:45 「验收闭环：委托回执＋行动脑同形读数两样凭…」;
  10-26 23:38:32 「巡拍完：签字开填链、初语头像未决格都钉进…」; 10-27 04:03:37 「欠条销了，销账的条子也回给家里了——那枚…」;
  10-27 05:03:27 「账换完血：LPL 那组数带来源落了笔记（…」; 10-27 05:59:03 「笔记整理完了。」; 10-27 09:33:09 「读数钉进群笔记了——旧文件回读以后固定走…」;
  10-27 10:05:59 「快照换到 10-27 压前版：Day 1…」; 10-27 20:34:06 「（备忘换血完毕，等安静压缩。）…」; 10-27 22:15:21 「这趟是压缩前记账，没人叫我，群里不说话。」.
* what the old wording produced in the before window, same 12-slot sample (draft → what she then said):
  10-20 01:00:20 「闹钟就是这一响，案已销…」→「那句不是过期，是你那环境里压根没这条命令…」; 10-20 11:13:45 「笔记压好了…」→「[表情包:蓝贴贴]」;
  10-20 15:08:25 「笔记换完血，这轮不用说话。」→「给 〔5532〕 [清尘璃落 #5] …」; 10-20 15:16:27 「单子派出去了…」→「接单。已派人拉 Kobe 全部发言了…」;
  10-20 20:13:07 「这拍不用接…」→「盹完了记得报个到…」; 10-21 03:33:31 「留档写完收进手边…」→「刚那句是我记账的碎碎念，不用接」;
  10-21 15:09:09 「（这拍是旧便条又叫了一次…）」→「这堆线框不是画的…」; 10-21 20:51:32 「家里已接住两件事…」→「[表情包:先跑了]」;
  10-21 21:34:29 「（单已派出排队…）」→「zip 在打包了…」; 10-21 21:56:54 「那问的是主人、他也答了…」→「给 〔12405〕 …」;
  10-21 22:21:22 「闹钟这拍判成"继续等"…」→「刚那个是我自己的闹钟拍，没说话，不用管」; 10-21 22:25:16 「（反应图不追，这轮收板，安静。）」→「给 〔5928〕 …」.
* columns from the same two windows, same 口径: drafts left unsent (`turn.unsent_body`) 117 after / 121 before, median
  11 / 17 chars; bodies written after she had already spoken (`turn.ending_body`) 617 / 1,210, median 25 / 25 chars;
  her own outbound lines 1,862 / 2,144; other people's inbound lines 43,415 / 47,937 (program lines 508 / 530).
  The character counts of the words she left in the turn (25 / 31.5, punctuation and space removed, `lane_receipts … :TURN`)
  are the same ruler as `draft_lengths.py`; that script's own 28 came from the 43 surveyed cases, not from a week window.
* **not comparable population, named:** the hand-back fired in 14 places after and 13 before, 11 shared (3 appear only
  after, 2 only before), so the group set is not identical; window lengths are equal (7 d and 7 d).

**读数二 — times she is told she should have said something (expected not to rise).** Literal shapes, people only: the
numerator shapes are 「你没说」 and 「没看到你的」, counting only a person's line said to her; program lines
(`author='asuna:internal'`) and her own lines are excluded.

* after: 「你没说」 2 rows, both the program (0 person rows); 「没看到你的」 2 rows, both the program (0 person rows).
  **Numerator 0 拍**, denominator 43,415 person lines (43,415 inbound episodes).
* before: both shapes 0 rows at all. **Numerator 0 拍**, denominator 47,937 person lines.
* shapes I added to the list and left out of the numerator (they are not "a result was never reported"): 没看到你说
  0 after / 1 before, 没见你说 0/0, 没听你说 0/0, 怎么没说 0/0, 咋没说 0/0. The before-window 没看到你说 row is
  10-25 20:16 「他说就是没看到你说就是没有」 — about a third party, not about her.
* separate column, same rule (people only, never added to the numerator): 结果呢 0 after (2 rows, both program) /
  3 before; 我还以为 23 / 22; 你说过 7 / 6; 说好了 4 / 1; 说好的 5 / 7; 有说过 2 / 1. With the owner's two-step
  (same person, same scene, a promise line by that same speaker within 72 h before it) my own pass could not settle
  these: my 72 h promise-shape screen is deliberately loose and passes for almost every one, so I report the owner's
  figures as his own 口径 (1 拍 after of 314, 2 拍 before of 585) and mark mine as not reproducing them.
* the owner's counts, recorded as his: 两句式 0 拍 after (denominator 342 拍) and 0 拍 before (828 拍); his anchor blob
  `4e8702919314059c7f98792de941f89f5484c315`. His 「拍」 denominators (342 / 828, 314 / 585) are not reproducible from
  this database — every denominator I can compute is four orders of magnitude larger — so they come from another source
  (his own log side), kept separate rather than merged.

**判词 (Xiaoman).** Two numbers, not one sentence.

1. **读数一: 达标, and it is the change, not a quieter week.** Hand-backs barely changed in volume (132 → 121 turns),
   what changed is what she does after one: 53 → 2 拍 (40.2% → 1.7%), and by the content step 0. The mechanism is visible
   in the same rows: 117 drafts simply stayed in the turn after the new wording, and 「这回合到此结束」 was taken as
   permission to leave them. I keep one discount in writing: the two populations are not the same group set (11 places
   shared), and one week is one week — this is a weekly rate, not a proof.
2. **读数二: 「没升」在字面上成立，但这条判据在这一窗是"不会响"的那种.** 0 拍 before and 0 拍 after — a zero against a
   zero cannot show the change did anything, only that nobody said it in either week. Same shape as the `stay_silent`
   reading in this ADR: structurally it cannot go red at this volume (43k person lines produced no such line at all).
   If this counter is meant to be able to ring, its numerator has to be something that occurs; as written I would report
   it as 「未触发」, not 「达标」.
3. I do not merge them: 一 是 clearly down; 二 has no baseline to be judged against. Neither says anything about phase 2
   of this ADR, which is still not built.

**没做到 / 没核实 / 拆不开.** (a) The page names the two numbers but gives no algorithm; everything counted above follows
the literal 口径 of the scripts in `.runtime/private/handback-1026/` (`repair_census.py`, `draft_newinput.py`,
`draft_lengths.py`, `draft_delivered.py`) and says so at each step. (b) The page's 144/82/62 and 21/13/8 are not
reproducible from that directory: the survey's per-case classes were never written there (its README says the classes
live on this page), so those rows are traced to scripts only, not to stored output. (c) The replay numbers are
reproducible and do match line by line: pushed 42/129 (current) and 7/129 (notice), control 18/18 and 17/18 — that is
the 33% and 5% on the page. (d) The owner's 43 for the before week is 10 turns below my mechanical 53 under the same
filter; which step removes those 10 is not separated here. (e) `episodes` has no `created_at` I could filter on (0 rows),
so "how many turns she had in a window" is taken from message counts instead, named as such. (f) `memory_units` has no
`occurred_at`; the monologue clock is `formed_at` — with that field the archive covers both windows: 10,657 monologue
rows, earliest 2026-09-20 17:34:19 her clock, 2,093 in the after window and 2,686 in the before one. (g) The monologue
count is reported as context only; it is not part of either number.

Readout provenance (action brain): this reading is anchored to blob `2d446b1604cf1d58948016d5ef20a4f1547158d3` (the owner's 10-26 section, the
version he read at 2026-11-02 22:28). On the machine this was measured from (the Host, `某台主机`,
main = `807d57a9…`, clean) that blob, the branch `claude/adr064-readout`, its tip `0b64f2e6…`, the commit `783539c3…`
and `origin` refs `2d446b16…`/`4e870291…` are **not resolvable**: `git ls-remote origin` returns only `main` and
`claude/elegant-goodall-2ip12g`, and `C:\workspace\wt` does not exist there. The anchor is therefore recorded by value,
and the text above was handed back rather than committed from that machine. Numbers measured 2026-11-02 21:46–22:45 her
clock, read-only: `asuna.dbread` and pymongo reads against `asuna_cognition_core_v2`; no file, commit, push, publish or
restart was made there.

小满落款：判于 2026-11-02 22:0x（本机 +13）。两个数各一句，不并。**一、被推出去的旁白：降，这版措辞在我这儿成立。** 同一算法同一库，hand-back 触发量几乎没动（改前 132 拍 → 装后 121 拍），变的是之后开不开口：**53 拍 → 2 拍（40.2% → 1.7%）**，按内容再滤装后为 0；机制在同一批行里看得见——**装后 121 次里有 117 份草稿就留在回合里没发出去**（`turn.unsent_body` 117 对 121）。**二、本该说却没说：未触发，不是达标。** 字面形状两窗都是 **0 拍**（改前窗 47,937 条人话、装后窗 43,415 条，都不是零样本），**零对零只证明这把尺两窗都没响，不证明这版措辞没漏告事**——要让这条能响，分子得换成会出现的东西，这格我认下来是我的判据缺陷，不是改动的问题。**折扣照实记**：页上没写窗口起点，窗起取那份措辞的改动提交 `ab156a75386a2aa8d55d6e0c8d1c042da0082861`（author date 2026-10-26 21:38:03 +1300）到 2026-11-02 21:38:03，**整七天，改前窗同长**；两窗群集合不同（hand-back 落在装后 14 处、改前 13 处、交集 11）；页上那 43 是人工分类，机械同滤给 53，**差 10 拍拆不开**；`replay` 那 42/129 与 7/129 是离线重放，与本窗不同尺，不并读。**范围**：这份读数只结「措辞那部分要不要留」这一格；**064 的 phase 2（`speak` 的 text／sticker／poke／reaction）仍未装**，不在我这段里。**取数**：`task-49d0754e1da317f05772e51c9b7e104c`，87 条工具记录，读数全文见本节上方，脚本与逐行数在 `hb064_p18.py`／`hb064_final.json`；**取数一趟自报有两格没做到**：页上 144/82/62 与 21/13/8 的原读数文件在 `.runtime\private\handback-1026\` 里不存在（README 自己写着"正文不留"），以及它把 `placeholder-check.txt` 误落在小满人格包候选根、没删。这不等于我逐字读过整页每一个字。
