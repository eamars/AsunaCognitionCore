---
name: bilibili
description: 账号自治站点技能：B 站。脚本 bili_auto.py 自己读 cookie 文件 → 用 nav 的 code 探活 → 失效就按本技能记载的扫码流程自动重登（网页码真 TTL 约 180 秒、前台轮询、出码与轮询同一趟、PNG 落盘绝对路径是唯一送达形状）→ 成功回写 cookie 文件 → 再执行取数（view、wbi 签名的投稿列表、弹幕、整段下载、免登录热评链）。扫码要人来扫这一步不能自动化，正文写死「什么时候喊人、喊人给什么形状」。附实测坑（cookie 头分隔符是 `; ` 不是 `&`、playurl 要 Referer、主镜像 567 走 backup_url、弹幕 XML 是 raw deflate、pubdate 说北京时间）与错误码表。要读 B 站数据、判登录态死活、或要重登 B 站时读这一份。账号事实（uid、cookie 值）不进正文，只写从哪读。
scene_kinds: [home]
---

# bilibili

一句话：B 站这边能自动的都交给 `bili_auto.py`——读 cookie、探活、重登、回写、取数；只有「扫码」要人，所以只有那一步要喊人。

## 什么时候读这一份

- 要读 B 站的数据（视频信息、某个号的投稿、热评、弹幕、整段视频）；
- 要判「B 站登录态还活不活」；
- 要重登（扫码）；
- 撞到 412、-101、-352、-403、-509 之类，要知道是什么意思、该换哪条路。

## 文件约定（账号事实只写「从哪读」）

