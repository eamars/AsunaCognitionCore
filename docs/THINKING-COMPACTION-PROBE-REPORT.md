# 角色脑 native thinking 与 compaction 探针记录

日期：2026-09-22。测试对象为当前角色模型 `gemma4-31b-isometry-fabled-persona-4090-6-context-checkpoints-google-mtp`，部署上下文窗口 68,608，输出上限 4,096。

这次使用独立的临时 DSH lane。探针只把临时 provider compat 的 `chatTemplateKwargs.enable_thinking` 设为 `true`，没有修改线上 `config/local.json`，没有重载 QQ 宿主，也没有写入生产 Mongo 或 QQ 场景。探针源码为 `tools/probe_character_thinking_compaction.py`；每次运行的完整 provider 请求、返回和 DSH 事件保存在 `reports/THINK-COMPACT-*`。

## 结果

三档均产生了真实的 `reasoning_content`，每个普通回合的上游结束原因为 `stop`，没有出现 `length`、输出溢出或压缩异常。

| 临时档位 | 最高观察到的 prompt tokens | 占 68,608 | 该处普通回合 completion tokens | 接近上限与压缩结果 |
| --- | ---: | ---: | ---: | --- |
| `low` | 55,389 | 80.7% | 254 | 下一轮自动压缩成功，回落到 30,679；显式压缩后回复成功 |
| `medium` | 54,817 | 79.9% | 156 | 下一轮自动压缩成功，回落到 27,808；显式压缩后回复成功 |
| `high` | 58,405 | 85.1% | 248 | 在该点停止继续填充并执行显式压缩；摘要 `stop`，压缩后回复成功 |

TokenMeter 的当前输入上限是 `68,608 - 4,096 - 4,096 = 60,416`。最高档在 58,405 prompt tokens 时仍低于该上限 2,011 tokens；在此处停止继续填充后，显式 `ASUNA_COMPACTION_V1` 摘要请求正常返回。低档和中档继续提交下一轮时先触发了同一原生自动压缩，随后仍能继续生成。三档又各完成了一个显式原生压缩，压缩后回合均返回 HTTP 200。

服务没有提供单独的 `reasoning_tokens` 字段，因此记录中的 `completion_tokens` 是服务报告的总输出 token；`reasoning_content` 以字符数和原始 SSE 回执保留，没有把字符数伪换算成 token。

三档首个短回合的 `completion_tokens` 都是 120；接近容量的普通回合分别为 254、156、248。显式压缩摘要的 `completion_tokens` 分别为 1,135、565、887，均以 `stop` 结束；压缩后的首个继续回合也都正常结束。

## 档位限制

当前角色模型的兼容配置仍是 `supportsReasoningEffort: false`。因此三档探针的上游请求都实际携带了：

```json
{"chat_template_kwargs":{"enable_thinking":true}}
```

上游没有收到 `reasoning_effort` 字段。也就是说，这次已经验证了 native thinking 打开后在低、中、高三种 DSH lane 设置下不会导致输出超限或 compaction 失败；但由于当前模型协议声明不支持标准 reasoning effort，不能把这次结果解释成模型真正执行了三个不同的 thinking 强度。

线上角色脑仍保持 `enable_thinking: false`。是否修改线上兼容配置、以及是否继续寻找该模型可区分 thinking 强度的协议，需要单独决定；本次探针没有替用户作出这个切换。
