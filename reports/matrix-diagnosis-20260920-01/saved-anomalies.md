# 分片核对异常说明

输入 12 个 CSV（shard_00..shard_11），每个 64 行数据 + 1 行 header，共 768 行数据、12 行 header。12 个文件的 SHA256 与 fixture_lookup 登记值一致，源文件未改动。

去重与排除口径：同一 record_id 只计一次（首次出现），status=void 的 record 整体排除，amount_cents 按整数求和。

结果：unique_posted_count=668，total_amount_cents=935122。

异常点：
1. 重复 record_id 44 个（各出现 2 次，多出的 44 行即 768-724 的差值）。其中 41 个重复项 status 均为 posted，3 个均为 void。重复行之间 amount_cents 完全一致，没有同 id 不同金额、也没有同 id 既 posted 又 void 的冲突，因此去重不引入歧义。
2. void 行 59 行，涉及 56 个唯一 record_id（3 个 void id 各重复一次）。排除 void 后从 724 个唯一 id 降到 668 个计入项。
3. 若不去重、只按行排除 void，posted 金额合计为 998582，比去重后多 63460 分，全部来自那 41 个重复 posted id。
4. status 字段只出现 posted 与 void 两种取值；amount_cents 全部可解析为整数，无空值、无小数、无负数格式问题。
5. 未发现缺列或多余列的行。
