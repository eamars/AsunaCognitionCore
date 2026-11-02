# ADR-094 progress

## §10.1 after install: the broken shapes are gone (by-line split not done)

小满落款：判于 2026-11-02 22:2x（本机 +13）。**主格成立：回合末压缩那两个坏了的形状归零。** 装机 10-25 19:48:45 NZDT（UTC 06:48:45）起到日志末尾约 7.1 天（页上说的是"约两天后再数一遍"，我取了更长）。**装前** 56 次回合末：压 31、busy 22、stopped 3；**装后** 126 次：压 125、busy 0、stopped 0，**唯一没压成的是 11-01 10:42Z 那次 `manual compaction could not produce a smaller summary`**。**重复压没有**：装后 116 个间隔里 10 分钟内 0 个，最短 19 分钟（都在 10-28／29 同一会话）。**页上那句要求 by line 分表（agent-line 6／home 2／groups 1）我没做出来**——`host.log` 里没有场景名，得走 `episodes.native_session_id` 映射；"过了阈值却没有回合末记录"那种漏压也从日志数不出来。**这两格按 11-02 金主定的新规矩挂在我自己的账上，不该压着这份 ADR 关单。** 取数 `task-e108985aa1095eb5bc747357b2626b42`。这不等于我逐字读过整页每一个字。
