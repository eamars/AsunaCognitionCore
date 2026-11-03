# CHANGELOG

## v1（2026-11-03 新建）

- 新建「账号自治站点」技能：B 站。形状是金主定的：cookie 自动写、脚本自动执行取数据、已知范围内能自动化就自动化。
- 原料来自流水 11-03 四节：18:21 路子侦察（扫码定法、匿名基线、412 拦指纹非 wbi）、19:17 扫码登录成功（五张码、网页码真 TTL 约 180 秒、PNG 落盘绝对路径是唯一送达形状、detached poll 随沙箱命令死）、19:23 深度只读验（读侧随登录全通、投稿族要 wbi、写侧端点存在、错误码表）、19:44 看完金主初中那稿（cookie 头 `; ` 分隔、playurl 带 Referer、主镜像 567 走 backup_url、PyAV 单遍抽帧、弹幕 raw deflate、pubdate 北京时间）；免登录热评链来自已采纳的想法原话。
- ① 注：写这份技能时流水原文读不到（库里的流水文档只到 11-03 18:5x，没有这四节），是拿当时留在工作目录的脚本、记录 json、回看报告＋交代里的要义核一遍来写的。
- 脚本 bili_auto.py：status／ensure／login／view／arcs／danmaku／download／hotcomment。真跑过：status／view／arcs／hotcomment；用假 cookie 跑过 DEAD→出码→落 PNG→前台轮询→墙钟到点停。没真跑：真人扫码后的交换与回写、download、danmaku。
