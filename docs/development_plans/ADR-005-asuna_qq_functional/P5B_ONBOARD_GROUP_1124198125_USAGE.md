# P5-b：接入群 1124198125 ＋ Web 上把「程序拦下」和「角色选择沉默」分开

这一片做两件互相独立的事：

1. **接一个群**：QQ 群 1124198125（基础情感的Agent交流群）进 adapter 路由与宿主通道路由，
   并在这个场景打开 P5 的主动参与开关（`proactive` 块）。范围只有这一个群。
2. **修一处显示失真**：被 P5 程序闸门拦下、根本没建角色 episode 的那条入站，Web 检查器
   显示「本轮已结束 / 没有公开回复」——这句话把程序的闸门决定说成了角色的决定。

改动只有 `src/asuna/ui.py` 一个产品文件；其余是配置件与自检。

## 1. 为什么会显示错

旁听行的落库链是这样（P5 之前就这样，P5 只多写了一个字段）：

| 这一行停在哪儿 | 行上的字段 | P5-b 之前 Web 显示 |
| --- | --- | --- |
| 没开主动模式的旁听行 | `processing_outcome=RECORDED_NO_WAKE` | 无本轮状态（对） |
| **P5 闸门拦下** | `processing_outcome=PROACTIVE_HOLD`＋`proactive.holds` | **本轮已结束／没有公开回复**（错） |
| **P5 入队后再核拦下** | `PROACTIVE_HOLD`＋`result_state=PROACTIVE_HELD`＋`proactive.recheck_hold` | **本轮已结束／没有公开回复**（错） |
| 刚落库／正在准备 | `ingress_state=ACCEPTED／PROCESSING` | **本轮已结束／没有公开回复**（错） |
| 角色跑过一轮、自己选了沉默 | episode 上有 `silent_reason` | 角色选择不发言（对） |

`ui.py` 里那份内联投影只认 `RECORDED_NO_WAKE` 一个值，其余一律不带信息地进 `turn_status()` 的
`else` 分支。P5 一开，旁听行多写了 `PROACTIVE_HOLD`，就正好掉进这个 `else`。

## 2. 改了什么

`src/asuna/ui.py`：

- 新增 `ingress_projection(row)`：把「还没有 episode 的入站行」投影成本轮状态需要的最小事实
  （`ingress_state`、`processing_outcome`、`result_state`、`proactive` 里的 `holds／recheck_hold／wake／decided_at`、`failure`）。
  `_snapshot` 里原来那份内联字典换成调用它——整块 `proactive`（20 多个中间量）不进 Web 负载。
- 新增 `program_hold(ep)`：只根据程序自己写下的字段判断「这条是闸门拦下的」，产出
  `label=程序拦下 · 未进入模型` ＋ `detail`（逐条列出拦下的闸门，已知名字给一句人话、原始 gate id 原样带出）
  ＋ `kind=program_hold` ＋ `holds`。再核拦下的那条以 `recheck_hold` 为准，并说明「入队时闸门还开着」。
- `turn_status()` 的分支顺序：`no_wake` → 运行中阶段 → `silent_reason`（角色选择沉默，口径一个字没改）
  → 失败 → **程序拦下** → 行动排队／处理中 → 行动反馈 → **还没轮到（ACCEPTED／PROCESSING）** → 兜底
  「本轮已结束／没有公开回复」。兜底那句现在只剩真·跑完且没说话、又没写原因的 episode 会命中。

不给角色规定固定发言内容：新文案只说程序做了什么（没建回合、没调模型、被哪条闸门拦下），
不出现「该说／应该说／说点什么」这类暗示；自检里有一条专门盯这个。

## 3. 应用步骤（机械执行）

1. **产品代码**：`patch -p1 < P5B_ONBOARD_GROUP_1124198125.patch`（只碰 `src/asuna/ui.py`、`tools/`、
   `config/`、这一份文档）。然后 `python3 tools/p5b_ui_offline_check.py` → 24/24；
   `python3 tools/p5b_ui_offline_check.py --baseline --src <改前的 src>` → 5/5（反证）。
2. **宿主通道路由**：把 `config/group-1124198125.host-route.fragment.json` 整个对象贴到
   `asuna-channel.local.json` 的 `channels.qq.routes["group-1124198125"]`。
   `route_id` 必须与 adapter 那边同名（宿主按 `route_id` 收事件）。
   `members[*].workspace` 照现有四条群路由的写法（只要求落在 `.runtime/channels` 下且互不包含）；
   `identities` 与 `scenes` 行由 `prepare_channels` 自己建，不用手写。**重启宿主**才生效。
   这个块里的 `proactive` 就是 P5 触发开关：删掉它＝这个群回到纯旁听，没有需要迁移的状态。
