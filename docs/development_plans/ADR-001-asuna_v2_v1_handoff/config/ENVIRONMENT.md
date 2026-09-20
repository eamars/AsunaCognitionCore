# 本地环境变量
只设置到独立 Asuna 运行环境。不要将此文件改为含真实口令的已提交文件。

```dotenv
ASUNA_MONGODB_URI=<从本地 Kazusa 有效配置读取>
ASUNA_MONGODB_DB_NAME=asuna_v2_dev
KAZUSA_CONFIG_PATH=<本地有效.env的绝对路径，可选>
ASUNA_GEMMA_BASE_URL=<实际本地endpoint>
ASUNA_GEMMA_API_KEY=<仅本地保存>
ASUNA_QWEN_BASE_URL=<实际本地endpoint>
ASUNA_QWEN_API_KEY=<仅本地保存>
ASUNA_EMBEDDING_BASE_URL=<复用本地embedding endpoint>
ASUNA_EMBEDDING_API_KEY=<需要时，仅本地保存>
```

doctor 需把 v1.example.json 的 null/占位值解析到 resolved config，记录模型/维度/模板指纹。example 不是可直接连接服务的配置，不能自动用 localhost 猜地址。`declared_context_tokens=262000` 是保守标记，真实值必须由服务配置和调用探针确定。

数据库名优先使用显式CLI参数，其次ASUNA_MONGODB_DB_NAME，再次配置文件database字段；所有来源仍必须通过asuna_v2命名与旧库写保护检查。不从旧MONGODB_DB_NAME继承正式库名。
