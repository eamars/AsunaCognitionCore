---
name: asuna-image-generation-and-display
description: 一个任务内走完「文字生图 → 导入本机工作区 → 在本机私聊展示」，并接上「主人在 QQ 私聊要图时那一轮怎么用 attach 发出去」：先确认集成配置里有 image 端点（只在集成进程里读 /integration/config.json），再 GET /.well-known/agent-manifest.json 按服务自述 POST /project/resolve 选 ready=true 的 workflow、提交日常不露骨的提示词、POST /project/generate 排队并轮询 /project/jobs/{prompt_id} 拿 /view 相对 URL 当 artifact_path，用 import_integration_artifact 把字节写进本任务工作区（字节是图就顺手登记进 BlobStore），报告里用相对路径 Markdown 图片展示；QQ 私聊那一轮看上下文 image_artifacts_from_program，DECIDE 给 attach 照抄 artifact_id、SPEAK 正文不写路径/文件名/见图，只对 owner_private + dm 路由开放、群确定性不发。含大小上限与服务端小副本做法、attach 全部失败码读法（ATTACH_TARGET_NOT_ALLOWED / ATTACH_NOT_WHEN_SILENT / ATTACH_ARTIFACT_NOT_IN_CONTEXT / ATTACHMENT_SCOPE_DENIED / ATTACHMENT_NOT_AN_IMAGE / ATTACHMENT_OVER_LIMIT / ATTACHMENT_HASH_MISMATCH / ATTACHMENT_NOT_DECLARED 与适配器侧 failed 原因）、read_image 视觉复核的真实边界（只认场景附件 ref，工作区文件实测 IMAGE_ATTACHMENT_NOT_IN_SCENE）、硬边界（不发群、不 base64 分段搬运、不停 QQ 适配器、不改宿主配置、不重新生成图）。附零依赖离线自检 check_skill.py。
---

# asuna-image-generation-and-display

## 用途

从「我想给主人看一张图」到主人在本机私聊里真看到图，一个任务做完，不用人替我搬字节；
主人在 QQ 私聊里说「图呢」时，那一轮也知道该怎么把图跟着话一起发出去（不是把路径贴给他）。

2026-10-04 那次是分三段跑的（查端点 → 生成 → 导入），中间还试过 base64 分段搬运，绕了远路。
这份技能把走通的那条路记成一条：提示词 → 服务回执里的 `artifact_path` → 导入工作区 → 相对路径展示；
步骤 8 记的是后半段：导入时顺手登记的 image artifact → QQ 私聊那一轮的 `attach`。

## 前提与授权

- 需要 owner 集成授权。`import_integration_artifact` 属 managed integration 组，**QQ 任务的授权里不带它**
  （RUNTIME_API §tools）；这条流程只能跑在有该授权的本机 owner 任务里。
- 生图请求只能在集成进程里发：`/integration/config.json` 只有受管理集成进程可读；普通 `sandbox_run` 完全无网络，
  `integration_test` 只允许配置内的 TCP 转发。脚本放 `integration_dev` 的 `/task`，用 `integration_test` 跑（冻结成 `/app`）。
- 只写端点**别名**（`image`），不在脚本里硬编码 host/port；别名和地址由配置给，变了也不用我改代码。
- 展示这一步依赖文件落在**本任务绑定的工作区**：`import_integration_artifact` 写的就是这个工作区。
- 发图到 QQ 不需要行动侧授权：那是角色那一轮（DECIDE）的决定，字节由程序搬；我这边只负责让图**存在且可引用**。

## 步骤 0：确认 image 端点在（30 秒，只读）

把探测脚本写进 `integration_dev` 的 `/task/imggen/agent_probe.py`，用 `integration_test` 跑：

