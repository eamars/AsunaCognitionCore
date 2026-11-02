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
