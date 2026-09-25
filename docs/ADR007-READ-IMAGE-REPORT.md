# 看图（read_image）接线报告

范围：ADR-007 附录里 `DSH read_image = 添加 / 接通` 那一条，以及 ADR-005/QQ_AND_VISION.md 的口径
（读图不按模型名写死；没真看到不假称看过）。本轮只做这一条，不重开 P2 或其它 ADR 的验收。
接口面那份英文说明在 `RUNTIME_API.md` 的 “Media and image reading” 一节。

## 结论

- **接线完成并已上线**：工具定义、拉取实现、能力门、角色现场说明、DSH 附件投影、离线自检都在跑动的宿主里
  （证据：本会话工具面上的 `read_image` 描述就是 `src/asuna/vision.py` 里那份）。
- **默认还差一句声明**：`read_image` 进任务能力清单需要行动路由显式声明收图（见「打开它」）。
  没声明时清单会写明原因，不会留一个点了必然失败的工具，也不会把占位符当成看过。
- **仍未验证**：真宿主里图片确实进了模型请求（DSH 附件目录落对象、插件回执 `visual:"attached"`）。
  沙箱无网络，且这条路由还没声明收图。

## 起点（核实过，不是推断）

- `read_image` 在代码里零定义，只在两份 ADR 文档里被裁定过。
- 入站侧早就有货：adapter 把非文本段整理成 `event.raw.asuna_media`，库里存着二十条带图消息，
  字段是 `type/file/url/size/sub_type/summary/placeholder`，url 指向 `multimedia.nt.qq.com.cn`；
  `sub_type` 是字符串（`"1"`＝动画表情），`size` 是字符串字节数，最大的一条 5,592,581 B。
- DSH 侧（官方包源码）：`ImageBlock` 是 durable attachment，必须先 `ctx.attachments.saveImage`；
  `sdk-minimal` 那棵插件树没有 attachment 行，要显式挂 `@deepseek-ai/dsh-attachment-local`；
  pi-ai 适配器允许 `user` 与 `tool` 两种角色带图（工具结果里的图转成 handle 文本 + `image` 内容），
  而**没声明模态的模型按 `DEFAULT_INPUT=['text']` 处理**——不声明，图片在附上前就被拒。

## 数据流（Pull：不拉就不进上下文）

1. 入站：adapter 给元数据 + 诚实占位符；宿主原样存，不取字节。
2. 角色现场：`media_from_program` —— 有什么段、能不能按需拉、不能拉是因为什么。要不要看图由她决定。
3. 行动输入：一份 `attachments` 清单（含 `ref`、`pullable`、原因），没有图片正文。
4. `read_image(ref)`：场景围栏 → 能力核对 → 标准库 HTTP 拉字节（scheme 闸门、主机白名单、重定向后主机复检、
   字节上限）→ 魔数确认 png/jpeg/webp/gif → 按任务 scope 存进既有 GridFS `BlobStore` → base64 交给 DSH 插件。
5. 插件：`ctx.attachments.saveImage` → `ImageAttachmentRef` → 工具结果渲染成
   `[{type:'image',attachment},{type:'text',元数据}]`。到这里图片才是这一轮真实的视觉输入。
6. 回执：写进 `artifacts` 的副本不带 base64，只带 `blob_artifact` 与内联摘要；最终是否成为视觉输入看
   模型侧回执的 `visual`（`attached` / `unavailable:原因`）。

没有新集合、没有新端口、没有第二个存储服务：字节进 `artifact_blobs`，回执进 `artifacts`，
附件对象进本 lane 自己的 `DSH_HOME/attachments/v1`。

## 能力门与可见性

- 单一来源：`executor.input_modalities` + `vision.image_hosts`。同一份模态声明转成 DSH provider model 的 `input`，
  所以「工具列不列」和「DSH 发不发图」依据同一句话，不会一边说能一边说不能。
- 不支持时：`read_image` 不进 `allowed_capabilities`，清单里那条附件直接标 `pullable:false` 并写明原因；
  broker 的执行校验照旧独立兜底，两层不互相替代。
