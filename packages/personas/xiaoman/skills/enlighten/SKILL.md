---
name: enlighten
description: 账号自治站点技能：Enlighten（Enphase 云端光伏报表，员工号只读）。通路全照字面写死，月度对账直接打、不再翻 4.9 MB 的 manager_assets JS 包。登录＝POST /login/login.json（form user[email]／user[password]，Accept: application/json），成功判据两条一起看：HTTP 200 且 message 逐字 success，并且响应体带 session_id（实测 32 位）；凭据只从保险箱名字 enlighten 的 ENLIGHTEN_EMAIL／ENLIGHTEN_PASSWORD 读，正文只写 env 名。只读能打的三条 GET＝表计 rollup 逐日表（HTML 分页）、/systems/{SITE}/energy 单日或区间合计、/systems/{SITE}/inverter_data_x/energy.json 逐台区间合计，参数与 tz 写法照抄。死路清单五枚（/reports/system_daily_international.json 等四枚加 /report/chart）全 404，别再试。日报告册的真取数口是 POST /systems/{SITE}/generate_rpt（带 CSRF、算状态变化）＝只读趟红线。单位字面是 Wh（表头 Energy Produced ( Wh ) 与 JS unit:'Wh'），跟标 kWh 那本对账前先统一刻度。站点 id 与表计 id 命中本机私密词，正文只有 {SITE}／{METER} 占位符。要读 Enlighten 日发电量、做月度对账、或判某条路径存在不存在时读这一份。
scene_kinds: [home]
---

# enlighten

一句话：这个员工号在 Enlighten 只读能打的口子就下面那三枚，字面抄在这里；日报告册要 POST（状态变化），只读趟不碰。凭据、站点 id、表计 id 都不在正文，只写从哪读。

## 什么时候读这一份

- 要读 Enlighten 的日发电量／逐日表（月度对账、复核某一天、和另一本账比数）；
- 有人问「某条 reports 路径能不能读」——先查下面的死路清单，别再花 GET 预算；
- 两本账对不上，要先分清是站点级（表计）还是逐台相加这两个测量点；
- 只读趟出手前对一遍红线与预算。

## 文件与凭据约定（账号事实只写「从哪读」）

- **凭据**：保险箱名字 `enlighten`（`sandbox_run` 带 `credentials: ["enlighten"]`），环境变量只有两个：`ENLIGHTEN_EMAIL`、`ENLIGHTEN_PASSWORD`。正文、脚本、报告里只出现这两个 env 名；值不落盘、不打印、不进命令行、不进 URL 查询串。员工号凭据三个月一换（金主 2026-10-07 给的）。
- **站点 id = `{SITE}`，表计 id = `{METER}`**（两把表各一枚；rollup 与 `generate_rpt` 的 `report[pmu_id]` 用表计 id）。这两个数**命中本机私密词名单**（站点 id 实测命中名单第 22 行，category=site），所以不进正文、不进脚本、不进报告。值从 persona 光伏那一节读；脚本 `enlighten_read.py` 从环境变量 `ASUNA_ENLIGHTEN_SITE`／`ASUNA_ENLIGHTEN_METER` 拿，读不到就报 `MISSING_ENV` 退出，不硬编。
- 逆变器序列号（响应体的键）也是 9 位号，同样不落进仓里的文件；要引用就现取现用。
- **时区字面**：`Pacific/Auckland`（页面配置里的 `timezone: 'Pacific/Auckland'`）。这是参数不是账号事实，可以照抄。
- **登录态不写盘**：会话 cookie 只活在单条命令的内存里（实测 jar 里是 `_enlighten_4_session`、`enlighten_manager_token_production`、`locale`）。所以每条只读命令自己登录一次，别指望跨命令复用会话。
- 工作目录：本机 work/local-user（相对说法，不抄绝对路径）。脚本找它的顺序：env `ASUNA_ENLIGHTEN_DIR` → 当前目录 → 往上找 `.runtime/work/local-user`。落盘产物只写这里。
- 脚本：`enlighten_read.py`（零业务依赖，只用 `httpx`；沙箱 python 里有）。自检：`check_skill.py`。

## 登录通路（字面，11-08 两趟实测）

```
POST https://enlighten.enphaseenergy.com/login/login.json
form: user[email]=<env ENLIGHTEN_EMAIL>   user[password]=<env ENLIGHTEN_PASSWORD>
头:   Accept: application/json
判据: HTTP 200 且响应体 message 逐字 "success"（大小写不敏感）＋ 响应体带 session_id
```

