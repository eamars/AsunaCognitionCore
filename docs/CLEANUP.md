# 清理状态 · 2026-09-20

按用户最新指令清除生成数据，不创建备份，开发与测试继续暂停。

- 保留唯一交接文件 `evidence.zip` 及 `evidence.manifest.json`。ZIP SHA256：`4f923ee9db293f85385883e18fe21457dc93175e01e385cd4b2cc28c9808d96a`。文件在本机仓库根目录，未提交进 Git。
- 删除 1,785 个 `asuna_v2_test_*` 数据库，共 23,224 个集合；删除后查询确认此命名空间剩余 0 个数据库。归属通过本地实验记录、探针目录、测试代码命名规则及 collection schema 交叉确认。
- Asuna 主库中唯一应用 episode 对应已记录的 CLI fixture 运行；核对事件 ID、audit stream 与文档数量后，删除其 15 个生成集合（191 条文档，含种子及探针数据）。保留归属不明、文档数为 0 的 `delete_me` 集合。未修改其他数据库。
- 从当前工作树删除历史 `reports/`、独立报告、部署快照、旧 ZIP、撤回的范围草稿、测试 DSH_HOME、测试工作目录、锁文件、探针临时目录、pytest 缓存及本项目拥有的三个系统临时 pytest 目录。
- 保留源码、测试代码、迁移、原始架构/夹具、锁文件、启动说明，以及本地运行配置和已安装的代码依赖（`.venv`、`node_modules`、固定版本 DSH 源码 checkout）。临时 SSH 配置与本次清理清单删除。
- 为生成结果补充 Git ignore 规则，避免再次把批量运行数据提交进代码树。本次是普通清理提交，未重写既有 Git 历史。

没有新模型调用或验收测试；仅核对删除结果、交接 ZIP hash 和提交内容。旧验收结论不变：整体 FAIL，COGNITION INCONCLUSIVE。重新授权运行时，需要重新初始化 Asuna schema、种子数据与向量索引，不能继续使用已删除的测试 session/database ID。
