# CHANGELOG

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
