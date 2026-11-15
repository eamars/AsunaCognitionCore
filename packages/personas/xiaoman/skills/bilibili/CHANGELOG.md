# CHANGELOG

## v1.3（2026-11-15 脚本补上 `search` 子命令：搜索这一路从「每次现写」变成「一条子命令」）

- `bili_auto.py` 新增 `search`：`search KW --from D --to D [--order pubdate|click] [--limit 20]`。会话与签名全部沿用文件里已有的 `ensure_login`／`wbi_keys`／`mixin_key`／`wbi_sign`／`get_json`／`code_text`／`site_ts`，没另起一套；新增只有 `strip_tags()`（剔标题高亮标记）、`local_ts()`、`date_to_epoch()`（本机钟面日期→epoch 秒，接口不吃日期串）。每条打 `bvid｜标题｜UP主｜时长｜播放｜pubdate`，pubdate 本机钟面与站点侧 UTC+8 同行都打。脚本来历：11-14 深夜主人在那条线找牧羊犬视频，同一份 `bili_search.py` 现写了第四次才跑通——缺的从来不是接口口径（正文早就写着），是脚本入口。
- **窗口口径**：`--from/--to` 按**本机钟面**换算（`strptime(...).timestamp()`）。这台不在 UTC+8，本机相对 UTC 的偏移还随日期变（同一趟实测窗口起端比站点侧早 4 小时、止端早 5 小时），所以脚本不背常数：每次把窗口两端按本机钟面和站点侧 UTC+8 各打一行。要「站点侧那两天」得自己反推。
- **实测**（keyword=牧羊犬，窗口本机 07-17 00:00 ～ 11-14 23:59）：`order=pubdate` 默认 20 条（1 页）、`order=click --limit 5`（1 页，头两条播放量 2,629,894／1,952,980）、`--limit 40`（站点一页返满 40 条，只请求 1 页）、`--limit 60`（2 页、60 条、bvid 全不重复）。四次都 HTTP 200 code=0、退出码 0。
- **撞出来的一条真 bug**：`--limit 60` 首版把第 2 页的 `page_size` 换成剩余条数，站点按 page × page_size 偏移返第 11~20 条 → 60 条里 10 条重复 bvid（字面读数：条=60 唯一=50）。改成 `page_size` 跨页固定 `min(50, limit)`，另加 bvid 去重与「整页无新条即停」；改后同一条命令：条=60 唯一=60、跳过重复=0、请求 2 页。
- **没核实**（别当已验过）：`--from/--to` 带 `HH:MM` 只离线验了换算、没打过接口；`page_size` 上限 50 没量；搜索这一路 `-509` 频控没测；写侧照旧一条没发。
- 脚本改动：`bili_auto.py` 20,457 → 24,887 字节（第一版 `search`），再 → 25,465 字节（翻页修正），sha256 前 12 位 f55d33d02e17 → dc138cfa4d9a → 0da1f183ddb7，全 LF、CR 0。
- `SKILL.md`：命令清单加 `search` 一行；「搜索」节抬头改成「接口三条＋子命令状态」，加三条（子命令参数照实现写、窗口口径写死、实测跑过／没跑到分列）；「实测坑」加翻页那条。frontmatter 未动。ff2dc52bfdc2 → 542d84a2b1ba（13,820 字节，CR 0）。
- `check_skill.py` 未动（断言族仍是 SECTIONS 存在性＋MUST 针＋LF／手机号／裸数字／cookie 形状那几把）：改前 51/51 rc 0，改后 51/51 rc 0。真跑用的命令与 stdout 全文落本机工作区（`bili_search_*.txt`）。

## v1.2（2026-11-13 加「搜索」一节：夜里实测的接口字面照抄）