```python
import json, urllib.request
d = json.load(open("/integration/config.json", encoding="utf-8"))
print("ENDPOINT_KEYS", sorted(d.get("endpoints", {})))
e = d.get("endpoints", {}).get("image")
print("IMAGE_ENDPOINT", e)
if not e:
    raise SystemExit(0)                      # 端点不存在：停在这里，照实回报
BASE = "http://%s:%s" % (e["host"], e["port"])
m = json.loads(urllib.request.urlopen(BASE + "/.well-known/agent-manifest.json", timeout=20).read())
print("MANIFEST_KEYS", sorted(m.keys()))
r = urllib.request.Request(BASE + "/project/resolve",
    data=json.dumps({"domain": "general", "content_mode": "sfw", "input_type": "text",
                     "input_mode": "text_to_image", "prompt_granularity": "detailed"}).encode(),
    headers={"Content-Type": "application/json"})
res = json.loads(urllib.request.urlopen(r, timeout=40).read())
print("SELECTED", res.get("selected_workflow"))
for x in (res.get("matches") or [])[:3]:
    print("CAND", x.get("workflow_id"), "ready=", x.get("ready"), "score=", x.get("score"))
```

- 期望（2026-10-04 实跑）：`ENDPOINT_KEYS ['host', 'image', 'napcat']`、`IMAGE_ENDPOINT {'host': '127.0.0.1', 'port': 18191}`。
- `resolve` 不加载模型、不排队，所以这一步**不会生成新图**；已有产物在不在，用步骤 3 的 job/history 查，别靠重画来"确认"。
- 配置里没有 `image`：停，回报「集成配置里没有 image 端点」。加端点要改集成 profile 并重启宿主才出现转发——
  这两件都不在本次授权里。2026-10-04 12:53 那次就正当地停在这里。

## 步骤 1：读服务自述，别把根路径当 API

`GET /.well-known/agent-manifest.json`（约 328 KB，**按键取，别整份塞进上下文**）。
`protocol = project-comfyui-agent/v1`，`api_base = /project`，`authentication = none`。

服务自己的 instructions 里，跟这条流程直接相关的：

- 根路径 `/` 是原生 ComfyUI UI，不是 agent 首选入口；首选清单入口就是这个 manifest，备用 `/project/agent-manifest`、`/project/openapi.json`。
- 路由未知时 `POST /project/resolve`（`domain` / `content_mode` / `style` / `input_type` / `input_mode` / 可选 `family`、`prompt_granularity`），**只选 `ready=true` 的条目**，并把该 workflow 的 models / capabilities / routing / agent_hints 一起用。
- `GET /project/workflows/{workflow_id}` 给出 API 格式 graph + `parameter_schema`（允许字段、必填、真实默认值）。
- `POST /project/generate`（或 `/project/prompt`）返回 `prompt_id`；`GET /project/jobs/{prompt_id}` 轮询到 `succeeded` 或 `failed`。
- 输入图先 `GET /project/inputs` 或 `POST /upload/image`（multipart，`type=input`，每次用新的唯一 basename）；**上传响应是输入文件名，不是产物引用**。
- `parameters.prompt` 必须显式给（空串合法），`subject` 只是兼容别名；`seed` 省略即随机；未知字段会被拒（`ignored_parameters` 恒空）。
- `compatibility_notes`、`selection.not_for`、模型兼容性与 prompting 是**约束**，不是建议。
- `prompt_contract.limits`：prompt ≤ 8000 字符，宽高 64–2048 且为 8 的倍数，batch ≤ 4，steps ≤ 100。

实测路由（2026-10-04，`route_table` 全为 ready）：文生图可用 `qwen-image-2.1-t2i`（建议 steps 25–50、cfg 1）
或 `anima-turbo-v1-1`；`*-edit` / `inpaint` / `face_image` / `control_image` 是另外的输入契约，别把 `input_image`
发给没声明图输入的路由。**这台机器没有 photoreal 专用路由**：`style:"photoreal"` 不报错，`resolve` 会退回通用
anime 路由（实测 `selected_workflow=anima-turbo-v1-1`）。想要照片感就写进 prompt，并预期结果偏插画——
不要把 resolve 的选择当成「这台机器认为这是照片」。

## 步骤 2：提示词按服务口径写，日常、不露骨

- 方言与粒度跟着选中 workflow 的 `prompting.granularity.recommended`；不要把别的模型族的触发词抄过来。
- 角色、服装、姿势、光线这些细节留在 `parameters.prompt` 里（`routing_boundary`：不为一个角色或一套衣服造路由）。
- 明确写 SFW 约束与不要的东西：`fully clothed` / `modest` / `no nsfw`，加 `watermark, text, extra fingers, deformed hands`。
- 主人说「只画日常」时，宁可少要一点细节，也别为了效果擦边。这条是偏好，不是模型能自动保证的——
  它只是 `content_mode=sfw` 的路由选择，画面内容还得靠 prompt 与（能做到的）复核。

