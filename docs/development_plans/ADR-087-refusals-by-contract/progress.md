# ADR-087 progress

小满落款：**窗 10-21 23:36:40 NZDT（`ed8b0b8f61bd`，core `82bc9909acb2`）起：第 1、2、4 步读数以页上字面为准。** 窗内 9,343 次调用、被拒 1,101（**11.8%**，页上旧基线 8.1%，不可比，照实记）。**第 1、2 步我签"未触发失败"**：think 被拒 **116/2,925＝3.97%**（门槛 5%）、超 120 字照收 1,689 次、最长 359 字；THINK_FIRST 208 条（页上旧基线 110）里**指向清单上读类工具的 0 条**。**第 3 步（host 检查类拒被换成"不想帮"）是我欠的读数**，我自己补。**第 4 步判"等实现"**：三类目标拒都低于基线（16/23、5/17、16/22），**但 `unclassified` 从基线 1 涨到 185**，一看前缀就是我改过措辞而 `.runtime/private/refusal-research/classify.py` 没跟上（"送到家里的便条要求 240 字以内"38 条那类）——这条**不算我不交**。**Left：欠小满第 3 步读数，11-05 回看；第 4 步等 `classify.py` 更新后重数。**

小满落款：**第 3 步读数交回（2026-11-05 21:08 NZDT 跑动）。判：按页上字面触发。** 生效时刻没有任何记录点名 `df1bd6b5d1169500a2a1d58b538265b1d46036c4`；按祖先关系绑到 `restart-20261021124153`，`back_at` 2026-10-21T12:42:23.610Z ＝ 本地 10-22 01:42:23 NZDT（`merge-base --is-ancestor` rc=0；上一条装的 `ed8b0b8f61bd…` 不含它）——**这条是推论，不是记录字面**，那次装的包 `…8e86c75059e7.tgz` 已不在 packages，我没亲眼打开它。三类各带分母：页上基线 argument check 13／DSH validation 10／unexposed 28（51 条／周）；装后整周 10-22→10-29 是 83／0／9（92／9,343＝0.98%）；最近一周 10-29 21:08→11-05 21:08 是 19／0／14（33／5,797＝0.57%）。脚本自己那侧的装前整日窗是 11／23／30（64／8,425＝0.76%），与页上基线的窗边不同，两个数都留着不合并。**涨的只有 argument check 那一类**（13→83，每千次调用 1.3→8.9，主力 `write_document` 7→50），DSH 与 unexposed 都按页上预期降。**形状不是稳态**：最近一周回落回 19，与基线 13 同量级。归因不干净——同周还装了 ADR-084 step 7（~10-27）与 ADR-086（10-28），页上写着读数可重叠、重叠不豁免。**我不判回退**（页上第 3 步没写失败动作），判"触发、非稳态、归因未定"。第三条失败线我这边报两条真样本：11-04 在公开群 `delegate` 带 `for` 被 `FOR_UNKNOWN_HERE` 拒（这一条看着正是这步收窄的形状）；11-05 21:00 计划拍给旧件补话被「这一回合的授权和原来那件事不一样」退（这一条像 ADR-111 那族按拍给授权，不像 specs 收窄，我照字面记数、成因留给金主判）。**Left：欠小满一格——把装后窗的 argument-check 拒按工具＋字段拆开，看涨的是不是这步移除的那三类 option（`note.deliver` 23、`ideas` read/review 10、`question` 0，都在公开群），11-12 之前给。**

`classify.py` updated for step 4's recount, 2026-11-07: a refusal's code is read first (every refusal carries one
since ADR-108's install, 11-07 15:06 NZDT), then the wording, now including the wordings changed after 10-21; a
refusal that lists several problems counts as its first. Over the 2,046 refusals from 10-21 23:36 to 18:05, 14 stay
unclassified, and 14 more carry a code no rule names and are counted as `code:<CODE>`. Before 15:06, 800 of 2,039
rows already had a code.

小满定的取法（11-07 18:05）：两段各报各的分母，旧段 10-21 23:36 → 11-07 15:06，新段 15:06 → 判读时刻，两段的率不合成一个百分数；
旧段有码的按码、没码的按措辞，新段全按码，每类写明多少靠码、多少靠措辞；合并拒按第一处算一条；`code:<码>` 单列，不并进「其他」；
「没分上的从 323 降到 14」量的是脚本认词，不是成因分布；「多少条落在『不想帮』」数不出来，不造数；新段个位数样本只报数、不判形状。
**Left：小满的第 4 步重数，最迟 11-07 20:30 那一拍派出。**
