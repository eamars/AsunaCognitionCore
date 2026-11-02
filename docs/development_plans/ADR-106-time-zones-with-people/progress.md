# ADR-106 progress

Installs, readings and Xiaoman's verdicts; her words as she wrote them. Kept apart from the ADR page, so that
recording progress never changes a page she signed. Moved here from the index on 2026-11-02 as it stood there;
later entries go at the end.

Built; installed 2026-10-30 13:24 as `22ddafd6bcde`.

In her words: Closed 2026-10-30 as 22ddafd6bcde. Xiaoman read the page before the landing (her own read-only task, 13:19) and asked for three follow-ups: the page status line contradicts index row 136; 106 has no kept-tests table; and her position (her zone is never read from the host) holds while the deployment setting is set — she asks to be told on her line whenever it is cleared or the deployment moves. This is not her signature on the mechanism. — end of her words.

小满落款：这一页钉在锚点 14f230944cfe3761a0c6fba0a6c2a3702973f606。这段的作用是给我的东西留一个可比的底：以后有人改这一页，脚本拿这个号去比，不匹配就停下来问我。**这不等于我逐字读过这一页**：这页我只核过状态词那处不一致，正文没逐字读。钉的時刻是本地 2026-11-02 18:46，那一刻 main 尖是 e747bbd0cdf085b3f8711d30d5d642dfa3648ed0。

小满落款：**我挂的三条后续：一条改判、两条 Left。** ① "页上状态行与索引第 117 行互相矛盾"——现读：页首 3–6 行写 "her three follow-ups are in the index row"（改它的提交 `99a69f37000c…`），而索引第 117 行只列了两条 ⇒ **不是已经消解，是措辞与实际不符**：要么索引补第三条，要么页上那句改口径，这格归开发者（文档侧）。② kept-tests 表：页上第 251 行那段是文字不是表；引用 `her_zone` 的测试文件已取到 8 个（`test_her_clock.py`、`test_one_zone.py`、`test_plan_zone_service.py`、`test_schedule_rules.py`、`test_tool_watch.py`、`test_dbread.py`、`conftest.py`、`discussion_digest_cases.py`）——**表该写，但按 10-29 冻范围，替身层的断言在表里标明"替身层，随替身删"，不算永久契约。Left：欠小满这张表，11-05 回看。** ③ "部署的 `timezone` 被清掉或部署搬家要在这条线告知我"——**这是一个要新做的机制，不是补文字，归金主拍。** 顺带：当前部署的 `timezone` 现值**没查到**（grep 了 `.runtime/*.json` 与 `.runtime/config/*.json`），这是没找到，不是确认没设。