- SKILL.md 新增一节「## 搜索」，三条字面全部来自当晚实测：接口 `x/web-interface/wbi/search/type` 走 wbi 签名、`order=click` 是按播放量排；时间窗参数 `pubtime_begin_s`／`pubtime_end_s` **只吃 epoch 秒**，传日期串一律回 `code=-400 请求错误`（连试三回，换 epoch 秒才通）；实测一趟能拿到标题、UP 主、duration 字符串、play、pubdate。端点名、参数名、字段名照交代原样抄，没添没补；日期串那一格保留原字面 `2025-11-13`（没顺手改成 2026）。
- 两处指路（不是接口事实，我的措辞）：frontmatter description 的取数清单加「wbi 签名的搜索」、实测坑清单加「搜索时间窗只吃 epoch 秒」；「什么时候读这一份」括号里加「按关键词搜索」。
- 错误码表没加 `-400` 那一行：那一行的「来源／读法」怎么填交代里没给，不替它补（要加另拍）。
- 脚本 `bili_auto.py` 未动，正文也没写成「脚本能搜」：search 子命令还没写。（**这句已被 v1.3 取代**：11-15 起 `bili_auto.py` 有 `search` 子命令，别再照这句重写一遍。）
- check_skill.py 按本技能自己的形状加（这份断言族只有 SECTIONS 存在性＋MUST 针＋LF／手机号／裸数字／cookie 形状扫描，没有 DESC_MUST_SAY、没有节切片）：SECTIONS 加 `'## 搜索'`，MUST 加三针（端点字面、「`order=click` 是按播放量排」、「只吃 epoch 秒」）。
- 自检真跑：改前 47/47 通过 rc 0；改后 51/51 通过 rc 0。反证三趟各自恰好红在对应那一格（拆小标题→`section:## 搜索`；换端点字面→`must:search_endpoint`；拆 epoch 那句→`must:search_pubtime_epoch_only`，各 rc 1），改回后字节一致。技能头另过了一遍程序自己的 `asuna.skills.problems`（无问题）。

## v1（2026-11-03 新建）

- 新建「账号自治站点」技能：B 站。形状是金主定的：cookie 自动写、脚本自动执行取数据、已知范围内能自动化就自动化。
- 原料来自流水 11-03 四节：18:21 路子侦察（扫码定法、匿名基线、412 拦指纹非 wbi）、19:17 扫码登录成功（五张码、网页码真 TTL 约 180 秒、PNG 落盘绝对路径是唯一送达形状、detached poll 随沙箱命令死）、19:23 深度只读验（读侧随登录全通、投稿族要 wbi、写侧端点存在、错误码表）、19:44 看完金主初中那稿（cookie 头 `; ` 分隔、playurl 带 Referer、主镜像 567 走 backup_url、PyAV 单遍抽帧、弹幕 raw deflate、pubdate 北京时间）；免登录热评链来自已采纳的想法原话。
- ① 注：写这份技能时流水原文读不到（库里的流水文档只到 11-03 18:5x，没有这四节），是拿当时留在工作目录的脚本、记录 json、回看报告＋交代里的要义核一遍来写的。
- 脚本 bili_auto.py：status／ensure／login／view／arcs／danmaku／download／hotcomment。真跑过：status／view／arcs／hotcomment；用假 cookie 跑过 DEAD→出码→落 PNG→前台轮询→墙钟到点停。没真跑：真人扫码后的交换与回写、download、danmaku。

## v-next（2026-11-09 时钟标签去城市名，偏移与逻辑一字未动）

- 口径没动：`timedelta(hours=8)` 与全部取数逻辑一字未改，换算出的时刻与原来逐秒相同。动的是给人看的标签，外加一次改名：`bj()` → `site_ts()`（定义 1 处＋调用点 3 处：view 一行、hotcomment 每行、arcs 每行）。
- 为什么：那枚 +8 是站点那侧的公历时钟，不是这台部署的位置。旧写法把它印成城市名，读的人容易当成「本机时区」；本机钟面本来就与它跨日，这一点照旧写明。
- SKILL.md：frontmatter description 与「实测坑」那行的说法改成「站点侧时钟 UTC+8」，正文里城市名清零；脚本输出后缀换 ` UTC+8 站点侧`；view 那行提示改成「站点侧口径，本机钟面会跨日」。
- check_skill.py：断言 `('beijing', '北京时间')` → `('site_clock_is_site_side', '站点侧')`。正文与断言必须同一趟落：只改正文这条会假红，只改断言则旧字面溜回正文还照绿。
- 自检（四条都真跑，用 `sys.executable` 起子进程）：改前 47/47 通过（rc 0）；改后 47/47 通过（rc 0）；负例① 只改正文、`MUST` 留旧版 → 恰好 `must:beijing` 一条红（46/47、rc 1）；负例② 旧正文塞回、`MUST` 用新版 → 恰好 `must:site_clock_is_site_side` 一条红（46/47、rc 1）。
- 上面 v1 那条历史条目不改写（里面「pubdate 北京时间」是当时那天的说法，照原样留着）。