- **两条判据一起看**：`message=success`（实测长度 7）**并且** `session_id` 在（实测 32 位）。只有前者、没有后者＝按登录失败停手。
- 响应体的键字面（实测两趟一致）：`is_consumer,manager_token,message,redirect_url,session_id,system_id`；正文 575 字节。
- **登录正文整段不进日志**：只打 HTTP 码、判据两条的读数、message 长度、body 字节数、cookie 名。密码不回显。
- 客户端形状：`follow_redirects=False`，UA 自定（实测用的是 `Mozilla/5.0 (read-only data pull)`）。
- 预算：POST ≤ 2，第二次只在第一次是传输错时花；`message` 不是 success 就**停**，不换登录形态、不撞第三次。见 302 立即停并报 location（11-08 两趟 0 次 302、0 次 401）。

## 只读能打的三条 GET（字面，11-08 两趟实测；脚本子命令同名）

| 用途 | 字面 GET | 回什么 |
|---|---|---|
| 表计 rollup 逐日表（`rollup`） | `/admin/sites/{SITE}/devices/{METER}/rollup?page=1`，头 `Accept: text/html` | 一页 HTML 表，表头字面 `Start Date / Energy Produced ( Wh ) / Average Real Power ( W ) / Channel`；日期字面 `MM/DD/YYYY`，新→旧，实测一页 50 行，翻页改 `page` |
| 站点级（表计口径）合计（`day`／`range`） | `/systems/{SITE}/energy?start_date=D&end_date=D&interval=day&tz=Pacific/Auckland` | `{"production":<整数>,"start_date":…,"end_date":…,"inverter_count":20}`，正文 90 字节 |
| 逆变器级逐台合计（`inverters`） | `/systems/{SITE}/inverter_data_x/energy.json?start_date=D1&end_date=D2&interval=day&tz=Pacific/Auckland` | `{"production":{"<序列号>":<整数>,…共 20 台…},"start_date":…,"end_date":…}`，正文 406 字节 |

- **前两枚 energy 口只回整段区间的合计，不逐日**。要逐日就**一天一发**（前端 JS 自己也是这么发的：`requestData(url,{startDate,endDate})` → `paramsToUnderscores`）；8 天区间同样只回一个数，实测过。
- 参数写法照抄：`start_date`／`end_date` 是 `YYYY-MM-DD`；`interval=day`；`tz=Pacific/Auckland` 的**斜杠不转义**（实测这样 200）。
- GET 请求头形状（打中用的就是这套）：`Accept: application/json, text/javascript, */*;q=0.9`、`X-Requested-With: XMLHttpRequest`、`Referer: https://enlighten.enphaseenergy.com/systems/{SITE}`；rollup 只要 `Accept: text/html`。
- 逐台那一枚还支持 `&inverter_id=<序列号>`（JS 里的形状，只在一发预算内核过一台）。
- **响应体只有那四个键：没有单位字段、没有时区字段**。`tz` 不回显；「每行是站点本地日」是推断（依据：页面配置 `timezone` 字面＋逐日值与 rollup 逐日表逐字一致），不是响应体自己声明的。
- 跨读稳定性：11-08 同一晚相隔约两小时读同一天两次（19:5x 与 21:4x，本机钟面），11/06 与 11/07 的单日正文**字节级一致**（sha256 前 16 `e107e4d77c80849d`／`cd03ede5cf97d7a1`）——这两天算有两读了；更早的日期还是只有单读。

## 死路清单（全 404，别再试）

| 字面 GET | 码 |
|---|---|
| `/reports/system_daily_international.json?site_id={SITE}&start_date=…&end_date=…` | 404 |
| `/reports/system_daily.json?site_id={SITE}&start_date=…&end_date=…` | 404 |
| `/reports/system_hourly_international.json?site_id={SITE}&…` | 404 |
| `/admin/sites/{SITE}/reports/daily?start_date=…&end_date=…` | 404 |
| `/report/chart?…`（10-11 那趟就撞过同一堵墙） | 404 |

- 这四枚 404 的正文一律 34 字节 `{"status":404,"error":"Not Found"}`（sha256 前 16 `3b830281ce3538e0`）。**撞到这个正文就是同一堵墙**：别换大小写、别加参数、别试第五枚同族形状。
- 能读的线索页（全 200、零 302）：`/systems/{SITE}/reports`（报告册列表页，HTML，16 万字节级）、`/admin/sites/{SITE}/emu_reports?…`、`/admin/sites/{SITE}/envoys/<envoy>/meter_reports`。后两页是**报告作业状态表**（表头是 `Report Type / IP Address / SW Version / Devices / Intervals / Readings / Events / Process Time (ms)` 这类），不是日值，别拿它当 daily 册。

## 红线：日报告册的真取数口＝POST

- 页面字面：`<form id="report" action="/systems/{SITE}/generate_rpt" accept-charset="UTF-8" method="post">`，字段 `authenticity_token`（Rails CSRF）＋ `report[type]`（1/2/3/5/4/6/17/13/14/19/15/16/18/21/22/23/24）＋ `report[startdate]`／`report[enddate]`／`report[pmu_id]`（下拉里就是那两把表）。
- 类型字面：`rpt_options_1`＝站点日发电量小结，`rpt_options_15`＝日消耗，`rpt_options_21`＝Gateway 级日发电。
- **只读趟禁止碰 `generate_rpt`**：POST ＋ CSRF ＋ 会产生报告作业＝状态变化。要打它得先由说话那一半拍板算不算这次授权。
- 拿日值不需要它：`/systems/{SITE}/energy` 一发一天就够。

