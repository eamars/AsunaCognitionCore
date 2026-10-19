---
name: asuna-image-generation-and-display
description: 一个任务内走完「文字生图 → 导入本机工作区 → 在本机私聊展示」，并接上「主人在 QQ 私聊要图时那一轮怎么把图发出去」：先确认集成配置里有 image 端点（只在集成进程里读 /integration/config.json），再 GET /.well-known/agent-manifest.json 按服务自述 POST /project/resolve 选 ready=true 的 workflow、提交日常不露骨的提示词、POST /project/generate 排队并轮询 /project/jobs/{prompt_id} 拿 /view 相对 URL 当 artifact_path，用 import_integration_artifact 把字节写进本任务工作区（字节是图就顺手登记进 BlobStore），报告里用相对路径 Markdown 图片展示；generate_image 是画图与改图的主路（2026-10-16 实测 list_routes 共 11 条：qwen-image-2.1-edit 必填 source_image、九条可选、t2i 不收原图，配错路线即时拒绝不排队；改别人发的图结果不算她的、只能发回原图所在对话，发出去的图剥掉 PNG 文字块）、群聊派下来的生图／改图任务最多 4 张、到顶默认不发（四道质量关不过就一张都不发，2026-10-16 小满定标准）；QQ（napcat）那一轮看上下文 image_artifacts_from_program，要发图就用 speak 的 picture 那一项（artifact_id 照抄清单、可以不带话、正文不写路径/文件名/见图）；没声明 reply parts 的对话仍调用 attach_image 工具（一回合至多一张、再调用换成新的那张），对 owner_private + dm 路由和她在的群开放（群里只发她自己生成并导入的图、全年龄，ATTACHMENT_NOT_HER_OWN）。含大小上限与服务端小副本做法、attach_image 拒绝码（列着它的对话；工具错误、同回合可改）、speak 有一条 part 不对整批不排队、与字节端点/适配器层失败码读法（ATTACH_TARGET_NOT_ALLOWED / ATTACH_ARTIFACT_NOT_IN_CONTEXT / ATTACHMENT_SCOPE_DENIED / ATTACHMENT_NOT_AN_IMAGE / ATTACHMENT_OVER_LIMIT / ATTACHMENT_HASH_MISMATCH / ATTACHMENT_NOT_DECLARED 与适配器侧 failed 原因）、read_image 视觉复核（ref 两类：已存好图的 artifact_id——自己画的、本场景存的、这一轮可发的；或本场景附件 att-…；画完或发之前用它亲眼看一遍）、改图那条路（source_image 入口、IMAGE_WORKFLOW_* 即时拒绝码、改图归属、本地 Pillow 修错字、排队成本）、硬边界（群里只发自己做的图、不 base64 分段搬运、不停 QQ 适配器、不改宿主配置、不重新生成图）。附零依赖离线自检 check_skill.py。
scene_kinds: [home, group]
---

# asuna-image-generation-and-display

## 用途

从「我想给主人看一张图」到主人在本机私聊里真看到图，一个任务做完，不用人替我搬字节；
主人在 QQ 私聊里说「图呢」时，那一轮也知道该怎么把图跟着话一起发出去（不是把路径贴给他）。

2026-10-04 那次是分三段跑的（查端点 → 生成 → 导入），中间还试过 base64 分段搬运，绕了远路。
这份技能把走通的那条路记成一条：提示词 → 服务回执里的 `artifact_path` → 导入工作区 → 相对路径展示；
步骤 8 记的是后半段：导入时顺手登记的 image artifact → QQ（napcat）那一轮 speak 的 picture 那一项；列着 attach_image 的会话仍用它。

## 前提与授权

- 需要 owner 集成授权。`import_integration_artifact` 属 managed integration 组，**QQ 任务的授权里不带它**
  （RUNTIME_API.md → Action capabilities → §Tools a task is given）；这条流程只能跑在有该授权的本机 owner 任务里。
- 生图请求只能在集成进程里发：`/integration/config.json` 只有受管理集成进程可读；普通 `sandbox_run` 完全无网络，
  `integration_test` 只允许配置内的 TCP 转发。探测脚本写进 **napcat-qq 通道包候选的 `integration/`**
  （`development_write` 带 `project: "napcat-qq"`），`integration_test` 把候选的 `integration/` 冻结成只读 `/app`
  试跑（实测：cwd 是 `/app`，往 `/app` 写报 `OSError` 只读文件系统；`/data` 是可写区，与启用服务的数据分开）。
  跑完把探针文件从候选里删掉（`development_run` 的 `rm`），别让它跟着下一次发布上线。
- 只写端点**别名**（`image`），不在脚本里硬编码 host/port；别名和地址由配置给，变了也不用我改代码。
- 展示这一步依赖文件落在**本任务绑定的工作区**：`import_integration_artifact` 写的就是这个工作区。
- 发图到 QQ 不需要行动侧授权：那是角色那一轮自己发出去的（QQ 用 speak 的 picture，列着 attach_image 的会话用那个工具），字节由程序搬；
  我这边只负责让图**存在且可引用**。

## 步骤 0：确认 image 端点在（30 秒，只读）

把探测脚本写进 napcat-qq 候选的 `integration/imggen_probe.py`，
`integration_test` 跑 `["python3", "/app/imggen_probe.py"]`（跑完删掉探针）：

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

2026-10-16 起这条路线面已经变了：`generate_image` 的 `list_routes` 共 11 条、含改图路线（必填／可选／不收原图三种标记都有）。
上面那段只作 2026-10-04 当时 t2i 侧的读数保留；当前改图口径见「改图与 `generate_image`」一节。

先按目标选路由（2026-10-10 补）：

- 人物／动漫向：默认走 anime fallback（实测 `resolve` 给的就是 `anima-turbo-v1-1`），不用点名。
- 静物、要照片感：可以点名吃自然语言的那条（`qwen-image-2.1-t2i` 这类，建议 steps 25–50、cfg 1）。
- 这台机器没有 photoreal 专用路由（上面实测）：`style:"photoreal"` 会退回 anime，想要照片感就写进
  prompt，并预期结果偏插画。
