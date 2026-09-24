# P3 日常自由定时：用法与边界

对应 DELIVERY_PLAN「P3：日常自由定时」与 ACCEPTANCE Q5。这份只写这次真改了什么、怎么自测、
哪些还等宿主核实；不替角色写台词，也不把\"她听懂了\"当成已验证事实。

## 1. 这次开的是什么

她在 DECIDE 里给意图＋计时，程序换算成一次原生提醒。四种计时：

| 写法 | 意思 | 原生那边 |
| --- | --- | --- |
| `after_seconds` | 一次性，N 秒后 | 单次（原生） |
| `every_seconds` | 固定间隔重复，最小 300 秒 | 重复（原生自己重复） |
| `at` | 一次性，某个本地钟点（或带偏移的绝对时刻） | 单次 |
| `clock` | 每日/每周本地钟点（`weekdays` 用 0=周一…6=周日） | 每次到期后再挂一次单次 |

查看、改期、取消都走自然语言＋现有 Web 计划记录：`plans_from_program` 里给她带 `_id`、人话规则、
这个场景时区的下一次钟面，她不需要抄 ID，也不需要自己拿 UTC 心算\"明天九点\"。

## 2. 一句话的走法

1. `context.py` 把 plans 行投影成她看得懂的样子（`schedule_rules.project`），并附一份
   `schedule_control_from_program`：现场钟面＋三个控制字段怎么写。
2. 她给 `schedule` / `update_plan` / `cancel_plan_id`；`coordinator.py` 只判形状（JSON Schema），
   换算与判定全在 `schedule_rules.py`。
3. `schedule.py` 落一行 plans（存**本地钟点规则**，不是换算死的 UTC），再向 DSH 原生挂那一次钟点。
   到期回调仍走原来的 `_deliver_locked → controller.receive`，唤醒理由 `scheduled_plan`。
4. 每日/每周到期后由 `_rearm` 再挂**一次**原生单次。这里没有线程、没有轮询、没有第二个时钟：
   日期换算在 `schedule_rules`，计时仍然只有 DSH 一个。

## 3. 时区读哪个

优先级：这条计划创建时记下的时区 > 群/私聊 route 的 `schedule.timezone` > 场景行 `timezone` >
顶层 `timezone` > 默认 `Pacific/Auckland`（与 DECISIONS §6 一致）。改配置不追改旧安排——旧计划
按它创建时那个钟面走，`tz_source` 里写着这条是从哪儿来的，投影里一并给她。

route 里可以这么写（与 `proactive` 同一层，同一个场景一个钟面）：

```json
"routes": {"g905": {"scene_id": "...", "schedule": {"timezone": "Asia/Shanghai"}}}
```

**时区库读不到时不猜**：`zoneinfo` 取不到那个 zone 名时，若 route 里另给了 `utc_offset_minutes`
就按固定偏移算（`tz_source=fixed_offset`，这一条没有 DST 规则）；连偏移都没有就退到宿主本地时区
（`tz_source=host_local`）。两种降级都会在投影里写 `timezone_note`，她看得见\"这条是按固定偏移算的\"。
宿主是 Windows 且环境里没有 `tzdata` 时就会走到这里——这是有意留的台阶，不是静默出错。

## 4. DST 的确定性例子（Q5 要的）

场景时区 `Pacific/Auckland`，2026-09-27 当地 02:00 拨快到 03:00，2026-04-05 当地 03:00 拨回 02:00：

- 规则 `clock 09:00` 在 09-26 响于 `2026-09-25T21:00Z`（+12），下一次响于 `2026-09-26T20:00Z`
  （+13）：**本地仍是 09:00**，两次间隔 23 小时。跨回拨那天间隔 25 小时，本地还是 09:00。
- 规则 `at 2026-09-27T02:30`（那个钟点不存在）→ 明确拒绝，报 `SCHEDULE_LOCAL_TIME_MISSING`
  并提示\"那天 02:30 不存在，要不要 03:00\"，不自己挑一个时间。
