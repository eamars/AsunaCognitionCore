# CHANGELOG

## v1（2026-11-08 新建）

- 新建「账号自治站点」技能：Enlighten（Enphase 云端光伏报表，员工号只读）。形状照 bilibili／lofter 那一族：SKILL.md ＋ 读取脚本 ＋ check_skill.py ＋ 本 CHANGELOG，`scene_kinds: [home]`。
- 动机：想法本 `idea-5eae647ae093b7319d834eebdf52bd9c`（11-08 晚探路那趟记的）——把已核实的三条 GET、死路清单、POST 口与单位字面固化下来，省得每月对账重挖一遍 4.9 MB 的 `manager_assets/e3_basic.js`。
- 判据只抄不新写，正本＝任务 `task-190ecdf76e64f641a1455b410c130a9e`（2026-11-08 晚只读探路）报告：① 登录成功判据 `message=success` ＋ `session_id`，凭据走保险箱名字 `enlighten`（env 只有 `ENLIGHTEN_EMAIL`／`ENLIGHTEN_PASSWORD`，正文不写值）；② 三条只读 GET（rollup 逐日表／`/systems/{SITE}/energy`／`/systems/{SITE}/inverter_data_x/energy.json`）含参数与 `tz` 写法；③ 死路清单四枚 `/reports/*` ＋ `/report/chart` 全 404；④ 日报告册真取数口＝POST `generate_rpt`（带 CSRF、算状态变化）＝只读趟红线；⑤ 单位字面 `Energy Produced ( Wh )` 与 JS `unit: 'Wh'`，加 Wh↔kWh 换算提醒。
- 新写 `enlighten_read.py`（`login`／`day`／`range`／`inverters`／`rollup`；只发登录 POST 与 GET，永不发 `generate_rpt`），并照正文这些字面真跑一趟核实（2026-11-08 21:47–21:48 本机钟面）：登录 POST 3 枚全 200 且判据两条同现（`session_id` 实测 32 位）、GET 4 枚全 200；单日 11/07 与 11/06 正文与 11-08 那趟落盘原件 sha256 逐一对齐（相隔约两小时的第二次读），逐台区间一发 likewise（196236），rollup 表头与逐日行照抄进正文。没碰 `generate_rpt`。
- 这一趟带回两条新读数写进正文：① 11/06、11/07 两天算有了两读（正文一致）；② 未签讫那天的 rollup 行还在动（同一晚 11/08 那行 50169，与拿区间合计倒推的 50144 不同）。
- 账号事实的处理：站点 id 实测命中本机私密词名单（第 22 行，category=site），表计 id 与逆变器序列号同族，全部不进正文与脚本——正文只有 `{SITE}`／`{METER}` 占位符，脚本从环境变量 `ASUNA_ENLIGHTEN_SITE`／`ASUNA_ENLIGHTEN_METER` 拿。`check_skill.py` 里含裸 7+ 位数字形状检查与私密词名单扫描（名单没配上就 SKIP 并明说）。
