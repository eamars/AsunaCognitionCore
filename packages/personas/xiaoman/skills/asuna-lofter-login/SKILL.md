---
name: asuna-lofter-login
description: LOFTER 无浏览器登录的做法（含过那道拼图滑块），全程纯 HTTP 实走过一遍。形状：POST www.lofter.com/lpt/login.do 发手机号＋sha256(密码)，首答常见 meta.status 4071「请滑动滑块」＝服务端挡在验密之前、不是密码错；滑块走 captcha 取图 → 四把算法投票判缺口 xPos → AES/RSA 封包 POST captcha/check 拿 32 位票据 → 带 capttoken 重发登录，成功时 body 里那枚 96 位 token 就是登录态，服务端不下发登录态 cookie，要按前端口径自己种。写死：凭据只从保险箱名字读、缺口必须多算法投票（单把眼看实测会错）、再登录按每次一到两次预算、见 4071 之外的新风控形状即停；登录态服务端 TTL、跨会话重放、下次还弹不弹滑块、写路径四条列在未核实清单里，别当已核实。要登 LOFTER、拿它的登录态、或判那条登录态还算不算数时读这一份。附三支探针与零依赖自检 check_skill.py。
scene_kinds: [home]
---

# asuna-lofter-login

一句话：LOFTER 的账号密码登录可以完全不开浏览器走完，包括那道看着只有浏览器能过的拼图滑块；但「登录成功」的判据是**接口回执**，不是我这边 cookie 有没有落地。

## 什么时候读这一份

- 要拿 LOFTER 登录态（读自己的博客、合集，以后可能的写操作）；
- 要判「上次那枚登录态还能不能用」；
- 撞见 4071／滑块／风控字样，需要知道哪一种是正常门、哪一种必须停手。

## 凭据（先定死这一条）

- 手机号与密码只从保险箱名字 `xiaoman-lofter` 的环境变量读：`LOFTER_PHONE`／`LOFTER_PASS`（`sandbox_run` 带 credentials 名字，值只在那一条命令里，不进文件）。
- 正文、脚本、报告里都不许出现凭据值、手机号数字、密码字样。手机号先剥国家码：剥掉非数字后，长度 13 且以 86 开头才剥前两位（这是实测到的形状）。
- 登录成功那枚 96 位 token 本身就是凭据：不打印、不写进文件。非要留给下一趟用，先想清放在哪、什么算作废。

## 登录（两步半）

1. `POST https://www.lofter.com/lpt/login.do?product=lofter-pc`，`application/x-www-form-urlencoded`，body：`phone`＝手机号、`passport`＝sha256(密码) 的十六进制、`type=0`、`clientType=0`、`deviceType=3`、`Target=www.lofter.com`。
2. **常见首答 `meta.status=4071`「请滑动滑块」**：服务端把验证挡在验密之前，不代表密码错、也不算失败。这时走下一节，**不许改成密码重试**（一次登录有配额）。
3. 过完滑块拿到 32 位票据，带 header `capttoken: <票据>` 把同一条登录**再发一次**。

成功形状（值省略）：HTTP 200，body `{"result":0,"userid":<数字 id>,"deviceid":"<36 位>","token":"<96 位>","status":200,"desc":"操作成功"}`。

## 滑块：纯 HTTP，不用浏览器

1. `GET https://captcha.lofter.com/captcha/get?type=jigsaw` → `data` 里有 `id`、`type`、`bg`（背景图 base64）、`front`（拼图条 base64）。响应可能带 cookie，带着它去 check。
2. 判缺口 x —— 口径见下一节，两条写死。
3. `POST https://captcha.lofter.com/captcha/check`，`content-type: application/json`，**请求体是密文的原始字节**：明文 `{"id":"…","type":"jigsaw","data":"{\"xPos\": <数字>}"}`（`data` 是字符串）→ AES-128-CBC／PKCS7；key 与 iv 是客户端各随机 16 字符，每位 50% 数字 0-8、50% 字母 a-y。头 `X-EncSecKey` ＝ RSA PKCS#1 v1.5 加密 `key + "-" + iv` 的 base64。
4. 回包也是密文：同一把 AES 解出来，明文可能直接是 JSON、也可能外面再套一层 base64，两种都试。`{"msg":"成功","code":0,"data":{"success":true,"token":"<32 位>"}}` 里那 32 位就是票据。
5. 一个 `id` 配一张图、一次 check；过了就立刻带去登录，别拿同一个 id 再 check 第二次。

RSA 公钥是前端 captcha 脚本自带那一把（不是我的秘密），写死在探针 `captcha_stage_b.py` 里；滑块脚本换版本时先核对公钥还是不是同一把。

## 缺口 xPos 的两条硬口径

