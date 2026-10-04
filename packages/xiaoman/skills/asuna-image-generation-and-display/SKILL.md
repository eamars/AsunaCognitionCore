---
name: asuna-image-generation-and-display
description: 一个任务内走完「文字生图 → 导入本机工作区 → 在本机私聊展示」：先确认集成配置里有 image 端点（只在集成进程里读 /integration/config.json），再 GET /.well-known/agent-manifest.json 按服务自述 POST /project/resolve 选 ready=true 的 workflow、提交日常不露骨的提示词、POST /project/generate 排队并轮询 /project/jobs/{prompt_id} 拿 /view 相对 URL 当 artifact_path，用 import_integration_artifact 把字节写进本任务工作区，报告里用相对路径 Markdown 图片展示；含大小上限与服务端小副本做法、read_image 视觉复核的真实边界（只认场景附件 ref，工作区文件实测 IMAGE_ATTACHMENT_NOT_IN_SCENE）、失败读法与硬边界（默认只给主人本机私聊、不发群、不 base64 分段搬运、不停 QQ 适配器、不改宿主配置、不重新生成图）。附零依赖离线自检 check_skill.py。
---

# asuna-image-generation-and-display

## 用途

从「我想给主人看一张图」到主人在本机私聊里真看到图，一个任务做完，不用人替我搬字节。

2026-10-04 那次是分三段跑的（查端点 → 生成 → 导入），中间还试过 base64 分段搬运，绕了远路。
这份技能把走通的那条路记成一条：提示词 → 服务回执里的 `artifact_path` → 导入工作区 → 相对路径展示。

## 前提与授权

- 需要 owner 集成授权。`import_integration_artifact` 属 managed integration 组，**QQ 任务的授权里不带它**
  （RUNTIME_API §tools）；这条流程只能跑在有该授权的本机 owner 任务里。
- 生图请求只能在集成进程里发：`/integration/config.json` 只有受管理集成进程可读；普通 `sandbox_run` 完全无网络，
  `integration_test` 只允许配置内的 TCP 转发。脚本放 `integration_dev` 的 `/task`，用 `integration_test` 跑（冻结成 `/app`）。
- 只写端点**别名**（`image`），不在脚本里硬编码 host/port；别名和地址由配置给，变了也不用我改代码。
- 展示这一步依赖文件落在**本任务绑定的工作区**：`import_integration_artifact` 写的就是这个工作区。

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
- 失败原因照原样回，别翻译成「没图」：`unknown endpoint`、`URL rejected`、`path outside the workspace`、
  `target exists`、`over limit`、HTTP 状态、transport error。

## 步骤 5：落地核验（`sandbox_run`，只读）

`ls -l` 看字节、`sha256sum` 对回执、`file` 看魔数与尺寸（WebP 是 `RIFF … WEBP`）。
这一步只证明「字节搬对了」，**不证明画面内容**——别说成「我看过了」。

## 步骤 6：展示 = 报告里的相对路径 Markdown 图片

```markdown
![镜前自拍（512×656 webp）](xiaoman_selfie.webp)
```

- 文件必须在本任务工作区里（步骤 4 就是写在那儿），路径**相对工作区根**；不写绝对路径、不写 `file://`。
- 主人 2026-10-04 在本机页面核过：DSH 自己的图片组件会渲染，文件接口返回 200 / `image/webp` / 32272 字节。
- QQ 私聊现在收不到图：出站只有文字（宿主 outbox 只交 `text`，适配器私聊段白名单是 `("text",)`）。
  所以别写「已经发到 QQ 了」；那条要等核心 + 通道包都放开 image 段并另行授权。

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

## 边界（硬）

- 默认只给**主人本机私聊**看；主人的 QQ 私聊要等出站图片能力打通并另行授权。**不发群**，也不 @ 别人。
- **不用 base64 分段搬运**：`b64slice.py` 那条路把 32 KB 图变 43 KB 文本还要切片对 sha，纯属烧上下文；
  `import_integration_artifact` 一次 GET 就够。