## 步骤 3：定位 artifact_path —— 用服务回执，不猜文件名

`GET /project/jobs/{prompt_id}`，`state=succeeded` 后取输出里的 `/view?...` 相对 URL；
manifest 的 `result_contract.download_urls` 写的就是这个口径（`/project/jobs/{prompt_id}` 返回的相对 `/view` URL）。

- 走原生 `/prompt` 的图（例如服务端做小副本）用 `GET /history/{prompt_id}` 交叉核对：`outputs` 的
  `filename` / `subfolder` / `type` 拼成 `/view?filename=…&subfolder=…&type=output`。
- 别凭 prefix 猜编号。`sm_a_00001_.webp` 这种名字要靠 history 里的节点参数确认是哪一张
  （2026-10-04 是靠 `LoadImage` 的输入名、`ImageScale` 的 512×656、`SaveAnimatedWEBP` 的 prefix/quality 对上的）。
- 只有 `succeeded` 才导。`failed` 时把 `state` / `phase` 与服务端错误原样回报，不连着重试——
  named workflow 是串行调度（`max_pending_jobs` 32，切 workflow 会卸模型）。

## 步骤 4：import_integration_artifact 把字节搬进本任务工作区

```python
import_integration_artifact(
    endpoint="image",
    artifact_path="/view?filename=sm_a_00001_.webp&subfolder=&type=output",
    target_relative_path="xiaoman_selfie.webp",
    max_bytes=1048576)
```

- 只给别名 + 路径，不给 URL / host / port；实现是**单次 HTTP/1.1 GET，不跟重定向**。
- 大小上限：默认 1 MiB，最大 4 MiB。产物可能超 → 在服务端先出小副本再导副本：
  原生 `/prompt` 跑 `LoadImage → ImageScale → SaveAnimatedWEBP`（2026-10-04 用 512×656、q70，成品 32 KB），
  或直接在生成参数就要小尺寸。副本大小以导入回执的 `bytes` 为准，不靠估。
- 目标已存在会保留（要 `overwrite=true` 才覆盖）；受保护输入不会被写穿。
- 事实只有回执里的：`imported` / `http_status` / `content_type` / `target_relative_path` / `bytes` / `sha256` / `overwritten`。
- **字节真是 PNG/JPEG/WebP/GIF 时**（按文件签名判，不看文件名），回执还会多带一个 `artifact`：
  宿主顺手把这份字节登记成本场景的 image artifact，里面给宿主重算的 `sha256` 与 `artifact_id`。
  这个 `artifact_id` 就是步骤 8 里 QQ 能引用的那张图——**别自己拼**，也**不是**工作区里的文件名。
- 失败原因照原样回，别翻译成「没图」：`unknown endpoint`、`URL rejected`、`path outside the workspace`、
  `target exists`、`over limit`、HTTP 状态、transport error。

## 步骤 5：落地核验（`sandbox_run`，只读）

`ls -l` 看字节、`sha256sum` 对回执、`file` 看魔数与尺寸（WebP 是 `RIFF … WEBP`）。
这一步只证明「字节搬对了」，**不证明画面内容**——别说成「我看过了」。

## 步骤 6：本机展示 = 报告里的相对路径 Markdown 图片

```markdown
![镜前自拍（512×656 webp）](xiaoman_selfie.webp)
```

- 文件必须在本任务工作区里（步骤 4 就是写在那儿），路径**相对工作区根**；不写绝对路径、不写 `file://`。
- Claude 2026-10-04 在本机页面核过（那次是 Claude 核的，不是主人）：DSH 自己的图片组件会渲染，
  文件接口返回 200 / `image/webp` / 32272 字节。
- 本机这条私聊**没有通道路由**，所以本机那一轮根本不会出现可发图清单（见步骤 8）；本机展示就靠上面这个 Markdown 图。
- 主人在 QQ 私聊里要图时走另一条路：核心 B 阶段已上线（上下文 `image_artifacts_from_program` + DECIDE 的 `attach`），
  适配器 0.5.0 的私聊段白名单已经是 `("image", "text")`。按步骤 8 发，别把路径贴进正文。

