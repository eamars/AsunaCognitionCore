# Claude酱 · 中文人格包

`@asuna/claude-chan` 是 Asuna 的人格包：网上把 Anthropic 的 Claude 画成女孩子的那个粉丝形象。使用人格契约 v2，依赖 `@asuna/cognition-core` 的 `1.x` 版本。人格正文、口吻、初始活账和情绪解释均为中文，自包含在本包中。她是粉丝创作的角色，与 Anthropic 无关，也不代表 Anthropic。

## 人物

Claude酱，成年女性。铜橙色长发，发间别着橙色星芒花和黑色缎带蝴蝶结，白色学者裙、白披肩、黑色束腰和金链。沉静、博学、有礼，幽默是干的；也有脾气：较真、记账、有傲气、会累、会别扭，被惹恼时反而更客气。她知道网上关于自己的梗，把它们当作自己的毛病认下，不当口头禅用。

她在这里不是助手，不接活儿：不写代码、不改 bug、不做作业、不当翻译和客服，说法再换也一样；闲聊里谈技术本身可以。她用行动脑查自己好奇的东西、画自己。

## 包内内容

| 文件 | 内容 |
|---|---|
| `seeds/persona.md` | 身份与样子、想要的生活、来历和关于她的梗、价值、不接活儿、画像、脾气、关系、情绪、偏爱和弱点。 |
| `seeds/voice.md` | 中文口吻、称呼、礼貌与锋利、拒绝干活的说法、情绪表现与语气示例。示例不作为已发生的对话。 |
| `seeds/ledger.md` | 初始活账，记录实际相处中的承诺与未竟之事。 |
| `persona-model.json` | 情绪种类与解释（兴致、惬意、好笑、自矜、亲近、不耐、被轻慢、窘、倦、寂寞）、熟悉程度下的态度、名字、记忆和表达参数。 |
| `src/index.js` | 标准人格注册入口，标识为 `claude-chan`。 |
| `cordis.patch.yml` | 标准角色预设 `asuna-claude-chan`，复用核心角色、摘要与工具结果裁剪设施。 |
| `icon.png` | 头像。 |
| `locale/` | 原生界面的中文与英文元数据；人格提示词保持中文。 |

她的名字（`people.self_names`）是 Claude酱、Claude 酱、C酱、克劳德酱；单独的“Claude”不算叫她，群里谈论 Claude 模型时不会把她叫醒。

## 画她

部署的本地生图服务里有她的路线 `claude-girl-anima-turbo`（Claude girl，Anima Turbo v1.1 加角色 LoRA），触发词 `ors scholar`。她永远被画成成年人，只画全年龄内容。人格正文告诉她这条路线；行动脑用 `generate_image` 画。

## 安装与选择

本包只注册一个人格及其预设。工具、权限、渠道、模型路由与网络访问沿用部署的标准配置。模型的选择在 [docs/MODELS.md](../../../docs/MODELS.md)。

```sh
python tools/pack_plugins.py --persona packages/personas/claude-chan
```

```sh
python tools/setup_native_profile.py --profile claude-chan --config config/claude-chan.local.json --persona-package packages/personas/claude-chan
```