- **不停 QQ 适配器**（它跑在同一个集成上）、**不重启宿主**、**不改宿主/集成配置**、不改 core 与通道包代码。
- **不为了「看起来完成了」重新生成图**：产物在不在，以 job / history 与导入回执为准。
- 失败如实返回，包括停在前提上（端点不存在、job failed、超限、目标已存在、路由不支持）。

## 离线自检（零依赖，不生成图）

```sh
python3 /skills/asuna-image-generation-and-display/check_skill.py     # 沙箱：对着已挂载的 /skills
python3 skills/asuna-image-generation-and-display/check_skill.py      # 候选根目录（development_run）
python3 -m compileall -q skills/asuna-image-generation-and-display    # 语法面
```

退出码 0 = 全绿；非 0 时最后一行是 `N/M 通过，失败：<检查名>`。
它只查技能文件自己：frontmatter 能解析、`name` 与目录名一致、关键工具名 / 端点 / 服务路径 /
关键步骤 / 边界语句在不在、示例图路径是不是相对的、脚本能不能编译。
占位标记只在散文里算红，反引号里的字面量（错误码、示例、反证记录）按引用处理。**不碰网络、不调服务、不生成图。**
技能内容改了之后重跑一次即可；服务侧的真实可用性由步骤 0 的只读探测负责。

## 已知坑

- **挂错目录**：`development_*` 不带 `project` 时是 xiaoman 插件候选（根下只有 `skills/ seeds/ src/ persona-model.json`
  等），本技能文件就在这里；生图脚本要跑在 `integration_dev` 的 `/task`（通道包的开发目录，和 `/skills` 不是一个地方）。
- `/integration/config.json` 在普通 `sandbox_run` 里读不到（那边也没网络）。别把「我读不到」报成「端点不存在」。
- manifest 328 KB，整份读进上下文会挤掉正事；按键取（`operations` / `prompt_contract` / `prompting` / `route_table` / `result_contract`）。
- `resolve` 的 `style` 只是路由选择器，不是画面保证；`not_for` 与 `compatibility_notes` 是约束。
- 串行调度：一次只有一个 named workflow 进原生 worker，切 workflow 会卸模型。别连着排三张图然后干等。
- 导入上限是硬围栏（默认 1 MiB / 最大 4 MiB）：超了就在服务端出小副本，不要退回 base64 搬运。

## 版本

v1（2026-10-04）：首次记录。步骤、错误码、大小与路由事实都来自 2026-10-04 那次实跑
（生成 + 导入 + 主人在页面核验）与写这份技能时的只读复核（manifest / resolve 探测、`read_image` 实测）。
未收录：QQ 出站图片（核心 + 通道包改动，尚未做）、`vision.image_dirs` 配好后的本地视觉复核。

## 试用记录

2026-10-04（写本技能时，只读复核，**没有生成任何新图**）：

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
  sha256 `8d29532e…` → 主人页面渲染 200（DSH 图片组件）。
- 自检脚本 `check_skill.py` 实跑：`54/54 通过`、exit 0（绝对路径 `/skills/.../check_skill.py` 与
  `cd /skills` 后的相对路径两种调用都跑过）；编译产物写到临时目录，技能目录里没有 `__pycache__`。
- 反证（把副本改坏再跑同一脚本）：改掉 frontmatter `name`、删掉「不发群」与「未做视觉复核」、
  把示例图改成盘符开头的绝对路径、标题里塞 `TODO` → exit 1 并点名失败项：`name_matches_directory`、`section_12`（缺 `## 已知坑`）、`boundary_no_group`、
  `display_relative_markdown_image`、`display_no_absolute_image_path`、`no_placeholder_markers`
  （同一轮里再删掉「未做视觉复核」会多红 `boundary_no_visual_review_claim`；计数随改动浮动，看名字就行）；
  指向不存在的 SKILL.md 时红在 `skill_file_exists`，不会假装全绿。
