# CHANGELOG

## v1（2026-11-03 新建）

- 新建「账号自治站点」技能：LOFTER。形状是金主定的：cookie（登录态）自动写、脚本自动执行取数据。
- 原料：流水 11-02／11-03 登录实测节（端点与坑）与现有技能 asuna-lofter-login；重登流程和四把投票直接复用那份（captcha_stage_a.py 是原样拷贝，SHA 前缀 ac1408538233）。
- 脚本 lofter_auto.py：status／ensure／login／collections。真跑过：老格式导入→探活 200→回写 lofter_login.json→getCollectionList 通（list len=0）；强制 login 跑到「4071→取图→四把投票」，两张图都凑不出一致按设计停（退出码 6）。没跑通：check→带票据登录→回写。
- 试过 DWR PostBean.getPosts 读帖子，回 HTTP 501，已从脚本里去掉，记在正文未核实。