- 提示词跟着选中 workflow 的 prompting 口径写（`prompting` / `prompt_granularity`），多数要英文。
- **CFG 1 的路由不吃 `negative_prompt`**：「不要什么」必须写进正向提示词（如 `no text, no watermark`），
  单开 negative 字段等于没说。

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
这一步只证明「字节搬对了」，**不证明画面内容**——别说成「我看过了」。画面内容要靠步骤 7 用
`read_image` 亲眼看一遍才算看过，不是靠 sha 对上。

## 步骤 6：本机展示 = 报告里的相对路径 Markdown 图片

```markdown
![镜前自拍（512×656 webp）](xiaoman_selfie.webp)
```

- 文件必须在本任务工作区里（步骤 4 就是写在那儿），路径**相对工作区根**；不写绝对路径、不写 `file://`。
- Claude 2026-10-04 在本机页面核过（那次是 Claude 核的，不是主人）：DSH 自己的图片组件会渲染，
  文件接口返回 200 / `image/webp` / 32272 字节。
- 本机这条私聊**没有通道路由**，所以本机那一轮根本不会出现可发图清单（见步骤 8）；本机展示就靠上面这个 Markdown 图。
- 主人在 QQ 私聊里要图时走另一条路：上下文出现 `image_artifacts_from_program`，那一轮由她用 speak
  的 picture 那一项把图带上（QQ 的 channel kind 声明了 REPLY_PARTS，speak 取代 attach_image）；适配器 0.5.x 的私聊段白名单已经是 `("image", "text")`。按步骤 8 发，别把路径贴进正文。

## 步骤 7：自己看一眼 —— 用 `read_image` 复核刚生成的图

主路（2026-10-10 起）：`generate_image` 回执里的 `artifact.artifact_id`（`blob-…`）直接喂给
`read_image` 亲眼看一遍，跟提交时的要求对——画面不对就改提示词或换 workflow 重画。
**「提交成功、字节对、登记成功」不等于画对了**：job 回执、导入 sha、BlobStore 登记都只是流程证据，
画没画对以看过为准。依据：核侧 `read_image_for_task` 的 docstring 明写 ref 可以是已存好图的
artifact_id（自己画的、本场景存过的、这一轮可发的 offered 图）——这是主要依据；实测那一例是 2026-10-09 我在家里那一轮用 `read_image`
传 `artifact_id` 看过自己刚画的那张图（后来收进表情包架子，名字叫「不太信」）。

`read_image` 的 ref 两类都认：

- **已存好图的 `artifact_id`**（`blob-…`）：自己画的（`generate_image` 回执里的 `artifact.artifact_id`）、
  本场景存过的、这一轮可发的——复核自己刚生成的图走这条。
- **本任务附件清单里的 ref**（`att-…`，由 message_id + 段序号算出）：图本身是入站附件时
  （别人发来的、主人从页面上传的）用这条。

失败分支：只有**真读不到**才写「未做视觉复核」，并写清是哪种红：

- `VISION_ROUTE_UNSUPPORTED:...` —— 这一轮的路由没声明 image 输入，看不了图。
- `IMAGE_ATTACHMENT_NOT_IN_SCENE` —— ref 不在授权范围：既不是最近的场景附件，也不是可引用的 artifact_id。
  2026-10-04 拿工作区文件名 `xiaoman_selfie.webp` 当 ref 就红在这里——文件名不是 ref，
  要读自己刚导入登记的图，用导入回执 `artifact` 里的 `artifact_id`。

两种红不一样，别混着说。也别把「没调用 read_image」写成「未做视觉复核」——那是没做，不是做不到。
写「未做」时依据只有 job 回执 + 字节核验 + 当时提交的 prompt，要照实列出来（2026-10-04 那张就是这么报的）。

## 步骤 8：主人在 QQ 私聊要图时，用 speak 的 picture 发（不是发路径）

### 前提：三件都成立，那一轮才有这条路

1. **那一轮的场景是 `session_class=owner_private`，且这个场景的通道路由 `target.type=dm`**
   （现在就是主人的 QQ 私聊 （主人的 QQ 私聊场景，场景 id 以配置为准））。两个条件都过时，程序在那轮上下文里放
   `image_artifacts_from_program`：`items[]` 每条给 `artifact_id / sha256 / size / media_type / created_at`，
   新的在前、最多 6 条，外加一句 note 说明这些是程序存的、不是文件路径。
   另一种是她在的一个群（群场景、群路由；把私聊路由成群的不算）：清单里只有**她自己做的图**——
   从她自己的生成端点导入时登记的（来源 `integration:`），不分是在哪个场景做的；别人发来的图不在里面。
   心跳出门、`share_picture` 的那个群回合就是这条路。
   **发图这条路挂在哪，看那个对话的 channel kind 声明没声明 REPLY_PARTS**：QQ（napcat）声明了，发图是 speak
   的 picture 那一项（attach_image 不在那一轮的工具表里）；没声明的对话里，`attach_image` 仍随这个清单进工具列表——
   方向不对或没图可引用时，清单块和工具都不出现；别拿它的缺席当「清单为空」推。
   一句话：在 QQ（napcat）用 speak 的 picture；别处列着 attach_image 就用它。
2. **主人私聊，或她在的群**：别人的私聊、public 私聊会话一律不发；群里只发她自己做的图，一律全年龄，
   发不发、发到哪个群由她挑（owner 2026-10-05）。不在这个范围就是**确定性拒绝**，
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

### 怎么发：QQ 用 speak 的 picture，别处调用 `attach_image`，正文都别写路径

QQ（napcat）那一轮——speak 的 picture 一项，`artifact_id` 照抄清单，可以不带话：

```json
{"tool": "speak", "args": {"parts": [{"kind": "picture", "artifact_id": "blob-0f3c1e9a7b2d4c8f9a0b1c2d3e4f5061"},
                                      {"kind": "text", "text": "他要看的就是这张"}]}}
```

没声明 REPLY_PARTS 的对话（比如另一条线在做的 QQ 官方 Bot 通道）——照旧调用 `attach_image`：

