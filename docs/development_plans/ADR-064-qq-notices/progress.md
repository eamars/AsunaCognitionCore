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