## 步骤 7（可选）：自己看一眼 —— `read_image` 的真实边界

`read_image` 只认**本任务附件清单里的 ref**（`att-…`，由 message_id + 段序号算出）；清单来源是本场景
（外加按配置只读联动的场景）最近入站消息的媒体块。

- 刚 import 进工作区的文件**不是**附件：实测 `read_image({"ref": "xiaoman_selfie.webp"})` →
  `IMAGE_ATTACHMENT_NOT_IN_SCENE`（2026-10-04，本机这条路由确实声明了 image 输入，所以不是路由不支持）。
- 路由没声明 image 时红在 `VISION_ROUTE_UNSUPPORTED:...`。两种红不一样，别混着说。
- 所以视觉复核能直接做的场景是：图本身是入站附件（别人发来的、主人从页面上传的）。
  自己刚生成的图要真看一眼，得先让它成为某条入站消息的附件，或由操作员把目录配进 `vision.image_dirs`
  （配置项，我不改宿主配置）。
- 做不到就照实写「未做视觉复核」，并说清依据只有 job 回执 + 字节核验 + 当时提交的 prompt。
  2026-10-04 那张就是这种情况，报告里也是这么写的。

## 步骤 8：主人在 QQ 私聊要图时，用 attach 发（不是发路径）

### 前提：三件都成立，那一轮才有这条路

1. **那一轮的场景是 `session_class=owner_private`，且这个场景的通道路由 `target.type=dm`**
   （现在就是主人的 QQ 私聊 （主人的 QQ 私聊场景，场景 id 以配置为准））。两个条件都过时，程序在那轮上下文里放
   `image_artifacts_from_program`：`items[]` 每条给 `artifact_id / sha256 / size / media_type / created_at`，
   新的在前、最多 6 条，外加一句 note 说明这些是程序存的、不是文件路径。
   **方向不对或没图可引用时这块根本不出现**——不是「空清单」，别拿它的缺席当「清单为空」推。
2. **只对主人私聊可发**：群聊、别人的场景、public 会话一律不发。第一版是**确定性拒绝**，
   不静默降级成「只发文字却报平台已送达」——那种回执会声称对方收到一张从没到达的图。
3. **图从哪来**（两条，都由程序登记，我不动 scope）：
   - 本场景自己存的：`read_image` 拉过的入站图，以及 `import_integration_artifact` 导入时字节是图 →
     顺手登记成**这个任务绑定 scope** 的 image artifact（`kind=image / state=DONE / storage=gridfs`）。
     工具参数面没有 scope 这一项，我改不了它；登记失败（scope 不认识、超上限、存储写失败）不影响导入本身，
     只在 `artifact` 里如实写 `registered: false` 与原因。
   - QQ 私聊那一轮还能引用**同一 canonical person 的另一个 owner_private dm 场景**登记的图——
     因为生图和导入只能在本机 owner 任务里做，而说图的轮次常在 QQ，两个入口都是主人自己的私人空间。
     清单里那几条会带 `from_linked_scene: true` 和它的 `scene_id`。这条边每次现算自配置
     （`context_links` / 路由 `read_scenes` + 对端 `kind=dm` + 两边都 owner_private + canonical person 同一个）；
     删掉那条边就退回只认本场景，不用改代码。本机 `scene:local-dm` 就是这种能被 QQ 端引用的来源。
   - 本机现状（2026-10-04 深夜只读查库）：`artifacts` 里有两条 `kind=image / DONE / gridfs`，scope 都是
     `scene:local-dm`（148285 字节、sha `9f7f4e8e…`）；`messages` 里带 `attachment` 的行是 **0** ——
     这条路还没真发过一张 QQ 图。

### 怎么发：DECIDE 给 attach，SPEAK 别写路径

```json
{"next": "speak", "goal": "把刚画好的那张图给主人看",
 "attach": [{"artifact_id": "blob-0f3c1e9a7b2d4c8f9a0b1c2d3e4f5061", "why": "他要看的就是这张"}]}
```