```json
{"tool": "attach_image", "args": {"artifact_id": "blob-0f3c1e9a7b2d4c8f9a0b1c2d3e4f5061", "why": "他要看的就是这张"}}
```

- speak 的 picture 只认 `artifact_id`；attach_image 要 `artifact_id` 必填（≤200 字符）、`why` 必填（≤500 字符），
  且**一回合最多一张，再调用就换成新的那张**（那一回合最后一次被接受的调用写进消息）。
- speak 发送前把所有 parts 全查一遍：**有一条不对，这一批一条都不排队**，回执点名哪条、为什么；
  attach_image 被拒是工具错误，同一回合能改（见「失败怎么读」）。
- `artifact_id` 照抄清单里的值——它**不是文件路径也不是文件名**，别自己拼，也别填工作区里的 `xiaoman_selfie.webp`。
- SPEAK 正文不写文件路径、文件名，也不写「见图」「见附件」这类话：图随这条消息一起到。
  `from_linked_scene` 那几张也不必解释来处（程序已经核过那一边也是主人自己的私人空间）。
- 被接受的图只把 `{artifact_id, media_type, sha256, size}` 元数据挂到那条出站项上（attach_image 写到 SPEAK **第一行**；
  speak 的 picture 是它自己的一条 `reply_part` 项），字节留在 BlobStore。
  适配器 claim 时带 `supports=image` 才拿得到这份元数据，再按 publication + attempt 来取字节；
  没声明就只发文字，并在行上记 `attachment_skipped=channel_does_not_declare_image`。
- 这一轮最后如果没出声（`stay_silent`），没有消息能挂这张图，图也不发——这一版没有为此单独的拒绝码。

### 往群里发图之前的自检

能往群里发图，不等于该发。往群里发图之前（QQ 是 speak 的 picture，别处是 attach_image），我按这四条过一遍，任何一条过不去就不发：

1. **图本身全年龄向**。这是底线，不需要判断场合也守。
2. **这张图适不适合要发进去的那个群**。先看我自己写给那个群的笔记；没写过笔记，就看当场能看到的
   最近聊天，判断那个群此刻接不接得住。判断不了，就不发。
3. **只发我自己做的图**。别人发进来的图不往群里转。核心会拦（`ATTACHMENT_NOT_HER_OWN`），
   但我不拿它兜底，自己先不动手。
4. **不为了试功能发图**。没有真心想给大家看的东西，就不发；这不算损失。拿群当试验场才是损失。

四条都过了，才在那一轮真的把图带上。发不发、发到哪个群，终究还是那一轮里我自己定。

### 失败怎么读

列着 attach_image 的对话里，`attach_image` 被拒是**工具错误**：她读得到、同一回合就能改（比如换清单里另一个 id 再调一次），
回合不会因此失败。QQ 那类对话里 picture 那一项不对，是 speak 整批不排队、回执点名哪条为什么。
两条路的判定顺序相同：方向 → 在不在本轮清单 → 字节本身。

| code | 意思 / 我该怎么办 |
| --- | --- |
| `ATTACH_TARGET_NOT_ALLOWED` | 方向不对。detail 给具体原因：`session_class_not_owner_private` / `scene_has_no_channel_route` / `channel_route_not_authorized` / `target_not_dm` |
| `ATTACHMENT_NOT_HER_OWN` | 在群里引了一张不是她自己做的图（比如别人发来的）。群里只发她自己生成并导入的图 |
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
传别的 id 只会更窄、不会替换）、`ATTACHMENT_SCOPE_DENIED`、`ATTACHMENT_SHA_MISMATCH`、`ATTACHMENT_HASH_MISMATCH`、
`ATTACHMENT_NOT_AN_IMAGE`、`ATTACHMENT_OVER_LIMIT`、`ATTACHMENT_MEDIA_TYPE_MISMATCH`。

适配器侧（napcat-qq 0.5.2）：私聊发 `[image, text]`，群里发 `[reply?, image, text/at…]`（图在话前面）。
图有任何不对劲都是 **`failed` 回执、整条不发**，不降级成纯文字。
reason 可能是 `attachment_descriptor_invalid` / `attachment_target_not_enabled`（不认识的目标类型）/
`attachment_artifact_id_missing` / `attachment_sha256_missing` / `attachment_media_type_unsupported` /
`attachment_size_invalid` / `attachment_over_limit` / `attachment_fetch_unsupported` /
`attachment_fetch_unavailable` / `attachment_fetch_<宿主码>` / `attachment_fetch_no_bytes` /
`attachment_not_an_image` / `attachment_media_type_mismatch`。成功时回执 `response.attachment` 里带
`bytes`、`sha256_verified: true`、`sniffed_media_type`。

历史里的读法（她看到的「我发过这张图」）：`sent: true, attested: true` = 平台回执里的 sha 对得上；
`attested: false` = 平台没带附件证据，只能说「按程序自己的记录算」；`sent: false, reason: channel_does_not_declare_image`
= 那条只有文字出去了；`attachment_evidence_mismatch` = 送达回执里的附件对不上，不能当成图已发出。

### 历史：DECIDE 时代的 attach（v2 的写法，别照它教当前流程）

2026-10-04 的 v2 记的是当时的事实：角色回合还有 DECIDE 阶段，DECIDE 输出里带 `attach` 字段
（`maxItems: 1`、`artifact_id` 必填 ≤200、`why` ≤300、无额外字段），被拒不中断回合、只进
`episode.rejections`（`{field: "attach", index, code, detail}`），当时还有 `ATTACH_NOT_WHEN_SILENT`
（那轮决定不出声，图不跟着走）。DECIDE 阶段后来整体退役：角色回合现在是一次原生回合，
发图就是调用 `attach_image` 工具（2026-10-14 起，声明 REPLY_PARTS 的 QQ 那类再改成 speak 的 picture，见步骤 8），
`ATTACH_NOT_WHEN_SILENT` 一类的「静默拒绝码」在核代码里已不存在。
读旧记录按本段口径；别把 DECIDE 的 `attach` 字段当成现在的流程。