- 每日 `clock 02:30` 撞上空档 → 顺延到那天第一个真实存在的钟点 `03:00 NZDT`（`2026-09-26T14:00Z`），
  投影里带 `dst_note` 说明顺延了多少。
- 回拨日 `at 2026-04-05T02:30` 出现两次 → 取**较早**的那一次（`2026-04-04T13:30Z`，+13）。

这四条都是 `tests/p3_schedule_cases.py` 里的真断言，跑的是系统 tzdata 的真规则，不是 86400 秒。

## 5. 改期与取消：为什么不会多出两个版本

改期在**同一行 plans** 下换掉底层提醒：先建新、再删旧，`plan_version` 推一版。派发时如果来的那一次
对不上当前 `schedule_id`，只记 `STALE_PLAN_VERSION` 不产生行动——所以\"建新成功、删旧失败\"这个窗口
里多出来的那一条也不会让她动两次。取消就是删原生那一次＋状态落 `CANCELLED`＋清 `next_fire_at`，
`reconcile` 只认领/重挂 `ACTIVE` 的行，不会把取消的复活。到期与取消撞在一起时以取消为准：刚挂上的
那条会被删掉。

## 6. 停机、错过与失败

沿既有 latest-only：错过不补发。停机期间原生派发过一次，回来 `reconcile` 只补做那一次行动，
然后把下一次挂到**未来**的钟点（不会为过去三天各响一次）。一次到期没排进队列，只记在这条计划的
`last_outcome` 上，下一次登记照挂、这个场景的聊天照走。换算类拒绝（时间已过、钟点不存在）记在
本轮 `plan_result`/`plan_update_result` 的 `error` 里让她能回话问一句，不把整轮聊天打死。

## 7. 自测口径

```text
python3 tools/p3_offline_check.py            # 零依赖：编译＋37 条用例＋两份基线反证
python3 tests/p3_schedule_cases.py           # 只跑用例（假集合＋假原生 lane 真算）
python3 -m pytest tests/test_p3_schedule.py  # 真 Mongo 那一层（操作员跑，见文件头）
```

本机（Linux，有 tzdata）实跑结果：离线用例 **37/37 通过**。这批用例跑的是真文件：`schedule.py`
的 create/update/cancel/deliver/reconcile、`coordinator.py` 的真 JSON Schema 与 `_plan_control`、
还有 `context.py` 的真 `prepare`（她拿到的计划行与现场钟面就是这么投影出来的）。

反证 A（改动前的驱动＋新换算模块）18 条变红，红的都是驱动、接线与 schema；反证 B（纯基线）37 条
全红，因为换算模块本身是新增。真 Mongo 那份（`tests/test_p3_schedule.py`：真集合校验、真 CAS、
真审计流）本机没有 pymongo/bson，**还没跑过**，等操作员在宿主上跑。

## 8. 还等宿主核实

- 原生 `/schedule/delete` 是否往事件日志里记一条 `delete`：认领与\"还活着\"的判定按\"记\"写的；
  若不记，取消后重启可能把那条当成还在（多挂一次），不会导致重复行动。
- `/schedule/create` 响应确切字段：现在只认 `id`，拿不到就报 `NATIVE_SCHEDULE_CREATE_INCOMPLETE`，
  不会当成功。
- Windows 宿主上 `zoneinfo` 能不能取到 `Pacific/Auckland`：取不到就走 §3 的降级台阶，
  投影与审计会写明 `tz_source`。要按命名时区跑（含 DST），要么装 `tzdata`，要么 route 里给
  `utc_offset_minutes`。

## 9. 有意没做的

不做 cron 表达式、不做\"每月最后一天\"这类日历规则（原生没有，薄映射也不该自己长成日历）；
不给原生加 update（它没有这个口，改期就是换一次底层记录）；不在宿主侧起任何轮询或线程定时器；
不补发错过的次数；不让计划到期自动获得新授权——到期只是把她叫醒，做不做仍由她判断。