- 错误都是真实错误码：`VISION_ROUTE_UNSUPPORTED`、`IMAGE_NOT_PULLABLE`、`IMAGE_ATTACHMENT_NOT_IN_SCENE`、
  `VISION_SCENE_FENCE_MISMATCH`、`IMAGE_FETCH_FAILED:HTTP_…`、`IMAGE_TOO_LARGE`、`IMAGE_TYPE_UNSUPPORTED`、
  `IMAGE_INSECURE_URL_DENIED`、`IMAGE_REDIRECT_HOST_DENIED`、`IMAGE_FILE_NAME_DENIED`、`READ_IMAGE_ARGUMENT_DENIED`。
  未知 ref 与「围栏外的场景的图」给同一个码，不借这个工具探测别人的图。围栏范围 = 本场景 + 配置里那条只读联动边（现算自配置，删键即回滚），见下面「第二轮」。

## 本轮实测到的两件事（都改掉了）

1. **下载 URL 会被截断**：原先按 420 字符清洗 URL，而 QQ 的 `fileid`+`rkey` 可以很长（自检里用 531 字符的
   真实形状 URL 复现）。截断等于静默把链接改坏。现在 URL 上限 2048，且只在拉取时按原消息回读、不进清单。
2. **非 2xx 只有一个状态码**：经宿主网络实测库里存着的一条旧链接，`multimedia.nt.qq.com.cn` 可达、TLS 正常，
   返回 `HTTP 400 {"retcode":-5503007,"retmsg":"download url has expired"}`——本机拉得到这台主机，只是那条
   `rkey` 过期了。现在错误里带上这段有界原因（`rkey` 值先隐掉）：
   `IMAGE_FETCH_FAILED:HTTP_400:{"retcode":-5503007,"retmsg":"download url has expired","rkey":"[已隐藏]"}`。

顺带把拉取默认上限从 4 MiB 抬到硬上限 8 MiB：库里已有一条 5,592,581 B 的照片，4 MiB 是我自己加的围栏，
不是路由的能力边界（DSH 会把请求内图片重编到 1 MiB 目标再发）。

## 离线验证（本次实跑）

`python3 tools/read_image_offline_check.py` → **全部通过**。它装的是真 `vision.py`/`tokens.py`/`evidence.py`
（只替 `state.Denied`），并：

- 用线上真实元数据形状出清单（含无 `version`、`sub_type` 为字符串、长 URL 的当前形状），核对 ref 可重算、
  URL 不内嵌、语音段以占位符事实保留；
- 起本机 HTTP 服务真拉一次真 PNG：sha256、字节、BlobStore 的 scope/kind/来源消息、base64 可解回原字节；
- 逐条打错误面（超限、非图片、404、链接过期的 400 带原因、重定向出白名单、明文 http、白名单外主机、
  越场景、未知 ref、能力未开、非法参数）；
- 装载真 `dsh-plugin/tools.ts`（只替换那一行包导入）跑 node：`saveImage` 收到的就是原字节、渲染出
  `["image","text"]` 两块、文本块里没有 base64；附件服务缺失 → `unavailable:ATTACHMENT_SERVICE_MISSING`；
  保存抛错 → `unavailable:IMAGE_ADMISSION_TOO_LARGE`；
- 核对写进 `artifacts` 的回执副本 < 4 KiB 且不含 base64；核对 TokenMeter 不被一坨 base64 顶高，
  但如实报 `inline_images` / `inline_image_bytes`。

同期回归：P2 `24/24`、P3 `38/38`、P5 `19/19`、P5-b `24/24`、讨论整理 `18/18`、`compileall` 干净。

## 打开它（一步，owner 侧）

`config/local.json` 与 `config/*.models.local.json` 是自我开发的受保护文件，我不能替自己改
（连示例 `config/local.example.models.local.json` 都因这个命名规则不能代改）。在
`config/local.models.local.json` 的 `executor` 里加一行：

```json
    "input_modalities": ["text", "image"],
```

`vision.image_hosts` 有默认值（这套部署真出现过的 `multimedia.nt.qq.com.cn`）；换 CDN 时清单会点名被拒的主机，
照提示加一行即可。删掉 `input_modalities` 就回到今天：工具不出现，清单说明为什么。

## 第二轮：围栏只认本场景，联动场景里的图看不见（已改）

