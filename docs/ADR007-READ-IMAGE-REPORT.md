# 看图（read_image）接线报告

范围：ADR-007 附录里 `DSH read_image = 添加 / 接通` 那一条，以及 ADR-005/QQ_AND_VISION.md 的口径
（读图不按模型名写死；没真看到不假称看过）。本次只做这一条，不重开 P2 或其它 ADR 的验收。

## 结论

- **接线完成**：工具定义、执行实现、能力门、角色现场说明、DSH 附件投影、离线自检都在候选里，离线全绿。
- **默认是关着的**：`read_image` 要进任务能力清单，需要行动路由显式声明收图（见「打开它」）。
  没声明时清单会写明原因，不会有个点了必然失败的工具，也不会把占位符当成看过。
- **未验证**：真 QQ CDN 的一次真实拉取、真宿主里图片确实进了模型请求（沙箱无网、不起宿主）。

## 接之前的真实状态（核实过，不是推断）

- `read_image` 在代码里**零定义**：全仓只出现在两份文档（ADR-007 附录的裁定与验收项、ADR-005 的口径说明）。
- 入站侧已经有货：adapter 0.4.0 把非文本段整理成 `event.raw.asuna_media`，库里已存着三条带图消息
  （`in-ep-435b26313c18e27b84c855c89e7ada05` 私聊 png 46695B、`in-ep-f8e6c110be0d89b22cb4f3b6addcb4d2`
  群 905393941 jpg 49159B、`in-ep-efb85e2e66557a55ccac40292db90b9a` 群 54369546 png 1481845B），
  字段是 `type/file/url/size/sub_type/summary/placeholder`，url 指向 `multimedia.nt.qq.com.cn`。
- `src/asuna` 里 grep 不到任何 media 处理：**元数据在存，但没人用**。
- DSH 侧（官方包文档与源码）：`ImageBlock` 是 durable attachment，必须先 `ctx.attachments.saveImage` 才有 ref；
  `sdk-minimal` 那棵插件树里没有 attachment 行，要显式挂 `@deepseek-ai/dsh-attachment-local`；
  pi-ai 适配器允许 `user` 与 `tool` 两种角色带图（工具结果里的图会被转成 handle 文本 + `image` 内容），
  而**没声明模态的模型按 `DEFAULT_INPUT=['text']` 处理**——不声明，图片在附上前就会被拒。

## 数据流（Pull：不拉就不进上下文）

1. 入站：adapter 给元数据 + 诚实占位符；宿主原样存，不取字节。
2. 角色现场：`media_from_program` —— 这条消息里有过哪些段、能不能按需拉、不能拉是因为什么。她决定是否委托。
3. 行动输入：任务输入带 `attachments` 清单（同一条消息的图，含 `ref`、`pullable`、原因），没有图片正文。
4. `read_image(ref)`：场景围栏（任务绑定 scene + policy epoch）→ 能力核对 → 标准库 HTTP 拉字节
   （scheme 闸门、主机白名单、重定向后主机复检、字节上限）→ 魔数确认 png/jpeg/webp/gif
   → 按任务 scope 存进既有 GridFS `BlobStore` → base64 交给 DSH 插件。
5. DSH 插件：`ctx.attachments.saveImage` → `ImageAttachmentRef` → 工具结果渲染成
   `[{type:'image',attachment},{type:'text',元数据}]`。到这里图片才是这一轮真实的视觉输入。
6. 回执：写进 `artifacts` 的副本不带 base64（普通 BSON 行 1 MiB 上限），只带 `blob_artifact` 与内联摘要；
   最终是否成为视觉输入看模型侧回执里的 `visual`（`attached` / `unavailable:原因`）。

没有新建视觉服务、没有新集合、没有新端口：字节进 `artifact_blobs`，回执进 `artifacts`，附件对象进本 lane 自己的
`DSH_HOME/attachments/v1`。

## 改了哪些文件

| 文件 | 改动 |
|---|---|
| `src/asuna/vision.py` | 新增：元数据清单、ref 派生、能力门、拉取、落盘、`read_image` 实现、`VisionService` |
| `src/asuna/tasks.py` | 注册工具定义；broker 分派（不持副作用锁）；回执去 base64；行动输入带 `attachments` |
| `src/asuna/coordinator.py` | 新建任务时的能力清单走同一份裁剪 |
| `src/asuna/application.py` | `VisionService` 绑到 broker（同一个 store） |
| `src/asuna/context.py` | 角色现场 `media_from_program`；能力齐备时说明看图入口 |
| `src/asuna/dsh_lane.py` | 行动 lane 挂 `@deepseek-ai/dsh-attachment-local`；provider model 条目转达 `input` 模态；`maxRequestImageBytes=8MiB` |
| `src/asuna/tokens.py` | 内联图片不再被当成文本字节计入保守上界，份数与字节如实报 |
| `dsh-plugin/tools.ts` | `execute` 里存附件、`render` 投影成 ImageBlock + 元数据文本块；失败如实标 `unavailable` |
| `config/local.example.json` | 新增 `vision` 段与 `executor.input_modalities` 示例（`config/*.models.local.json` 受保护，未代改） |
| `tests/p3_schedule_cases.py` | 夹具补带 `vision.py`；新增一条：带图消息进现场时她只拿到事实、拿不到图片正文 |
| `tools/read_image_offline_check.py` | 新增离线自检 |
| `RUNTIME_API.md` | 新增「非文本段与看图（Pull 模式）」一节 |

