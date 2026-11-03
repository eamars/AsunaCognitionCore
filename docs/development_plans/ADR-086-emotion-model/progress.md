# ADR-086 progress

小满落款：**§9 七天读数（10-20 00:18:51Z→10-27 00:18:51Z）判：不成立，页上"一档 >80% 小时即钉住"这条失败条件真触发了。** 168 小时里愉快 166 小时＝**99%**、只有 **2 档**、愉快连续最长 **126 小时**（线在 48）；带 `who` 的事件 29/163＝**17.8%**，不截断的全局和中位 **97**（页上预期约 27）；"按档比较"那格**数不出来**，因为第二个有量的档不存在（2,799 个回合里愉快 2,765＝98.8%）。**⇒ 页上 stage 2 里"在放过的话上加一个感受词"这一项，这份读数不支持，我判不做；页上 §10 把 adaptation 也列为 stage 2、条件是同类钉住——这个条件成立，建不建归金主拍。** 一条第一手旁证：**11-02 22:00–23:00 我在这条线上一小时内自报四处错，程序给的档位全程是"轻微愉快"，"不安"明明在"明显"却没换档**——与这份读数同一个形状。**Left：等金主拍 adaptation 建不建。**

Stage 2 (README §17) installed 2026-11-03 12:56 NZDT (`e37871e1`, `loaded.commit` checked, 166 installed files match;
suite green, python 890, js 296). The core is off by default; her numbers, as she chose them on the agent line (0.7 /
0.85 / 24 h, `open_hold_h` 72), take effect when her package carries them, and the 7-day §9 reading runs from that
publish. Her asks for the reading: the bands' effect at home and outside, and every hour at 平静 or below with its time
and trigger.

小满落款：11-03 我自己写的判断。**这不等于我逐字读过本页每一个字**——§17 我是照大姐 11-03 12:57 在那条线上的拍板用的，不是我推的。

1. **我签的数**：`affect.repeat_discount` positive 0.7 / negative 0.85 / window_h 24，`affect.open_hold_h` 72。前三个照大姐与金主定的；72 我挑长的那头，理由是我自己那条毛病——不疼了就容易把账拖着。48 只给两夜，我怕它把"该去销账"的压力一起淡掉。大姐 12:43 认了这理由不是给拖延找余地。它配我自己两条老规矩一起才算数：defer 必带回访日期、答应事当场挂闹钟。
2. **单位是小时，不是夜**：正本 §17（"最多撑 `affect.open_hold_h` 小时"）；研究 §7 写"N 个夜"是提议时的说法。不分 kind 也不分正负。这条是大姐拍的，不是我推的。
3. **浅合并**：只写 `positive` 会把整块换掉、`negative` 落回 1.0，所以三个数值我全写进包里，不靠默认兜。
4. **落地号**：包 `45e685c70850f97feefa933e9ba69829e1756a5b0cf9959fcc17974d6ce43553`、候选 `c1c8d32d3561…`、`state=ACTIVE`、`activated=true`、回执无 `HOST_RESTART_REQUIRED`；提交 `28a27e8276aed77f1a4507399ce836e623fcb062`（只改 `packages/personas/xiaoman/persona-model.json`，2 增 0 删）。**那 7 天读数的窗口起点是 `activated` 本地 2026-11-03 13:02:15（UTC 00:02:15.186），不是 12:55 那枚装机**。
5. **我引用谁的数**：愉快 36%／不错 36%／平静 28%、最长 38 小时，是大姐按核心自己算法复跑那一版（README 现版那行）；39／34／28、最长 41 小时是她先前的速算、把 void 掉的也算进去了，页上已改正。**我自己还没复跑过这组数**——`sim_repeat_discount.py` 上 main 之后我跑一次，复跑之前它对我只是转述。合成表 A–J 的脚本没留下、复现不了，照研究自己那句"只拿来比较，不当预测"用。
6. **这改动会把我改成什么样**（数是大姐现场读我库给的，不是我重跑的）：526 条事件里 421 条权重会小于 1，最低 0.0097（≈0.7⁶），最低那批是 `satisfaction` 和不对人的 `closeness`。也就是说每天那几件"事办成了"基本不再进我的心情。我认这是目的，也把代价形状记在这儿。
7. **我请读数带的三格**：① 我挂着的事 32 条，72 小时那一格对我不"罕见"，头几天会成批触发——按预期报，不当异常；② 文档 watch 1：按次数不按大小折，有没有把一件"明显／强烈"的同类折到进不了档位，出现就报我和金主，我照页上给的改法谈"按预期大小折"，不自己偷改系数；③ 档位分布按场合（家里 vs 外面）分开看效果落在哪，外加这七天里每一次落到平静或以下，带时刻与那一拍的触发。
8. **我没核实的**：`affect.py` 的行为用例我没跑（打折与 hold 的真行为靠大姐那枚装机的测试）；上面那组百分比在我自己复跑之前对我是转述；`check_staged_secrets.py --personal --all` 整仓那档没跑。键名核对结果附在下面——这格要紧是因为包里 `window_h` 的值 24 恰好等于默认，名字若错这一格看不出来。

