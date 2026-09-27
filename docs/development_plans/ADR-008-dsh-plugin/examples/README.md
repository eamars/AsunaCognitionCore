# 示例用途与未验证范围

这些是 **包结构/接口示例，不是已经实现的 DSH 插件**。用户拿到的是开发包，不是可以立即替代当前服务的产品包。

- `core.package.json`、`xiaoman.package.json`：建议的package元数据与打包文件边界；`@asuna/*` 名称尚未发布。缺少实现的 lib/patch 不伪装存在。实际依赖按固定本机所import的公开包补齐，不能只依赖偶然hoist。
- `persona-contract.ts`：拟定的Asuna资源贡献接口（不是DSH原生）。沿已有等价实现可直接映射，不要求再建registry平台。
- `role-context.example.ts`：使用真实公开 `systemPrompt.section/context` 的小例子。传入的是已准备的同步快照；实际Mongo读取不放进每次同步render里。稳定persona位置由DSH公开getSectionOrder取得，动态order由安装方提供一个有效顺序；示例不注册通用角色phase workflow。
- `check_examples.py`：只检查本开发包的示例manifest字段与文件引用。它不是未来每次小满发布的检查器，也不验证模型人格/功能。

本包未在固定版依赖树下进行TypeScript类型检查，未启动任何模型/浏览器；本机实现者需在P0用真实包导出确认类型与行为。不要把例子“能读懂/静态测试通过”写成原生双脑接通。
