# CHANGELOG

## v1.2（2026-11-13 加「tag 页读法」一节：夜里实测的接口字面照抄）

- SKILL.md 新增一节「## tag 页读法」，四条字面全部来自当晚实测：`m.lofter.com/tag/<tag>` 302 → `https://www.lofter.com/front/blog/tag/<tag>`，那一页是服务端渲染，正文数据在 `window.__initialize_data__.tagInfoData`（`postList[].postView` 有 title／tagList／publishTime／digest／permalink，`postList[].blogInfo` 有 blogNickName／blogName；`type=1` 是文章）；`digest` 去标签就是列表里可见的开头；老 `www.lofter.com/tag/<tag>` 只有模板没有数据、`api.lofter.com` 除 `postCollection.api` 以外试过的 22 个文件名全 404、DWR `plaincall` 回 `SecurityException: Batch IDs...`；核对正文用 `https://<blogName>.lofter.com/post/<permalink>`。端点与字段名照交代原样抄，没添没补。
- 两处指路（不是接口事实，我的措辞）：frontmatter description 末尾加一句 tag 页读法（302 之后的 front/blog/tag 服务端渲染页与数据位置）；「什么时候读这一份」加一条指向本节。
- 「## 已验端点」那一节一字未动：tag 页是页面不是端点，`loginCheck.do` 与 `postCollection.api` 两行原样留着。
- 脚本 `lofter_auto.py` 未动，正文也没写成「脚本能读 tag 页」：还没有那个子命令。
- check_skill.py 按本技能自己的形状加（这份断言族同样只有 SECTIONS 存在性＋MUST 针＋LF／手机号／裸数字／cookie 形状扫描，没有 DESC_MUST_SAY）：SECTIONS 加 `'## tag 页读法'`，MUST 加三针（302 那一行、`window.__initialize_data__.tagInfoData`、`https://<blogName>.lofter.com/post/<permalink>`）。
- 自检真跑：改前 46/46 通过 rc 0；改后 50/50 通过 rc 0。反证两趟各自恰好红在对应那一格（拆小标题→`section:## tag 页读法`；换数据位置字面→`must:tag_page_data`，各 rc 1），改回后字节一致。技能头另过了一遍程序自己的 `asuna.skills.problems`（无问题）。

## v1.1（2026-11-03）

- 采纳想法 idea-3fead70d 四小格按口径搬到本技能（老技能正文与 CHANGELOG 本次不动）：① 自检格数按本技能实数写：check_skill.py 由 44 格增到 46 格（新增两格钉「谁读账号文件」「键名错时静默回退」），现跑 46/46；② 正文「账号事实」段写明只有 lofter_auto.py 读 lofter-account.txt，老技能里只有 check_skill.py 读，三支探针不读；③ lofter_auto.py 打印时 blogName／blogId／blogdomain 一直只露首末两位，这次核过没有漏的；④ 「文件在但键名错」的实况写进正文，脚本在这种情况下打 WARN 行（用错键名的临时文件真跑过一次，WARN 出现、回退到 blogName、collections 仍通）。

## v1（2026-11-03 新建）

- 新建「账号自治站点」技能：LOFTER。形状是金主定的：cookie（登录态）自动写、脚本自动执行取数据。
- 原料：流水 11-02／11-03 登录实测节（端点与坑）与现有技能 asuna-lofter-login；重登流程和四把投票直接复用那份（captcha_stage_a.py 是原样拷贝，SHA 前缀 ac1408538233）。
- 脚本 lofter_auto.py：status／ensure／login／collections。真跑过：老格式导入→探活 200→回写 lofter_login.json→getCollectionList 通（list len=0）；强制 login 跑到「4071→取图→四把投票」，两张图都凑不出一致按设计停（退出码 6）。没跑通：check→带票据登录→回写。
- 试过 DWR PostBean.getPosts 读帖子，回 HTTP 501，已从脚本里去掉，记在正文未核实。