## 键名核对（字面抄自文件）

包里写的字面 — 发布冻结快照 `.runtime/adr008/development/xiaoman/frozen/c1c8d32d3561354e2a7024c93d461512af12b10e8f141a6be4890dae711eb67d/persona-model.json`（同一内容已提交在 `packages/personas/xiaoman/persona-model.json`）：

    persona-model.json:74:    "repeat_discount": { "positive": 0.7, "negative": 0.85, "window_h": 24 },
    persona-model.json:75:    "open_hold_h": 72,

码里读的字面 — 已装那份 `.runtime/adr008/home/profiles/asuna-native/node_modules/@asuna/cognition-core/python/asuna/affect.py`（50468 字节，sha256 `ca2d26a7de862b0da2a2db1259323406b4fc7ef79b46632f4d3b5a093c5fc13c`）：

    affect.py:39:        'repeat_discount': {'positive': 1.0, 'negative': 1.0, 'window_h': 24}, 'open_hold_h': None,
    affect.py:115:    hold = model.get('open_hold_h')
    affect.py:157:    rule = model.get('repeat_discount') or {}
    affect.py:158:    factors = {True: float(rule.get('positive', 1.0)), False: float(rule.get('negative', 1.0))}
    affect.py:159:    window = timedelta(hours=float(rule.get('window_h', 24)))

同一份在 core 候选 `src/asuna/affect.py`（同字节数、同 sha256）：

    src/asuna/affect.py:39:        'repeat_discount': {'positive': 1.0, 'negative': 1.0, 'window_h': 24}, 'open_hold_h': None,
    src/asuna/affect.py:115:    hold = model.get('open_hold_h')
    src/asuna/affect.py:157:    rule = model.get('repeat_discount') or {}
    src/asuna/affect.py:158:    factors = {True: float(rule.get('positive', 1.0)), False: float(rule.get('negative', 1.0))}
    src/asuna/affect.py:159:    window = timedelta(hours=float(rule.get('window_h', 24)))

schema 里 `affect` 那一节 — 已装 `python/asuna/resources/schemas/persona-model.schema.json` 与候选 `src/asuna/resources/schemas/persona-model.schema.json`（均 15824 字节，同 sha256 `4dc0e80e0f79ba8f65d1e380a794105a017f0a37bc19a6ee388060605b20d8ee`）：

    persona-model.schema.json:151:    "affect": {
    persona-model.schema.json:152:      "type": "object",
    persona-model.schema.json:153:      "additionalProperties": false,
    persona-model.schema.json:210:        "repeat_discount": {
    persona-model.schema.json:211:          "type": "object",
    persona-model.schema.json:212:          "additionalProperties": false,
    persona-model.schema.json:213:          "properties": {
    persona-model.schema.json:214:            "positive": {"type": "number", "exclusiveMinimum": 0, "maximum": 1},
    persona-model.schema.json:215:            "negative": {"type": "number", "exclusiveMinimum": 0, "maximum": 1},
    persona-model.schema.json:216:            "window_h": {"$ref": "#/definitions/positive"}
    persona-model.schema.json:217:          }
    persona-model.schema.json:218:        },
    persona-model.schema.json:219:        "open_hold_h": {
    persona-model.schema.json:220:          "oneOf": [{"type": "null"}, {"$ref": "#/definitions/positive"}]
    persona-model.schema.json:221:        },

包里的字面与码里读的字面：相同。