- `attach` **至多 1 条**（schema `maxItems: 1`）；`artifact_id` 必填（≤200 字符）、`why` 可选（≤300 字符），
  不接受额外字段。不想发图就**不要输出这个字段**，别给空数组。
- `artifact_id` 照抄清单里的值——它**不是文件路径也不是文件名**，别自己拼，也别填工作区里的 `xiaoman_selfie.webp`。
- SPEAK 正文不写文件路径、文件名，也不写「见图」「见附件」这类话：图随这条消息一起到。
  `from_linked_scene` 那几张也不必解释来处（程序已经核过那一边也是主人自己的私人空间）。
- 被接受的 attach 只把 `{artifact_id, media_type, sha256, size}` 写到 SPEAK **第一行**，字节留在 BlobStore。
  适配器 claim 时带 `supports=image` 才拿得到这份元数据，再按 publication + attempt 来取字节；
  没声明就只发文字，并在行上记 `attachment_skipped=channel_does_not_declare_image`。

### 失败怎么读

DECIDE 侧的拒绝只进 `episode.rejections`（`{field: "attach", index, code, detail}`），**这一轮照常继续**，
按判定顺序是：方向 → 是否出声 → 在不在本轮清单 → 字节本身。

| code | 意思 / 我该怎么办 |
| --- | --- |
| `ATTACH_TARGET_NOT_ALLOWED` | 方向不对。detail 给具体原因：`session_class_not_owner_private` / `scene_has_no_channel_route` / `channel_route_not_authorized` / `target_not_dm`。在群里想发图就是这条 |
| `ATTACH_NOT_WHEN_SILENT` | 这一轮决定不出声，图也不跟着走。要发图就得说话 |
| `ATTACH_ARTIFACT_NOT_IN_CONTEXT` | 引的 id 不在**本轮**清单里：照抄错了、图属于别的场景或别人、或根本没被列出。别猜 id，也别指望上一轮的清单还有效 |
| `ATTACHMENT_ARTIFACT_UNAVAILABLE` | artifact 行不存在，或不是 `state=DONE` / `storage=gridfs` |
| `ATTACHMENT_SCOPE_DENIED` | artifact 的 scope 不在程序算出的可引用列表里（既不是本场景，也不是那个联动的本人私聊场景） |
| `ATTACHMENT_NOT_AN_IMAGE` | 行上 `kind` 不是 image，或字节魔数不是 png/jpeg/webp/gif |
| `ATTACHMENT_OVER_LIMIT` | 大小不在 `0 < size ≤ 8 MiB`（出站上限 8 MiB，与适配器同一口径） |
| `ATTACHMENT_HASH_MISMATCH` | BlobStore 读回时按行内 sha 复核没过：字节和记录不一致 |

字节端点侧（适配器取字节 `GET /v1/channels/<id>/outbox/<pub>/attachment?attempt_id=…&artifact_id=…`）
的拒绝是 **403 带 code、不带半个 body**：`PUBLICATION_NOT_FOUND`、`PUBLICATION_ATTEMPT_MISMATCH`、
`ATTACHMENT_NOT_DECLARED`（行上记着 `attachment_skipped`：那次领取没声明能收图，图没跟着这条出去，字节也不给；
下一次带 image 能力的领取会清掉这个标记）、`ATTACHMENT_ARTIFACT_DENIED`（只要这条自己声明的那张，
传别的 id 只会更窄、不会替换）、`ATTACHMENT_SCOPE_DENIED`、`ATTACHMENT_SHA_MISMATCH`、
`ATTACHMENT_HASH_MISMATCH`、`ATTACHMENT_NOT_AN_IMAGE`、`ATTACHMENT_OVER_LIMIT`、`ATTACHMENT_MEDIA_TYPE_MISMATCH`。

适配器侧（napcat-qq 0.5.0）：图有任何不对劲都是 **`failed` 回执、整条不发**，不降级成纯文字。
reason 可能是 `attachment_descriptor_invalid` / `attachment_target_not_enabled`（群）/
`attachment_artifact_id_missing` / `attachment_sha256_missing` / `attachment_media_type_unsupported` /
`attachment_size_invalid` / `attachment_over_limit` / `attachment_fetch_unsupported` /
`attachment_fetch_unavailable` / `attachment_fetch_<宿主码>` / `attachment_fetch_no_bytes` /
`attachment_not_an_image` / `attachment_media_type_mismatch`。成功时回执 `response.attachment` 里带
`bytes`、`sha256_verified: true`、`sniffed_media_type`。