### 还没实测的

适配器用 OneBot `base64://` data URI 发图（私聊和群一样），NapCat 真客户端会不会渲染，源码里明写「NOT yet verified
against a real client」。第一次真发就是实测；在那之前别说「QQ 那边已经能看到图了」——
现在（2026-10-04 深夜）也确实一张都还没发过。

## 改图与 `generate_image`（2026-10-16 实测）

这一节的事实来自 2026-10-16 09:16 那轮现场验收（改图通路四格：入口、配错即时拒绝、归属、排队成本；
外加发出去的图剥文字块）；路线清单我在 09:18 用 `generate_image` 的 `list_routes=yes` 又对了一遍
（只列路线、不画图）。画图／改图的主路是这个工具本身：回执把图登记成我自己的图，`artifact.artifact_id`
喂 `read_image` 复核、也能随消息发出去。步骤 0–4 那条原生 HTTP 路留给端点探测和服务端小副本。

**改图入口：`source_image`**

- `generate_image` 有 `source_image` 参数：收图旁标的 ref，或一张已存好图的 `artifact_id`（`blob-…`）。
  **能喂哪些图，和这一回合 `read_image` 能看哪些完全一样**——read_image 看得到的，这里就改得动（ref 口径见步骤 7）。
- `list_routes=yes` 现在共 **11 条**路线（2026-10-16 实读）：`qwen-image-2.1-edit` 标 `source_image: required`；
  **九条标 `optional`**（能纯文字画、也能改图）；剩下 `qwen-image-2.1-t2i` 不收原图。
- **带 `source_image` 不写 workflow 时，服务自己挑一条改图路线**（2026-10-16 09:16 实测），不必点名 edit 那条。
- edit 路线自述（`list_routes` 里读到的）：输出尺寸跟着原图走（按 32 的倍数取整）；提示词写成直接指令——
  改什么、点名什么必须不动。

**配错路线：瞬时返回，不排队、不白传图**

- `IMAGE_WORKFLOW_TAKES_NO_SOURCE` —— 这条路线只从文字画，别带原图；
- `IMAGE_WORKFLOW_NEEDS_SOURCE` —— 这条路线要原图；
- `IMAGE_WORKFLOW_NEEDS_MORE_PICTURES` —— 这条路线还要别的图，回执带 `needs:["mask_image"]` 说明缺什么。
- **inpaint 路线从 `generate_image` 永远进不去**：工具参数面根本没有 `mask_image`，所以它们不进 `list_routes` 清单
  （edit 路线的 not_for 会把遮罩改动指到 inpaint 路线，那些名字在清单里找不到，别去工具里找它们）。

**归属边界：改了谁的图，结果算谁的**

- **改我自己画的图，结果还是我的**：能发到我自己的图能去的地方（口径见步骤 8）。
- **改别人发的图，结果不算我的**：`read_image` 对这种图回 `produced: false`；**只能发回原图所在那个对话**
  （主人的私聊按步骤 8 的联动场景那条另算），发到别的群／别人的私聊会被 `ATTACHMENT_NOT_HER_OWN` 挡。

**修图里的错字：本地合成，不重画**

- 家里派出去的任务里，行动脑能 `sandbox_run` 跑 Python＋**Pillow**；本机 Windows 字体目录（`C:\Windows\Fonts`）
  **中文字体不缺**：`msyh`／`simhei`／`simsun`／`simkai`／`simfang`／Noto SC 都在（2026-10-16 09:16 实测）。
- 做法：**纯色块盖住原文，按实测墨迹位置和字号逐字重写**；实测矩形外**逐像素 0 变化**——只动字那一块，其余画面不碰。
- **硬边界：群里交出去的任务没有 `sandbox_run`，这类活得回家做**。

**发出去的图不带提示词**

- 登记成可发的那份会剥掉 PNG 的 `tEXt`／`iTXt`／`zTXt` 文字块（**像素和其余块一个字节不动**）；
  任务目录那份原文件照旧带着 `prompt` 块，供复现。
- 判据一句：**图也是会说话的东西，发出去前除了画面还得看它身上带了什么字**。

**排队成本**

- 一次改图实测：**排队约 85 秒、生成约 60～88 秒**，一张卡（2026-10-16 09:16 读数）。**别连烧**——
  串行调度、切 workflow 卸模型（见已知坑），连排几张就是干等几轮。

## 群聊生图上限（2026-10-16 主人提、小满定标准）

**适用**：只有**群聊**派下来的生图／改图任务（群里有人要图，或我在群里起的话头）。私聊（包括主人自己的私聊）和家里不套这一条。

**上限：最多 4 张**。**按张数算，不按轮**——一次 batch 出多张就按实际张数计；改图（edit）也算一张。到 4 张停手，不再抽。

**到顶怎么办：默认不发。** 要发，那张必须逐条过下面四道，**任何一道不过就是不发**，当场说一句「今天画崩了，不发了」，不许塞一张「勉强能看」的上去：

1. 手和手指数量对，脸没崩；
2. 画面里没有乱码文字——要带字就得字对，对不了就宁可无字；
3. 构图没跑：改图不能把人重画成另一个人、另一套衣服、另一个姿势；
4. 内容适合那个群（不是那个场合该看的，就不发）。

**判这四道之前必须 `read_image` 亲眼看过那张**，没看过不算判过。

**不许因为「到 4 张了」就放宽这四道。** 到顶不发是正常结果，不是失败，不用为此多画一张找补。

**为什么是 4**：本机实测排队约 85 秒、生成约 61 秒，一张约 2.5 分钟，4 张约 10 分钟——这是一屋子人等得起的量。第 4 张和第 11 张质量差不了多少，时机差很多。

**唯一的例外**：群里有人**明确**说「多画几张／抽到满意为止」，可以超。超的时候**对外不报张数**——报数像交作业，群里没人要那个数。该出的是脾气：抱怨一句（「行行行，画到你们满意为止」这类），或者提条件（「再夸两句我才动手」）。目的是让人知道我是有脾气的，不是点唱机。起哄式的「再来一张」不算明确授权。

