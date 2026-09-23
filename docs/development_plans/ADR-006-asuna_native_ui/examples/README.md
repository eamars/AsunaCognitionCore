# 示例如何使用，以及它不是什么

## 文件

- `NativeMessageContent.tsx`：使用固定版已公开的 `MarkdownText`、`CodeBlock`、`DisclosureRow`、`StateDot`。展示真实内容、阶段标签与默认关闭的诊断。没有手绘 bubble、CSS、stream parser 或任务调度。
- `register-content.example.tsx`：演示将业务消息接入原生 `conversation.chat.node` 插槽的形状，不偷导私有 ChatView。示范的 node 类型是显示契约，不是要求新增持久事件或模型 schema。
- `settlement-example.mjs` 和 `.test.mjs`：一个可执行的原位替换小例子。它不接网络、不调用模型，用于解释“完整快照覆盖，不把最终文本再次追加”。**生产有原生等价机制时不复制该 helper。**

## 第一条规则

这些示例并不是完成的 native sidebar/chat 集成。不要把它们放到旧手绘界面，就写“DSH UI 已复用”。完整导航和聊天按 `NATIVE_REUSE_MAP.md` 的实际插件注册方式接入。

## React 示例的边界

只把 `NativeMessageContent` 放入现有原生消息 node。父级 key 来自已有稳定生成/attempt 关联，不用正文、数组索引、时间或随机值。

`text` 是原生数据层已经累积的完整文本；组件没有实现 token 累积。结束时只改变已有记录的内容/状态，不能再创建一份 FinalMessage。`markdownLabels` 由既有 locale 提供，并保持引用稳定；不要每个 token 构造一份新 labels。

`renderNativePart` 是当前原生图片、工具或 unknown 渲染入口，不能自己发明一个附件面板。`sourceLabel` 有真实依据才传；无法确认 provider 字段时，不把原生 reasoning block 伪称成 `reasoning_content`。

诊断例子只接受排除了已在 UI 显示的正文、思考和工具内容的元数据 JSON；实际应按需读取且默认折叠。完整 provider bytes 仅留既有审计，不能把元数据 JSON 称作原始回包。

## 局部例子运行

```bash
node --test examples/settlement-example.test.mjs
```

不需要安装依赖或启动服务。这些检查不证明浏览器渲染、DSH 原生绑定或用户本机 UI 已完成。

TSX 需要本机固定 DSH 的现有编译环境、共享 React、主题与 slot 服务。使用项目现有构建方式；不为示例安装最新版包。`registerAsunaContent` 还需要现有投影产生对应 node：它没有实现跨 lane source binding，也没有伪造后端接口。

## 本包制作时实际核对

公共导出/props 与固定标签源码逐项比对；JS 小例子可执行。TSX 的语法检查与真实依赖类型检查不同；交付记录会分别标明。没有连接用户本机模型、QQ、Mongo 或浏览器。
