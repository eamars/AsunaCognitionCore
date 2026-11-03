---
name: lofter
description: 账号自治站点技能：LOFTER。脚本 lofter_auto.py 自己读登录态文件 → 用 loginCheck.do 探活（401 死、200 活）→ 失效就按 asuna-lofter-login 记载的流程自动重登（login.do 撞 4071 → 取拼图 → 四把算法投票判缺口 → 唯一一次 check → 带 capttoken 重登，凭据只从保险箱 xiaoman-lofter 的环境变量读）→ 成功回写登录态文件 → 再执行取数（已验端点：loginCheck.do、postCollection.api 的 getCollectionList）。LOFTER 的滑块能自动过，所以平时不需要喊人；只有 4071 之外的新风控字样、凭据缺失、滑块连续凑不出一致时才停下报字面。账号事实（blogdomain、blogId、token、手机号）不进正文，只写从哪读。要读 LOFTER 数据、判登录态死活、或要重登时读这一份；登录细节与滑块口径读 asuna-lofter-login。
scene_kinds: [home]
---

# lofter

一句话：LOFTER 登录态的「读、探、重登、回写、取数」交给 `lofter_auto.py`；滑块能自己过，所以不用喊人，能不能过看四把算法凑不凑得出一致。登录与滑块的原理、四把口径、配额，细节在技能 `asuna-lofter-login`，这里不重复。

## 什么时候读这一份

- 要读 LOFTER（自己的合集；以后再加已验端点）；
- 要判「LOFTER 登录态还活不活」；
- 登录态死了要自动重登。

## 文件与凭据约定（账号事实只写「从哪读」）

- 工作目录：`.runtime\work\local-user\`（即本机运行目录下的 work/local-user，完整绝对路径由脚本按下面的顺序找到并在输出里打出）（`private\` 若被写围栏挡，一律用这里）。找目录的顺序：环境变量 `ASUNA_LOFTER_DIR` → 当前目录（有登录态文件或目录名是 `local-user`）→ 往上找 `.runtime/work/local-user`。
- 登录态文件：该目录下 `lofter_login.json`（键：`token`、`deviceid`、`saved_at`、`by`）。**脚本自己写**，原子写。token 是凭据：不打印、不进报告。
- 老格式：同目录的 `lf1104_token.json` ＋ `lf1104_token.key`（Fernet 密文，key 同目录）。`ensure` 找不到新文件时会读它（只读、不改旧文件），探活为活就导入写成新文件。
- 账号事实：`blogdomain`、`blogId` 两条从本机私有处的 `lofter-account.txt`（`key=value` 两行）读；定位顺序：环境变量 `ASUNA_LOFTER_ACCOUNT` → `ASUNA_DATA_ROOT` 下 `private/lofter-account.txt` → 往上找 `.runtime/private/lofter-account.txt`。读不到就用 loginCheck 回的 `blogName` 拼 `.lofter.com`。值当场用，不抄进正文、脚本、报告；脚本打印时只露首末两位。
- 凭据：手机号／密码只在保险箱名字 `xiaoman-lofter` 的环境变量 `LOFTER_PHONE`／`LOFTER_PASS`。重登要用 `sandbox_run` 带 `credentials: ["xiaoman-lofter"]`；不带就只能探活、取数，要重登会停在 `NEEDS_CREDENTIALS`（退出码 5）。
- 依赖：`httpx`、`numpy`、`Pillow`、`cryptography`（沙箱 python 里都有；重登才用到后三个）。

## 自动化的最低形状（脚本已经这样做）

1. 读登录态文件（没有就试老格式）；
2. 探活：`GET www.lofter.com/loginCheck.do`（带按前端口径种的 cookie）：`meta.status` **401＝死、200＝活**，其余＝无法判定——**无法判定不重登**，字面报（退出码 3）；
3. 死了／没有 → 自动重登：`login.do` 首答 `4071` 是正常门 → 取拼图 → 四把投票（≥3 把落在 ±5 像素内才发）→ 唯一一次 check → 带 `capttoken` 再登录 → 拿到 96 位 token；
4. 重登后先 loginCheck 验 200，再回写文件；
5. 再执行取数。

```
python3 lofter_auto.py status          # 只读文件、只探活（不读老格式、不重登）
python3 lofter_auto.py ensure          # 探活；死了才重登（重登要 credentials）
python3 lofter_auto.py login           # 不管死活直接重登
python3 lofter_auto.py collections     # ensure → getCollectionList（已验端点）
```

退出码：0 成功；3 探活无法判定／4071 之外的新风控形状／登录回包不是 JSON；4 取数失败；5 没有凭据；6 滑块凑不出一致或 check 没过。

## 已验端点

- `GET www.lofter.com/loginCheck.do`（cookie 登录态）：401→200 才算登录真换到了东西；`response` 给 `blogName`／`blogId`／`blogNickName`。
- `POST api.lofter.com/v1.1/postCollection.api?product=lofter-android-7.6.12`，body `method=getCollectionList&blogdomain=<blogdomain>`，头带 `lofter-phone-login-auth: <token>`：`meta.status` 200 为通；合集为空是 `list len=0`，正常。
- **登录态 cookie**：服务端不下发，要按前端口径自己种 `LOFTER-PHONE-LOGIN-AUTH`、`token`、`LOFTER-PHONE-LOGIN-FLAG=1`（和 `deviceid`），域 `.lofter.com`、path `/`。

## 什么时候该停、什么时候喊人

LOFTER 不需要人扫码，所以**平时不喊人**。这几种情况脚本会停，由我把字面报给说话那一半，再由它决定要不要找金主：

- **4071 之外的新风控形状**（账号异常、操作频繁、要短信验证这类字样）：即停，不试第二下、不改大小写、不换 UA；报 HTTP 码＋脱敏后的 body。
- **凭据缺失**（`NEEDS_CREDENTIALS`）：检查是不是忘了带 `credentials`；带了还缺就是保险箱里没有这个名字，停，不绕。
- **滑块两张图都凑不出一致**（退出码 6）：不硬发，停；登录态文件没动；换个时间再来，别循环。
- 给人看的形状：报「停在哪一步、看到什么码或字样、票据用过没有」三件事，不贴 token、手机号。

## 重登预算

一次运行里：`login.do` 最多 2 次（一次撞 4071、一次带票据）；captcha 取图最多 2 张，**只有四把凑不出一致才换第二张**；同一张图只发一次 check。再来一趟是另一次预算，但别连着循环。

## 未核实（别当已核实）

- **老格式导入（`ensure`）和 `collections` 读到 `list len=0`** 是真跑过的；**重登整条链在这个脚本里只跑到「撞 4071→取图→四把投票」**：那一趟两张图的四把读数都离散，凑不出一致，按设计停了（退出码 6、登录态文件没动）。「check→带票据登录→拿 token→回写」这一段是照上一次走通过的流程搬进来的，**这个脚本形态没走通过**。
- 四把投票在有些图上凑不出一致（实测一趟里连着两张都不一致）；这不是口径错，是单张图的事，但意味着自动重登**不保证一次成**。
- 登录态服务端 TTL 未知；跨会话重放只在同一台机器、同一个小时级窗口里验过（老格式 token 在新沙箱命令里仍为活）。
- 发文与写路径：本技能不含。DWR `PostBean.getPosts` 读自己的帖子，按我这里的参数格式回了 HTTP 501，**没打通，别当已验端点**。
