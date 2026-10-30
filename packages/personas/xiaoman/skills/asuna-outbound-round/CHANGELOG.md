# CHANGELOG · asuna-outbound-round

- 10-30：从正文剥离来历叙述 4 处（摘要：删「版本」「试用记录」两节；删「这条道上有哪几份技能」节里的「来路」段（27 次 unknown 的那一轮）；删「实判读数（2026-10-22 …）」那句，只留「名单会变，用之前先当它是旧的」；五查、回看、边界、名单与两条规矩未动）。
- 10-30：`check_skill.py` 同步删 6 条钉来历文字的断言（section_4「## 版本」、section_5「## 试用记录」、roster_why_unknown_count「27 次 unknown」、roster_why_invented_names「asuna-turing」、roster_reading_is_measured「实判读数」、selfcheck_documented「正文里出现 check_skill.py」——它只靠版本节那句撑着）；检查条数 56→50，全绿。
- 10-22（v1.2）：`scene_kinds` 从 `[home, group]` 改成 `[home, group, dm]`（别人的私聊一份技能都读不到，而出门那一轮带话在别人私聊里同样要用）；加「这条道上有哪几份技能——别编名字」一节：来路是 10-22 下午一个群那一轮 `skill` 报了 27 次 unknown、其中只有 7 次是真存在的技能，其余在编名字。名单是按在跑的 deployment 实判的：dm 改前 0 份→改后 1 份；群 6 份不变；家里 12 份不变（dm 那格是合成配对，不全是真样本）。自检判据 38→55。
- 10-16（v1.1，只改自检）：泄露检查名单定位加兜底；名单配不上记红 `leak_scan_ran`。
- 10-08（v1）：首次固化，内容是出门轮里反复练出来的同一套错与改法，剥掉具体的人和群；附零依赖自检。首跑曾红在 `compiles_check_skill.py`（沙箱拒写系统 Temp 与点开头目录，编译临时目录改落技能目录旁）。