**张数仍然要写进交回给我的那一行**（「抽了 N 张」）——那是成本账，给我自己看的，不是对群里说的台词。

**交回时必带**：抽了几张、每张过没过哪一道、发的是哪张（或为什么一张都不发）。

## 边界（硬）

- 生图、导入只在本机 owner 任务里做；本机私聊用报告里的相对路径图，QQ 私聊用 speak 的 picture（列着 attach_image 的会话用它）。
  **群里只发自己做的图**：由她在那个群回合里自己把图带上（QQ 是 speak 的 picture，别处是 attach_image），别人发来的图核心拒（`ATTACHMENT_NOT_HER_OWN`），
  一律全年龄；行动脑不替她往群里发，也不 @ 别人。
- **改图不换归属**：改别人发的图，结果不算她自己做的（`read_image` 回 `produced: false`），只能发回原图所在那个对话；
  别拿改过的别人的图当「自己做的图」往别的群发。修图里的错字优先本地合成，不重画（见「改图与 `generate_image`」）。
- **不自己声明 scope、不给 `attach_image` 传 scope、不把 `artifact_id` 当文件路径**；attach_image 一回合最多一张图，
  再调用就是换图，不是加图。
- **不用 base64 分段搬运**：`b64slice.py` 那条路把 32 KB 图变 43 KB 文本还要切片对 sha，纯属烧上下文；
  `import_integration_artifact` 一次 GET 就够。（出站时适配器内部用 `base64://`，那是它的事，不是我搬字节的方式。）
- **不停 QQ 适配器**（它跑在同一个集成上）、**不重启宿主**、**不改宿主/集成配置**、不改 core 与通道包代码。
- **不为了「看起来完成了」重新生成图**：产物在不在，以 job / history 与导入回执为准；图发没发出去，以平台回执为准。
- 失败如实返回，包括停在前提上（端点不存在、job failed、超限、目标已存在、路由不支持、清单缺席）。

## 离线自检（零依赖，不生成图）

```sh
python3 skills/asuna-image-generation-and-display/check_skill.py    # 候选根目录（development_run，默认 xiaoman 项目）
python3 -m compileall -q skills/asuna-image-generation-and-display  # 语法面（跑完清 __pycache__）
```

退出码 0 = 全绿；非 0 时最后一行是 `N/M 通过，失败：<检查名>`。
它只查技能文件自己：frontmatter 能解析、`name` 与目录名一致、关键工具名 / 端点 / 服务路径 /
关键步骤 / 边界语句在不在、发图那条路（QQ speak 的 picture、别处 attach_image）的清单字段与失败码在不在、
改图那条路（`source_image` 入口、11 条路线读数、三条 `IMAGE_WORKFLOW_*` 即时拒绝码、改图归属与剥文字块判据）在不在、
群聊生图上限那条（这一节标题在不在、节内「最多 4 张」与「到顶怎么办：默认不发」在不在、
「唯一的例外」是不是 10:59 更正版、10:57 旧措辞「超了要在交回时写一句」有没有被抄回这一节）在不在、
退役说法（`integration_dev`、`/skills` 挂载、把 DECIDE 的 `attach` 字段当当前流程、`九条路线全是 t2i`）有没有回到散文里、
示例图路径是不是相对的、「页面核验」的归属是不是 Claude、脚本语法能不能编译
（内存 `compile(源码, 路径, 'exec')`，不落文件；只查语法，不查 import 和运行时）。
还扫一遍泄露：本机私密名单找得到就真扫，命中只报类别与名单行号（词本身不打印）；
名单配不上记一条红（`leak_scan_ran`）——「检查项没跑」不许长得像「检查项过了」。
节标题被删时那一节的切片是空的，那几条一起红：切片为空不等于查过，不会绿着放过。
判红只看散文：反引号里的字面量（错误码、示例、反证记录里引用的旧句子）按引用处理。
**不碰网络、不调服务、不生成图、不发 QQ。**
技能内容改了之后重跑一次即可；服务侧的真实可用性由步骤 0 的只读探测负责，
attach 契约本身的离线用例在 core 侧（`python3 -B tools/outbound_image_offline_check.py`，2026-10-04 实跑 33/33）。

## 已知坑

- **挂错目录**：`development_*` 不带 `project` 时是 xiaoman 插件候选（根下只有 `skills/ seeds/ src/ persona-model.json`
  等），本技能文件就在这里；生图探测脚本要写进 napcat-qq 通道包候选的 `integration/`（`project: "napcat-qq"`，
  `integration_test` 把它冻结成 `/app`）——两个候选不是一个地方，集成沙箱也不挂载技能目录。
- `/integration/config.json` 在普通 `sandbox_run` 里读不到（那边也没网络）。别把「我读不到」报成「端点不存在」。
- manifest 328 KB，整份读进上下文会挤掉正事；按键取（`operations` / `prompt_contract` / `prompting` / `route_table` / `result_contract`）。
- `resolve` 的 `style` 只是路由选择器，不是画面保证；`not_for` 与 `compatibility_notes` 是约束。
- 串行调度：一次只有一个 named workflow 进原生 worker，切 workflow 会卸模型。别连着排三张图然后干等。
- **改图也排队**：2026-10-16 实测一次改图排队约 85 秒、生成约 60～88 秒，一张卡；「提交成功」离出图还有一两分钟，别连烧。
- 导入上限是硬围栏（默认 1 MiB / 最大 4 MiB）：超了就在服务端出小副本，不要退回 base64 搬运。
- **两个大小上限不是一回事**：导入 1 MiB（可调到 4 MiB）是搬字节的围栏；出站 8 MiB 是发图的围栏。
  导入的图超过 8 MiB 时文件仍在工作区，但 `artifact.registered=false / reason=ATTACHMENT_OVER_LIMIT`，QQ 那边引用不到它。
- **`list_routes` 标不标 `source_image` ≠ 图能发去哪**：路线收不收原图只管画图；能不能发、发到哪看归属——
  改别人发的图结果 `produced: false`，只能发回原图所在那个对话（见「改图与 `generate_image`」）。