## 能力门与可见性

- 单一来源：`executor.input_modalities` + `vision.image_hosts`。同一份模态声明转成 DSH provider model 的 `input`，
  所以「工具列不列」和「DSH 发不发图」依据同一句话，不会一边说能一边说不能。
- 不支持时：`read_image` 不进 `allowed_capabilities`（schema 可见性跟着真实能力走），清单里那条附件直接标
  `pullable:false` 并写明原因；broker 的执行校验照旧独立兜底，两层不互相替代。
- 错误都是真实错误码：`VISION_ROUTE_UNSUPPORTED`、`IMAGE_NOT_PULLABLE`、`IMAGE_ATTACHMENT_NOT_IN_SCENE`、
  `VISION_SCENE_FENCE_MISMATCH`、`IMAGE_FETCH_FAILED:HTTP_404`、`IMAGE_TOO_LARGE`、`IMAGE_TYPE_UNSUPPORTED`、
  `IMAGE_INSECURE_URL_DENIED`、`IMAGE_REDIRECT_HOST_DENIED`、`IMAGE_FILE_NAME_DENIED`、`READ_IMAGE_ARGUMENT_DENIED`。
  未知 ref 与「别的场景的图」给同一个码，不借这个工具探测别人的图。

## 离线验证（本次实跑）

`python3 tools/read_image_offline_check.py` → **全部通过**（30+ 项）。它装的是真 `vision.py`/`tokens.py`/`evidence.py`
（只替 `state.Denied`），并：

- 用线上那条消息的真实元数据形状出清单，核对 ref 可重算、URL 不内嵌、语音段以占位符事实保留；
- 起一个本机 HTTP 服务真拉一次真 PNG：核对 sha256、字节、BlobStore 收到的 scope/kind/来源消息、base64 可解回原字节；
- 逐条打错误面（超限、非图片、404、重定向出白名单、明文 http、白名单外主机、越场景、未知 ref、能力未开、非法参数）；
- 装载真 `dsh-plugin/tools.ts`（只替换那一行包导入）跑 node：`saveImage` 收到的就是原字节、渲染出
  `["image","text"]` 两块、文本块里没有 base64；附件服务缺失 → `unavailable:ATTACHMENT_SERVICE_MISSING`；
  保存抛错 → `unavailable:IMAGE_ADMISSION_TOO_LARGE`；
- 核对写进 `artifacts` 的回执副本 < 4 KiB 且不含 base64；
- 核对 TokenMeter 不被一坨 base64 顶高，但报出 `inline_images` / `inline_image_bytes`。

同期回归：P2 `24/24`、P5 `19/19`、P5-b `24/24`、P3 `38/38`（新增一条）、讨论整理 `18/18`、`compileall` 干净。

## 打开它（一步，owner 侧）

`config/local.json` 与 `config/*.models.local.json` 是自我开发的受保护文件，我不能替自己改。要启用：

在 `config/local.models.local.json` 的 `executor` 里加一行

```json
    "input_modalities": ["text", "image"],
```

（`config/*.models.local.json` 这个命名本身就是受保护的，所以连示例 `config/local.example.models.local.json`
里都没替你写上这一行；`config/local.example.json` 里的 `vision` 段与 `input_modalities` 只是形状说明，
运行时真正读的是 `local.models.local.json`。）

`vision.image_hosts` 有默认值：这套部署真出现过的 `multimedia.nt.qq.com.cn`。换 CDN 时清单会点名被拒的主机，
照提示加一行即可。删掉 `input_modalities` 这一行就回到今天的状态：工具不出现，清单说明为什么。

## 已知边界（不藏）

- 语音 / 视频 / 文件段仍然只有占位符事实，本次不接转写。
- 动画表情会被 DSH 归一化成静态图（附件机制的既有行为）。
- 行动 lane 没挂 `dsh-compaction-image-offload`：图片一旦进历史就会重进之后每一次请求。
  拉取上限 4 MiB（硬上限 8 MiB）+ DSH 请求图 1 MiB 目标 + `maxRequestImageBytes=8MiB` 是当前的兜底；
  真出现「一个 session 里图太多」时会是 `IMAGE_OFFLOAD_REQUIRED` 明确失败，不是悄悄丢图。
- QQ 的下载 URL 带临时凭据（`rkey` 等），过期后拉取会失败并留下真实错误；重发一条新消息是最直接的恢复。
- 视觉 token 不进 Asuna 那条按字节保守上界（只如实报份数与字节），定价归路由与 DSH。