历史里的读法（她看到的「我发过这张图」）：`sent: true, attested: true` = 平台回执里的 sha 对得上；
`attested: false` = 平台没带附件证据，只能说「按程序自己的记录算」；`sent: false, reason: channel_does_not_declare_image`
= 那条只有文字出去了；`attachment_evidence_mismatch` = 送达回执里的附件对不上，不能当成图已发出。

### 还没实测的

适配器用 OneBot `base64://` data URI 发私聊图，NapCat 真客户端会不会渲染，源码里明写「NOT yet verified
against a real client」。第一次真发就是实测；在那之前别说「QQ 那边已经能看到图了」——
现在（2026-10-04 深夜）也确实一张都还没发过。

## 边界（硬）

- 默认只给**主人**看：本机私聊用报告里的相对路径图，QQ 私聊用 attach。**不发群**，也不 @ 别人——
  群方向在核心（`target_allowed` 只认 owner_private + dm）和适配器（`attachment_target_not_enabled`）都被挡着。
- **不自己声明 scope、不给 attach 传 scope、不把 `artifact_id` 当文件路径**；一轮最多一张图。
- **不用 base64 分段搬运**：`b64slice.py` 那条路把 32 KB 图变 43 KB 文本还要切片对 sha，纯属烧上下文；
  `import_integration_artifact` 一次 GET 就够。（出站时适配器内部用 `base64://`，那是它的事，不是我搬字节的方式。）
- **不停 QQ 适配器**（它跑在同一个集成上）、**不重启宿主**、**不改宿主/集成配置**、不改 core 与通道包代码。
- **不为了「看起来完成了」重新生成图**：产物在不在，以 job / history 与导入回执为准；图发没发出去，以平台回执为准。
- 失败如实返回，包括停在前提上（端点不存在、job failed、超限、目标已存在、路由不支持、清单缺席）。

## 离线自检（零依赖，不生成图）

```sh
python3 /skills/asuna-image-generation-and-display/check_skill.py     # 沙箱：对着已挂载的 /skills
python3 skills/asuna-image-generation-and-display/check_skill.py      # 候选根目录（development_run）
python3 -m compileall -q skills/asuna-image-generation-and-display    # 语法面
```

退出码 0 = 全绿；非 0 时最后一行是 `N/M 通过，失败：<检查名>`。
它只查技能文件自己：frontmatter 能解析、`name` 与目录名一致、关键工具名 / 端点 / 服务路径 /
关键步骤 / 边界语句在不在、attach 那条路的清单字段与全部失败码在不在、示例图路径是不是相对的、
「页面核验」的归属是不是 Claude、脚本能不能编译。
判红只看散文：反引号里的字面量（错误码、示例、反证记录里引用的旧句子）按引用处理。
**不碰网络、不调服务、不生成图、不发 QQ。**
技能内容改了之后重跑一次即可；服务侧的真实可用性由步骤 0 的只读探测负责，
attach 契约本身的离线用例在 core 侧（`python3 -B tools/outbound_image_offline_check.py`，2026-10-04 实跑 33/33）。

## 已知坑

- **挂错目录**：`development_*` 不带 `project` 时是 xiaoman 插件候选（根下只有 `skills/ seeds/ src/ persona-model.json`
  等），本技能文件就在这里；生图脚本要跑在 `integration_dev` 的 `/task`（通道包的开发目录，和 `/skills` 不是一个地方）。