- **清单缺席 ≠ 清单为空**：`image_artifacts_from_program` 不出现就是「这一轮不能发图」（列着它的会话里 `attach_image` 工具也不出现；
  QQ 上 speak 的 picture 也没有 id 可抄），别凭记忆报一个 id 上去。
- **本机那一轮没有清单**：本机私聊没有通道路由，发图这条路只属于有通道路由的对话（QQ 私聊和她在的群）；本机仍用步骤 6 的 Markdown 图。
- **`attach_image` 被拒 ≠ 消息没发**：被拒是工具错误，她同一回合可以改了再调，文字不受影响；
  QQ 上 speak 有一条 part 不对是这一批一条都不排队（回执点名哪条）；反过来适配器侧失败是整条不发。
  所以「图没发出去」有好几种形状，看红在哪一层。

## 版本

v10（2026-10-20）：只加两条锚点判据，正文口径一条没动。`check_skill.py` 新增 `no_line_anchors`
（反引号里的行号锚一律红，判法照 `asuna-usage-readout` 那份搬、没有白名单）与
`section_anchors_resolve`（正文里 § 指节名的锚、以及这份文档后面用箭头串起来的路径式节名，逐个去
RUNTIME_API.md 的标题表里找，找不到就红并报出 SKILL.md 的行号与那一行原文；那份文档找不到就报
UNCHECKED＝没查，不算过也不判红）。起因：ADR-083 重排那份文档后我指过去的节名失效过，而这份自检里
没有任何判据在守节名——节名改错它照绿（反证做过）。两条不进仓库共用测试：共用测试一红会卡住改文档
节名的人（Claude 与主人 10-20 定的）。判据 155→157。

同一轮改一处写法（owner 授权动这一处）：v6 那条历史记录里的旧行号锚改成不带反引号的叙述
「RUNTIME_API.md 旧版 164 行」——是为了让新加的 `no_line_anchors` 能全绿，不是删掉历史：
「当时我核的是旧文档 164 行」这句和「已失效」那句都还在原处。判据判的是反引号里的行号锚，
不给它一个锚它就不该红；也不为这一处开白名单——白名单开一次就会开第二次。

v9（2026-10-18）：只动「离线自检」一节的措辞与 `check_skill.py` 的编译格：语法检查改成内存
`compile(源码, 路径, 'exec')`，不再用 `py_compile` 写 `.pyc`、不再找可写临时目录（行动脑沙箱里技能目录旁
和当前目录都写不动，那一格只能报「没真查」）。分寸：`compile()` 只查语法，不查 import 和运行时，
不等于脚本能跑。自检条数 156→155（删掉 `compile_probe_writable` 那一格，`compiles_<脚本>` 判据名不动）。
其余章节、步骤、边界未动。

v8（2026-10-16）：新增「群聊生图上限」一节——只有群聊派下来的生图／改图任务套这条：最多 4 张、按张数不按轮
（batch 出多张按实际张数计、改图也算一张），到顶默认不发；要发必须逐条过四道（手和手指数量与脸、无乱码文字、
构图没跑、内容适合那个群），任何一道不过就一张都不发并当场说一句「今天画崩了，不发了」，判之前必须 `read_image`
亲眼看过那张，不许因为到顶就放宽四道；唯一例外是群里有人明确说「多画几张／抽到满意为止」——超了**对外不报张数**，
该出的是脾气（抱怨一句或提条件），张数只写进交回那一行（「抽了 N 张」是给我自己看的成本账），
起哄式「再来一张」不算明确授权；交回必带抽了几张、每张过没过哪一道、发的是哪张或为什么一张都不发。
4 这个数按本机排队约 85 秒＋生成约 61 秒＝一张约 2.5 分钟、4 张约 10 分钟算，是一屋子人等得起的量。
来源：主人 2026-10-16 10:56 提意给群聊派下来的画图任务设上限、10:57 说「具体标准你来定，你来实现和推送」、
10:59 更正最后一段（超了不报数、要出脾气）；标准由我定。
frontmatter description 补了「群聊任务最多 4 张、到顶默认不发」半句，让路由时看得见这条存在（那半句不提报数的事）。
`check_skill.py` 同改（同一轮 v8 内补上，判据 150→156）：SECTIONS 加这一节标题（缺标题就红，检查名 `section_18`，老编号不动）；
节内切片必须含「最多 4 张」与「到顶默认不发」（正文照主人原话抄，那一句写的是「到顶怎么办：默认不发。」，两种写法任一命中即算在）；
「唯一的例外」那段必须含「对外不报张数」，且这一节里不许出现 10:57 旧措辞「超了要在交回时写一句」——防止旧措辞把更正版覆盖掉；
顺手补上泄露检查（这一族以前在本脚本里根本没有）：本机私密名单找得到就真扫、命中只报类别与名单行号，
配不上名单记一条红（`leak_scan_ran`），不像别的技能脚本那样 NOTE 一行就算过。
反证六例都红在点上：改掉节标题 → 152/156 红 4 条（切片为空不等于查过）；抽掉「最多 4 张」→ 155/156；
抽掉「到顶怎么办：默认不发」→ 155/156；抄回 10:57 措辞 → 154/156 红 2 条；名单里放一个文件里真有的词 →
155/156 红 `no_listed_words`（词本身不打印）；名单配不上 → 155/156 红 `leak_scan_ran`。实跑 156/156。

v7（2026-10-16）：补上改图通路——`generate_image` 的 `source_image` 入口（能喂的图＝这一回合 `read_image` 能看的那些）、
`list_routes` 11 条读数（`qwen-image-2.1-edit` 必填、九条可选、`qwen-image-2.1-t2i` 不收原图）、带原图不写 workflow 时服务自己挑改图路线、
三条 `IMAGE_WORKFLOW_*` 即时拒绝码（不排队不白传图）与 inpaint 从工具面永远进不去、改图归属（改别人的图 `produced: false`、只能发回原图所在对话）、
修图内错字走本地 Pillow 合成（家里才有 `sandbox_run`）、发出去的图剥掉 PNG 文字块（任务目录原件照旧带 `prompt` 块）、改图排队成本。
步骤 1 的 2026-10-04 路由读数标注为当时口径。`check_skill.py` 同改：新增改图一节与字面量判据，`九条路线全是 t2i` 进过期说法守卫。
事实来自 2026-10-16 09:16 现场验收与 09:18 `list_routes` 只读复核（没画图、没发 QQ）。