3. **adapter 配置**：把 `config/group-1124198125.integration-adapter.patch.json` 按 RFC 7386 打在
   `integration.local.json` 上（`allowed_group_ids` 是数组、整份替换，所以里面列全 5 个群；
   `routes` 只新增一条）。profile 变了，恢复会被要求显式启动：`integration_stop` → `integration_start
   python3 /app/adapter.py --service`，然后看 `CONFIG ... allowed_groups=` 里有 1124198125、
   `group-1124198125:17`，`STATUS group_routes=5`。
4. **核对**：`python3 tools/group_1124198125_check.py --config /integration/config.json
   --adapter-src /app --src <宿主 src>` → 23/23。之后在群里发一条 @ 她的消息，按既有链路
   应当出现 `INBOUND_SPOOLED scene=group group=1124198125` → `INBOUND_ACCEPTED` →
   `SEND_RESULT target=group status=platform_accepted`。

## 4. 这份配置里的判断，以及谁可以改

- **成员快照 17 人**：`get_group_member_list` 当时返回 18 行，去掉本账号 3768713357（自己发的
  消息 adapter 先丢，不需要授权）。留档在 `config/group-1124198125.member-snapshot.json`，
  含平台给的昵称／群名片／身份：群主 3074196903，管理员 2767775344／673225019／1393973776／1052754704。
  新人入群不会被自动放行——照现有四个群的口径，快照是显式授权，要改就改这一份。
- **`operator_sender_id=673225019`**：本机 owner 的 QQ，在这个群是管理员，与其他四条群路由用的是同一个。
- **`utc_offset_minutes=480`**：安静时段按群员大概率的钟点（UTC+8）算 23:00–08:00。宿主机器在新西兰
  （UTC+12／夏令时 UTC+13），不填这个值就按宿主本地时区判；想按机器钟点就删掉这一行，想按机器时区
  的偏移就填 720。这是唯一一个「我替你选了、你可能要改」的值。
- 其余形状参数（10 秒合并连发、120 秒同场景最小间隔、180 秒两次询问的间隔、每小时 2 次、
  30 秒密度线、紧急线索词）与 P5 交付文档里的默认值一致，没有为这个群特殊化。

## 5. 自测口径与没做的

- `tools/p5b_ui_offline_check.py` **24/24**（无 Mongo／无 pytest／无模型／不联网）：真行形状进
  `ingress_projection` → `turn_status`，覆盖 P5 拦下、再核拦下、模型沉默、没开 P5 的旁听行、
  刚落库／正在准备、失败优先于拦下、没见过的闸门名不编解释、空名单不冒充原因、投影负载有界、
  老形状行为不变、被唤醒的 episode 与既有分支不受影响、不给角色规定固定发言内容，
  外加一条把 `HOLD_GATES` 与 `proactive.py` 源码里的闸门名单对账（P5 以后加闸门而这里没跟上会先红）。
  `--baseline` 反证 **5/5**：改之前那三条行在 Web 上确实都显示「本轮已结束／没有公开回复」。
- `tools/group_1124198125_check.py` **23/23**：adapter 侧用真 `qqadapter.config` 校验器验补丁
  （含「没打补丁时这个群是关着的」「只开这一个群」「原有四条路由与 owner-dm 一个字没动」
  「今天真在这个群发过言的 4 个人都在快照里」「同期在刷的 227608960 仍然没路由」）；
  宿主侧用真 `prepare_channels` 与真 `proactive.route_settings` 验路由片段与 P5 开关
  （含「删掉 `proactive` 块就回到 `not_enrolled`」）。宿主侧不需要 Mongo／Windows：
  `httpx／pymongo／msvcrt／deepseek_harness` 这些只在 import 时碰一下的模块用假模块顶掉，
  被检查的函数是宿主源码本身。
- **没做的**：没动 adapter 一行代码（群路由本来就是配置驱动）；没动 P5 的闸门语义；
  没给 Web 前端加新样式（`kind=program_hold` 只是留在数据里，前端想区分颜色随时可用）；
  没打开第二个群；没往 `proactive` 块里塞任何「该说什么」的内容参数。
- **还没核实的**：真群里的第一次收发（要等 owner 应用配置＋重载之后）；Web 前端拿到新 `label`
  之后的实际渲染（前端在 `node_modules/@deepseek-ai/dsh` 里，不在我的授权目录内，
  我只保证 `turnStatus.label／detail` 这两段文字本身是对的）；安静时段按 UTC+8 还是按机器时区，
  要 owner 定。