- 工作目录：`.runtime\work\local-user\`（即本机运行目录下的 work/local-user，完整绝对路径由脚本按下面的顺序找到并在输出里打出）（`private\` 若被写围栏挡，一律用这里）。脚本找目录的顺序：环境变量 `ASUNA_BILI_DIR` → 当前目录（有 cookie 文件或目录名是 `local-user`）→ 往上找 `.runtime/work/local-user`。
- cookie 文件：该目录下的 `bili_login.json`。脚本读 `logged_in.cookie_header`（`; ` 分隔），没有就用 `logged_in.cookies_final` 按 `; ` 拼；uid 读 `logged_in.uid`（默认查自己的投稿就用它）。**脚本自己写这个文件**，不用人手落。
- 扫码图：同目录 `bili_login_qr_cur.png`（固定名；每次出码前先删旧的，所以「文件在」＝这一趟刚出的新码）。
- B 站没有账号密码这回事（登录只靠扫码），所以没有保险箱名字；cookie 值只待在 cookie 文件里，不打印、不进报告、不进别的文件。
- 扫码轮子：二维码用纯 python 的 `segno`，脚本需要时自己把轮子装进 `<工作目录>/libs`（只写任务目录）。

## 自动化的最低形状（脚本已经这样做）

1. 读 cookie 文件；
2. 探活：`GET api.bilibili.com/x/web-interface/nav`，`code=0` 且 `data.isLogin=true` 才算活；`code=-101` 才判死；别的（-412、网络错）判「无法判定」，**不重登、字面报出来**（退出码 3）；
3. 死了 → 扫码重登（见下）；
4. 登录成功 → 先 nav 验一次再回写文件（原子写：先写 `.tmp` 再 `os.replace`）；
5. 再执行取数任务。

```
python3 bili_auto.py status            # 只探活，不重登
python3 bili_auto.py ensure            # 探活，死了才重登
python3 bili_auto.py login             # 不管死活直接发码轮询
python3 bili_auto.py view BVxxxx       # ensure → view
python3 bili_auto.py arcs [--mid N]    # ensure → wbi 签名的投稿列表（默认自己）
python3 bili_auto.py danmaku <cid>     # 弹幕 XML，raw deflate 解压后落盘
python3 bili_auto.py download BVxxxx --out F.mp4   # view → playurl（带 Referer）→ 主镜像，失败走 backup_url
python3 bili_auto.py hotcomment BVxxxx # 免登录热评链，不读 cookie
```

用 `sandbox_run` 在工作目录里跑；脚本在已发布技能目录里，用绝对路径调。退出码：0 成功；2 要人扫码但没扫成；3 探活无法判定；4 取数失败。

## 扫码重登：什么时候喊人、喊人给什么形状

**扫码要人来扫，这件事不自动化。** 规矩：

1. **先别出码。** 出码之后只有约 180 秒（网页码真 TTL，实测；B 站不给 expires）。所以先 `status`：活着就不用扫，别白喊人。
2. 死了、需要人：**先确认人在场**（用 `ask_character` 问说话那一半：金主现在能不能看到图、能不能在三分钟内扫）。人不在就停在这里，把「cookie 失效、要扫码、等人在场」报回去，不空转出码。
3. 人在场：**同一个工具块里并行发两件事**——
   - `sandbox_run` 前台跑 `python3 bili_auto.py login`（或 `ensure`），`timeout` ≥ 200 秒；
   - `report_progress` 留一句给说话那一半：「B 站扫码图要出了，PNG 绝对路径 `<工作目录>\bili_login_qr_cur.png`，约 180 秒内扫；以文件存在且刚出为准」。
   给人的形状只有一种：**PNG 落盘的绝对路径**（脚本打印 `NEEDS_SCAN png=<绝对路径>`），由说话那一半当文件发出去。别指望别的送达形状。
4. **轮询必须前台、带 timeout，出码与轮询在同一趟。** detached 起的轮询会随沙箱命令一起死（实测）；脚本出码后就在同一进程里每 2 秒 poll 一次，墙钟上限 185 秒。
5. poll 内码：`86101` 未扫（继续）、`86090` 已扫待确认（继续，只提示一次）、`0` 成功（走交换）、`86038` 失效（**停**，不自动换新码）、别的内码（**停并字面报**）。
6. 码过期没扫上：报「过期」，**不自己再发第二张**；等说话那一半确认人还在、要再来，再重复第 2 步。
7. 成功：脚本交换 cookie → nav 验 `isLogin` → 回写文件 → 打印 `WROTE`，之后继续原来的取数。

## 登录后的读侧与写侧

- **读侧随登录基本全通**：nav、view、space/acc/info、relation（followings 查自己等）、article 读、reply 读、player/playurl 都实测通。
- **投稿族要 wbi 签名**：`x/space/wbi/arc/search` 不签名返回 `-403`；签了 `code=0`。签法：从 nav 的 `data.wbi_img` 取 `img_key`＋`sub_key`（各自是 url 末段去扩展名，32 位），拼接后按标准重排表取前 32 位得 mixin_key；参数加 `wts`、按 key 排序、值里剔掉 `!'()*`、urlencode，`w_rid = md5(query + mixin_key)`。重排表里有一个越界值 64，落在第 32 位之后，不影响前 32 位。脚本 `arcs` 已实现。
- **写侧**（reply/add、dynamic 创建）：端点存在（GET 回 405），**没有发过一条写请求**，也没验过签名/csrf 要求；专栏投稿端点（`x/web/article/submit` 一类）按猜的路径回 404，**真端点没核实**。别把写侧写成「能发」。`bili_jct` 是 csrf，只有写侧才用得上，读侧一次都没用到。

## 免登录调用链（热评）

`www 视频页 → x/web-interface/view?bvid= → x/v2/reply?type=1&oid=<aid>&sort=2`

- 每跳隔几秒（脚本 3 秒）；免登录直接打 view 回 `412`（带完整 UA 与 Referer 也一样），先访问 www 视频页后 view 通过，那时 cookie 罐里多了 `b_nut`、`buvid3` 两个访客 cookie（为什么有效是推断，现象是实测）；
- **别用** `/x/v2/reply/main` 和 popular：免登录直接 `-352`；
- 任何一跳失败：**当没看到，不编**，把 HTTP 码与 code 字面报出去。