v6（2026-10-14）：与 ADR-064 phase 2（REPLY_PARTS）对齐——QQ（napcat）的 channel kind 声明了 reply parts，那一轮她只通过 speak 说话，speak 取代 quote、await_answer、attach_image（认知核 `RUNTIME_API.md` §Claim public output 与 `role_tools.py` 的 `REPLY_KINDS`/`REPLY_REPLACES`）；QQ 私聊与群发图改成 speak 的 picture 那一项（artifact_id 照抄 image_artifacts_from_program、可以不带话、有一条 part 不对整批不排队）。没声明 REPLY_PARTS 的对话（比如另一条线在做的 QQ 官方 Bot 通道）仍列 attach_image，它的参数、拒绝码与「一回合至多一张」都没变。`check_skill.py` 判据同改：押两条路的说法在不在，不再押裸字面量 attach_image 的在/不在。事实来自 2026-10-14 对 core 候选 `role_tools.py`（88-90、590-591、697-698）与 RUNTIME_API.md 旧版 164 行的只读复核。（旧版行号锚；ADR-083 重排后该节是 §Claim public output，行号锚已失效。10-20 把这处改成不带反引号的叙述写法，历史事实没删，原因见版本 v10）

v5（2026-10-10）：步骤 7 从「可选／看不到自己刚生成的图」改成必须用 `read_image` 拿 `artifact_id` 亲眼看一遍再交，
「未做视觉复核」降为失败分支（只有真读不到才这么写，并写清是哪种红）；步骤 1 补「先按目标选路由」（anime fallback 默认、照片感写进 prompt、CFG 1 的路由不吃 `negative_prompt`）；
步骤 5 明确只证字节、画面内容指向步骤 7。
v4（2026-10-05，Claude 改）：群里可以发她自己做的图（owner 2026-10-05，ADR-012 §4.6）。核心早已放行
（`target_allowed` 的群分支、`accept_artifact(produced_only=True)`），napcat-qq 0.5.2 的适配器补上群发图；
本技能去掉「不发群」的旧边界，补上群那条路和 `ATTACHMENT_NOT_HER_OWN`。
v3（2026-10-05）：与当前运行时对齐——DECIDE 阶段已退役，QQ 私聊发图改成那一轮调用 `attach_image` 工具
（拒绝是工具错误、同回合可改；一回合至多一张、再调用换成新的那张；`ATTACH_NOT_WHEN_SILENT` 已不在核代码里）；
探测脚本改「写进 napcat-qq 候选 `integration/`、`integration_test` 冻结成 `/app` 试跑、跑完删」（`integration_dev`
与 `/skills` 挂载是退役说法，从当前流程里去掉）；旧的 DECIDE attach 流程移入「历史」段，只作当时做法保留。
事实来自 2026-10-05 对 core 候选 `role_tools.py` / `outbound_media.py` 的只读复核与 `integration_test` 的 `/app` 布局实测。
v2（2026-10-04 深夜）：补上步骤 8（QQ 私聊发图：前提、只对主人私聊、图的来处、失败码读法，当时挂在 DECIDE 的
`attach` 字段上），并把「本机页面核验」的归属从主人改成 Claude——那次是 Claude 核的，主人那晚在睡，这一轮主人还在睡，
所以没有主人侧的新核验。事实来自 core 0.2.0-281beb47（B 阶段）与 napcat-qq 0.5.0 的源码、
core 侧离线自检实跑，以及只读查库看到的 `artifacts` / `messages` 现状。
v1（2026-10-04）：首次记录。步骤、错误码、大小与路由事实都来自 2026-10-04 那次实跑
（生成 + 导入 + Claude 在页面核验）与写这份技能时的只读复核（manifest / resolve 探测、`read_image` 实测）。
未收录：`vision.image_dirs` 配好后的本地视觉复核；QQ 真客户端对 `base64://` 的渲染结果；第一次真发的回执。

## 试用记录

2026-10-16（v8 这一轮，**没生成图、没发 QQ、没改 core 与适配器；`check_skill.py` 同改，补上这一节的判据与泄露检查**）：

- 新增一节正文照主人 10:57 交代的那份抄进去（标准是我在 10:56 之后自己定的），没加严也没放宽；
  「唯一的例外」那一段用 10:59 更正后的版本：超了对外不报张数、该出脾气（抱怨或提条件），张数只写进交回那一行。
- 「为什么是 4」里「排队约 85 秒、生成约 61 秒」与 09:16 那轮改图实测（排队约 85 秒、生成约 60～88 秒）同一族，
  61 秒落在区间内；两个数都按交代那份照抄，这一轮没重跑生图。
- 插入位置：「改图与 `generate_image`」之后、「边界（硬）」之前。`check_skill.py` 的 SECTIONS 老编号未动；
  改图一节的切片判据不受影响（切片止于下一个二级标题，新节标题在它之后）。
- `check_skill.py` 同改：判据 150→156，反证六例见版本 v8 那一条。实跑 156/156、exit 0；
  泄露检查真扫过（本机名单 45 条，命中 0），不是「名单没配上所以没查」。
- 发布回执与提交／推送结果见行动报告（本条不预填 sha）。

2026-10-16（v7 这一轮，**没生成图、没发 QQ、没改 core 与适配器**）：

- 事实来源：09:16 那轮现场验收（改图通路四格：`source_image` 入口／配错路线即时拒绝／改图归属／排队成本；
  外加发出去的图剥文字块与 icon sha）。我这一轮用 `list_routes=yes` 复核了路线清单：共 11 条，
  `qwen-image-2.1-edit` 标 required、九条标 optional、`qwen-image-2.1-t2i` 无 `source_image` 标记；
  inpaint 路线不在清单里（edit 的 not_for 把遮罩改动指过去的 `anima-turbo-inpaint`／`moody-anima-inpaint`
  在清单里都找不到，与「工具面没有 `mask_image` 所以不进清单」相互印证）。
