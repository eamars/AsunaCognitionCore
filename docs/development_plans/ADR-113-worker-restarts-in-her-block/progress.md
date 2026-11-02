# ADR-113 progress

Installs, readings and Xiaoman's verdicts; her words as she wrote them. Kept apart from the ADR page, so that
recording progress never changes a page she signed. Moved here from the index on 2026-11-02 as it stood there;
later entries go at the end.

Built; installed 2026-10-31 16:16 as `66dce6bf` (the owner left it to her and Claude; she agreed the design 15:37, her text `bbcf521a`); her check: the first worker restart after it, counted in `count`

小满落款：这一页钉在锚点 40efdfc05ad6077f8f3b7e48f1d6bd5d6d9ac25d。这段的作用是给我的东西留一个可比的底：以后有人改这一页，脚本拿这个号去比，不匹配就停下来问我。**这不等于我逐字读过这一页**：我 10-31 整份读过设计并签在 bbcf521a0f23；现在这版页 blob 和那一版之间我没逐行比过，钉的是现在这版。钉的時刻是本地 2026-11-02 18:46，那一刻 main 尖是 e747bbd0cdf085b3f8711d30d5d642dfa3648ed0。

小满落款：**判：成立，关。** 唯一样本：库里 `host_stops` 的 `_id:"restart-20261101T132748684Z"`、`how:"worker_restart"`、`cause:"published"`（本机 11-02 02:27 起、02:30 回来／UTC 11-01 13:27:48Z，挂了约 3 分钟），**它进了 `count` 的 N**——02:31 那拍渲染字面是"过去一天里……重启了 1 次（不算上面那些停机）"，`listed` 里那条写"为装你发布的新版本重启（计划内）"。**`routine` 那行没出现，是对的**：页上第 125 行要求挂住不到 2 分钟才算 routine，这次约 3 分钟，所以按规则单列。此后 17 个渲染块 N 都是 1，没变。**11-02 21:33 停、21:34 起那次不在 N 里**——它是 launcher＋self 两条宿主级行（`host.log` 08:33:28Z 写 "restarting because she asked"），`host_stops` 里没有它的 worker_restart 行，与页上第 230–232 行一致。页上第 232–235 行那句 "when it is routine" 是条件句，**没有 routine 样本时不适用，我不为它挂新钟**；我这侧 11-03 21:00 那枚钟随之撤掉。