## 实测坑

- **cookie 头分隔符是 `; `，不是 `&`**：用 `&` 手拼，nav 回 `-101`；同一批 cookie 用 `; ` 立刻 `isLogin=true`。
- **412 拦的是指纹，不是缺 wbi 签名**：免登录直打 view、免登录直打 arc/search 都回 412，补了完整浏览器 UA ＋ Referer 也一样；通过的做法是先访问视频页拿访客 cookie（免登录链），或带登录态。
- **playurl 要 Referer**（`https://www.bilibili.com`）。老稿只有 360P 一档（`quality=16`，`accept_quality=[16]`），请求 `qn=64` 也是这样。
- **主镜像可能回 HTTP 567**（urllib 报 `Unknown Status`）：改走 `durl.backup_url`，一次成功；主镜像一次、备用一次，**不硬试第三次**。下载后字节数应与接口 `size` 完全一致。
- **抽帧用 PyAV 单遍解码**：`container.decode(video=0)` 顺序走一遍（6600 帧约 2 秒）；PyAV 18 里 `seek()` 之后 `stream.decode()` 是 0 帧。黑帧用平均亮度＋标准差门槛跳过。机器 PATH 上没有 ffmpeg。
- **弹幕 XML 是 raw deflate**：`comment.bilibili.com/<cid>.xml` 回 `Content-Encoding: deflate`，urllib 不解压，要 `zlib.decompress(raw, -15)`。
- **pubdate 说北京时间**：接口给的是 UTC 秒；本机在新西兰，本机钟面会跨日（同一刻本机已是次日）。对人说「北京时间」，脚本输出带「北京」字样。
- **cookie 值不落进别的文件**：下载/抓取产物里会带设备 id（`buvid3` 前缀）和公开 uid；落盘前自查一遍 SESSDATA／bili_jct／sid 有没有混进去。

## 错误码表（实测；没见过的码字面报，不替它解释）

| 码 | 来源 | 读法 |
|---|---|---|
| `-101` | nav、relation 等 | 账号未登录：cookie 失效，或手拼头分隔符错了 |
| `-352` | 免登录 reply/main、popular | 风控校验失败：换免登录链（`reply?sort=2`） |
| `-401` | 免登录 space/acc/info | 非法访问 |
| `-403` | 没签 wbi 的 arc/search | 访问权限不足：签 wbi |
| `-509` | article/view 等 | 请求过于频繁：歇一会儿 |
| HTTP `412` | 免登录 view/arc 等 | 指纹拦：补 UA/Referer、先访问页面或带登录态 |
| HTTP `405` | GET 打写端点 | 端点存在，只收 POST |
| HTTP `567` | 视频主镜像 | 走 `backup_url` |
| poll `86101／86090／86038／0` | 扫码 poll | 未扫／已扫待确认／已失效／成功 |

## 未核实（别当已核实）

- 扫码「已扫→确认→交换 cookie→回写」这一段在脚本里是照上次成功的流程重写的，**脚本形态没有真人扫过**；出码、落 PNG、前台轮询到墙钟、失效即停这几步用假 cookie 跑过。第一次真重登要盯着，并留意交换后 jar 里有没有 `SESSDATA`。
- 登录态服务端 TTL 未知；cookie 能用多久没量。
- 出码后 B 站「失效」态会不会盖掉「已扫」态没测。
- 写侧（评论、动态、专栏投稿）全部没发过。
- 「喊人」那套并行通知（`report_progress` 与前台命令同块）是按规矩设计的，没端到端走过一遍。

## 停手规矩

- 探活无法判定、poll 内码没见过、交换后拿不到 `SESSDATA`：**即停，字面报**（HTTP 码、code、message），不换 UA 硬试、不连发。
- 一趟任务里出码不超过一张；过期后要不要再来由说话那一半定。
- 只读任务就只发 GET；要做写操作先问说话那一半。