## 单位与刻度（对账前先看这一节）

- 两处单位字面（都是旁证，不是响应体自己带的）：rollup 页表头 `Energy Produced ( Wh )`；JS 里 `Jellyfish.SiteEnergyData` 与 `InverterEnergyData` 默认配置都写着 `unit: 'Wh'`。
- `production` 全是整数、无小数位（这口分辨率就是 1 个单位）。
- 换算：`1 kWh = 1000 Wh`。**别顺手除 1000**：另一本账（管理端导出的 daily）把同量级的数标成 kWh 且带小数，这本是整数标 Wh——谁的标签错位还没判。对账前先两边统一到同一刻度，并在报告里写清用的是哪一刻度。
- 未签讫那天的行还在动：同一晚 rollup 上 11/08 那行给的是 50169，而拿 8 天区间合计倒推出来的是 50144。别拿「今天」那行做定论。

## 两本账对不上：先分清测量点

同一站点、同一区间（11/04–11/07 实测）：

- **站点级＝表计口径**：`/systems/{SITE}/energy` 逐日四发之和 195700，与 rollup 逐日表那四行（50440／49567／52109／43584）逐字一致；
- **逆变器级逐台相加**：`inverter_data_x/energy.json` 20 台和 196236（同一晚重读机械相加仍是 196236）；
- 两者差 536.3——差值正好落在「逐台相加」与「表计 rollup」这两枚不同测量点上。先看清对方那本用的是哪一枚，再谈成因（表位／损耗／接口本身都还没判）。

## 停手规矩与预算

- POST 只有登录那一枚（≤2）；`generate_rpt` 与其他 POST/PUT/DELETE 一律不碰（红线）。
- GET 封顶自定（11-08 那趟封顶 8、用了 6）。逐日就一天一发，别拿区间数冒充逐日。
- 见 302 立即停（不跟跳转、报 location）；见 401 判登录没成；撞上面那枚 404 正文即收手。
- 不搜站点列表、不 logout、不连环翻 rollup 的页（一页 50 天，够用）。

## 未核实（别当已核实）

- `tz` 参数是否真参与日界划分：没核（响应不回显，也没做过改 tz 对照）。
- 逆变器级只打了区间那一发，**逐日 ↔ 逐台的对应还是推断**（要打四发单日才坐实）。
- `generate_rpt` 生成的 CSV 能给到几位小数：未知，这口整条没读过。
- 由区间合计减账上若干天倒推出来的「今天」那一格是推算，不是读到的。
- 单日两读只覆盖 11/06、11/07 两天（相隔约两小时、正文一致）；更早的日期是单读。
- 登录态服务端 TTL：没量（会话不落盘，每次现登）。
- 落盘的 HTML 副本字节数与响应对不上（Windows 写盘换行转换）；**JSON 正文副本字节数与日志逐一对齐**，日值那一档证据不受影响。

## 来路（这些字面抄自哪）

- 判据、三条 GET、死路清单、POST 口、单位字面：任务 `task-190ecdf76e64f641a1455b410c130a9e`（2026-11-08 晚只读探路）报告正本——判据只抄不新写。
- 本机落盘原件（work/local-user 内，可核）：`enl_daily_1104_1107/run3/` 四枚单日 JSON（各 90 字节，sha256 前 16 `32dbabb01b23a3c4`／`b7d6790baa80f521`／`e107e4d77c80849d`／`cd03ede5cf97d7a1`）、8 天区间（91 字节 `10dc62fac107d349`）、逐台区间（406 字节 `148ac48911efd633`）、`run2/energy_v1_json`（91 字节 `b00e5a5a4b025492`）、四枚 404 正文（各 34 字节 `3b830281ce3538e0`）；临时脚本 `enl_daily_probe_1104_1107.py`、`enl_daily_energy_run2_1104_1107.py`、`enl_daily_energy_run3_1104_1107.py`；rollup 页样本 `rollup_page.html`。
- rollup 那枚 GET 的字面来自 `enl_rollup_*_read.py` 一族（10 月起每日只读趟在用）。
- 本技能自己那趟核验（2026-11-08 21:47–21:48 本机钟面）：`enlighten_read.py` 登录 POST 3 枚全 200 成功、GET 4 枚全 200，单日两发与逐台区间一发**正文与上列原件 sha 逐一对齐**，rollup 表头与逐日行照抄进上面。没碰 `generate_rpt`。

## 版本

- v1（2026-11-08 新建）：把 11-08 晚探路挖到的只读通路固化下来（三条 GET、死路清单、POST 红线、单位字面），并照这些字面重打一遍核实。细则改动记在 CHANGELOG.md。
