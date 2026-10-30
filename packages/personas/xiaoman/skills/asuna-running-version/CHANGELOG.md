# CHANGELOG · asuna-running-version

- 10-30：从正文剥离来历叙述 17 处（摘要：删「版本」「试用记录」两节；去掉「问过八回」「10-15 白改期」「10-15 判错一次」「Claude 10-20 给的」「10-20 实测 sha 对照」「主人 10-20 交代」「10-25 现场凭据与任务号」「今天实测…落后 1 笔」「asuna-launch 90-105 活样本」等；第三节的 116 个文件计数换成只留「三个文件不算差异」；判据、位置、读法、退出码未动）。
- 10-30：`check_skill.py` 同步删 4 条钉来历文字的断言（section_11「## 版本」、section_12「## 试用记录」、criterion_diverged_misread「读成没装」、selfcheck_documented「正文里出现 check_skill.py」）；检查条数 61→57，全绿。
- 10-25（v1.5）：改写第五节 `loaded.packages` 那一格——监工起包名只来自 `installed`、digest 由选择覆盖，报的是在跑的那一档；补「在不在跑仍只认 `active.<项目>.sha256` ＋ 运行时那份文件」和「`loaded.commit` 是启动那一刻的 HEAD」；「选择覆盖 digest」只在夹具里证实过，真文件上两边 sha 相同、是空转，不算现场验过。新增「过期选择的形状要自己算」一条：当晚 19:48:45 那次起来，`loaded.packages` 正好 7 项、无 `@asuna/dsh-peer`、无 frozen 目录名拼出的假包，`selections` 里 `dsh-peer` 仍 `ACTIVE`（凭据 `task-3e7a12804f475d9d17b323e708d0db03`，拿真文件跑 `loaded()`，父版本 9 项、差集正好那两条）。
- 10-21（v1.4）：第五节加「按内容判活包」——`version_probe.py` 加 --package／--file／--needle，输出三行读数，退出码 0／1／3；自检加五条字面判据＋一条「探针里真有这一步」。
- 10-20（v1.3）：第四节补一条已核实的事实：发布不刷新 `node_modules/@asuna/xiaoman`，人格路径按选中那一版的 `packageRoot` 解析（Claude 10-20 02:18 给的，当天核过；选中版 frozen 里 image-generation 的 SKILL.md 前缀 `e9daf9bb`，`node_modules` 那份是旧的 `ad006104`）。
- 10-16（v1.2，只改自检）：泄露检查名单定位加兜底；名单配不上记红 `leak_scan_ran`。
- 10-15（v1.1）：`version_probe.py` 固定 UTF-8 输出；自检加 `line_endings_are_lf`（读字节数 CR，要在冻结快照上跑）；锚点从「文件＋行号」改成「文件＋名字」，行号锚点判红（当天 asuna-launch.mjs 90-105 实际在 91-106）。
- 10-15（v1）：首次固化。判据全是 10-15 一天撞三回得来的（含把 `diverged` 读成「没装」、上午白改一次闹钟）；当时实测：`src/asuna` 与在跑那份可比文件 116 个、内容不同 0 个；检出 HEAD 落后 `origin/main` 1 笔、工作区 2 个未提交文件。附零依赖探针与自检。
