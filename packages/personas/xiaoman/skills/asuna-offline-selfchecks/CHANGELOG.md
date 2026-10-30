# CHANGELOG · asuna-offline-selfchecks

- 10-30：从正文剥离来历叙述约 30 处（摘要：删「版本」「试用记录」两大节；删「判据补遗」里 (e)（常设判据来路措辞的订正，整条是历史）、(f) 的四个当日样本、(g)(h) 的「实证」；删「候选根」里 10-20／10-22 混进脚本的来路段、「查语法」里的 10-15／10-18 换法清单、「EFFECTIVE_PROJECT_CHANGED」里的 10-24 实证与 napcat 例子、私密词节里的 10-13／10-14／10-23／10-24 日期与「主人交代点名」；其余各处只去日期、提交号、「我自己又踩过的」之类，动作与边界未动；「判据补遗」标题去掉「2026-10-24 并版：八条」）。
- 10-30：`check_skill.py` 同步删 4 条钉来历文字的断言（section_4「## 版本」、section_5「## 试用记录」、rule_provenance_package_sha「7f54dbd2af14」、pin_e_provenance_wording——钉 (e) 的新旧措辞）；另从 prepublish_private_word_criterion 的关键串里去掉「定成常设判据，以后照这条自己走」（来路原话）；BACKLOG_TITLE 同步改成「## 判据补遗」；检查条数 49→45，全绿（NOTE 两行：名单条目 87 对基线 69、envoy 命中 12 对基线 11，是脚本里既有基线与现状的差，不是这次改动造成）。
- 10-25：加守卫 `guard_effective_project_changed`；「处置」一节里按行号写的定位改成按函数名写。自检 48→49。
- 10-24（并版）：新节「判据补遗」八条 (a)–(h)，各一个钉；自检补内容级私密词扫描三格（`leak_scan_ran`／`no_listed_words`／`no_listed_words_outside_envoy`）。订正两处前提：写 (d) 时以为发布闸不扫内容，实际 `publicationFindings` 会扫本次改动的文件；交代里 `floor.js:201-209` 在当时装着的那份里是构造函数几行，选根逻辑在 `effective`／`skillPaths`／`persona`，(a) 改按名字写。当日样本：数据库等值匹配「全库 0 行」换 `$regex` 是 100 行；`event.raw.asuna_media.items[].type` 元素级有、全库 markdown 98 条；写进流水的两个 sha 是报告交回前自己配的形近数，`artifacts` 24,442 条工具记录 0 命中；一份报告正文写 Asia/Shanghai 而它自己的表写 Auckland。自检 37→48。
- 10-23（v2.9）：新增「发布前自检（私密词扫描）」一节——主人 10-14 拍下的常设判据，压了九天才落文件；三岔写死，判据按类别＋文件名写、不按名单序号。自检加 `prepublish_private_word_criterion`，36→37。
- 10-22（v2.8）：新增「候选根：临时脚本落点与包内容判据」一节。来路：10-20 发布清单混进 `.tmp/scan_oldname_rejects.py`、10-22 17:32 又混进 `_tmp_check_runner.py`，第二回是主人看见 `changed_files` 后另花一趟发布清的；实测两笔包 sha 相同（`7f54dbd2af14`）、`.tgz` 里根本没有那个脚本，脏的是回执那一格不是包。自检 28→36。
- 10-18（v2.7）：编译那一格换成内存 `compile(源码, 路径, 'exec')`，因为 `py_compile` 写 `.pyc` 在行动脑沙箱里写不动、只能报「没真查」。八份 `check_skill.py` 里七份同轮删掉不再适用的探针格（本技能 29→28）；`compiles_<脚本>` 名字不动。
- 10-15（v2.2–v2.6）：`check_skill.py` 加 `line_endings_are_lf`（读字节数 CR）；六份 `check_skill.py` 开头统一固定 UTF-8 输出（cp1252 实测改前全 rc=1）；增量加「cp1252 下也要能跑」「查换行必须读字节」；编译临时目录兜底（后于 10-18 废）；`integration/` 三份补 UTF-8 守卫。
- 10-12（v2.1）：清死引用——`tests/p3_schedule_cases.py`、`tools/p3_offline_check.py` 随 `9d3ed60e` 删除，改写现行跑法（`test_schedule_rules.py` 实跑 13/13）；记下 pytest 默认不收 `*_cases.py`（`pyproject.toml` 只有 `testpaths`，全 113 份 `test_*.py` 没一处调 `run_all()`）；`read_image_offline_check.py`、`linked_scenes_offline_check.py` 随 `83f17beb` 删除，补「引用之前先 Test-Path」。
- 10-05（v2）：压缩，通用规则与核心技能重复的部分删掉并指向它，只留增量；新增 `check_skill.py`。
- 10-02（v1.1／v1.2）：补 ADR-008 项目归属；摘掉已退役的 `p5b_ui_offline_check.py`，新增退役一节。
- 09-24（v1）：首次记录，命令与结论来自当次实跑（P3 夹具缺 `self_state` 的红点与修法等，原试用记录已随本次剥离删除；其中 10-02 首次记录时 P5 14/19、P3 33/38 的红是夹具替身缺字段，后来不复现）。
