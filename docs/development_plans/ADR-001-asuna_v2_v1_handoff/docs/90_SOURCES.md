# 90 · 资料来源、证据边界与本地待核实项

核对日期：2026-09-19。外部来源均为项目官方仓库/官方文档。下列链接指向核对时的分支页面，不视为已经固定的本地安装 commit；Codex 阶段0必须保存实际 revision/lockfile。未取得用户本地运行权限，不声称测试了 endpoint 或数据库。

## 用户材料

U1：本次对话需求。新项目、两模型、local-only、262k部署、复用既有 vector Mongo、独立monologue、记忆稳定注入、agent可写人格、多场景、个性化、独立压缩、可审计与可复现验收。实现语言偏好已按最新要求更新：Python优先，必要时可用Node.js/TypeScript；不沿用此前“绝不改Node”的旧约束。

U2：`Pasted markdown(8).md`，用户小满人设。参考段落：自有意愿/自我修订（33–44），性格与喜好（62–67、115–122），双语域/直接表达（173–180、198–215），人物声音可更新（267–272）。简版夹具经过明确删减，不是原文或完整迁移。原文件SHA256见 `source_manifest.json`。

U3：`Pasted text(20260918-121351).txt`，Gemma26B实验轨迹。用于定位历史provider/model alias、262000客户端标记，以及人格由模型自行读文件的加载风险；不能用这一样本证明官方Gemma系列能力。原文含私密内容，本包不复制。

U4：`Pasted text(20260918-110709).txt`，Qwen长流程摘录。用户明确说明它已经经历多次compaction；不是与Gemma短会话的公平对照。本包不复制原记录，仅据此设置受控noise/compaction实验。

## 已核对的外部接口与事实

[S1] DSH Python SDK：subprocess JSON-RPC、显式home、profile/patch、长寿命runtime及结果/通知。只引用这些能力，不假设它覆盖全部插件API。
`https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/master/python/sdk/README.md`

[S2] DSH core：Agent发送/注入/唤醒与作用域、followup不是完成句柄、request事件不能随意修改消息。业务交接回执由Asuna实现。
`https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/master/docs/subsystems/core.md`

[S3] DSH system-prompt：完整section、动态context的变化/压缩后追加机制，完整prompt不等于自动移除工具与所有动态贡献。
`https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/master/docs/subsystems/system-prompt.md`

[S4] DSH compaction-basic：默认压力/尾部保留配置、summarize扩展点、范围事务及辅助生成路径。具体角色预算是本包新建议，不是上游标准。
`https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/master/packages/compaction/compaction-basic/README.md`

[S5] DSH presets与session：preset composition；持久日志/派生上下文概念。
`https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/master/packages/preset/agent-presets/README.md`
`https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/master/docs/subsystems/session.md`

[S6] Kazusa HOWTO：MongoDB/embedding环境变量与localhost示例。只用于连接配置发现，不作新架构依据。
`https://raw.githubusercontent.com/eamars/KazusaAIChatbot/main/docs/HOWTO.md`

[S7] Kazusa Compose：容器内部mongo hostname示例，不是宿主机/用户实例的真实地址证明。
`https://raw.githubusercontent.com/eamars/KazusaAIChatbot/main/docker-compose.yml`

[S8] MongoDB 原子性：单文档条件更新、并发条件与多文档事务的区别。Asuna的CAS/outbox恢复流程是本包设计。
`https://www.mongodb.com/docs/manual/core/write-operations-atomicity/`

[S9] Gemma4 26B官方模型卡：native thinking及多轮历史处理建议。用户实际量化/MTP部署需单独确认。
`https://huggingface.co/google/gemma-4-26B-A4B-it`

[S10] vLLM automatic prefix caching：共享前缀prefill复用与新增decode成本的区别；并不表示用户正在使用vLLM。
`https://docs.vllm.ai/en/latest/features/automatic_prefix_caching/`

[S11] MongoDB BSON文档限制：单文档16MiB，超大内容可使用GridFS。本包1MiB应用阈值是新建议。
`https://www.mongodb.com/docs/manual/reference/limits/`

[S12] Kazusa embedding client：配置入口及query/document处理参考。不得整体导入旧db包或兼容层。
`https://raw.githubusercontent.com/eamars/KazusaAIChatbot/main/src/kazusa_ai_chatbot/db/_client.py`

[S13] MongoDB vector search：pre-filter能力及标准索引字段说明。用户兼容后端按功能探针确认，不仅按版本推断。
`https://www.mongodb.com/docs/manual/reference/operator/aggregation/vectorsearch/`
`https://www.mongodb.com/docs/vector-search/indexes/vector-search-type/`

## 特别不能当成已证实的内容

实际Mongo URI、认证/拓扑；模型实际上下文容量、权重来源/量化差异、MTP及KV行为；当前DSH安装revision和本地修改；Python SDK是否覆盖此次定制；服务端的缓存统计；人格自然度和工具成功率；真正的跨session恢复可靠性。

这些都被写入doctor与验收，不能由本文档替它们宣布通过。所有算法、阈值、库名、CLI、schema、scope设计和合成夹具均为本次建议，未声称来自旧Kazusa实现。