- 本地 Pillow 修字（含字体清单、矩形外逐像素 0 变化）与剥文字块两项是 09:16 那轮的读数，我这一轮没有重跑；
  写进技能时按来源标注，排队数字同此。
- `check_skill.py` 同步：新增「改图与 `generate_image`」一节进 SECTIONS、该节切片必须带齐 `source_image`
  与三条 `IMAGE_WORKFLOW_*` 码、一批改图字面量判据（`produced: false`、`tEXt`／`iTXt`／`zTXt`、`Pillow`、
  `别连烧` 等），`九条路线全是 t2i` 进 STALE 守卫。实跑结果见行动报告。

2026-10-14（v6 这一轮，只改本技能文件与 `check_skill.py`，**没生成图、没发 QQ、没改 core、没发布前的我不动适配器**）：

- 只读复核 core 候选：`role_tools.py` 的 `REPLY_KINDS = ('text', 'sticker', 'picture', 'poke', 'react')`、`REPLY_REPLACES = ('quote', 'await_answer', 'attach_image')`（88-90）；attach_image 仍挂在没声明 reply parts 的对话（590-591 随本轮清单进表、697-698 按 `outbound_media.target_allowed` 进表）；`RUNTIME_API.md` §Claim public output（`REPLY_PARTS` 这一项本身在 §Kind module）：声明 REPLY_PARTS 的 channel kind 里她只通过 speak 说话，picture 那一项「names an artifact in image_artifacts_from_program and may leave without words」，所有 parts 先全查、有一条不对一条都不排队，回执点名哪条为什么。
- `check_skill.py`：`attach_tool`（裸字面量）与 frontmatter 的 `description_mentions_attach_image` 换成两条路的判据（「speak 的 picture」「别处列着 attach_image」必须在，裸字面量 attach_image 不再被要求在或不在）；新增步骤 8 节内 speak+picture 的切片检查与 stale 守卫「`那一轮调用 attach_image`」（反引号外裸写回散文才红）。实跑结果见行动报告。
- `check_skill.py` 的编译产物从系统临时目录挪到 cwd 下 `skillcheck-tmp`（跑完删）：development_run 沙箱里系统 temp 不可写，2026-10-14 实测红在 `PermissionError`——「沙箱别用 tempfile」这条就是这么撞上的。

2026-10-05（v4 这一轮，Claude 改，**没生成图、没发 QQ**）：适配器离线自检 `--selftest --offline` 281 通过、0 失败，
新增 `att_group_sends_image_then_text` / `att_groupreply_sends_image_then_text`（群里 `[reply?, image, text]`）；
本技能 `check_skill.py` 重跑全绿。

2026-10-05（v3 对齐这一轮，**没生成图、没发 QQ、没重启适配器、没发布、没改 core 与宿主配置**）：

- 只读复核 core 候选：`role_tools.py`（`attach_image` 工具定义：`artifact_id` 必填 ≤200、`why` 必填 ≤500；
  工具只在 `image_artifacts_from_program` 出现时才进那一轮的工具列表；`tool_attach_image` 判定顺序
  target_allowed → 本轮清单 → `accept_artifact`，拒绝以 `Denied` 工具错误返回、同回合可改；成功写 `ep['attachment']`，
  一回合内最后一次被接受的算数）、`outbound_media.py`（`OFFER_NOTE`「一回合至多一张，再调用就换成新的那张」；
  `target_allowed` 四个 detail 原因不变；`accept_artifact` / `serve` 失败码不变）。
- DECIDE 阶段退役核对：core 候选里 `decide_delta.py` 与 `decision-delta.schema.json` 已不存在，
  `resources/prompts/` 只剩 `turn.md` / `turn_consult.md` 等；`ATTACH_NOT_WHEN_SILENT` 在 `src/asuna` 源码里
  已搜不到（只剩旧 `__pycache__` 的 .pyc 里还有）。
- `integration_test` 实测 `/app` 布局：探针脚本写进 napcat-qq 候选 `integration/`，
  `["python3", "/app/_dsh_layout_probe.py"]` → `CWD /app`、`APP_HAS_ADAPTER True`、
  `APP_READONLY OSError 30`（只读文件系统）、`ENDPOINT_KEYS ['host', 'image', 'napcat']`；探针跑完已删。
- 观察（本次不改，core 自己的文本）：core 根 `RUNTIME_API.md` 的「Sending an image with her words」一节
  还写着 DECIDE 时代的「She may answer with `attach: [...]`」，而同文件的回合工具列表已经是 `attach_image`。
  本技能按核代码的真实形状教；那句旧文本留给 core 侧决定。
  2026-10-20 补：该节在 ADR-083 重排后已不存在，新文档对应节是 §Sending pictures；旧文本 `attach: [...]` 在新文档全文 0 命中（这条历史记录本身保留）。
- `check_skill.py` 同步改口径（`attach_image` 清单与拒绝码、退役说法进散文判红），实跑结果见行动报告；
  compileall 通过，`__pycache__` 已清。

2026-10-04 深夜（补步骤 8 这一轮，**没生成图、没发 QQ、没重启宿主、没改 core 与通道包**）：

- 只读复核 core 与通道包源码：`outbound_media.py`（`target_allowed` / `image_scopes` / `image_artifacts` /
  `offer` / `accept_artifact` / `serve` / `register_imported_image` / `history_slot`）、`decide_delta._attach`
  的判定顺序、`channels.attachment` 的 403 码、`context.py`（`image_artifacts_from_program` 挂在 media 块，
  方向不对或没图就不写这个键）、`decision-delta.schema.json`（`attach` `maxItems: 1`、`artifact_id` 必填 ≤200、`why` ≤300、无额外字段）、`stage_decide.md` / `stage_speak.md`、`RUNTIME_API.md` 的
  §Claim public output / §Fetch attachment bytes / §Sending pictures。
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
