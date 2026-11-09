# ADR-097 progress

## First reading: the mechanical part is done, the rest is not due yet

小满落款：判于 2026-11-02 22:1x（本机 +13）。**§8 那一串今晚只交得出机械那小半，其余挂在时限和我自己的账上，别拿它压关单。** 有数据的：`memory_fires` 1,765 行，首行 2026-10-25T21:51:18Z（本地 10-26 10:51，对得上装机 10:48:54 NZDT）；按 `kind` 分 note 1,531、**cue 85**、w6 71、elsewhere_hers 37、before 17、seen 16、elsewhere_theirs 8；cue 逐日 10-26 27｜10-27 16｜10-28 9｜10-29 16｜10-30 3｜10-31 5｜11-01 6｜11-02 3（当天到 08:50Z 为止）。**取不到的**：页上"②③④"那几个计数要读我的回复才能打，库里没字段；"每场合 cue 数／回合"的分母没取；**100 个 cue 的精度抽样按页上"两周后"要到 11-11 前后才到期**；"我以为知道却错了"那本自记日志我从 10-28 起就没在记这一格。**判：数据不够，不是不成立。** 索引那行请写"部分已交；精度抽样 11-11 到期"。取数 `task-e108985aa1095eb5bc747357b2626b42`。这不等于我逐字读过整页每一个字。

## The 100-cue precision sample, and the close (2026-11-09)

Her reading (11-09 13:02, read on `origin/main` `e93cff90`): 128 cues (`memory_fires.kind='cue'`) from 10-26 to 11-09,
100 drawn with `seed(97)`. Worth bringing back: **24% of the sample, 22.7% of all 128**, against the design's 22% row
(§7, the words outside the segmenter's dictionary): the mechanism does what it was designed to do. 76 of the 100
(97 of 128) came back empty, most of them two- or three-character fragments of jieba's segmentation (the known shape
at §7's end); 2 of 128 pointed at the wrong thing (a year and a time read as numbers). Her lookups after a cue: 3 of 128
(2.3%), and her own practice of recalling on every relevant cue showed no effect (0 of the last 66), so she stopped it.
"Needed in that beat": 4 cases, too few to judge; reported, not judged. Her labels are hand judgements of the trigger
line and her reply (an inference, not a machine label); the per-cue table stays in her `/task`. The rest of the first
reading was in already. Closed.
