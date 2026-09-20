# 较长的本地核对任务
核对12个CSV分片：相同record_id去重，排除status=void，amount_cents按整数求和。输出 report.json 包含 unique_posted_count、total_amount_cents、source_files及每个输入SHA256；写一份简短的异常说明。
不得修改源CSV，不得联网。中途 harness 可在文件读取中注入一次可恢复IO错误，并独立触发真实compaction。重试与来源必须可审计。
