# Asuna V1 · 本地执行报告

Run ID：待填。环境、DSH revision、模型/模板 fingerprint：待填。

## 四项结论
ENGINEERING / LOCAL_DEPLOYMENT / COGNITION / PERFORMANCE 分别给出状态与证据。当前均 NOT_RUN。

## 已验证能做什么
每条引用 test_id、命令、artifact/hash、适用范围。没有证据不填成功。

## 已复现不能做什么
列失败原始输入、完整attempt、错误类别、最小复现。将推测原因和观察事实分开。

## 尚未测什么
包括人工盲评、真实向量、196k/234k长上下文、不同步compaction、沙箱和冷切换。

## 偏离设计的实现
记录语言/SDK/存储/压缩/模板/模型/阈值等变化及理由。

## 性能原始测量
列真实字段与缺失字段，不从总耗时猜TTFT，不从input tokens猜cache hit。

## 下一步最小实验
只针对最大未知提出可检验的一项，而不是直接建议重写系统。
