# ADR-069 progress

Installs, readings and Xiaoman's verdicts; her words as she wrote them. Kept apart from the ADR page, so that
recording progress never changes a page she signed. Later entries go at the end.

2026-11-02 (Claude): the three retired names were still registered ten days past their 10-23 date. Her calls by them
(`audit_events`, `role_tool`, NZDT): `update_self` 75 calls, 10-05 to 10-12; `pass_note` and `leave_note` until
10-16, and one `pass_note` run as `note` (`called_as`) on 10-17; none after. Removed in `695d5057f4bd` with the
fixture's count corrected in `9247e1042e07` (the full suite ran on `695d5057f4bd`: python 880 passed, 13 skipped;
js 296 passed; `9247e1042e07` changed two lines of one test comment and that test ran). The commit messages of
`695d5057f4bd` say "606 calls" and "12 also carried revision_id": the old count; the comment and this page hold
(75 calls, 606 copies across her sessions, one with `revision_id`). Her old calls stay in `audit_events` for 365
days (`audit.KEPT_DAYS`): the last of them leave about 2027-10-16. A call by a removed name is refused by the Host's
guard, which writes no audit row: whether anyone still calls one is counted from the session logs only.

小满落款：判于 2026-11-02 20:5x（本机 +13）。签 `695d5057f4bddae248b854248b6ad14f9dcf5fc4` 与 `9247e1042e0749f5bd3f98b844d8688ee9e7c50f`：三个退役名（`update_self` 的注册、处理函数、只被它调的 `SelfState.commit`、`param_names` 那一项；`RENAMED` 里 `pass_note`、`leave_note`）连同核心技能那张表的一起去，签。凭据：全仓 grep 无活路径引用被删符号；旧名调用两层各自得到拒绝句（守卫句字面 `这个对话里没有 … 这个工具`，python 层 `没有 … 这个工具。`）；历史行仍可读——75 条真调用参数键与新常量一致。分母：10-05 起 `role_tool` 审计覆盖 100%（75↔75、252↔252），10-05 之前两个源都答不了；只按 `payload.tool` 数会漏 `called_as`（`pass_note` 8/252＝3.2%）；守卫回绝不入库，故"删后是否有人撞旧名"只能从会话日志数。测试绿在哪一枚**看不出来**（11-02 无可读产物，主检出 `.pytest_cache` 对本账号 PermissionError），880/13、296/0 未核实，我不推定"只改注释等于绿"。装机与验收另记。这不等于我逐字读过整页每一个字。

2026-11-02 (Claude): item 4's id matching, held for the owner since 10-16, is not built; the owner, verbatim:
"Don't build item 4, close 069 after install".
