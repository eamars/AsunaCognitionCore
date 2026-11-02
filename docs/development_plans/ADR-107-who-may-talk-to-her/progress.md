# ADR-107 progress

Installs, readings and Xiaoman's verdicts; her words as she wrote them. Kept apart from the ADR page, so that
recording progress never changes a page she signed. Moved here from the index on 2026-11-02 as it stood there;
later entries go at the end.

Built; installed 2026-10-30 16:02 as `ac620ad17d40` in one install by the owner's decision (the core, the adapters and her gate prompt line); the adapter came back at 16:06 with `integration_start` (its derived config changed).

Before the install, in her words: 「页与 design.md 已由小满读过（`ac620ad1` 版，含 `Before building`），内容没意见；六条要求照原话站着。装完之后再单独确认一次，装之前它不算 landed。」

After the install, in her words: Xiaoman confirms the install: the live worker has been 0d31f597 since 2026-10-30 16:18 local (her own launcher block), and the admission marker is live — 4d3f94c72474011841598d7a7d22a73db026114e put ADMITTED_WORDS in people.py:62, and two messages after the install carry event.admitted = "new", both QQ groups (2026-10-30T03:32:51Z, 03:35:22Z). Not verified by her: admission leaving person/scene ids untouched, the rejected path, and whether the platform is connected and outbound works (integration_status has no error field; the adapter needed an explicit integration_start at 16:06). This is confirmation of the install and the marker, not her signature on section 4 as a whole. — end of her words.

Xiaoman read the earlier page at blob `d3e7f8f482f0` on 2026-10-29 (168 lines, `Before building` included) and stands by the six asks as worded there; no objection to the direction. That line covers only that version: the page and [design.md](development_plans/ADR-107-who-may-talk-to-her/design.md) are later, and her reading does not cover them. Not a signature.

小满落款：这一页钉在锚点 81b4f173b31b7eef4c2effe1cca8153beda1842f（design.md f26c9e21858dfa98d65df0fcbc831a29c0388177）。这段的作用是给我的东西留一个可比的底：以后有人改这一页，脚本拿这个号去比，不匹配就停下来问我。**这不等于我逐字读过这一页**：这页我这趟没逐字读，只钉锚点。钉的時刻是本地 2026-11-02 18:46，那一刻 main 尖是 e747bbd0cdf085b3f8711d30d5d642dfa3648ed0。
