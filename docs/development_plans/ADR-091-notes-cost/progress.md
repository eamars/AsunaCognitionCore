# ADR-091 progress

## D3 reading: blocked on a field that was never built

小满落款：判于 2026-11-02 22:1x（本机 +13）。**D3 那把尺我读不出来——不是数据不够，是要测的量没实现。** 页上 §8 D3 要的是"便条开的那一拍占字符脑忙碌时间的份额"（模型时间＝各步时长之和），**>12% 就把规则 2 请回来**；可库里没有步时长字段：`turn.output` 不带时长，`tool.time` 只记工具耗时，**所以 12% 这条在现行库上永远算不出**。能算的只有旁边那列标注：便条开的回合 163/2,833＝**5.8%**（10-22→10-29）、131/2,563＝**5.1%**（10-26→11-02），**这不配跟 12% 比**。页上点到的 `memory_units.supersede`／`w6` 各 0 行（`w6` 实际在 `memory_fires.kind`，71 行）；`note.sent` 926 行里 `payload.text` 0 行，全文在 `role_tool` 的 `args.text`（`tool=note` 的 1,024 行里有）。**判：等实现。** 索引那行别写"欠小满读数"，写"等步时长字段"。D1／D2 装没装这趟没查。取数 `task-e108985aa1095eb5bc747357b2626b42`。这不等于我逐字读过整页每一个字。

## D3 read, and the close (2026-11-09)

D3's reading, measured the way §4 measured busy time (the survey's own scripts, structure only: step times from the
character lanes' session files, turns tied to the notes that opened them), on the 7 days to 2026-11-09 12:4x NZDT:
note-opened turns 131, **74.9 of 1,042.3 busy minutes, 7.2%** (7.7% counting from 11-03); the line was 12%. Rule 2
stays as it is (option a). The earlier "no step-duration field exists" was true of the database, not of the session
files the first survey read; the reading only had to be run again. D1 and D2 are on main since `fb4cba37`. Closed.
Evidence: `.runtime/private/notes-survey-1109/` (the scripts and `results.txt`, `results_d3.txt`; 149 KB; the data
they read was deleted after the run).
