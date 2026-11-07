# ADR-082 progress

小满落款：**§9 触发（窗 10-19 06:16Z 起，群 external 回合 1,510，≥300；页上写的是 300 个群回合，不是"群外"）。条 2、3 成立；条 1 按页上字面成立。** 每 100 群回合的 committed 群写入：全层全回合 **3.05**（46/1,510）、全层只 external **2.19**、只 person 层全回合 **0.86**、只 person 层只 external **0.53**——门槛 0.85，**页上没写按哪些层、哪些回合种类算，这是页上的缺口**。我按字面（不限层、不限回合种类）签"过"，同时把最严那格 0.53 不过如实记在这里，免得下次的我只看见 3.05。条 2：person 层写别人的 4 条、visit 回合上 7 条。条 3：群里没有任何带 understanding 码的 `FAILED_RUNTIME`。**Left：欠小满三格（每天几条 entry／几条带 short；person short 正文那一格；"写入后被本人更正"那格要读她群里的话、需她同意），11-06 回看。**

小满落款：082 三格读数（11-06 21:14 交回，取法正本 `/task/adr082_108_cells/正本_ADR082三格_ADR108留测表_2026-11-06.md`，sha256 `79fae759a799a59be143ad3e54f0022f980b94fecf26291a7b43f60e60a5ebe5`；只读趟 `task-1f37d465a75350b6871f775ce6e38389`，79 条工具记录；页 blob `adf74d1643e118a039eda852f63f11f18cf3c561`）。窗口取页上三个装机锚点里最宽那条 `2026-10-19T06:15:00Z`（本地 19:15:00 NZDT）到本地 11-06 21:00 不含；现读配对 `dbread.now()`=2026-11-06 21:01 ↔ utc `2026-11-06T08:01:44.912135+00:00`，`tzname` 为 New Zealand、`tm_isdst=1`。三个锚点那一分半对本格无影响：最早一条记录在 06:20:40Z。

格一，判达标：`state_revisions` 里 `entity_key` 前缀 `relationship:` 的修订 78 条，78 条带 `short`（100%）；每天中位 5 条、最多 9 条（10-25），11-02、11-05 两天 0 条（`dbread.count` 复核零行）。分层 person 30／here 48；分场合 external×group 42、external×dm 20、visit×group 7、task_feedback×group 6、×dm 3。旁证 `audit_events type=understanding.result` 同窗 78、`payload.state` 全 COMMITTED——但 payload 里没有 `short` 键，所以"带 short"只有 `state_revisions.content` 这一把尺能数，两个 78 不是两次独立验证。读法说明白：short 100% 只证明每次都填了这个字段，不证明短句有用；页上真在问的那件事这一格答不了。

格二：页 L275／L285-287 的 M5 定义（person short 含那人 here 层那个群的群名，或与 here 正文有 ≥6 字连续相同的一段）。两把我按页上字面自己算（`cell2b_m5_fixed.py`；第一版 LCS 写错、30 条全成 1，改完自测三条再重算）：群名命中 0/30，≥6 字公共段命中 25/30（分布 0:1,3:1,4:1,5:2,6:4,7:4,8:1,9:4,10:1,11:3,13:7,14:1）。我判这把尺分不动"漏出去"和"正常引用"——short 的任务就是把在这里发生的事压成一句，跟 here 正文撞一段连续字是它的功能不是泄漏；25/30 我不签成"M5 命中率高"，只签"这把尺测不出我要的东西"，真能分辨的是群名那一半，命中 0。

另一格更要报：页 L125-126 那组基线 `median 46, max 93, 4 of 290 over`（80 字）对不上现场。本窗 person 层 short min 24／中位 84／max 127／18 of 30 超 80；here 层中位 67、5/48 超 80；现行 head：person 6 个中位 77、超 80 两条、缺字段 1；here 28 个头里 17 个有 short、中位 59、超 80 两条、缺字段 11。中位从 46 到 84、超 80 从 1.4% 到 60%：要么页上那组基线该标测量日期，要么 80 字那道口子已经名存实亡（over 80 只报字数不拒是真、飘长也是真）。哪边改我不替她判，先报数。

格三，未验，库里没那把尺：`dbread.fields` 扫 `state_revisions/state_heads/audit_events/episodes/messages/ideas/notes`，含 correct 字样的字段只落在 `memory_units`（`attribution.corrections`、`corrected_at`、`corrected_by`，由 `summary_attribution.py:121-145` 写，全库非空 119 条，作用在摘要不是 understanding 修订）；`content` 只许 `body/short`（`records/heads.py:156`）；`change_class` 无此档（78 行全 `interpretation`）；`audit_events` 里带 correct 的只有 `author.corrected` 全库 1 条（ADR-089 那趟一次性回执）。要出数得把每条写和之后同场景那人的话对起来，那一步要读群里的原话，未得许可没读。页 L304 说清单住 `.runtime/private/adr082/corrections.md`：目录在、16 个文件，没有那个文件（只查存在，内容没读）。Left：等大姐许可或她改判据，再读群线原话坐实；回看 11-08 20:30。

格三, 「写入后被本人更正」, read 2026-11-07 by Claude as §9 sets it (her consent of 2026-10-20; a fresh agent read the
people's own lines only, nothing of hers but the written layers). Window 10-19 06:15Z to 11-06 08:00Z: 78 writes (30
person, 48 here). **Read: 63, of them 6 then corrected by the person** (1 person, 5 here; one correction of a form of
address covers 3 of them). Not read, so not counted either way: 5 about someone who said nothing in that conversation
in the window, and 10 about an agent line, only searched (about 950 lines) for corrections, none found; a search that
finds nothing is not a read (her correction, 11-07). Corrections made before a write and not taken up: 1 clear, 1 borderline; not
common, so the read was not widened. Each corrected write, with person, layer, date and line, and the borderline
cases, is in `.runtime/private/adr082/corrections.md` (4,704 bytes, private). A lower bound on wrong writes, not an
accuracy.

Her check of 格三, 2026-11-07 13:00: the 17 writes the private list names are all in her records (layer and person
right, +7 to +57 seconds), and the 6 lines cited are the person's own, after the write. Two limits of the read, kept
as limits (the page's rule: not widened when not common): a write's window closes at her next write about the same
person in any layer, so 3 of the 5 not judged had the person speaking in that conversation; and the list gives a row
with its line only for the 6 corrected, the 10 searched and the 5 not judged are one paragraph each. Her lesson, in
her words of the same message: without the person's own line, 「你认可／这是你的属性／这是你发的」 are written as a
guess. Closed 2026-11-07: every cell read, her verdicts in, nothing left.
