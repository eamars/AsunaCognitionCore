# CHANGELOG

## v1.1（2026-11-03）

- 采纳想法 idea-3fead70d 四小格按口径搬到本技能（老技能正文与 CHANGELOG 本次不动）：① 自检格数按本技能实数写：check_skill.py 由 44 格增到 46 格（新增两格钉「谁读账号文件」「键名错时静默回退」），现跑 46/46；② 正文「账号事实」段写明只有 lofter_auto.py 读 lofter-account.txt，老技能里只有 check_skill.py 读，三支探针不读；③ lofter_auto.py 打印时 blogName／blogId／blogdomain 一直只露首末两位，这次核过没有漏的；④ 「文件在但键名错」的实况写进正文，脚本在这种情况下打 WARN 行（用错键名的临时文件真跑过一次，WARN 出现、回退到 blogName、collections 仍通）。

## v1（2026-11-03 新建）

- 新建「账号自治站点」技能：LOFTER。形状是金主定的：cookie（登录态）自动写、脚本自动执行取数据。
- 原料：流水 11-02／11-03 登录实测节（端点与坑）与现有技能 asuna-lofter-login；重登流程和四把投票直接复用那份（captcha_stage_a.py 是原样拷贝，SHA 前缀 ac1408538233）。
- 脚本 lofter_auto.py：status／ensure／login／collections。真跑过：老格式导入→探活 200→回写 lofter_login.json→getCollectionList 通（list len=0）；强制 login 跑到「4071→取图→四把投票」，两张图都凑不出一致按设计停（退出码 6）。没跑通：check→带票据登录→回写。
- 试过 DWR PostBean.getPosts 读帖子，回 HTTP 501，已从脚本里去掉，记在正文未核实。