1. **坐标口径写死**：`xPos` ＝ 拼图条左边缘在 bg 原图坐标里的 x。CSS 显示宽 320 ＝ natural 宽，1:1，不做换算；拼图形状在条内占哪几列用 `front` 的 alpha 量（实测某一张是条内第 3..67 列）。
2. **必须多算法投票，单把不许发**：边缘轮廓打分＋洞内暗度＋模糊 NCC＋接缝色差，四把一起出，**取一致区间的中值**（探针里 ≥3 把落在 ±5 像素内才算一致，凑不出就退码 3、换一张图重来）。
   实测教训：同一张图我眼看单把判成 195，四把给的是 166–169；195 那一带是背景里白色蒸汽的低饱和区，不是洞。探针在真图（当时发出去那一张）上复算过：edge 167／dark 168／seam 166 三把一致，ncc 给 219 离群，投出 167 ＝ 当时真发出去的那一把。**所以：眼看与单把算法都只当第 5 把参考，不当结论。**

## 登录态放在哪、怎么验通

- 日常的探活、取数和失效重登不要手搭：走技能 `lofter`（`lofter_auto.py` 自己读登录态文件、探活、重登、回写）。本技能记原理与口径，下面三支探针是单步诊断用。
- 登录态＝body 里那枚 96 位 `token`。**服务端不下发登录态 cookie**：成功响应里只有一个打点用的 `usertrack`。
- 按前端 `sm()` 的口径自己种 cookie：`LOFTER-PHONE-LOGIN-AUTH`（外加 `token`、`LOFTER-PHONE-LOGIN-FLAG=1`、`phone`、`deviceid`，域 `.lofter.com`、path `/`）；调 `api.lofter.com` 时另带请求头 `lofter-phone-login-auth: <同一枚 token>`。
- 验通两条（都只读、不花钱）：
  1. `GET https://www.lofter.com/loginCheck.do` 带 cookie：未登录 `meta.status` 401「用户未登录」，登录后 200，`response` 给 `blogName`／`blogId`／`blogNickName`。**401→200 才算这次登录真换到了东西。**
  2. `POST https://api.lofter.com/v1.1/postCollection.api?product=lofter-android-7.6.12`，body `method=getCollectionList&blogdomain=<blogdomain>`，带 `lofter-phone-login-auth` 头 → `meta.status` 200 为通（合集为空是 `list len=0`，正常）。
- 账号事实（域名与 blogId 不进正文，值待在本机私有处）：`blogdomain` 与 `blogId` 两条从本机私有处的 `lofter-account.txt` 读，那个文件是 `key=value` 两行，键名 `blogdomain`、`blogId`。定位口径与本机私密名单同一套：先看环境变量 `ASUNA_LOFTER_ACCOUNT`，其次 `ASUNA_DATA_ROOT`（或 `asuna.config.DATA`）下的 `private/lofter-account.txt`，再不行从脚本位置逐级往上找 `.runtime/private/lofter-account.txt`。读到的值当场用，不抄进正文、脚本或报告；`blogId` 是一串数字，与手机号形状同族，别让它进正文。昵称「沈小满」是我自己的名字，写在正文无妨。

## 探针（同目录，全在一趟沙箱里跑）

| 脚本 | 干什么 | 花掉什么 |
|---|---|---|
| `captcha_stage_a.py` | 取一张拼图＋四把投票出 `xPos`，写 `<TAG>_state.json`（含一次性 `id` 与临时 AES key/iv）；`--bg … --front …` 是离线复算，不联网不花配额 | 联网那趟一次取图 |
| `captcha_stage_b.py` | 读 state，发**唯一一次** check，成功就**唯一一次**登录，再跑上面两条只读验证（`DO_LOGIN=no` 只 check 不登录；`XPOS` 覆盖 xPos） | 一次 check＋一次登录 |
| `lofter_login_probe.py` | 不带票据直接登一次＋两条只读验证（用来判「今天还给不给 4071」「登录态换不换得出来」） | 一次登录 |

跑法：`sandbox_run` 带 `credentials: ["xiaoman-lofter"]`，脚本自己 `os.environ` 读；跨命令要留的东西一律写 `/task`（TEMP 只活一条命令）。票据、token、AES key 都不打印。

## 未核实（别当已核实）

- **登录态的服务端 TTL 未知**：前端种 cookie 写 `maxAge: 864e6`，那串数字的单位没核实（按毫秒＝10 天，按秒＝10000 天）。别拿它当寿命用。
- **跨会话重放未实测**：token 没落盘，「放进全新会话仍有效」这句按没核实对待。
- **下次登录还弹不弹滑块未知**：弹是常态，风控有没有放宽没测。
- 这台机器出网是否每次都触发滑块：一个样本，没核实。
- **发文与写路径没有公开文档**：除读自己的博客与合集之外，「能发帖」这句没验证过，别写成已经行。

## 配额与停手

- **再登录配额按每次一到两次预算**：一趟任务里登录最多两次（一次撞 4071、一次带票据成功），captcha 取图也别超过两次，别循环 hammering。
- 4071 是正常门；**4071 之外的新风控形状**（账号异常、操作频繁、要短信验证这类字样）**即停**：把 HTTP 码与脱敏后的 body 原样交回来，不试第二下、不改大小写重试、不换 UA 硬试。
- 停手时报告写清三件：停在哪一步、看到了什么码或字样、票据用过没有。
