# 示例与参考实现

这些文件**全部是合成的**：不含任何真实人格、账号、地址、时区或私密内容。它们是规格的一部分，不是已经实现的代码。

| 文件 | 用途 | 规范性 |
|---|---|---|
| `persona-contract.ts` | 人格契约 v2 的形状（Asuna 拟定接口，不是 DSH API） | 规范：字段与规则 |
| `persona-model.schema.json` | 人格模型的 JSON Schema（draft-07） | **规范**：实现用它校验 `registerPersona` 的 `model` |
| `persona-model.example.json` | 合成人格 `demo` 的模型 | 示例；也是 `tests/fixtures/personas/demo` 的起点 |
| `decision-delta.schema.json` | DECIDE 新增可选字段的 schema，附三条示例决策 | **规范**：并入现有决策 schema |
| `affect_reference.py` | 情感投影与注入描述的参考实现（纯函数、只用标准库） | **规范**：实现必须逐点一致（误差 < 1e-6） |
| `affect-events.example.json` | 合成事件、修订与固定期望值（两种 `close_mode`、中途时刻） | 规范：黄金夹具 |
| `persona-data-api.example.json` | 人格数据 API 的请求与响应示例 | 示例 |
| `source-manifest.example.json` | 人格自己写的迁移清单可以长什么样 | **仅示例**：清单格式由人格决定，核心不规定 |
| `question-bank.example.json` | 人格自己的召回题库可以长什么样（只存锚点） | **仅示例**：题库格式由人格决定 |
| `check_examples.py` | 本文件夹的自检：JSON/schema、情感参考实现对一个独立"旧账本"口径的逐点一致、链接与锚点、个人数据守卫 | 本地检查，不是部署闸门 |

运行：

```text
python docs/development_plans/ADR-009-persona_residency/examples/check_examples.py
```

需要 `jsonschema`（项目已有依赖）。缺失时 schema 用例会被跳过，并在输出中注明。

未验证范围：TypeScript 未在固定版依赖树下做类型检查；没有启动任何模型、浏览器或 DSH。
