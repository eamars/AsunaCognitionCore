# ADR-106: the tests that keep her clock, by layer

正本来源：ADR-106 §Tests that earn their place（README 第 251–298 行）；本页列的是留下哪些测试、各守哪条规则。"替身层，随替身删"＝断言的宾语是替身对象本身，按 10-29 冻范围不算永久契约。

## Static

| Test | What it guards |
|---|---|
| `tests/test_one_zone.py`（1） | 扫 `src/asuna` ＋ `tools` 真源码，断旧解析一处不剩，且除 `schedule_rules.py`／`native_worker.py` 白名单外谁都不许自己读配置里的 `timezone`（写不算）。**hers**（页上第 1 条"没有第二个解析器"的唯一闸；它读真源码，不是替身） |

## Unit, on the in-memory store

| Test | What it guards |
|---|---|
| `tests/test_her_clock.py`（6） | 解析器各态：没设→`unset`／`UTC`、设 `TZ`→`machine`、宿主报的 `ASUNA_HOST_TIMEZONE` 排在 `TZ` 前、配置设了→`setting`＋`setting_unreadable=False`、载不进的时区名跳过并退回、空串算"没设"不算"坏了"；另两条钉"两个演示时区名不出现在她读到的四样东西里"与"到期计划块不给存储里那条 naive 的 `rule`"。`:59`／`:72`／`:88` 三条观测面＝假库＋时间桩。**hers**（页上第 2、3 条） |
| `tests/test_schedule_rules.py`（17，其中 15 条经 helper `her()`／`tz()`，真实调用点只有 `:20` 一处） | 纯函数：相对计时、`every`、过去的绝对钟点被拒、带偏移的绝对时间就是那个瞬间、DST 里不存在的本地钟点不猜、daily 按她钟面逐日、跨 DST 23h／25h 而钟面仍是 09:00、weekly 只在她点名的钟点、落在缺口挪到第一个有效瞬间、重复格取较早瞬间、墙钟钉成 UTC 后换钟面不变、`plan_zone` 按各自存的时区读、`clock_note` 说"比你的钟快 7 小时"且注里不出现时区名、`moved_from` 只在改计时时搬。**替身层 0。hers**（页上第 5 条）⚠ 计数口径：`__main__` 段 `:177-188` 在 `:191` 那条之前 `SystemExit`，单跑脚本只到 16 条，pytest 收 17 条。 |
| `tests/test_plan_zone_service.py`（7） | ScheduleService 走内存 store ＋ DSH 排程的记录式替身（页上 5b 本体）：daily 存她时区且不带 `tz_source`、一次性约会钉成 UTC 瞬间、同 `plan_id` 重发拿同一 `_id`、别人钟上的旧计划重报搬回她钟并 `plan_version`+1、已在她钟上的重报不改版本、只改文案不动钟、无墙钟规则换新计时不存任何时区、按它自己那条钟重新武装。**替身层断言 7 条，标"替身层，随替身删"：`:62`、`:65`、`:74` 后半、`:95`、`:108`、`:118`、`:132`**（同一用例里对库里文档字段的断言是永久的）。**hers** |
| `tests/test_dbread.py`（3，其中 1 条与本节相关） | `dbread.environment()` 交出的 env 恰好只有 `ASUNA_MONGO_URI`／`ASUNA_DATABASE`／`ASUNA_TIMEZONE` 三键，空配置＋`UTC` 交出空 dict。守"时区不外溢到环境"这条边界。**hers** |
| `tests/test_tool_watch.py`（5，只有 `:44` 那条经它） | action 路三种结局各在 `tool.time` 恰好留一条、`dispatch` 交回 `{'files': []}`、`flight` 清空。文件与用例保留；`:31` 那句 `monkeypatch.setattr(local_time, 'her_zone', lambda *a: None)` 只为让 `BusinessWorker` 跑得下去，三条断言没有一条断它的返回——**替身本体，标"替身层，随替身删"**。**hers** |

## Fixtures（不是用例，但全套都跑在它们上面）

| Test | What it guards |
|---|---|
| `tests/conftest.py:110-115` | autouse 抹掉 `TZ` 与 `ASUNA_HOST_TIMEZONE`（解析器会读它们；全套与 `tests/fixtures/world.json` 都按 UTC 假设），要钟点的用例自己设。**环境替身**，但它是页上 §Tests 开头明写的前提，删了其余各份在别的机器上就漂——留。 |

## 不进这张表的

| Test | What it guards |
|---|---|
| `tests/discussion_digest_cases.py`（20 条 `case_*`） | 里面 `FakeStore.config = {}` 是替身本体，零条用例引用 `her_zone`；**实测 pytest 不收这份文件**：`pytest --collect-only -q tests/discussion_digest_cases.py` → `no tests collected in 0.44s`（exit 5），加 `-o python_functions=case_*` 才收 20 条；整目录 `--collect-only -q tests` → `939 tests collected`，没有一行提到它。**随替身删，且它本来就不在 pytest 默认收集面里**（由 `tools/p1c_offline_check.py` 带起来）。 |

## Her rules, each to what holds it

| Rule | Held by |
|---|---|
| 「关于她签字的那句状态行只有她能改口径」 | `no test holds it`（文档侧规矩，11-02 起） |
| 「时区设置被清掉要告诉她」 | `no test holds it`；页上索引第 117 行写着这条归主人定（`The owner's call`） |
| 「替身层断言不算永久契约，要在表里标明」 | 本页的标法本身；10-29 冻范围 |