**实测到的现象**（不是推断）：操作员在本机 owner 私聊（`local-dm`）里委托重试验图，ref 给的是
`att-28d96d82c156`（= `ref_of('in-ep-245d91c91ae4294a9addd1fb644d67e9', 0)`，那条消息在 QQ 私聊
`qq:3768713357:dm:673225019`，`scene_seq` 34，jpeg 148,285 B）。返回
`IMAGE_ATTACHMENT_NOT_IN_SCENE`——而且是在能力门**之后**才报的，说明 `input_modalities` 已经声明了
`image`、主机白名单也过了；拦下来的不是路由，是我自己那道只扫 `task['scene_id']` 的围栏。
本机场景里一张图都没有（`messages` 查 `scene_id=local-dm` + `event.raw.asuna_media` 为空），
而 `scenes.local-dm.readable_scenes` 里明明写着那条 QQ 私聊的边。

**为什么算缺陷**：A2 那条边已经让历史、讨论整理、上下文都跨得过去（同一个人的另一个入口），
只有看图没跟上——文字能同步、图片被拦在围栏外，是割裂的。架构裁定里「A2 保持不动」那句是针对
lifecycle 那一轮，不是把这条边永久冻住。

**改了什么**（只动 `src/asuna/vision.py`）：

- 新增 `readable_image_scenes(store, task, config)`：本场景的围栏比对一字未改（不同步仍然
  `VISION_SCENE_FENCE_MISMATCH`），额外那份来自 `scene_links.read_scope`——现算自配置，不是工具参数，
  所以她既不能把范围换宽、也不能把别人的场景说成自己的；联动场景在库里查不到或纪元与本任务不同步，
  就照实不扫它。
- `scene_attachments` 按这个集合逐场景扫（各自最近 50 条入站），跨场景归并用 `scene_links.message_times`
  的有效时间——各场景的 `scene_seq` 互不可比，拿它排序会得出假的新旧。条目多带 `scene_id` 与
  `linked_scene`，返回体多带 `scanned_scenes` / `linked_scenes`，覆盖范围照实报。
- `media_source_url(store, task, config, entry)`：URL 按条目**自己**那条消息回读，回读前再核一次围栏，
  不串场景、不放宽。
- 落盘不变：字节仍按**本任务**的 `scope_key` 进 BlobStore——图来自联动场景也不会写进别人场景的账本。
  放宽的只有读：写、出站、场景成员资格都不因此放宽。
- 回执多带 `image_scene_id` / `linked_scene`，联动时加一句 `scene_note`；工具描述与行动输入的附件清单
  同步（`linked_scenes`、`scanned_scenes`），她看得见这条来自哪。

**回滚**：删掉配置里 `context_links` / 路由级 `read_scenes` 那条边，就回到「只扫本场景」——自检里有这条反证。

**自检**（本次实跑）：`python3 tools/read_image_offline_check.py` → 全部通过，新增 9 条覆盖
联动场景进清单并标来源、如实报扫了哪些场景、真拉到那张图、字节仍按本任务 scope 落盘、URL 按自己场景回读、
行动输入清单带联动标记、**删键回到只扫本场景**、纪元不同步照实不扫、配置写了边但库里没那个场景不猜。
同期回归：P2 `24/24`、P3 `38/38`、P5 `19/19`、P5-b `24/24`、讨论整理 `18/18`、只读联动 `11/11`、`compileall` 干净。

**仍未验证**：真宿主里图片确实进了模型请求（插件回执 `visual:"attached"`）。这次改动要发布并重启才生效，
生效之后让他把那张图重发一次，才算真看过、真验过。

## 已知边界（不藏）

- 语音 / 视频 / 文件段仍然只有占位符事实，本轮不接转写。
- 动画表情（`sub_type=1`）会被 DSH 归一化成静态图。
- 行动 lane 没挂 `dsh-compaction-image-offload`：图片一旦进历史就会重进之后每一次请求。
  拉取上限 8 MiB + DSH 请求图 1 MiB 目标 + `maxRequestImageBytes=8MiB`（低于本机审计代理 16 MiB 请求体上限）
  是当前的兜底；真出现「一个 session 里图太多」时会是 `IMAGE_OFFLOAD_REQUIRED` 明确失败，不是悄悄丢图。
- QQ 下载 URL 带临时凭据，过期后拉取失败并留下真实原因；最直接的恢复是让对方重发一次那张图。
- 视觉 token 不进 Asuna 那条按字节保守上界（只如实报份数与字节），定价归路由与 DSH。