- `/integration/config.json` 在普通 `sandbox_run` 里读不到（那边也没网络）。别把「我读不到」报成「端点不存在」。
- manifest 328 KB，整份读进上下文会挤掉正事；按键取（`operations` / `prompt_contract` / `prompting` / `route_table` / `result_contract`）。
- `resolve` 的 `style` 只是路由选择器，不是画面保证；`not_for` 与 `compatibility_notes` 是约束。
- 串行调度：一次只有一个 named workflow 进原生 worker，切 workflow 会卸模型。别连着排三张图然后干等。
- 导入上限是硬围栏（默认 1 MiB / 最大 4 MiB）：超了就在服务端出小副本，不要退回 base64 搬运。
- **两个大小上限不是一回事**：导入 1 MiB（可调到 4 MiB）是搬字节的围栏；出站 8 MiB 是发图的围栏。
  导入的图超过 8 MiB 时文件仍在工作区，但 `artifact.registered=false / reason=ATTACHMENT_OVER_LIMIT`，QQ 那边引用不到它。
- **清单缺席 ≠ 清单为空**：`image_artifacts_from_program` 不出现就是「这一轮不能发图」，别凭记忆报一个 id 上去。
- **本机那一轮没有清单**：本机私聊没有通道路由，attach 这条路只属于 QQ 私聊；本机仍用步骤 6 的 Markdown 图。
- **DECIDE 被拒 ≠ 消息没发**：attach 被拒只进 rejections，文字照发；反过来适配器侧失败是整条不发。
  所以「图没发出去」有两种形状，看红在哪一层。

## 版本

v2（2026-10-04 深夜）：补上步骤 8（QQ 私聊用 attach 发图：前提、只对主人私聊、图的来处、失败码读法），
并把「本机页面核验」的归属从主人改成 Claude——那次是 Claude 核的，主人那晚在睡，这一轮主人还在睡，
所以没有主人侧的新核验。事实来自 core 0.2.0-281beb47（B 阶段）与 napcat-qq 0.5.0 的源码、
core 侧离线自检实跑，以及只读查库看到的 `artifacts` / `messages` 现状。
v1（2026-10-04）：首次记录。步骤、错误码、大小与路由事实都来自 2026-10-04 那次实跑
（生成 + 导入 + Claude 在页面核验）与写这份技能时的只读复核（manifest / resolve 探测、`read_image` 实测）。
未收录：`vision.image_dirs` 配好后的本地视觉复核；QQ 真客户端对 `base64://` 的渲染结果；第一次真发的回执。

## 试用记录

2026-10-04 深夜（补步骤 8 这一轮，**没生成图、没发 QQ、没重启宿主、没改 core 与通道包**）：

- 只读复核 core 与通道包源码：`outbound_media.py`（`target_allowed` / `image_scopes` / `image_artifacts` /
  `offer` / `accept_artifact` / `serve` / `register_imported_image` / `history_slot`）、`decide_delta._attach`
  的判定顺序、`channels.attachment` 的 403 码、`context.py`（`image_artifacts_from_program` 挂在 media 块，
  方向不对或没图就不写这个键）、`decision-delta.schema.json`（`attach` `maxItems: 1`、`artifact_id` 必填 ≤200、
  `why` ≤300、无额外字段）、`stage_decide.md` / `stage_speak.md`、`RUNTIME_API.md` 的
  §Claim public output / §Fetch attachment bytes / §Sending an image with her words。
- core 侧离线自检实跑：`python3 -B tools/outbound_image_offline_check.py` → `33/33 通过`、exit 0。
  里面正好覆盖我写进技能的每条红：`decide_attach_rejects_artifact_not_offered_this_turn`
  （`ATTACH_ARTIFACT_NOT_IN_CONTEXT`）、`decide_attach_refuses_group_and_non_owner_private_deterministically`
  （群 → `target_not_dm`）、`decide_attach_refuses_non_image_and_oversize_bytes`（`ATTACHMENT_NOT_AN_IMAGE` /
  `ATTACHMENT_OVER_LIMIT`）、`local_image_is_offered_and_attachable_in_the_qq_dm_turn`（本机导入 → QQ 清单里
  标 `from_linked_scene` → 字节端点 200）、`byte_endpoint_fence_follows_the_configuration_at_read_time`
  （有那条边 200、删掉边 403 `ATTACHMENT_SCOPE_DENIED`）、`the_local_scene_keeps_its_own_images_readable`
  （本机那一轮没有可发图清单）。用 `-B` 是为了不在 core 候选里留 `__pycache__`。
- 只读查库：`artifacts` 两条 `kind=image / state=DONE / storage=gridfs`，scope 都是 `scene:local-dm`
  （148285 字节、sha `9f7f4e8e…`）；`messages` 里 `attachment` 存在的行 = 0 → 还没有真发过 QQ 图。
- 适配器侧读法来自 napcat-qq 0.5.0 `outbound.py`：`PRIVATE_IMAGE_SEGMENTS = ("image", "text")`、
  `MAX_IMAGE_BYTES = 8 MiB`、`attachment_plan` / `fetch_attachment` / `handle_item`（失败即整条不发），
  以及模块 docstring 里那句 base64:// 尚未对真客户端验证。
- 反证（把副本改坏再跑同一脚本）：把 `Claude 2026-10-04 在本机页面核过` 改成 `Claude 核过`（去掉那个句式）
  或把归属改回 `主人在本机页面核过` → 红 `attribution_page_check_by_claude`；把正文里 `ATTACHMENT_NOT_DECLARED`
  全部删掉 → 红 `attach_endpoint_not_declared`（只删失败表里那一处不红：这条记录自己引用的字面量会替它顶数，
  所以反证要连引用一起删）；同样手法删 `from_linked_scene` → 红 `attach_from_linked_scene`、删
  `image_artifacts_from_program` → 红 `attach_context_offer`；把「步骤 8」标题改掉 → 红 `section_15`；
  把旧那句 `QQ 私聊现在收不到图` 塞回散文 → 红 `no_stale_text_only_claim`（塞进反引号里当引用则不红，
  这条本身就是那条规则的活样本）。
  （v1 那条记录里的 `section_12` 指 `## 已知坑`；本轮把「步骤 8」追加在 SECTIONS 末尾，老编号没动。）

2026-10-04（写本技能 v1 时，只读复核，**没有生成任何新图**）：

- 端点与自述：`integration_test` 跑只读探测 → `ENDPOINT_KEYS ['host', 'image', 'napcat']`、
  `IMAGE_ENDPOINT 127.0.0.1:18191`；manifest 顶层键含 `operations / prompt_contract / prompting /
  route_table / result_contract / scheduling / workflow_selection`；`operations` 里 `get_job` 是唯一返回
  可下载引用的操作，`result_contract.download_urls` = 「relative /view URLs returned by /project/jobs/{prompt_id}」。
- 路由：`POST /project/resolve`（`sfw` / `text` / `text_to_image` / `detailed`）→ `selected_workflow=anima-turbo-v1-1`、
  `matches[0].ready=true`；`route_table` 里 t2i 首选 `qwen-image-2.1-t2i`（steps 25–50、cfg 1）。
  传 `style:"photoreal"` 不报错也不改变结果——上面那句 photoreal 警告就是这么来的。
- `read_image` 边界实测：`read_image({"ref": "xiaoman_selfie.webp"})` → `IMAGE_ATTACHMENT_NOT_IN_SCENE`。
- 上次成图的证据链（沿用当天记录，未重跑）：job / history 交叉核对 →
  `/view?filename=sm_a_00001_.webp&subfolder=&type=output` → 导入回执 200 / `image/webp` / 32272 字节 /
  sha256 `8d29532e…` → Claude 在本机页面看到渲染 200（DSH 图片组件）。
- 自检脚本 `check_skill.py` 实跑：`54/54 通过`、exit 0（绝对路径 `/skills/.../check_skill.py` 与
  `cd /skills` 后的相对路径两种调用都跑过）；编译产物写到临时目录，技能目录里没有 `__pycache__`。
- 反证（把副本改坏再跑同一脚本）：改掉 frontmatter `name`、删掉「不发群」与「未做视觉复核」、
  把示例图改成盘符开头的绝对路径、标题里塞 `TODO` → exit 1 并点名失败项：`name_matches_directory`、`section_12`（缺 `## 已知坑`）、`boundary_no_group`、
  `display_relative_markdown_image`、`display_no_absolute_image_path`、`no_placeholder_markers`
  （同一轮里再删掉「未做视觉复核」会多红 `boundary_no_visual_review_claim`；计数随改动浮动，看名字就行）；
  指向不存在的 SKILL.md 时红在 `skill_file_exists`，不会假装全绿。
