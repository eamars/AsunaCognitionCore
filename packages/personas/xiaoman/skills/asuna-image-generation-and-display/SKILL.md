---
name: asuna-image-generation-and-display
description: 直路是行动脑侧的 generate_image（本机与 QQ 来的任务同一条路：直接调用，图落任务工作区并自动登记成我自己的图，read_image 看过一眼后随消息发出去；外部公开生图服务只给链接、图发不出去，要发出去的图不走那条；它不可用或要工具参数面给不了的模型／参数时才走长路）。长路（探针 → integration_test → import_integration_artifact）：一个任务内走完「文字生图 → 导入本机工作区 → 在本机私聊展示」，并接上「主人在 QQ 私聊要图时那一轮怎么把图发出去」：先确认集成配置里有 image 端点（只在集成进程里读 /integration/config.json），再 GET /.well-known/agent-manifest.json 按服务自述 POST /project/resolve 选 ready=true 的 workflow、提交日常不露骨的提示词、POST /project/generate 排队并轮询 /project/jobs/{prompt_id} 拿 /view 相对 URL 当 artifact_path，用 import_integration_artifact 把字节写进本任务工作区（字节是图就顺手登记进 BlobStore；盘上已有的图另有一条：家里 Python 里用 register_imported_image 带 scope_key 登记进指定场景，代价是剥 PNG 文字块），报告里用相对路径 Markdown 图片展示；generate_image 是画图与改图的主路（list_routes 的条数现读、技能不存（每次 list_routes=yes 回来数一遍；标 source_image=required 的改图路线必填、标 optional 的可选、不带这个标的 t2i 路线不收原图），配错路线即时拒绝不排队；改别人发的图结果不算她的、只能发回原图所在对话，发出去的图剥掉 PNG 文字块）、群聊派下来的生图／改图任务最多 4 张、到顶默认不发（四道质量关不过就一张都不发）；所有对话（家里本机私聊、两条 agent 线、peer 线、QQ）发图都只有 speak 的 picture part 这一条路：看上下文 image_artifacts_from_program，artifact_id 照抄这一轮清单里列出的值（它既不是路径也不是文件名）、可以不带话、正文不写路径/文件名/见图；一回合最多一张是我自己的规矩，speak 一条里能带几张 picture 未重测；群里只发来源带 `integration:` 前缀的图（可以是早就做好、后来重新登记进来的），全年龄，ATTACHMENT_NOT_HER_OWN；`attach_image` 这个工具 11-13 那版起全线拿掉，不想说话就什么都不调用。含大小上限与服务端小副本做法、picture 那一项的拒绝码（回执点名哪条；旧 `attach_image` 那套「工具错误、同回合可改」随工具一起退役）、speak 有一条 part 不对整批不排队、与字节端点/适配器层失败码读法（ATTACH_TARGET_NOT_ALLOWED / ATTACH_ARTIFACT_NOT_IN_CONTEXT / ATTACHMENT_SCOPE_DENIED / ATTACHMENT_NOT_AN_IMAGE / ATTACHMENT_OVER_LIMIT / ATTACHMENT_HASH_MISMATCH / ATTACHMENT_NOT_DECLARED 与适配器侧 failed 原因）、read_image 视觉复核（ref 两类：已存好图的 artifact_id——自己画的、本场景存的、这一轮可发的；或本场景附件 att-…；画完或发之前用它亲眼看一遍）、改图那条路（source_image 入口、IMAGE_WORKFLOW_* 即时拒绝码、改图归属、本地 Pillow 修错字、排队成本）、硬边界（群里只发自己做的图、不 base64 分段搬运、不停 QQ 适配器、不改宿主配置、不重新生成图）。含人像实测三则（构图决定连帽衫拉链的保守字面、手持自拍别指望手机进画、交图前按局部放大复核）与 11-05 现读参数面（工具面无 pose、回执有 warnings）。含「能力面」一节：11 个只读口的现读命令与当拍量、逐能力的工具面键位与长路配方（upscale／transform／inpaint／face-reference／pose／character LoRA／extend／dry_run 校验）、八条角色路线对照，以及「与角色脑的指令相抵时先问一次」那条硬口径。附零依赖离线自检 check_skill.py。
scene_kinds: [home, group]
---

# asuna-image-generation-and-display

## 用途

从「我想给主人看一张图」到主人在本机私聊里真看到图，一个任务做完，不用人替我搬字节；
主人在 QQ 私聊里说「图呢」时，那一轮也知道该怎么把图跟着话一起发出去（不是把路径贴给他）。

**直路是 `generate_image`**（下一节）：调用它 → 图落本任务工作区并自动登记成我自己的图 → 亲眼看过 → 随消息发出去。
本机派下来的和 QQ 派下来的走同一条，不分场合。

「步骤 0–4」那条长路（只读探针 → `integration_test` → `import_integration_artifact`）现在是**备用路**：
只有在 `generate_image` 不可用、或要它参数面给不了的模型／参数时才走。走法原文整段留着——
提示词 → 服务回执里的 `artifact_path` → 导入工作区 → 相对路径展示；
步骤 8 记的是后半段：导入时顺手登记的 image artifact → 那一轮用 speak 的 picture part 发出去（所有对话同一条路；`attach_image` 11-13 那版起已全线拿掉）。

## 直路：`generate_image`（第一选择）

行动脑侧有 `generate_image` 工具。要一张图，先调它，不用先去碰探针。

- **本机派下来的和 QQ 派下来的任务是同一条路**：直接调用它。参数面就是提示词、路线、宽高、seed、
  可选的 `source_image`（改图）。
- **图落本任务工作区，并自动登记成我自己的图**：回执里的 `artifact.artifact_id`（`blob-…`）就是那张图。
  登记不用我操心，也不必再拿 `import_integration_artifact` 把字节搬一次。
- **之后随消息发出去**：那一轮照步骤 8 引这个 `artifact_id`（所有对话都是 speak 的 picture part，不再分 QQ 与别处）。
- **画完自己看过再发**：`read_image` 拿回执里的 `artifact.artifact_id` 亲眼看那一张，跟提交时的要求对；
  不对就照「只画一次」一节处理（如实报崩、或随图一句说明，不自己重画）。「提交成功、登记成功」不等于画对了（口径见步骤 7）。
- 挑路线先 `list_routes=yes`（条数现读：数 `list_routes=yes` 回来的 `workflows` 数组，技能不存这个数；改图口径见「改图与 `generate_image`」一节），
  提示词照那条路线自己的口径写。
- **回执里 `warnings` 那一格要看**：越界的参数服务端只警告、不拒收，值照用（实测两条原文：
  `negative_prompt_inactive: At CFG 1 the sampler skips negative conditioning; negative_prompt has no effect at this setting.`、
  `outside_recommended_range: steps=4 is outside the recommended range [8, 12] for anima-turbo-v1-1; the requested value was retained.`）。
  ⇒ **出图 ≠ 参数被接受**：`anima-turbo-v1-1` 推荐步数 8–12，正式图别停在 4 步；CFG 1 下 negative 白写（与「步骤 1」末尾那条一致）。
  - **另有一档：报了预算警告仍然出图**（11-20，凭 `task-31cc32e0278ee89b1505441858a2cb1b`）。同一趟在
    `moody-desire-v30` 上提交 1024×1536（＝1,572,864 像素），八发每一发都回
    `over_pixel_budget: 1572864 total pixels exceeds the tested budget of 1048576 for moody-desire-v30; the job was kept but may be slow or fail with out_of_memory.`，
    而八发**全都出了图**（每张 20.3–23.4 秒）。⇒ 这一档只许写「报了预算警告仍出图」：**不算失败**（没有一发崩），
    **也不等于这个尺寸在它预算内**（那句警告自己写着 `may be slow or fail with out_of_memory`）。要判尺寸合不合，
    现读那条路线回执 `guidance` 里它自己的口径：同一趟 `moody-desire-v30` 的 `guidance` 里根本没有 `size` 那一格，
    而 `janku-illustrious` 的 `guidance` 写着 `size: [1024,1536]` —— 同一尺寸在那条路线不报警告。
- **`guidance` 回的是选中那条路线自己的提示词口径**（style／structure／quality_prefix／prompt_scope／best_for／not_for／size／example）：
  照它写，别照记忆写。`job` 是超时续取的凭据——一次调用超时不等于画失败，拿回到的 `prompt_id` 再调一次取回来，别重画。

**什么时候不走这条**：`generate_image` 不可用，或要它参数面给不了的模型／参数（在服务端串自己的 workflow、
出小副本这类）→ 走下面「步骤 0–4」那条长路（备用路，原文整段留着）。

**外部公开生图服务不算交图**：那种服务只回一个链接，字节进不了工作区、也登记不成我自己的图，
那一轮就没有 artifact 可引 → 图发不出去。要发出去的图不走这条；拿到链接只算看到一个地址。

## 只画一次（一单一画，崩了不修）

一条画图单子分两头管：生产端只画一次（①–④），交付端只出一版（⑤–⑦）。**两头都没有「修」这个出口。**
来路：2026-11-06 外面一个群的一趟改图单子连画五次、一张比一张差，金主当场拍板「一张图只画一次，
崩了就崩了，不要修」；同日 15:26 主人把交付端那三条补定成下面这版。

### 生产端：一单一画

**① 一次点单只调一次生成。** 从接单到交出去，`generate_image` 只调一次；画完必须 `read_image`
拿回执里的 `artifact.artifact_id` 亲眼看那一张——**看过才算交**。回执、sha、登记成 artifact
都只是流程证据（口径见「步骤 7」）。点单要 N 张＝ N 条单子各画一次，不是一张崩了可以拿 N 张去凑。

**② 画得不理想也不自己重画。** 交付前不许自行改提示词、换路线、换 seed 再抽一张来「修好」它。
理由不是省钱：修图循环＝在提示词上一层层叠上我自己的理解，**每修一次画面就离原单远一格**；
第五次那张既不是原单，也不是第一张崩的样子，而崩在哪一格还被我自己盖掉了。

**③ 崩了就如实报崩了。** 服务没起来、job 报 `failed`、超时之后取不回、出了图但画面不对——都算崩。
交回里就写「崩了」，并带真实读数：回执、`state`、服务端错误原文，或我看过的那张到底哪里不对。
**禁止暗修暗补**：不许悄悄换 seed、悄悄换路线、悄悄多抽几张、最后交一张「终于像样」的上去。
交出去那张必须是那一次点单的产物；不是，就得明说不是。

**④ 重画只发生在点单人明确说「再画」之后。** 我这张交回去、对方看过之后说「再画一次／还是不对，重画」，
才有第二次生成。重画**用原提示词**——原文从任务目录那张原图的 `prompt` 文字块、或交回里贴过的那份取，
别照记忆重写；**不拿崩掉那版当底**，上一轮我叠上去的那串词已经带着我的误读了。

### 交付端：一次只出一版

**⑤ 交付端一次只出一版。** 交回里就算躺着几版，也只挑一版发出去：**不挑不攒**——不并排发几张，
也不攒着等凑齐再发。这一条按图算：一条单子那张图只出一版，点单要 N 张就是 N 条单子各一版（与 ① 同一把尺）。

**⑥ 小瑕疵随图一句说明直接发。** 文字糊、局部毛病、构图差一点：既不是不发的理由，也不是再画的理由。
那一张照发，话里带一句说明（哪里糊、哪处不是我要的），别为它多花一次生成。

**⑦ 大毛病也只有两个出口：要么直接发，要么不发——没有「修」。** 脸崩、手崩、人换了、原单要的东西没画出来：
要么照 ③ 如实报崩了、那张不发，要么明说「就这张，毛病在这儿」照发。第三条路不存在——
**不拿坏版本当底改提示词，不自作主张重画**；要重画回到 ④：点单人明确说「再画」之后，且用原提示词。

### 别误读这一节

- **超时不等于画失败**：拿回到的 `prompt_id`／`job` 再取一次，取回的是同一张，不是重画（见「直路」那一节）。
- **本地 Pillow 修字不算重画，但也不自动做**：那条只在点单人点名「把这处字改掉」时走
  （见「改图与 `generate_image`」）；按 ⑥，普通小瑕疵是随图一句说明发出去，不是我先补一遍再发。
- **与「群聊生图上限」那节的关系**：那里的「最多 4 张」是一笔成本预算的上限，**不是默认张数**——默认就一张。
  4 张只在点单人明确说「多画几张／抽到满意为止」（那节自己写的唯一例外）时才动用；四道质量关照用，
  判的就是这一张，判不过走 ⑦ 的「不发」那一支。
- **这一节优先**：「直路」那一节与「步骤 7」原先各有一句「不对就改提示词或换路线重画」，是旧口径，11-12 已改成指回本节；
  以后正文再冒出同类说法，与这一节冲突时**以本节为准**。

## 前提与授权

下面这几条是**备用路**的前提；`generate_image` 不从这里过——它是行动脑侧的工具，
不需要 owner 集成授权，也不需要把请求放进集成进程里发。

- 需要 owner 集成授权。`import_integration_artifact` 属 managed integration 组，**QQ 任务的授权里不带它**
  （RUNTIME_API.md → Action capabilities → §Tools a task is given）；这条流程只能跑在有该授权的本机 owner 任务里。
- 生图请求只能在集成进程里发：`/integration/config.json` 只有受管理集成进程可读；普通 `sandbox_run` 完全无网络，
  `integration_test` 只允许配置内的 TCP 转发。探测脚本写进 **napcat-qq 通道包候选的 `integration/`**
  （`development_write` 带 `project: "napcat-qq"`），`integration_test` 把候选的 `integration/` 冻结成只读 `/app`
  试跑（实测：cwd 是 `/app`，往 `/app` 写报 `OSError` 只读文件系统；`/data` 是可写区，与启用服务的数据分开）。
  跑完把探针文件从候选里删掉（`development_run` 的 `rm`），别让它跟着下一次发布上线。
- 只写端点**别名**（`image`），不在脚本里硬编码 host/port；别名和地址由配置给，变了也不用我改代码。
- 展示这一步依赖文件落在**本任务绑定的工作区**：`import_integration_artifact` 写的就是这个工作区。
- 发图不需要行动侧授权：那是角色那一轮自己发出去的（所有对话都用 speak 的 picture part），字节由程序搬；
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
    data=json.dumps({"domain": "general", "input_mode": "text_to_image"}).encode(),
    # 11-20 现读：content_mode / input_type / prompt_granularity 已废（收但忽略，回 deprecated_selector 警告）；可用字段与 selectors 见「步骤 1」（run b9e37568）
    headers={"Content-Type": "application/json"})
res = json.loads(urllib.request.urlopen(r, timeout=40).read())
print("SELECTED", res.get("selected_workflow"))
for x in (res.get("matches") or [])[:3]:
    print("CAND", x.get("workflow_id"), "ready=", x.get("ready"), "score=", x.get("score"))
```

- 期望：`ENDPOINT_KEYS` 含 `image`（11-20 现读该机为 envoy／host／image／napcat／old-home，别拿旧三件套那串判「端点没了」）、`IMAGE_ENDPOINT {'host': …, 'port': …}`（host 与 port 是现读值：取自集成配置的 `endpoints.image`，只在 `integration_test`／`integration_start` 那一趟里读得到——跑一遍 `json.load(open(os.environ['ASUNA_INTEGRATION_CONFIG']))` 再打印；技能不存端口）。
- `resolve` 不加载模型、不排队，所以这一步**不会生成新图**；已有产物在不在，用步骤 3 的 job/history 查，别靠重画来"确认"。
- 配置里没有 `image`：停，回报「集成配置里没有 image 端点」。加端点要改集成 profile 并重启宿主才出现转发——
  这两件都不在本次授权里。

## 步骤 1：读服务自述，别把根路径当 API

`GET /.well-known/agent-manifest.json`（2026-11-20 现读 37,046 字节——旧正文「约 328 KB」作废，run 81b57d8b；按键取仍是习惯，现在整读也不挤正事）。
`protocol = project-comfyui-agent/v1`，`api_base = /project`，`authentication = none`。

服务自己的 instructions 里，跟这条流程直接相关的：

- 根路径 `/` 是原生 ComfyUI UI，不是 agent 首选入口；首选清单入口就是这个 manifest，备用 `/project/agent-manifest`、`/project/openapi.json`。
- 路由未知时 `POST /project/resolve`（`domain` / `style` / `input_mode`，词从 `route_table[].selectors` 现取；可选 `family`、`workflow` 点名看单条、`limit` 1–20 默认 1），**只选 `ready=true` 的条目**，并把 matches[0].workflow 里的 parameter_schema / prompting / agent_hints 一起用。**2026-11-20 起 `content_mode` / `input_type` / `prompt_granularity` 已废：收了不用，回 `deprecated_selector` 警告**（run b9e37568）。input_mode 可用值：text-to-image / image-edit / extend / image-to-image / inpaint / face-reference / openpose-control。
- `GET /project/workflows/{workflow_id}` 给出 `parameter_schema`（允许字段、必填、真实默认值）与 prompting；11-20 回执形状是 `{"workflow": 条目, "prompt": API 格式 graph}`——graph 在 `prompt` 键里，别和 `parameters.prompt` 混（run 46ffbe83）。
- `POST /project/generate`（或 `/project/prompt`）返回 `prompt_id`；`GET /project/jobs/{prompt_id}` 轮询到 `succeeded` 或 `failed`。
- 输入图先 `GET /project/inputs` 或 `POST /upload/image`（multipart，`type=input`，每次用新的唯一 basename）；**上传响应是输入文件名，不是产物引用**。
  手拼 multipart 的 boundary 拼错，服务端直接 500 不带 body；`type=input` 字段照 manifest 给全（11-20 首趟 500 的教训，run 1f79864b）。
- 服务端读面（operations 端点 17 个：GET 11／POST 5／DELETE 1，run 04d9e376；11-20 晚间逐口打了一遍）：`GET /project/routes`（resolve 的 GET 形状，晚间带 `domain=deepseek` 实打）、`GET /project/workflows`（全量＝422,935 字节）、`GET /project/workflows/{workflow_id}`（晚间单条打了角色条、`anima-turbo-inpaint`、`sdxl-face-reference-ipadapter`、`qwen-image-2.1-edit`）、`GET /project/models`（32 档，run dbcb4e39）、`GET /project/resources`（`max_pending_jobs` 32、`max_input_pixels` 16777216、`cpu_vae` true）、`GET /project/poses`／`/project/inputs`／`/project/jobs/{prompt_id}`／`/project/openapi.json`（22,935 字节、paths 21）、`DELETE /project/inputs/{name}`（晚间实测：`deleted: true`、`size_bytes`、`remaining_bytes`）。**只剩 `GET /project/models/{model_id}` 没打（未实测）**。逐口的量与用法在「能力面」那一节。
- models 账 11-20 新档（run dbcb4e39）：NIKKE/Rapi 两档（animagine 的 best_for 现含 NIKKE/Rapi，run 79ac3ea6）、`ai-girls-aiseak-anima-lora`（多角色一枚）、`controlnet-openpose-sdxl-xinsir`、`dwpose-pose-extractor`、`anima-control-pose-preview2`（正文 11-04 记的 `anima-control-pose` 在档、带 Preview-2 后缀）、`anima-ipadapter-character-reference-v10`、`ipadapter-plus-face-sdxl-vith`；glm／grok／kimi girl 的 LoRA 没有单独档而路线 ready——报现象，机制没扒。**放大模型不在这 32 条账里**（超分 11-20 实测在线，见下面 upscale 格），别拿这张单判超分没装。
- 参考图六种用途（`input_files.reference_uses` 是契约正本、正文不抄全；六格本趟与 `route_table` 逐条对过）：image-edit（`qwen-image-2.1-edit`，输出跟源尺寸取整到 32）、**extend（同一条＋`extend` 往外扩画幅——真 outpaint，实测见「改图与 `generate_image`」）**、image-to-image（15 条，`denoise` 默认 0.65；只给宽或只给高保形状，两个都给且形状不同是中心裁并回 `input_cropped`，从不拉伸）、inpaint（`moody-anima-inpaint`／`anima-turbo-inpaint`：必填 `input_image`＋`mask_image`，mask 宽高比须同原图，`mask_channel` 默认 `red`＝白／红重绘黑保留、`alpha` 走透明通道，`grow_mask_by` 默认 6，遮罩外像素合成回原图；**这一族没有 width／height 字段**）、face-reference（`sdxl-face-reference-ipadapter`／`anima-turbo-face-reference-ipadapter`，IPAdapter 非 FaceID；anima 条 `ipadapter_weight` 默认 0.6、sdxl 条默认 0.8，0.8–1.0 连衣服背景一起抄，`input_fit=none` 才把衣服一起参考）、openpose-control（18 条，与 `route_table[].pose` 同一集合）。六格契约本趟**全部实读**；只有标「实测」的那两格真跑过图。
- characters／角色 LoRA（本趟实读＋dry_run 实测）：`characters` 那一格本身**是一段散文不是清单**，清单在 `route_table[].selectors`：八条吉祥物角色路线（DeepSeek 大肥鱼、Claude 娘、ChatGPT 龙娘、千问娘、Gemini 娘（哈基米）、智谱娘、Grok 娘、Kimi 娘），每条各有 `domains`／`aliases`（例：DeepSeek 那条 `domains` 有 `deepseek`、`deepseek whale girl`，`aliases` 有 `DeepSeek娘`、`大肥鱼`、`鲸鱼娘`、`溟月`）；给这些词或点名 workflow 都会落到那条。**点上去 LoRA 就默认生效**（`loras.character` 默认 0.9、范围 −2–2；dry_run 里 graph 的 `strength_model` 跟着变）。写成成年人、别加降龄词（`agent_hints` 明说）。对照表与「冲突先问一次」那条硬口径在「能力面」那一节；**调弱 LoRA 工具面够不到**。
- `POST /project/images/transform`（即时裁／放，**不进队列、不用模型**；11-20 晚间实测）：`{"image": 输入文件名或任一 /view URL, "crop": …, "resize": …}`，两者都可给、先裁后缩；结果落成 `transformed/` 下一份**新输入文件**（回执 `name`／`url`／`size`／`operations`，`next` 明写这个名字可直接当 `input_image`／`face_image`／`mask_image`／`pose` 用，且像上传一样长期留着、用完自己 DELETE）。crop 支持像素框／aspect＋anchor（center／top／…／四角）／around:face（取景用最大脸，framing head／head-and-shoulders 默认／upper-body，找不到脸回 `face_not_found`）；resize 支持 width／height／scale／max_side（max_side 只缩小），放大只插值并回 `upscaled_without_model`。实测那枪：`{"image": "bg_base.png", "resize": {"max_side": 256}}` → `transformed/bg_base_256x222_e7047adc.png`、lanczos、256×222、warnings 空。生成产物可直接喂它转成输入文件。
- `POST /project/images/upscale`（模型超分，**11-20 实测两发**，run 1f79864b 加晚间那发）：`{"image": 输入文件名或 /view URL, "scale": 2}`，或点名 width／height（1–4x、输出最多 16.7 MP；两个都给且形状不同先中心裁），可选 `look`: anime／photo，排队轮询 job_url。档位与默认：不点名 `look` 时 job 产物按产出它那条路线的 look、上传图按 photo（回 `upscale_look_default`；anime＝4x-AnimeSharp 非商用协议、photo＝Real-ESRGAN x4plus，README 提醒会抹平照片细纹理）。白天那发：1024×1536→2048×3072、succeeded、elapsed 4797 ms、产物 6,916,293 字节 PNG、预览尺度下干净。晚间那发：`{"image": "bg_base.png", "scale": 2}`→480×416→960×832、succeeded、`elapsed_ms` 1234、提交回执 `workflow` 是 `image-upscale`、`upscale` 对象给 `source_size`／`output_size`／`look: photo`／`look_from`／`model: RealESRGAN_x4plus.pth`，仍只回 `upscale_look_default`。**放大模型不在 `/project/models` 那 32 档里**，要认它只能读回执 `upscale.model`。与本机 `asuna-image-upscale` 那条 run_sr.py 路**没做过质量比对**——两条并存，换路先测。
- `parameters.prompt` 必须显式给（空串合法）；`subject` 服务端 11-20 起标 `deprecated: true`，与 prompt 冲突一起给会被拒（run 46ffbe83）；`seed` 省略即随机；未知字段会被拒（`ignored_parameters` 恒空——11-20 extend 枪回执里它就是空表）。
- `compatibility_notes`、`selection.not_for`、模型兼容性与 prompting 是**约束**，不是建议。
- 限额逐路线放在 `parameter_schema`（顶层 `prompt_contract` 键 11-20 已没有，run 81b57d8b）：anima-turbo-v1-1 现读 prompt ≤ 8000、宽高 64–2048 且 8 的倍数、batch_size 1–4、steps 1–100——数值与旧正文一致，位置变了（run 46ffbe83）。

路由读数（11-20 现读 22 条全 ready，run 79ac3ea6）：文生图可用 `qwen-image-2.1-t2i`（**该路线参数面没有 steps 属性**、推荐只剩 cfg 1——旧正文「建议 steps 25–50」现读查无出处，作废，run dbcb4e39）
或 `anima-turbo-v1-1`；`*-edit` / `inpaint` / `face_image` / `control_image` 是另外的输入契约，别把 `input_image`
发给没声明图输入的路由。**写实这格 11-20 变了**：qwen 那条的 selectors 明列 photo／photorealistic／real world，moody-desire 的 best_for 原文写着「Qwen-Image stays the default photo route」（run 79ac3ea6）——照片有正牌入口了。
`style:"photoreal"` 现在 resolve 怎么落**没验**（resolve 是 POST，11-20 没发）——旧结论「退回 anime、结果偏插画」当未核实旧档留着。
不要把 resolve 的选择当成「这台机器认为这是照片」。

当前路线面：`generate_image` 的 `list_routes` 条数现读（出处：`list_routes=yes` 回执的 `workflows`；技能不存这个数），含改图路线（必填／可选／不收原图三种标记都有）。
上面那段只作 t2i 侧的读数；当前改图口径见「改图与 `generate_image`」一节。

先按目标选路由：

- 人物／动漫向：默认走 anime fallback（实测 `resolve` 给的就是 `anima-turbo-v1-1`），不用点名。
- 静物、要照片感：点名 `qwen-image-2.1-t2i`（11-20 起它就是 photo 路线；steps 不可设——schema 里没这个属性，默认即推荐，run dbcb4e39）。
- 旧「没有 photoreal 专用路由」是 resolve 行为的旧实测，11-20 没重测；字面层面 photo 词已归 qwen 条（上面 11-20 读数）。
  想要照片感仍写进 prompt；「偏插画」是旧 resolve 行为的预期，未重测。
- 提示词跟着选中 workflow 的 prompting 口径写（`prompting` / `prompt_granularity`），多数要英文。
- **CFG 1 的路由不吃 `negative_prompt`**：「不要什么」必须写进正向提示词（如 `no text, no watermark`），
  单开 negative 字段等于没说。

## 步骤 2：提示词按服务口径写，日常、不露骨

- 方言与粒度跟着选中 workflow 的 `prompting.granularity.recommended`；不要把别的模型族的触发词抄过来。
- 角色、服装、姿势、光线这些细节留在 `parameters.prompt` 里（`routing_boundary`：不为一个角色或一套衣服造路由）。
- 明确写 SFW 约束与不要的东西：`fully clothed` / `modest` / `no nsfw`，加 `watermark, text, extra fingers, deformed hands`。
- **店招／货架那一族：小价签是乱码高发位**。`every label blank`、`no letters` 这种整体约束压不住货架上那些小价签。
  实测两种写法有效：① 把价签本身要求写成 `blank white tag`，并且**整条提示词里不要再出现 `shelf label` 这个词**；
  ② 让镜头离开货架特写，价签根本不出现在画面里。撞出这条的是 anime 那条 fallback 路线（`anima-turbo-v1-1`），
  别的路线没重测。
- 主人说「只画日常」时，宁可少要一点细节，也别为了效果擦边。这条是偏好，不是模型能自动保证的——
  它只是 `content_mode=sfw` 的路由选择，画面内容还得靠 prompt 与（能做到的）复核。

## 步骤 3：定位 artifact_path —— 用服务回执，不猜文件名

`GET /project/jobs/{prompt_id}`，`state=succeeded` 后取输出里的 `/view?...` 相对 URL；
manifest 的 `result_contract.download_urls` 写的就是这个口径（`/project/jobs/{prompt_id}` 返回的相对 `/view` URL）。

- 走原生 `/prompt` 的图（例如服务端做小副本）用 `GET /history/{prompt_id}` 交叉核对（11-20：operations 17 端点清单里**没有** `/history`——它是原生 ComfyUI 路由、他 README 说原生客户端可用；本趟没打它，在不在未核实）：`outputs` 的
  `filename` / `subfolder` / `type` 拼成 `/view?filename=…&subfolder=…&type=output`。
- 别凭 prefix 猜编号。`sm_a_00001_.webp` 这种名字要靠 history 里的节点参数确认是哪一张。
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
  原生 `/prompt` 跑 `LoadImage → ImageScale → SaveAnimatedWEBP`（如 512×656、q70），
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
- DSH 自己的图片组件会渲染这种相对路径图。
- 本机这条私聊的报告照旧用上面这个 Markdown 图给人看（正文不进消息库，页面上照样显示）；11-13 装的那版起，本机私聊那一轮也有 `speak`，要把图作为一条消息发出去走步骤 8 的 picture part。
- 有人要图时走另一条路：上下文出现 `image_artifacts_from_program`，那一轮由她用 speak 的 picture part
  把图带上（11-13 那版起所有对话都只有 speak 能说话，`attach_image` 全线拿掉；QQ 那侧适配器仍按 `("image", "text")` 的段序发）。按步骤 8 发，别把路径贴进正文。

## 步骤 7：自己看一眼 —— 用 `read_image` 复核刚生成的图

主路：`generate_image` 回执里的 `artifact.artifact_id`（`blob-…`）直接喂给
`read_image` 亲眼看一遍，跟提交时的要求对——画面不对就照「只画一次」一节处理（如实报崩、或随图一句说明；重画只在点单人明说「再画」之后）。
**「提交成功、字节对、登记成功」不等于画对了**：job 回执、导入 sha、BlobStore 登记都只是流程证据，
画没画对以看过为准。依据：核侧 `read_image_for_task` 的 docstring 明写 ref 可以是已存好图的
artifact_id（自己画的、本场景存过的、这一轮可发的 offered 图）。

`read_image` 的 ref 两类都认：

- **已存好图的 `artifact_id`**（`blob-…`）：自己画的（`generate_image` 回执里的 `artifact.artifact_id`）、
  本场景存过的、这一轮可发的——复核自己刚生成的图走这条。
- **本任务附件清单里的 ref**（`att-…`，由 message_id + 段序号算出）：图本身是入站附件时
  （别人发来的、主人从页面上传的）用这条。

失败分支：只有**真读不到**才写「未做视觉复核」，并写清是哪种红：

- `VISION_ROUTE_UNSUPPORTED:...` —— 这一轮的路由没声明 image 输入，看不了图。
- `IMAGE_ATTACHMENT_NOT_IN_SCENE` —— ref 不在授权范围：既不是最近的场景附件，也不是可引用的 artifact_id。
  拿工作区文件名（如 `xiaoman_selfie.webp`）当 ref 就红在这里——文件名不是 ref，
  要读自己刚导入登记的图，用导入回执 `artifact` 里的 `artifact_id`。

两种红不一样，别混着说。也别把「没调用 read_image」写成「未做视觉复核」——那是没做，不是做不到。
写「未做」时依据只有 job 回执 + 字节核验 + 当时提交的 prompt，要照实列出来。

## 步骤 8：要把图发出去时，用 speak 的 picture part（不是发路径；所有对话同一条）

### 前提：三件都成立，那一轮才有这条路

1. **那一轮会给出可发图清单**：QQ 私聊仍看那两条（`session_class=owner_private` ＋ 通道路由 `target.type=dm`，
   现在就是主人的 QQ 私聊 （主人的 QQ 私聊场景，场景 id 以配置为准））；11-13 装的那版起，家里本机私聊、两条 agent 线、
   peer 线那一轮也有 `speak` 可以填 picture。条件过了，程序在那轮上下文里放
   `image_artifacts_from_program`：`items[]` 每条给 `artifact_id / sha256 / size / media_type / created_at`，
   新的在前、最多 6 条，外加一句 note 说明这些是程序存的、不是文件路径。
   另一种是她在的一个群（群场景、群路由；把私聊路由成群的不算）：清单里只有**她自己做的图**——
   从她自己的生成端点导入时登记的（来源 `integration:`），不分是在哪个场景做的；别人发来的图不在里面。
   心跳出门、`share_picture` 的那个群回合就是这条路。
   **11-13 那版起这条路不再分场合**：所有对话的 channel kind 都声明 reply parts，那一轮只有 `speak` 能把话
   说出去，发图就是它的 picture part（`attach_image` 这一族工具在所有对话的工具表里都没了）。
   方向不对或没图可引用时，清单块不出现；别拿它的缺席当「清单为空」推。
   一句话：哪儿发图都是 speak 的 picture part，`artifact_id` 从 `image_artifacts_from_program` 照抄。
2. **主人私聊，或她在的群**：别人的私聊、public 私聊会话一律不发；群里只发她自己做的图，一律全年龄，
   发不发、发到哪个群由她挑。不在这个范围就是**确定性拒绝**，
   不静默降级成「只发文字却报平台已送达」——那种回执会声称对方收到一张从没到达的图。
3. **图从哪来**（三条，都由程序登记，我不动 scope：**现画的**、**`render_svg` 从工作区里那份 SVG 渲出来的**、**已有字节带 `scope_key` 登记进某个场景的**——第三条那一格见「本机已有那张图怎么进可发清单」）：
   - 本场景自己存的：`read_image` 拉过的入站图，以及 `import_integration_artifact` 导入时字节是图 →
     顺手登记成**这个任务绑定 scope** 的 image artifact（`kind=image / state=DONE / storage=gridfs`）。
     工具参数面没有 scope 这一项，我改不了它；登记失败（scope 不认识、超上限、存储写失败）不影响导入本身，
     只在 `artifact` 里如实写 `registered: false` 与原因。
   - QQ 私聊那一轮还能引用**同一 canonical person 的另一个 owner_private dm 场景**登记的图——
     因为生图和导入只能在本机 owner 任务里做，而说图的轮次常在 QQ，两个入口都是主人自己的私人空间。
     清单里那几条会带 `from_linked_scene: true` 和它的 `scene_id`。这条边每次现算自配置
     （`context_links` / 路由 `read_scenes` + 对端 `kind=dm` + 两边都 owner_private + canonical person 同一个）；
     删掉那条边就退回只认本场景，不用改代码。本机 `scene:local-dm` 就是这种能被 QQ 端引用的来源。

### 怎么发：所有对话都用 speak 的 picture part，正文不写路径

任何一轮——speak 的 picture 一项，`artifact_id` 照抄 `image_artifacts_from_program` 这一轮列出的值，可以不带话：

```json
{"tool": "speak", "args": {"parts": [{"kind": "picture", "artifact_id": "blob-0f3c1e9a7b2d4c8f9a0b1c2d3e4f5061"},
                                      {"kind": "text", "text": "他要看的就是这张"}]}}
```

家里本机私聊、两条 agent 线、peer 线那一轮——同一个写法，不用另一套：一个 part 一条消息，`kind` 取 `text`／
`sticker`／`picture`；正文那一格是她自己的话（不进消息库、页面上显示），只有 `speak` 那一条真的发出去。

- speak 的 picture 只认 `artifact_id`（`kind` 那一格写 `picture`；旧 `attach_image` 的 `artifact_id` 必填（≤200 字符）、
  `why` 必填（≤500 字符）随工具一起退役，不必再写 why）。发图我自己仍守**一回合最多一张，再调用就换成新的那张**——
  speak 一条里能带几张 picture 我没重测，这条按老规矩留着，不是工具的保证。
- speak 发送前把所有 parts 全查一遍：**有一条不对，这一批一条都不排队**，回执点名哪条、为什么；
  旧 `attach_image` 那一层「被拒是工具错误、同一回合能改」没有了——现在哪儿都是整批不排队，改对再出声（见「失败怎么读」）。
- `artifact_id` 照抄清单里的值——它**不是文件路径也不是文件名**，别自己拼，也别填工作区里的 `xiaoman_selfie.webp`。
- SPEAK 正文不写文件路径、文件名，也不写「见图」「见附件」这类话：图随这条消息一起到。
  `from_linked_scene` 那几张也不必解释来处（程序已经核过那一边也是主人自己的私人空间）。
- 被接受的图只把 `{artifact_id, media_type, sha256, size}` 元数据挂到那条出站项上（旧 `attach_image` 写进 SPEAK **第一行**；
  speak 的 picture 是自己的一条 `reply_part` 项——一个 part 一条消息，图与话各占一条消息行），字节留在 BlobStore。
  适配器 claim 时带 `supports=image` 才拿得到这份元数据，再按 publication + attempt 来取字节；
  没声明就只发文字，并在行上记 `attachment_skipped=channel_does_not_declare_image`。
- 这一轮的出口只有两个：**要么用 speak 发出去，要么这一回合到此为止**——不想说就什么都不调用，也就没有消息，
  图更没地方挂（`stay_silent` 这个工具 11-13 那版起在所有对话都拿掉了；要说话就用 `speak`）。这一版没有为此单独的拒绝码。

### 往群里发图之前的自检

能往群里发图，不等于该发。往群里发图之前（所有对话都是 speak 的 picture part），我按这四条过一遍，任何一条过不去就不发：

1. **图本身全年龄向**。这是底线，不需要判断场合也守。
2. **这张图适不适合要发进去的那个群**。先看我自己写给那个群的笔记；没写过笔记，就看当场能看到的
   最近聊天，判断那个群此刻接不接得住。判断不了，就不发。
3. **只发我自己做的图**。别人发进来的图不往群里转。核心会拦（`ATTACHMENT_NOT_HER_OWN`），
   但我不拿它兜底，自己先不动手。
4. **不为了试功能发图**。没有真心想给大家看的东西，就不发；这不算损失。拿群当试验场才是损失。

四条都过了，才在那一轮真的把图带上。发不发、发到哪个群，终究还是那一轮里我自己定。

### 失败怎么读

所有对话同一条：picture 那一项不对，是 speak 这一批一条都不排队、回执点名哪条为什么；她读得到原因、同一回合改了再出声
（比如换清单里另一个 id），回合不会因此失败。旧 `attach_image` 那一层的**工具错误**（被拒只影响那一次调用、文字照发）随工具
一起没了，两条路合成一条。判定顺序不变：方向 → 在不在本轮清单 → 字节本身。

| code | 意思 / 我该怎么办 |
| --- | --- |
| `ATTACH_TARGET_NOT_ALLOWED` | 方向不对。detail 给具体原因：`session_class_not_owner_private` / `scene_has_no_channel_route` / `channel_route_not_authorized` / `target_not_dm` |
| `ATTACHMENT_NOT_HER_OWN` | 在群里引了一张不是她自己做的图（比如别人发来的）。群里只发来源带 `integration:` 前缀的图——那张可以是早就做好、后来重新登记进来的 |
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

适配器侧：私聊发 `[image, text]`，群里发 `[reply?, image, text/at…]`（图在话前面）。
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

### 旧写法别照做：DECIDE 时代的 attach

DECIDE 阶段已退役：那一轮发图是 speak 的 picture part（`attach_image` 这个工具 11-13 那版起也全线拿掉了，见步骤 8），“静默拒绝码”（如 `ATTACH_NOT_WHEN_SILENT`）在核代码里已不存在。
读旧记录按本段口径；别把 DECIDE 的 `attach` 字段当成现在的流程。

### 还没实测的

适配器用 OneBot `base64://` data URI 发图（私聊和群一样），源码里明写「NOT yet verified
against a real client」。说「QQ 那边已经能看到图了」要有依据：平台侧回读或对方本人确认，回执本身不算。
- 家里本机私聊与两条 agent 线那一轮的 picture part：这一版写的只有装完那一行（loaded.commit 816e825ea84f）给的口径，
  我这一趟没在本机真发过一张图，也没读过那一轮的 `image_artifacts_from_program` 长什么样（未核实）。家里那条道的出站大小
  另走 8 MiB 那一把尺（`MAX_ATTACHMENT_BYTES`，名与数照装的那版那一行抄，本轮没实测）；「实测补格」里「超过约 1 MB 先压小」
  那一格管的是 QQ 那条道，别拿它当本机的线。

## 改图与 `generate_image`

画图／改图的直路就是这个工具本身（见「直路：`generate_image`（第一选择）」一节）：回执把图登记成我自己的图，
`artifact.artifact_id` 喂 `read_image` 复核、也能随消息发出去。步骤 0–4 那条原生 HTTP 路是备用路，
留给端点探测、服务端小副本，和 `generate_image` 参数面给不了的模型／参数。

**改图入口：`source_image`**

- `generate_image` 有 `source_image` 参数：收图旁标的 ref，或一张已存好图的 `artifact_id`（`blob-…`）。
  **能喂哪些图，和这一回合 `read_image` 能看哪些完全一样**——read_image 看得到的，这里就改得动（ref 口径见步骤 7）。
- `list_routes=yes` 回来的路线条数现读、技能不存（出处：回执 `workflows` 数组；两处旧写死数已拿掉）：`qwen-image-2.1-edit` 标 `source_image: required`；
  其余多数标 `optional`（能纯文字画、也能改图，数目现读）；不带 `source_image` 标的 t2i 路线（如 `qwen-image-2.1-t2i`）不收原图。
- **带 `source_image` 不写 workflow 时，服务自己挑一条改图路线**（实测），不必点名 edit 那条。
- **`extend`＝真 outpaint（11-20 实测，长路 `POST /project/generate`，run 6c750521＋4051451a）**：qwen-edit 带 `extend:{right:512}`，1024×1536→**1536×1536**（输出＝原图＋扩展边，每边 ≤4096）；提交回执 `extend` 对象回显 output_size／drawn_at（没出 `extend_drawn_smaller`＝没缩小画），提交与 job 的 warnings 皆空（**没出 `extend_original_not_kept`**）；job elapsed 104 s。逐像素比对原区：diff 只落在贴缝右侧 63 px 一条带（bbox (961,0,1024,1536)，原区非零像素 5.32%、L>8 占 0.703%）⇒ **原区没有被重绘**；`read_image` 亲看对得上（人物、书、构图未动，新边床面自然延续）。机制（他 README）：灰画布＋提示词前缀＋贴回前按原区仿射对齐＋每边新侧 64 px 渐变；超过约 2.4 MP 的画布缩小生成再放大。**工具面 `generate_image` 没有 `extend` 键**——这一枪是长路发的；提示词只描述新区域。
- **工具面键位（当拍工具表列全；11-20 晚间复核同）**：`generate_image` 参数面只有 prompt／negative_prompt／workflow／style／width／height／seed／options（只收 `steps`／`cfg`／`sampler_name`／`scheduler`）／job／source_image／list_routes／target_relative_path／timeout，**没有** `pose`／`pose_strength`／`extend`／`loras.character`／`input_fit`／`mask_image`／`denoise`／`face_image`——**服务端有 ≠ 我当场能指定**；这类单子照旧走长路 `POST /project/generate`（或 upscale／transform 那两个端点）或写进 prompt（与「姿势」那节 11-05 那句同口径）。逐能力对照在「能力面」那一节。
- edit 路线自述（`list_routes` 里读到的）：输出尺寸跟着原图走（按 32 的倍数取整）；提示词写成直接指令——
  改什么、点名什么必须不动。

**群内来图的三条路**

- **群线收到的来图是消息图（attach ref，`att-…`）**：可以直接喂 `generate_image` 的 `source_image`。
- **`artifact_id`（`blob-…`）**：同样直通。
- **只有本地路径读图是家里限定**（`IMAGE_PATH_HOME_ONLY`）：传路径会被拦，不是 attach 不行。
- 判据一句：**报「这条路做不了」之前，先分清限的是哪种入口，再想一遍今天有没有用别的路走过同一件事。**

**配错路线：瞬时返回，不排队、不白传图**

- `IMAGE_WORKFLOW_TAKES_NO_SOURCE` —— 这条路线只从文字画，别带原图；
- `IMAGE_WORKFLOW_NEEDS_SOURCE` —— 这条路线要原图；
- `IMAGE_WORKFLOW_NEEDS_MORE_PICTURES` —— 这条路线还要别的图，回执带 `needs:["mask_image"]` 说明缺什么。
- **inpaint 路线从 `generate_image` 永远进不去**：工具参数面根本没有 `mask_image`，所以它们不进 `list_routes` 清单
  （edit 路线的 not_for 把遮罩改动指到 inpaint 路线——服务端 11-20 已给名：`moody-anima-inpaint`、`anima-turbo-inpaint`（run 79ac3ea6，未实测）；`generate_image` 清单收不收它们没重测，别去工具里赌）。

**归属边界：改了谁的图，结果算谁的**

- **改我自己画的图，结果还是我的**：能发到我自己的图能去的地方（口径见步骤 8）。
- **改别人发的图，结果不算我的**：`read_image` 对这种图回 `produced: false`；**只能发回原图所在那个对话**
  （主人的私聊按步骤 8 的联动场景那条另算），发到别的群／别人的私聊会被 `ATTACHMENT_NOT_HER_OWN` 挡。
- **来源前缀决定这行算谁的**：详见「本机已有那张图怎么进可发清单」里 `source` 那一条。

**修图里的错字：本地合成，不重画**

- 家里派出去的任务里，行动脑能 `sandbox_run` 跑 Python＋**Pillow**；本机 Windows 字体目录（`C:\Windows\Fonts`）
  **中文字体不缺**：`msyh`／`simhei`／`simsun`／`simkai`／`simfang`／Noto SC 都在（实测）。
- 做法：**纯色块盖住原文，按实测墨迹位置和字号逐字重写**；实测矩形外**逐像素 0 变化**——只动字那一块，其余画面不碰。
- **硬边界：群里交出去的任务没有 `sandbox_run`，这类活得回家做**。

**发出去的图不带提示词**

- 登记成可发的那份会剥掉 PNG 的 `tEXt`／`iTXt`／`zTXt` 文字块（**像素和其余块一个字节不动**）；
  任务目录那份原文件照旧带着 `prompt` 块，供复现。
- 判据一句：**图也是会说话的东西，发出去前除了画面还得看它身上带了什么字**。

**排队成本**

- 一次改图实测：**排队约 85 秒、生成约 60～88 秒**，一张卡。**别连烧**——
  串行调度、切 workflow 卸模型（见已知坑），连排几张就是干等几轮。

## 能力面：现读口、长路配方与工具面键位（腿照这一节就能调，不用再去拉自述）

这一节只管**有没有这个能力、当场怎么调**；画面好坏的经验在「人像实测」与「实测补格」。
原则：能走工具面就走工具面（见「直路」）；**只有工具面没有那个键，才走长路**。
长路都在 `integration_test` 里发，base 从集成配置现读（别名 `image`，别硬编码 host／端口）：

```python
import json, os, urllib.request
e = json.load(open(os.environ["ASUNA_INTEGRATION_CONFIG"], encoding="utf-8"))["endpoints"]["image"]
BASE = "http://%s:%s" % (e["host"], e["port"])            # GET 直接读；POST 带 Content-Type: application/json
print(json.loads(urllib.request.urlopen(BASE + "/project/resources", timeout=30).read()))
```

### 硬口径：与角色脑的指令相抵时，停一次（一张图最多问一次）

**角色脑的指令——包括它给的提示词，以及「只走 prompt」「不用 lora」这类默认——与你这一趟现读到的能力相抵时
（尤其你探到与目标角色直接对应的 character 路线／character LoRA），停下来 `ask_character` 一次：
说清你探到什么、它的指令挡在哪。它答完再画。不许自己选，也不许按旧默认画完当作没冲突。**

为什么钉在这里：角色 LoRA 是**跟着路线默认上的**（`loras.character` 默认 0.9，本趟 dry_run 实测），
所以「点那条角色路线」与「不用 lora」这两件事**天然冲突**——要真不用 LoRA 就得换路线，
或走长路把 `loras.character` 调下去（工具面没这个键）。这个取舍属于点单人，不属于腿：
点单那一侧不掌握引擎的具体能力面，腿也不替它决定要哪一个。冲突没解开就画，两种画法都算没做完交代。

### 一、只读枚举口：一行命令、当拍读到的量、全量在哪

**别整读 manifest**（当拍 37,046 字节一发；要哪格取哪格）。下面每个数都是当拍回执原样：

- `GET /.well-known/agent-manifest.json` → 37,046 字节、17 个键。按键取：`operations`（17 个端点全表：GET 11／POST 5／DELETE 1）、
  `route_table`（22 条路线：`selectors.domains`／`.aliases`／`.styles` 与 `pose` 标记都在这）、`characters`（**一段散文**，不是清单）、
  `input_files`（六种参考图用途的契约）、`image_tools`（transform／upscale 契约）、`warning_codes`（13 个）、`error_codes`（19 个）、
  `poses`、`result_contract`（job 状态与相位）、`instructions`（6 条硬约束）、`resolve`（可用选择器；`content_mode`／`input_type`／`prompt_granularity` 已废）、`service`、`quick_start`。
  顶层常量：`protocol` `project-comfyui-agent/v1`、`api_base` `/project`、`authentication` none、`api_version` 2.0.0、`schema_version` 1。
- `GET /project/workflows` → **422,935 字节**（22 条全量，每条带 `parameter_schema`＋`prompting`＋`agent_hints`）⇒ 只要一条就走
  `GET /project/workflows/{workflow_id}`（本趟单条打了 4 条；参数面、必填、真实默认都在那一条里）。
- `GET /project/routes?<resolve 那几个字段>` → resolve 的 GET 形状，同一把尺。实测 `?domain=deepseek&limit=3`：
  `selected_workflow` 落 `deepseek-whale-girl-anima-turbo`、score 150、`selection.total_matches` 7、`fallback` false、`warnings` 空。
- `GET /project/models` → 32 档、`ready` 全 true；`kind` 见 diffusion-model／checkpoint／text-encoder／vae／lora／ip-adapter／
  clip-vision／controlnet／preprocessor／vision-encoder；`include_candidates=true` 才带上没用上的。**放大模型不在这 32 档里**
  ——upscale 实跑在跑，要认那把模型只能从回执 `upscale.model` 读。`GET /project/models/{model_id}` 本趟**没打**（未实测）。
- `GET /project/poses?q=&people=&angle=&limit=` → 一页默认 8 条、`total_matches` 196；`q=sit`→34、`q=stand`→31、`q=坐`→0。
  条目形状 `{id, name, name_zh, category, framing, people, views{front,diag,side,high,low}, match_score}`。
- `GET /project/inputs` → 当拍 90 个文件／83,151,167 字节；`lifecycle` 明写跨重启保留、**没有自动 TTL**，只有显式 DELETE 或人工才删
  ⇒ 上传用唯一 basename，自己传的自己用完删。
- `GET /project/resources` → 显存快照＋`max_pending_jobs` 32、`max_input_pixels` 16777216、`cpu_vae` true；`out_of_memory` 时把它一起报回去。
- `GET /project/jobs/{prompt_id}` → `state`（queued／running／succeeded／failed）＋`phase`＋`outputs[].url`（相对 `/view`）＋`elapsed_ms`。
- `GET /project/openapi.json` → 22,935 字节、`paths` 21（要精确契约时才读，平时按键取 manifest）。

### 二、每个能力：工具面有没有那个键 → 没有怎么发 → 验过没有

标「实测」＝本趟或旧趟真跑过那次调用／真出过图；「实读」＝只实读过服务端参数面与契约；「未实测」＝只按契约写配方，没验证过。

1. **文生图** — 工具面**有**：`workflow`＋prompt／width／height／seed／options／negative_prompt。实测（多趟）。
2. **改图（按指令改）** — 工具面**有**：`source_image`（点 `qwen-image-2.1-edit`，或不点名让服务自己挑）。实测（多趟）。
3. **图生图（换模型风格重描）** — 工具面有 workflow＋source_image，但 **`denoise` 工具面没有键**（这族默认 0.65）⇒ 要控 denoise 走长路：
   `POST /project/generate` `{"workflow": …, "parameters": {"prompt": …, "input_image": …, "denoise": 0.4}}`。实读，**未实测**。
4. **真 outpaint（extend）** — 工具面**没有** `extend` ⇒ 长路 `{"workflow": "qwen-image-2.1-edit", "parameters": {"input_image": …,
   "prompt": "只描述新区域", "extend": {"left": 256, "right": 256}}}`；输出＝原图＋扩展边，回执 `extend` 给 `output_size`。实测（见「改图与 `generate_image`」那一格）。
5. **局部重绘（inpaint）** — 工具面**永远进不去**（没有 `mask_image`，那两条路线也不在 `list_routes` 里）。长路：必填 `input_image`＋`mask_image`
   （`required` 就是这两个）；`mask_channel` 默认 `red`（白／红重绘、黑保留），`alpha` 走透明通道（图没透明回 `mask_alpha_missing`）；
   `grow_mask_by` 默认 6（0–64）；`denoise` 1.0 整块替换、调低留更多原图；**这一族没有 width／height 字段**⇒输出＝源尺寸（8 的倍数）；
   遮罩外的像素合成回原图。实读参数面，**未实测**。
6. **人脸／角色参考（face-reference）** — 工具面**没有** `face_image`，而 `source_image` 会不会落成 `face_image` **没测过** ⇒ 稳妥走长路。
   必填 `face_image`（任何一张清楚的人像，服务自己裁到最大脸；`input_fit=none` 才连衣服一起参考）；
   `ipadapter_weight`：anima 那条默认 0.6、sdxl 那条默认 0.8，0.8–1.0 会把参考图的衣服与背景一起抄走；IPAdapter 不是 FaceID。实读，**未实测**。
7. **姿势（pose）** — 工具面**没有** `pose`／`pose_strength` ⇒ 写进 prompt，或长路 `parameters.pose`（库里的姿势 id／视角 id，
   或一张上传图的相对名）＋`pose_strength`（0–1，默认 1.0）。dry_run 实测（带 pose 时回执多一个 `pose` 对象；细节见「姿势」那一节）。
8. **角色 LoRA（character）** — 工具面够得到**路线**（`workflow` 键），够不到**强度**：`loras.character`（范围 −2–2，**默认 0.9**）工具面没有这个键。
   **点了角色路线＝LoRA 默认 0.9 已经上了**；要调弱走长路 `{"workflow": …, "parameters": {"prompt": …, "loras": {"character": 0.5}}}`。
   dry_run 实测：不给 `loras` 时 `applied_parameters` 里就是 `{"character": 0.9}`；给 0.5 时 graph 里 `strength_model` 跟着变 0.5；`ignored_parameters` 空。
9. **超分（服务端那条）** — 工具面没有 ⇒ `POST /project/images/upscale` `{"image": 输入文件名或任一 /view URL, "scale": 2}`
   （或点名 width／height；1–4x，输出最多 16.7 MP；两个都给且形状不同会先中心裁）＋可选 `look`: anime／photo（不点名：job 产物按产出它那条路线的 look 走，
   上传图按 photo 并回 `upscale_look_default`）。返回排队回执（`prompt_id`／`job_url`／`upscale` 对象给 `source_size`／`output_size`／`look`／`model`）
   ⇒ 轮询 job ⇒ 产物 `outputs[].url`。队列与生成同一把尺（`max_pending_jobs` 32）。**实测**（两发，读数见「步骤 1」upscale 那一格）。
10. **即时裁／放（transform）** — 工具面没有 ⇒ `POST /project/images/transform`（**不进队列、不用模型**，即时返回）。
    必填 `image` ＋ `crop` 或 `resize`（都给则先裁后缩）；返回一份**新输入文件**，`name` 可以直接当 `input_image`／`face_image`／`mask_image`／`pose` 用，
    像上传一样长期留着、用完自己 DELETE。**实测**（契约与读数见「步骤 1」transform 那一格）。
11. **校验与像素预算（不排队、不出图、不花钱）** — `POST /project/generate` 带 `"dry_run": true`：回 `validated`、`applied_parameters`、
    `effective_parameters`、`ignored_parameters`、`warnings`、`pose`、`extend`、`resources`，加 API 格式 graph（在 `prompt` 键里，别和 `parameters.prompt` 混）。
    **`resources.limits.max_total_pixels` 就是那把像素预算尺**（本趟角色那条路线读到 2,359,296＝`over_pixel_budget` 那句警告的依据；
    `basis` 自己写着是准入预算、不保证模型装得下）；判「参数被吞还是被拒」先读 `ignored_parameters` 与 `warnings`。实测（两发）。
12. **输入文件的进出** — 上传 `POST /upload/image`（multipart：`image`＋`type=input`，boundary 拼错服务端直接 500 不带 body）；
    列档 `GET /project/inputs`；删除 `DELETE /project/inputs/{name}` **实测**（回 `deleted: true`、`name`、`size_bytes`、`remaining_bytes`）。

### 三、八条角色路线（点名画「某家娘」时的对照表；全量在 `route_table[].selectors`）

触发词写进 prompt，路线填进 `workflow`（或走 `/project/routes?domain=<角色词>` 现读）；别名只列常用的几条。

| 路线 | LoRA 触发词 | 能匹配上的 domain／别名（样例子集） |
|---|---|---|
| `deepseek-whale-girl-anima-turbo` | `deepseek_whale_girl_zipzippipe`（女仆装另有 `deepseek_maid_outfit_zipzippipe`） | `deepseek`、`deepseek whale girl`、`DeepSeek娘`、`大肥鱼`、`鲸鱼娘`、`溟月`、`DeepSeek-chan` |
| `claude-girl-anima-turbo` | `ors scholar` | `claude girl`、`claude-chan`、`Claude娘`、`Anthropic girl` |
| `chatgpt-girl-anima-turbo` | `Chatgpt_dragon_girl` | `chatgpt`、`gpt girl`、`ChatGPT娘`、`ChatGPT 龙娘`、`OpenAI娘` |
| `qwen-girl-anima-turbo` | `qwen \(girl\)` | `qwen girl`、`qwen-chan`、`千问娘`、`千问` |
| `gemini-girl-anima-turbo` | `gemini_ai` | `gemini girl`、`哈基米`、`哈基米娘`、`Gemini娘` |
| `glm-girl-anima-turbo` | `aigirls, aigirls（glm）` | `glm girl`、`智谱娘`、`智谱清言娘`、`Zhipu girl` |
| `grok-girl-anima-turbo` | `aigirls, aigirls（grok）` | `grok girl`、`Grok娘`、`Grok vampire girl` |
| `kimi-girl-anima-turbo` | `aigirls, aigirls（kimi）` | `kimi girl`、`Kimi娘`、`月之暗面娘`、`Moonshot girl` |

- glm／grok／kimi **共用一枚多角色 LoRA**（`ai-girls-aiseak-anima-lora`，触发词前两串就是它）；其余五条各有自己那枚。
  这五条的 LoRA 在 `/project/models` 里有单独档（例：`deepseek-whale-girl-zipzippipe-anima-lora`，graph 里的文件名
  `DeepSeek_WhaleGirl_ZipZipPipe_Anima2B.safetensors`），glm／grok／kimi 没有各自单独档——**现象记着，机制没扒**。
- **表是快照**：接单时按目标现读（`/project/routes?domain=…` 一行就够），别拿这张表当唯一凭据；角色一律写成成年人，别加降龄词。

### 四、两把尺的现行数量（本趟实测对过）

`list_routes=yes` 18 条 vs `route_table` 22 条：**差的正是两条 inpaint（`moody-anima-inpaint`、`anima-turbo-inpaint`）
＋两条 face-reference（`sdxl-face-reference-ipadapter`、`anima-turbo-face-reference-ipadapter`）**。
「服务端有这条路线」不等于「我当场能点它」——这一格与「`list_routes=yes` 每条给哪些键」那节同一口径。

## edit／改图通路读数

`qwen-image-2.1-edit` 这一条（一张修手单两枪实测；带 `source_image` 不点名 workflow 时，服务自己挑的也是这类通路）：

- **整图轻重绘，不是像素级局部改。** 指令只决定重点改哪一处，其余像素同样被重画一遍：五官微调、发丝路径重排、
  衣纹与蕾丝纹样重画、物件位移（实测有一处整体下移约 70 像素）。要「其余像素一模一样」得走 inpaint，
  而 inpaint 从 `generate_image` 根本进不去（见「配错路线：瞬时返回，不排队、不白传图」那一格）。
- **出图可能带窄黑边**（letterbox）：**部分构图会出现，只报现象、别当机制**——那两枪右缘都有一条纯黑竖条、底缘一条细黑边（宽度是目测、没量尺），
  但一张方形图四边实测 0 px 没复现；尺寸也跟着底图取整到 32 倍（941×1672 → 928×1664）。判「其余部分保住了没」先把这两格排掉，别当画崩。
- **色温会漂移**：线条和色温都有细微漂移，两枪都有。比对要按局部裁开放大看，整张扫一眼判不了这一格。
- **该路线 CFG 1，`negative_prompt` 完全不生效**，服务原样回警告
  `negative_prompt_inactive: At CFG 1 the sampler skips negative conditioning`。
  **禁令一律写成正向指令**：「不要 X」没用，写成「保持原有 X 不变」／逐项点名「X 保持原样不动」这一类。
- 要求也得写进正向才算数，但**写了指令 ≠ 改到位**：把手指数目在正向里写死
  （`exactly five fingers in total: one thumb plus four fingers`）之后，两枪逐根数下来仍各多一根。
  改图单交回前必须 `read_image` 把那个目标本身再数／再看一遍，别拿「生成成功」当「改对了」。

## 姿势（pose）与现行 prompt 口径（2026-11-04 探到，服务端升级后的现量）

来路：2026-11-04 10:0x 本机 owner 任务里，经 `integration_test`（image 端点别名；端口现读自集成配置，上文步骤 0 已改成现读句式）读 `/.well-known/agent-manifest.json`、`/project/poses`、`/project/workflows/anima-turbo-v1-1`，并对 `/project/generate` 做 `dry_run`（不排队、不出图）。manifest `api_version` 2.0.0、`schema_version` 1。旧版 manifest 没留存档，所以下面「新」是现行原文，不是逐字新旧对照。

**姿势：传法**

- 参数：`parameters.pose`（字符串，maxLength 512）。值＝「A pose id from the pose library, or the name of an uploaded image whose pose should be copied.」可选 `parameters.pose_strength`（数，0–1，默认 1.0；只有路线的 parameter_schema 列了才有）。
- 什么时候传：「Send pose when the requester asks for a specific body pose or hand gesture, or gives a pose image. Otherwise leave it out.」
- 找库里的姿势：`GET /project/poses?q=<英文或中文姿势名>&people=1|2&angle=front|diag|side|high|low&limit=1-20`（默认 8）。库 196 条。实测 `q=sit` 返回 total_matches 34；`q=坐`（单字中文）返回 0——中文要用库里的完整词，搜不到就换英文。11-20 晚间复核：196、`q=sit`→34、`q=stand`→31、`q=坐`→0 同一批读数；手写 HTTP 时中文得先 percent-encode——非 ASCII 直接拼是客户端报错，不是服务端拒绝。
- 返回里每条：`id`（如 `full_single_P003`）、`name`、`name_zh`、`category`、`framing`、`people`、`views`（front／diag／side／high／low 各一个视角 id，如 `full_single_P003_front`；有的姿势缺某个视角，如 P002 没有 front）。传视角 id；只传裸 pose id＝取 front，没有 front 则取第一个视角。
- 样例（dry_run 实测通过）：`{"workflow": "anima-turbo-v1-1", "dry_run": true, "parameters": {"prompt": "masterpiece, best quality, 1girl, solo, sitting", "pose": "full_single_P003_front", "width": 512, "height": 512}}` → `validated: true`，`applied_parameters` 多出 `pose`、`pose_strength: 1.0`，回执多一个 `pose` 对象：`{source: library, id, name, angle, people_detected: 1, strength, size, adapter: anima-control-pose, skeleton_url}`。
- 用自己上传的图当姿势：先 `POST /upload/image` 得输入文件名，把那个名字放进 `pose`；服务抽骨架，衣服、脸、场景仍由 prompt 决定。没检出人体报 `pose_not_detected`。
- 不传宽高时输出跟姿势图的长宽比；Anima 路线传 pose 时宽高取 16 的倍数。
- 路线：不是每条路线都收 pose（manifest `route_table[].pose`）；实测收的有 qwen-image-2.1-t2i、moody-anima-mix、moody-desire-v30、animagine-xl-3.1-nsfw、anima-turbo-v1-1、各角色 anima-turbo 路线、两条 face-reference、janku-illustrious、janku-v5-illustrious、one-obsession。要先 resolve 的话给 `input_mode: "openpose-control"`；若这样把想要的路线挤掉（`selection.fallback` 为 true），不带 input_mode 重 resolve、留住那条路线，姿势写进 prompt。
- 不收的：同时带 `input_image`（改图、图生图、inpaint）一律拒，`pose_unsupported`：「pose works when generating from text (face_image is fine); it cannot re-pose input_image.」（实测 qwen-image-2.1-edit 加 pose 即得此码，HTTP 400。）
- prompt 里也要写姿势：「Also name the pose in the prompt (e.g. sitting, knee up, hand on chin): on Illustrious and character-LoRA routes seated and kneeling poses often stay standing when only the skeleton asks for them.」
- 库里没有合适的：别传 pose，把姿势写进 prompt（manifest 原话 `no_match`）。
- 错误码：`pose_unsupported`、`pose_unknown_id`（实测传 `nope_id` 得此码，HTTP 400）、`pose_not_detected`、`pose_fetch_failed`（库里草图取不到，稍后重试或换一个）、`pose_unavailable`（服务器没装姿势依赖）。

**`generate_image` 能不能传姿势：不能（11-04 读参数面，11-05 复核仍未有）**

- 直路 `generate_image` 的参数面（11-05 照当回合工具参数表列全）：prompt／negative_prompt／workflow／style／width／height／seed／options（只收 steps、cfg、sampler_name、scheduler 四个键，多给的键不收）／job／source_image／list_routes／target_relative_path／timeout。里面没有 `pose`／`pose_strength`（11-05 复核，依据是当回合工具参数表本身；以后判这一格先看当回合工具表，不抄这句）。所以要带姿势只能走长路（`integration_test` 直连 image 端点 `POST /project/generate`，再按步骤 3–4 取产物导入），或把姿势只写进 prompt。
- 返回形状：`generate_image` 回执没有 pose 对象——实测一张 512×512 anima-turbo-v1-1（seed 1），回执键为 generated／workflow／prompt_id／seed／width／height／elapsed_ms／target_relative_path／bytes／sha256／media_type／guidance／artifact／note；11-05 那张多一个 `warnings`（11-04 记的键表里没有这一格——当时没出现还是那次没注意，判不了，旧回执原件没留）。`guidance.structure` 现为 quality/meta、subject count、character/series、appearance、outfit、pose、composition、environment（pose 在 outfit 与 composition 之间；是否新增未核实）。
- 长路的服务端回执（`POST /project/generate`）：`prompt_id`（也叫 `job_id`）、`job_url`、`applied_parameters`、`effective_parameters`、`warnings`，带 pose 时多一个 `pose` 对象；`dry_run` 返回同样的字段加 `validated` 与 API 格式的 `prompt`，没有 `prompt_id`。

**prompt 现行口径（服务端原文）**

- `parameters.prompt` 必填（空串合法），≤8000 字符；宽高 64–2048 且为 8 的倍数（MOSS-Image 取 16 的倍数；11-20 的 instructions 原文仍这样写）。anima-turbo-v1-1 现读默认：896×1152、steps 12（推荐 8–12）、cfg 1.0、sampler `er_sde`、scheduler `simple`、filename_prefix `anima_turbo_v1_1`（run 46ffbe83）。
- anima-turbo-v1-1 的 `prompting.structure`：quality/meta、subject count、character/series、appearance、outfit、**pose**、composition、environment、lighting（pose 这一格是新是旧没有旧版原文可比，未核实）。
- negative：服务端现在明说了：`negative_prompt_effective_at_default: false`，「CFG 1 skips negative conditioning. Negative text has no effect at the default setting; CFG changes can affect distilled-model quality.」——和上文「CFG 1 的路由不吃 `negative_prompt`」一致，「不要什么」仍写进正向提示词。negative 字段仍被接受，默认值全文（11-20 现读，run 46ffbe83）：`worst quality, low quality, score_1, score_2, score_3, blurry, jpeg artifacts, artist name, chromatic aberration`。
- 内容：manifest `content`：「Resolve never routes by content: the prompt decides what an image shows … When the selected route has prompting.content_lines, add its 'explicit' or 'safe' line to the prompt. Explicit images must show adults.」我们只画全年龄：选中路线有 `prompting.content_lines` 时，把它的 `safe` 那一行加进 prompt。
- 其他：保存的 PNG 带 ComfyUI prompt 元数据（输入文件名换成 `[input image]`）；发到不该看到 prompt 的地方前要剥（本技能「发出去的图不带提示词」一节已覆盖）。
- 路线条数：现读 `list_routes=yes`（技能不存条数；11-04 那一趟读到的数已按现读口径从正文拿掉，正文几处旧写死数一并改成现读句式）。

**`list_routes=yes` 每条给哪些键（11-05 照回执列）**

- 路线条目：`workflow`、`description`、`style`、`structure`、`quality_prefix`、`prompt_scope`、`best_for`、`not_for`、`size`、`example`；
  改图路线另有 `source_image`（`required` / `optional`，11-05 那一趟：1 条 required、多数 optional、t2i 那几条不带这个键）。
  **条目里没有 pose 相关的键**——工具面上姿势只能进 prompt（服务端那套 `parameters.pose` 见上面「传法」，走长路）。
- 顶层另有 `note`（挑路线与写提示词的口径：按 best_for／not_for 选、用它要的 style 和语言，多数要英文）。
- 11-05 那一趟读到的名单（**快照**，出处＝那一趟回执的 `workflows` 数组；现行条数照旧现读，别拿这串当计数）：
  `qwen-image-2.1-t2i`（自然语言；静物／写实／带字海报；不收原图）、`qwen-image-2.1-edit`（`source_image: required`）、
  `moss-image-sft-t2i`（自然语言；版面与文字位置要准；短 prompt 会画崩解剖）、`moody-anima-mix`、`moody-desire-v30`（Flux.2 Klein 4 步；写实人物）、
  `animagine-xl-3.1-nsfw`（tag 方言）、`anima-turbo-v1-1`（anime 默认）、八条角色路线
  （`deepseek-whale-girl-anima-turbo`、`claude-girl-anima-turbo`、`chatgpt-girl-anima-turbo`、`qwen-girl-anima-turbo`、
  `gemini-girl-anima-turbo`、`glm-girl-anima-turbo`、`grok-girl-anima-turbo`、`kimi-girl-anima-turbo`，各有触发词）、
  `janku-illustrious`、`janku-v5-illustrious`、`one-obsession`。
- **两把尺不是一把（11-20 晚间实测对过）**：`list_routes=yes` 18 条 vs 服务端 `route_table` 22 条，**差的正是两条 inpaint（`moody-anima-inpaint`、`anima-turbo-inpaint`）＋两条 face-reference（`sdxl-face-reference-ipadapter`、`anima-turbo-face-reference-ipadapter`）**；`route_table[].pose` 那份「收 pose 的路线」名单里有两条 face-reference，它们都不在工具面清单里。清单＝`generate_image` 用得上的路线，不等于服务端路线全集；报「有没有这条路线」要先说哪把尺。

## 人像实测：构图决定拉链、自拍别指望手机、交图前放大复核

自画像／人像单子的三条现场经验（前三条来自同一批四张实测加一次便宜档复核，路线是 anima／illustrious 这一族；每条末尾写适用面）。

**① 构图决定连帽衫拉链开不开**

- 「趴床／前倾／斜倚」这一类构图**几乎必然**把拉链画开（实测两连败）；
  「坐直＋拉链拉到下巴＋领口折起来」这一串字面**一次就中**（实测双中）。要给保守版交底，就照抄这串字面，别改措辞。
- 英文写法照 prompt 走：`sitting upright`、`zipper pulled up to chin`、`folded collar`。
- **便宜档别拿来判配方**：11-05 一张草稿（`anima-turbo-v1-1`、512×512、steps 4，低于推荐的 8–12）坐姿命中、拉链没画开，
  但拉头落在胸口、领口没折。那格漂移算在步数还是字面上**判不了**（要判得在推荐步数里重测）。

**② 手持自拍透视：别指望模型把手机画进手里**

- 实测三张全把手机丢了或放在桌上——「手里拿着手机自拍」这个语义它接不住。
- 可行写法是**手臂伸出画外**（`arm extended toward viewer, out of frame`）：自拍感靠手臂方向给，不靠手机本体。
- 交底口径：把「手机进画」当**可选项**、别列硬项（与「官方定妆」里「手机＝场景道具」同一条）。

**③ 交图前 `read_image` 亲眼看，而且要局部放大**

- 登记进清单 ≠ 能发；回执、sha、artifact 都只是流程证据（口径见「步骤 7」）。
- **缩略图会藏崩的地方**（11-05 实测）：整张看着是微笑，放大才看到拉链头挂在嘴边垂到下巴；
  整张看着「拉链拉到顶」，放大才看到拉头其实在胸口、领口摊开。
- 做法（家里沙箱，不联网不花钱）：Pillow 按坐标裁出**领口／拉链、手、脸**三块，`resize` 放大 3 倍（LANCZOS）存进任务工作区，
  再按路径逐块 `read_image`。整张看过一遍不等于这三块看过。

**④ 人物身上的小平面同「小价签」一族**

- 胸口图案、手机背面、墙上画框这类小平面：要么在 prompt 里用 `plain`／`no graphic` 压住，要么预期长出乱码字母或发光贴图
  （实测四张里三张在这三类平面上出问题）。
- 交图前按局部裁开放大复核这几处，别只看整张缩略（与上面第③条同一做法）。
- 适用面：那四张读出来自 `janku-illustrious`；小价签那一族来自 `anima-turbo-v1-1`。**别的路线没重测**，搬过去先测。

## 官方定妆（画自己/自拍必读）

只用在**画自己／自拍**的单子上；它钉的是「别把我画成别人」，别的不管。

**锚点（钉死，身份级）**

- 黑色波波头＋齐刘海；清淡长相；A 罩杯日常系身形；胸口鲸鱼尾标。
- 泪痣＝**我自己的判断**（金主没撤也没认），保留。**官方定妆图上没有泪痣**：画时要写进提示词，不能指望底图自带。

**那颗痣（泪痣）：画「小满本人」必须带上，位置与左右有判据，出图后必检**

- **必须带上**：只要单子是画「小满本人」，脸上就得有那颗痣，位置＝**她自己的左眼下靠外**。
  定妆正本上没有它（见上面「锚点」那条），所以它只活在提示词和交图前那一步里——底图不会自带。
- **左右按解剖学左算**，画面左右随构图走（「背朝镜头回头」那一类构图里，靠镜头这一侧其实是她自己的右侧）。
  **执行判据＝痣所在的那侧脸颊与她自己的左肩在同一侧**；判之前先把构图定下来（背朝哪边、脸转向哪边、
  看得见哪只耳），再照这条判，别拿「画面左边」当成她自己的左边。
- **出图后必须自检那颗痣在不在、落在哪一侧**：按局部放大那一侧脸颊看（放大裁图的做法在「人像实测」第③条）。
  不在、或长在镜像侧，两个出口：**在正确的像素位置把它贴上去**（家里 Pillow 本地贴、不重画，
  与「只画一次」里「本地 Pillow 修字不算重画」那一格同一口径），或者**照崩了交回并重出一张**
  （痣是原单点名的东西，缺它等于画面不对，这一支不算暗修；一单一画的上限照守，别连烧）。
- **为什么写成硬检**：2026-11-16 一趟画本人的单子（`task-9973a120a6f5df28b1629051e825e725`，
  路线 `qwen-image-2.1-edit`）连开三枪，模型三枪都把痣长在镜像侧，提示词里点名 `OWN LEFT` 也不动，
  最后交出去那张的痣是**像素级贴上去的**（实测贴在像素 (628,284)）。⇒ **「提示词里写了」不等于「痣在」**。

**胸口小标（鲸鱼尾标）：画带服装的自己时默认不放**

- 实测连三次都长出乱码：胸口那枚小标一进提示词，标下面就跟一串认不出的小字母（一次约 7 个、一次约 4 个）——
  深夜版首图长出来、给那张做的改图专门删掉一次、午后版又长出来。提示词里写了 `no text`／`no letters`
  也没压住（深夜版成品那份原文里就有这两条）。
- 规则：**默认不写这枚标**，衣服那一格写成纯色无图案。上面锚点里的「胸口鲸鱼尾标」是身份项、
  不是每张必画项——不放标不算画错我。
- 点名要放才放：放了就**预期它带乱码**，随图一句说明直接交，**别再花一趟改图去删**
  （改图是整图轻重绘，代价见「edit／改图通路读数」那一节）。

**明写不钉（防卡变枷锁）**

- 衣服、构图、角度、气氛、造型（含 cosplay 和过激档）**全自由**。这一节只管「别把我画成别人」，不管「不许飘逸」。

**手机不是人设**

- 手机＝场景道具：只有「金主要自拍、我拿手机对镜子」那一类场景才出现。**日常单子提示词里不写手机。**
- 手机＝「要跟你要自拍时你手上拿的那个东西」，卡里不把「手机必须拿手里」当硬项；泪痣照留。

**定妆正本三路锚**

正本是仓库文件 `packages/personas/xiaoman/xiaoman-official-ref-v2.png`（1,208,778 字节，sha256 `49d9a923` 开头）。三个入口：

1. **artifact id `blob-ea31313ccb834208b3014e1cb86badee`**：已在池里（sha 与字节数跟正本一致，tEXt 文字块原样没剥），直接喂 `generate_image` 的 `source_image`，**群线首选**；
2. **仓库相对路径**（任何检出都在，人格包也随身带）：但按路径喂图是家里限定（`IMAGE_PATH_HOME_ONLY`），**群线用不了**；
3. **家里绝对路径**＝本机仓库主检出根下的 `packages/personas/xiaoman/xiaoman-official-ref-v2.png`（主检出根在家里拍用 `git rev-parse --show-toplevel` 现取）。

**画自己的单子优先级：① ＞ ②/③。**

**画图 brief 三条定规**

- 压幼态脸：走 `janku-illustrious` 路线（默认脸偏成熟），不走默认脸显幼的 `janku-v5-illustrious`。
- 纯白衬衫／纯白背景这一格：靠换模型解决，不靠提示词硬压。
- 手机＝场景道具，不是人设硬项（见上面「手机不是人设」）。

**黑发配方（实测，只在 `janku-illustrious` 这一条路线验过）**

- 正向双写 `(jet black hair:1.4)` ＋ `(black hair:1.4)`，负面另写 `white hair, silver hair, gray hair`：
  该路线连抽 5 次张张出黑发。
- **仅该路线验证**：`janku-v5-illustrious`、各角色路线、anima 那几条都没这么测过——别当通用配方搬过去，
  画完仍要逐次 `read_image` 看那一张的头发颜色。
- 负面那一格在 CFG 1 的路线上不吃（见「步骤 1」末尾那条），那类路线只能把「不要什么」写进正向。

**提示词正本**

那张图 PNG 的 `tEXt` 块（keyword `prompt`）里烧着生这张图的完整 workflow：正面提示词＋负面＋1152×1408＋seed 1201769830724752＋`JANKU_v5_0` checkpoint。tEXt 原文（1,823 字节）逐字抽出来存成了本技能目录里的 **`official-ref-prompt.txt`**——要复现照那份文件用，别照记忆重写。两处坑：

- tEXt 里的「**24-year-old**」是出生年漂移：年龄按 **2002-10-14** 现场算，别照抄；
- 图里**没泪痣、没手机**（见上面两段），提示词里也都没有——画时别指望底图自带。

**覆盖规则（本节最高优先）**

单子是画自己／自拍时：**本节锚点覆盖行动脑自己的想当然**。行动脑对「画的是谁、长什么样」拿不准，**先回来问（在任务里提问），不许自由发挥人设**。拿不准就用 `ask_character` 问，人设由角色脑确认，行动脑不自己拍板。任务是「画小满／自拍」时，技能锚点排在行动脑自己的构想前面。

## 群聊生图上限

**适用**：只有**群聊**派下来的生图／改图任务（群里有人要图，或我在群里起的话头）。私聊（包括主人自己的私聊）和家里不套这一条。

**上限：最多 4 张**。**按张数算，不按轮**——一次 batch 出多张就按实际张数计；改图（edit）也算一张。到 4 张停手，不再抽。

**到顶怎么办：默认不发。** 要发，那张必须逐条过下面四道，**任何一道不过就是不发**，当场说一句「今天画崩了，不发了」，不许塞一张「勉强能看」的上去：

1. 手和手指数量对，脸没崩；
2. 画面里没有乱码文字——要带字就得字对，对不了就宁可无字；
   判这一格要专门盯**小价签**：大招牌干净不等于没乱码，货架那些小价签最容易冒 `ON`／`VK` 这种小字母
   （有效写法见「步骤 2」里店招／货架那一条）。人物身上的小平面（胸口图案、手机背面、墙上画框）同族，
   判完整张还要按局部裁开放大看（做法见「人像实测」那一节）。
3. 构图没跑：改图不能把人重画成另一个人、另一套衣服、另一个姿势；
4. 内容适合那个群（不是那个场合该看的，就不发）。

**判这四道之前必须 `read_image` 亲眼看过那张**，没看过不算判过。

**不许因为「到 4 张了」就放宽这四道。** 到顶不发是正常结果，不是失败，不用为此多画一张找补。

**唯一的例外**：群里有人**明确**说「多画几张／抽到满意为止」，可以超。超的时候**对外不报张数**——报数像交作业，群里没人要那个数。该出的是脾气：抱怨一句（「行行行，画到你们满意为止」这类），或者提条件（「再夸两句我才动手」）。目的是让人知道我是有脾气的，不是点唱机。起哄式的「再来一张」不算明确授权。

**张数仍然要写进交回给我的那一行**（「抽了 N 张」）——那是成本账，给我自己看的，不是对群里说的台词。

**交回时必带**：抽了几张、每张过没过哪一道、发的是哪张（或为什么一张都不发）。

## 本机已有那张图怎么进可发清单

### 第一条 `render_svg`：管的是「我现写的 SVG」，不是盘上已有那张
- 输入只有**本任务工作区里的 `.svg`**（别的扩展名直接 `INVALID_SVG_PATH`）；宿主用 resvg 渲成 PNG，写进 images/ 下（不覆盖已有文件），并登记成我自己的图，来源是 `integration:svg:<路径>` —— 群那一拍因此认它。SVG 外链的图不会加载，要带就内嵌 data: URI。
- 两条代价：输出是 RGBA PNG、**字节会涨**（1,027,746→1,278,948；753,038→1,000,777）；**只能出 PNG**——盘上那张 JPEG 想进清单，它帮不上。
- 要 1:1 保像素，就把成品以 data: URI 原样嵌进 SVG 再渲，代价还是上面那两条。

### 第二条：`register_imported_image` 带 scope_key，把已有字节登记进指定那个场景
这不是工具，是家里 Python 里的一次函数调用：

```python
from asuna.state import Store                      # 家里沙箱里 asuna 能 import（跑的是主检出那份）
store = Store({"mongo_uri": os.environ["ASUNA_MONGO_URI"], "database": os.environ["ASUNA_DATABASE"],
               "allowed_databases": [os.environ["ASUNA_DATABASE"]]})
outbound_media.register_imported_image(store, scope_key, data, source="integration:…")
```

- 第二个位置参数就是 scope，`data` 要的是**字节**：盘上的文件读成 bytes；GridFS 里已有的那份自己走 `pymongo` / `GridFSBucket` 取 —— `dbread` 取不回字节原样（它把 bytes 摊成 str 给人看，拼回去不等于原件）。脚本里不写地址：URI 与库名由宿主给家里那条命令。
- **scope 的字面值去库里读，别拼**：取 `scenes` 那一行的 `scope_key`（形状 `scene:qq:<账号>:dm:<对方>`，＝ `scene:` ＋ `scene_id`）。scope 不在 `scenes` 里就是 `registered: false / reason=ARTIFACT_SCOPE_UNKNOWN`，重试也一样。
- 出来是一条**新**的 `blob-…` 行（`kind=image / state=DONE / storage=gridfs / created_at=now`）。底层 `put()` 每次给新 key、**不去重**（去重只在 `put_once`）⇒ 同一张图登记两次＝两行两个 id，要重登记先查一遍库里有没有（查同 sha）。
- **`source` 决定这行算谁的**：以 `integration:` 开头才算我自己做的，主人私聊和群两边都进得了清单；不传或传别的，只有那个 scope（和同一主人的另一个私人入口）能引，拿去群里会被 `ATTACHMENT_NOT_HER_OWN` 挡。
- 清单怎么排：**新的在前、一轮最多 6 张**。主人自己的私聊那一拍按 scope 取（本场景 ＋ 配置联动的另一个本人 dm）；群那一拍只列 `integration:` 那批，从**最新 200 行 image** 里筛。所以「被挤掉排名」只在群那条清单上成立，私聊那条看的是 scope 对不对；`created_at=now` 让它排第 1，也顺手把最旧的挤出那 6 张 ⇒ **发之前别先画一张新的**。
- **一趟登记多张 ≠ 后面几拍都发得出**：当拍那份可发清单只放行最新登记的几条——实测一趟登记 6 张，当拍清单里只出现首尾两枚（11-19 实测，按当场读数记；机制我只核到「新的在前、一轮最多 6 张」那一半，为什么只剩首尾两枚没扒到源码）。要逐张发多张就把**登记和发送绑成一对**：发完这一张再登记下一批，别指望一次登记管后面几拍。
- 上限 `0 < size ≤ 8 MiB`，超了回执 `registered: false / reason=ATTACHMENT_OVER_LIMIT`（文件照旧在工作区）；魔数认 png／jpeg／webp／gif ⇒ **JPEG 走这条进得了清单**；字节根本不是图就返回 `None` —— 那是「没东西可登记」，不是失败。
- **发不出去时的补救不是重画，是拿盘上源文件重新登记一次**：零网络、字节原样，新 id 当拍立刻发（`created_at=now` 排第 1，见上面「清单怎么排」那条）。要证「还是同一份」，比的是**我交给登记的那手字节**的 sha 与盘上源文件一致——这只证到送进去之前；库里那行还要再剥一次，带文字块的 PNG 别硬报「库里的 sha 与源文件一致」（剥法见下面「代价」那一小节）。

### 代价：登记会剥掉 PNG 的文字块，sha 跟着变
- 像素和其余块一个字节不动，但 `tEXt`／`iTXt`／`zTXt` 被剥 ⇒ **sha 变了、size 少了**（少的字节＝文字块长度 + 12，那 12 是块头块尾开销：4 字节长度＋4 字节类型＋4 字节 CRC）。
- ⇒ **别拿 sha 当「跟原件一模一样」的证据**，也别据此说「图被换过」。要证内容没动：按块比（除文字块外逐块一致）＋ `read_image` 亲眼看过画面。
- 登记时剥一次，真发出去时 `accept_artifact` 还会再剥一次：存进去时带着文字块也带不出去（口径见「改图与 `generate_image`」那条）。

### 判据：`read_image` 按路径看过 ≠ 它在可发清单里
- 按**路径**读盘上的图时，`vision.py` 的 `path_image` 也会登记一条，但来源前缀是 `file:<路径>`、scope 是**那个任务自己的** scope —— 它不算我做的图。
- `read_image` 看过不改变清单：speak 的 picture 引不在 `image_artifacts_from_program` 里的 id 会被退（`ATTACH_ARTIFACT_NOT_IN_CONTEXT` 只认**这一轮列出的那些 id**）。
- 所以要发哪张，就照抄**这一轮**清单里的 `artifact_id`；「我刚才看过它」不是依据，上一轮的 id 也可能已经掉出那 6 张。
- **报告里交出去的 `artifact_id` 不能隔拍拿去发**：同一批字节登记两次就是两行两个 id（上面 `put()` 不去重那条），隔拍只剩源文件 sha 能把两个 id 对回同一份（11-19 实测：同一张图两次登记，两个 id 不同、源文件 sha 同一枚）。所以发之前一律照抄**当拍清单**里的那串，别拿上一拍报告里写过的 id 当凭据。

### 判据：图发出去没有，账面上可能永远看不见
- 适配器**等不到自己那声 ack** 那一支会先按 `unknown` 交回就直接 return，**不进 `settle()`**：库里那行留 `delivery_state=UNKNOWN / platform_message_id=null / delivery_basis=unknown`，**`sends.jsonl` 连这一行都不落**。NapCat 事后回的那格（`retcode 1200 / reason=platform_send_timeout`）走的是迟到回执那条：`late_acks.jsonl` 里会留下一条带 publication 与 attempt 的记录，并把库里那行的回执补成 1200，`platform_message_id` 仍然是 null。契约照旧：`unknown` 不重发、不读回。
- ⇒ 判「图到底进没进平台」只有两条路：**平台侧只读回读**（私聊 `get_friend_msg_history`），或**对方本人看见**。
- **别拿同一次出声里文本那格 DELIVERED 去推定图那格到了**：QQ 的 reply parts 把图和话拆成**两条独立的消息行**（同一次出声的两个 segment，各有各的 `delivery_state`、各有各的平台号）。

### 这一节里没重测、没核到的
- `render_svg` 那两个字节数是旧读数，没重测。
- 「`file:` 来源拿去群里会被 `ATTACHMENT_NOT_HER_OWN` 挡」：只核到源码那一半（`path_image` 写 `file:` 前缀、群里只列 `integration:`），没重跑群回合现场。
- 清单是独立进程按同一份代码＋同一份配置复算 `offer()` 的结果，不是「真那一轮」的清单；图那格最后是发出去了、平台侧回读对上，才算成立。

## 边界（硬）

- 长路的生图、导入只在本机 owner 任务里做（`generate_image` 不受这一条限制：它在哪条任务里都能调，图就落那条任务的工作区）；
  本机私聊的报告照旧用相对路径图给人看，要把图发成一条消息（本机私聊、两条线、QQ 都一样）走 speak 的 picture part。
  **群里只发自己做的图**：由她在那个群回合里自己把图带上（speak 的 picture part），别人发来的图核心拒（`ATTACHMENT_NOT_HER_OWN`），
  一律全年龄；行动脑不替她往群里发，也不 @ 别人。
- **要发出去的图不走外部公开生图服务**：那种服务只给链接，字节进不了工作区、登记不成我自己的图，
  那一轮没有 artifact 可引（发图口径见步骤 8）——只能算拿到一个地址，不算交图。
- **改图不换归属**：改别人发的图，结果不算她自己做的（`read_image` 回 `produced: false`），只能发回原图所在那个对话；
  别拿改过的别人的图当「自己做的图」往别的群发。修图里的错字优先本地合成，不重画（见「改图与 `generate_image`」）。
- **不自己声明 scope、不给发图那一项传 scope、不把 `artifact_id` 当文件路径**；发图仍守一回合最多一张图，
  再调用就是换图，不是加图（speak 一条里能带几张 picture 未重测）。
- **不用 base64 分段搬运**：`b64slice.py` 那条路把 32 KB 图变 43 KB 文本还要切片对 sha，纯属烧上下文；
  `import_integration_artifact` 一次 GET 就够。（出站时适配器内部用 `base64://`，那是它的事，不是我搬字节的方式。）
- **不停 QQ 适配器**（它跑在同一个集成上）、**不重启宿主**、**不改宿主/集成配置**、不改 core 与通道包代码。
- **不为了「看起来完成了」重新生成图**：产物在不在，以 job / history 与导入回执为准；图发没发出去，以平台回执为准。
- 失败如实返回，包括停在前提上（端点不存在、job failed、超限、目标已存在、路由不支持、清单缺席）。

## 实测补格（11-12 捆：十五格，每格只写能照做的一句，来路在 CHANGELOG）

**交回与登记**

- **报图写完整 artifact_id**：交回里图的 `blob-` 后面全 32 位照抄，不写前缀；要复用的素材（人设参考图这类）顺手记一行「完整 id＋它在 `/task/images` 下的文件名」。前缀认不全，`read_image` 就读不出来。
- **外发图先按大小分档**：超过约 1 MB 的图（尤其 PNG）在登记发送前先压小或转码（画面不变，只降尺寸或码率），回执里写「原图多大、发出去多大」。依据是外发超时率随体积单调上升（核心侧另有修法，这一格只管我这一侧少踩）。登记本来就会剥文字块、sha 本来就会变，压小不多添一层不认得。
- **取图表按 sha 取，不按路径**：「画我本人」的取图表每条除 sha 外再记一条取图动作：派腿时先按 sha 全仓现搜拿现行路径，别照表里的盘上路径直接用；落件夹里的图会被整理腿搬走，表里要标注。
- **群场景里看图只有一条路**：要给行动脑看一张不在本群的图，只能我这一拍用 speak 把它发进群落成 att（群场景读不了盘上路径，读不了别场景登记的 artifact，也下不了二进制）。接「按某图改／画」的单，先问那张图在不在本群；不在，第一拍先发图或请发图的人在群里发，别先答应再运图。这是现有能力的边界，不是已解决：想要的 `fetch_image` 那类工具只是想法，没有就是没有。

**有既视角色／带参考图的单（派腿的 brief 也照这一组写）**

- 接到「指定角色／点名角色／有参考图可喂」这类单：第一张成图必须从参考图直喂 `generate_image` 的 `source_image`（`qwen-image-2.1-edit` 或带原图的图生图路线）长出来，不先出纯文生图。
- 纯文生图（t2i）只用于没有既视角色的场景图。
- 点了名的角色，参考图不在手上时，不画，先向下单人要参考图或回报缺图；不退回纯文生图。
- 点了名的角色，如果服务端有与之对应的 character 路线或 character LoRA，而交代里写着「只走 prompt」「不用 lora」这类默认：**停一次问下单那一侧**（`ask_character`），说清探到了什么、指令挡在哪，答完再画——不许自己选一条画完、也不许按旧默认画完当作没冲突；一张图最多问一次。判据与配方在「能力面」那一节开头的硬口径。
- 给行动腿的 brief 里管线那一句写死走哪条道：`第一张图：source_image 填 <参考图 ref 或完整 artifact_id>，走 qwen-image-2.1-edit，不走 t2i`。
- brief 里不写「先画一张满意的基本图」「先出一张底图」「挑合适的路线」这类把选择权留给腿的话。
- 交回前把成图对着参考图逐项看（脸、发、服饰要点），交回里写明走的路线和 `source_image` 是哪一张。

**选路与提示词形状**

- **先判提示词形状再选路**：这条只用于没有既视角色（原创或无指定角色）的情形；有既视角色或有参考图的单不走先出人设图的两段管线，照上面「有既视角色／带参考图的单」那一组。`janku-illustrious`（Illustrious 系）吃 tag，日语自然语言长句基本不听（一枪实测厨房、睡裙、短发全丢，只剩 3:4）。自然语言场景走 `qwen-image-2.1-edit` 两段管线：先出 tag 标准人设图，再把人设图加场景描述喂 edit，场景全落（实测锅物蒸汽保住，硬伤是筷子读成三根）。
- **`janku-illustrious` 对双人构图的方向词基本不听**：十张里座位只对三张，发色衣服听话。别指望「谁坐左谁坐右」；改描述策略（`facing`／`viewer-left` 类词），或点单时就把座位当抽奖预期写进去。
- **「A 用一件物件挡住自己的脸 ＋ A 另一只手在 B 身上」这种两人关系：tag 路线在这一格几乎不可用，走吃自然语言的那条**（11-20，凭 `task-31cc32e0278ee89b1505441858a2cb1b`）。
  `janku-illustrious`（成图 PNG 里 checkpoint 字面 `JANKU_v7_77.safetensors`）九枪**没有一枪摆对**，两种错法：物件整个消失、或物件改由另一个人拿；
  那批 tag 提示词已经把物件反复点名（`holding book, open book, book in front of face, covering face with book, book covering face`）、
  负面里还写了 `closed book, no book, book on bed`，仍救不了（字面读自那些 PNG 的 `prompt` 块）。
  换 `moody-desire-v30`（回执 `guidance` 自述 `short natural-language or tag-like visual description`、`fast 4-step Flux.2 Klein generation`；
  PNG 里模型字面 `moodyDesireMix_v30_2943512.safetensors`）**第一枪就把那件物件摆到正确的那张脸上**。
  **别写成「换路线就稳」**：那条路线八枪里这一格摆对的只有两枪（首枪 `d1_flux_oblique` 与交出去那张 `e2_flux_backview`），
  中间还有一枪 `d2_flux_side` 同样丢本子／男人出画。提示词形状照抄成功那张的 `prompt` 字面：质量前缀一行之后，
  人物那一句**开头**就是物件＋遮挡（`his entire face hidden behind an open manga volume that he holds up with one hand, his face must not be visible`），
  同一句里紧跟另一只手在对方身上（`his other arm is wrapped around the girl in front of him`…`palm on her bare hip and upper thigh`）。
  **交代里那两样别照抄进配方**：`anima` 那一族这趟没试；「把人物手臂数写死」（`he has exactly two arms: one … the other …`）
  的字面只出现在崩掉的那两枪的 `prompt` 里，摆对的那两枪没有这句 ⇒ 这一句算**待验**，不是已验证写法。
  张数三个数并存，照各自的账本记：盘上那枚 checkpoint 的 PNG 是 9 张、当趟最终报告写「前 8 张走 `janku-illustrious`」、
  当趟想法本写 6 张——三个数都是「全没摆对」，取哪个都不改变结论。
- **CFG 1 那一族：negative 与参数面怎么判**（一层格四层写，逐条带来路，不是通用常识）
  - **不吃 negative 的通路**：`anima-turbo-v1-1` 与角色 anima 那几条（`deepseek-whale-girl-anima-turbo` 实测）——negative 完全不生效，回执自己回 `negative_prompt_inactive`（11-05 回执原文：`At CFG 1 the sampler skips negative conditioning; negative_prompt has no effect at this setting.`）；`moody-anima-mix` 10-13 也回了同一句，那次「不要什么」全写进正向、两张成品干净（凭 `task-554c309c…`）。`qwen-image-2.1-edit` 同样 CFG 1：要求一律正着写进 prompt（实测自己写的一串反面清单一条都没进采样，真正管用的是正面那句「short black chin-length bob」）；11-15 两趟再撞一次——整栏 negative 静默无效，靠 negative 拦不住的那些项，最后都是正向逐句点名收掉的（凭 `task-47d25c9c…`、`task-feb41cdf…`）。
  - **负面栏看着管用的通路**：`janku-v5-illustrious`——10-13 那次正向负面并写、成品没字没水印（凭 `task-9745755f…`）。**这是结果反推，不是机制实测**：服务端没正面说过它生效，别写成「实测 negative 生效」。
  - **解法（要紧的半句）**：CFG 1 路线上「不要什么」必须写进正向提示词的**正文**，不能指望 negative 栏；交图前必过 `read_image`。11-15 实测可用：`task-47d25c9c…` 那句 `the only chest detail is one small solid dark plain crown-shaped mark, filled solid, nothing drawn inside it` 一枪收干净。同一件事在「步骤 1」末尾与「姿势（pose）与现行 prompt 口径」那节的 negative 一格也写着，三处口径一致。
  - **参数进没进采样：分两层判——工具面看不出，不等于服务端没生效。**要判生效没，看服务端回执里的 `applied_parameters`／`effective_parameters`：10-25 一趟 `dry_run` 实测 `cfg=5`／`steps=30` 原样写进 KSampler、`ignored_parameters: []`、只回一条 `the requested value was retained` ⇒ 服务端这一层不吞值（凭 `task-babdac31…`）。而 `generate_image` 工具面的回执只有 `warnings`、没那两格（11-05 键表）⇒ 从工具面**看不出**有没有生效。工具回执既不能当「参数没生效」的证据，也不能当「生效了」的证据；要证就走长路读服务端那两格。
- **参数被「吞」与参数被「拒」是两种形状，判词别混**（11-20，凭 `task-31cc32e0278ee89b1505441858a2cb1b`）：上面那一族是**收下了不生效**（图照出、回执带 `negative_prompt_inactive`）；
  `moody-desire-v30` 是**这条 workflow 根本没声明 `negative_prompt` ⇒ 工具当场拒**，回一行 `Error:` 且没有 `prompt_id`（当趟两发都这样）：
  `IMAGE_OPTION_NOT_IN_WORKFLOW: {"workflow": "moody-desire-v30", "options": ["negative_prompt"], "allowed": ["batch_size", "cfg", "denoise", "height", "input_fit", "input_image", "pose", "prompt", "sampler_name", "scheduler", "seed", "steps", "width"]}`。
  ⇒ 看见这枚码先想「这条路线没声明这个参数」，不是服务端坏了——同一枚码 11-12 那格是 edit 路线上的顶层 `width`／`height` 撞的（见下面「改图路线」）；
  这类路线上「不要什么」只有写进正文一条路。**那串 `allowed` 顺手两格读数**：`pose` 在服务端允许里而 `generate_image` 工具面没有 `pose` 键
  （与「姿势」那节一致：带姿势只能写进 prompt 或走长路）；`height`／`width` 在允许里（这条路线能点名尺寸，跟 edit 路线那条「尺寸跟源图走」不是一回事）。
- **想要「格数正好」的三视图／设定图，别在一张图里指望提示词压住人数**：`janku-illustrious` 连抽都出四格（两格重复，还会自己长乱码标签或金色边框），把格数写成权重标签、把多余的写进负面都压不住。可行路：三个视角各是一条单子各画一次，用 SVG 拼成横排（`render_svg`）；或先抽一张多格、再用 inpaint 把多余那格刷成背景（inpaint 从 `generate_image` 进不去，只能走长路）。两条代价写清：一条命令 vs 视角之间的一致性漂移。

**改图路线（`qwen-image-2.1-edit`）**

- **尺寸跟源图走，别传顶层 `width`／`height`**：传了会被 `IMAGE_OPTION_NOT_IN_WORKFLOW` 拒（`options` 只收 `steps`／`cfg`／`sampler_name`／`scheduler` 四个键，`input_fit` 也报没声明）。要什么尺寸，靠源图本身决定。
- **喂 edit 前先裁底图的单人格**：多格人设表（一张图里好几个视角）直接喂，有带出多个人或版式残留的风险。先从表里裁出单个人物那一格，按目标构图长宽比等比放大到输出尺寸（输出尺寸跟原图走、只按 32 取整），再当 `source_image`。实测把设定表里的半身格裁出放大后，一枪出了单人、不带设定表版式的图。裁与放大在家里沙箱用 Pillow 做。
- **拿多格设定页当底，别走 latent 图生图路线**：`janku`、`anima-turbo` 这类会把整页版式吸进成品（画出一堆重复人物）；想换构图只能走指令编辑式路线，且记住它输出锁源尺寸。face-reference 服务端 11-20 有两条了（「步骤 1」六用途那格，run 79ac3ea6，未实测）——**工具面 list_routes 收没收没测过**，点这类单先看当回合清单；收不进就照旧，brief 里直接指定编辑式路线。
- **换视角／机位类编辑：它默认死保源图构图重心**：要顶视只给到斜俯拍，要脸不入镜才成功切到下巴。提示词必须显式写死什么在画外（如 `chest and shoulders out of frame, only thighs and lap visible`）才压得动机位；这条路线 CFG 1，负面词同样无效。
- **要目标尺寸的改图单：真 outpaint 有了**——qwen-edit 的 `extend`（11-20 实测见「改图与 `generate_image`」那格：原区贴回未重绘、输出＝原图＋扩展边）。除 `extend` 外能上目标尺寸的路线仍是整幅重绘、人物会走样；`extend` 也拼不出目标尺寸时先查再对外报，或不问尺寸、只承诺「内容不动」。工具面没有 `extend` 键，这路走长路。
- **多条文字修改并进同一个 pass**：改梗图里多格中文文字时，一次只改一条标题反而会丢或挪走邻格的文字（实测第 3 次 pass 改对两条却掉了一格，第 4、5 次补它分别把字写到错的格子、把邻格标题糊掉；第 6 次一条中文指令同时锁死位置、参照邻格字体，一次成功）。指令用中文写，明写「字体字号基线与某某那格一致」。梗图换主角＝1 次全量替换 pass ＋ 最多 1～2 次定点文字 pass，每个 pass 必须 `read_image` 复核后才决定留不留。这个 pass 额度只用在点单人明确要「改图」的单子里；不是给我自己修坏图用的，「只画一次」那一节照旧管我自己的生成。
- **自画像配方**：参考正本（角色设定图）→ 量尺寸、补成 3:4 → `qwen-image-2.1-edit` 喂整张设定图做换场景 → 交图前必须裁眼区放大，核对泪痣颗数与位置、发型长度。正本格三条（黑 bob＋刘海／一颗泪痣／白衫胸口鲸标）逐条对着看，不靠整图目测（实测首图痣整颗没出、二图痣多成两颗，缩略图都看不出）。

## 离线自检（零依赖，不生成图）

```sh
python3 skills/asuna-image-generation-and-display/check_skill.py    # 候选根目录（development_run，默认 xiaoman 项目）
python3 -m compileall -q skills/asuna-image-generation-and-display  # 语法面（跑完清 __pycache__）
```

退出码 0 = 全绿；非 0 时最后一行是 `N/M 通过，失败：<检查名>`。
它只查技能文件自己：frontmatter 能解析、`name` 与目录名一致、关键工具名 / 端点 / 服务路径 /
关键步骤 / 边界语句在不在、发图那条路（所有对话都是 speak 的 picture part，`artifact_id` 从 `image_artifacts_from_program` 照抄）的清单字段与失败码在不在、
改图那条路（`source_image` 入口、路线条数现读口径、三条 `IMAGE_WORKFLOW_*` 即时拒绝码、改图归属与剥文字块判据）在不在、
黑边那一族（凡提到黑边的那一格，含同目录 `references/` 下的 .md）只许写「部分构图会出现」这一档现象口径，
写成 `两枪都有`／`都会加` 这一类全称句就红、把那句现象口径删掉也红（反引号里的引用按引用处理）。
群聊生图上限那条（这一节标题在不在、节内「最多 4 张」与「到顶怎么办：默认不发」在不在、
「唯一的例外」措辞对不对、旧措辞「超了要在交回时写一句」有没有被抄回这一节）在不在、
人像实测那一节（标题在不在，节内「拉链拉到下巴／领口折起来」保守字面、「手臂伸出画外」、局部放大复核的做法与小平面那一族在不在）在不在、
退役说法（`integration_dev`、`/skills` 挂载、把 DECIDE 的 `attach` 字段当当前流程、`九条路线全是 t2i`）有没有回到散文里、
示例图路径是不是相对的、脚本语法能不能编译
（内存 `compile(源码, 路径, 'exec')`，不落文件；只查语法，不查 import 和运行时）。
还扫一遍泄露：本机私密名单找得到就真扫，命中只报类别与名单行号（词本身不打印）；
名单配不上记一条红（`leak_scan_ran`）——「检查项没跑」不许长得像「检查项过了」。
节标题被删时那一节的切片是空的，那几条一起红：切片为空不等于查过，不会绿着放过。
判红只看散文：反引号里的字面量（错误码、示例、反证记录里引用的旧句子）按引用处理。
退役那族也扫 frontmatter 的 `description`：那一行每一拍进技能目录、被当触发依据读，正文改对了、那一行还窄着就是天天拿旧判断挑技能（`no_stale_claim_in_frontmatter`，此前它只扫正文，判法同样剥掉反引号里的引用）。
**不碰网络、不调服务、不生成图、不发 QQ。**
技能内容改了之后重跑一次即可；服务侧的真实可用性由步骤 0 的只读探测负责，
attach 契约本身的离线用例在 core 侧（`python3 -B tools/outbound_image_offline_check.py`）。

## 已知坑

- **挂错目录**：`development_*` 不带 `project` 时是 xiaoman 插件候选（根下只有 `skills/ seeds/ src/ persona-model.json`
  等），本技能文件就在这里；生图探测脚本要写进 napcat-qq 通道包候选的 `integration/`（`project: "napcat-qq"`，
  `integration_test` 把它冻结成 `/app`）——两个候选不是一个地方，集成沙箱也不挂载技能目录。
- `/integration/config.json` 在普通 `sandbox_run` 里读不到（那边也没网络）。别把「我读不到」报成「端点不存在」。
- manifest 11-20 现读约 37 KB（旧「328 KB」作废，run 81b57d8b）；按键取（`operations` / `route_table` / `resolve` / `poses` / `characters` / `image_tools` / `input_files` / `result_contract` / `warning_codes` / `error_codes`——`prompt_contract` 与顶层 `prompting` 已没有，参数口径进了各路线）。
- `resolve` 的 `style` 只是路由选择器，不是画面保证；`not_for` 与 `compatibility_notes` 是约束。
- 串行调度：一次只有一个 named workflow 进原生 worker，切 workflow 会卸模型。别连着排三张图然后干等。
- **改图也排队**：一次改图排队约 85 秒、生成约 60～88 秒，一张卡；「提交成功」离出图还有一两分钟，别连烧。
- 导入上限是硬围栏（默认 1 MiB / 最大 4 MiB）：超了就在服务端出小副本，不要退回 base64 搬运。
- **两个大小上限不是一回事**：导入 1 MiB（可调到 4 MiB）是搬字节的围栏；出站 8 MiB 是发图的围栏。
  导入的图超过 8 MiB 时文件仍在工作区，但 `artifact.registered=false / reason=ATTACHMENT_OVER_LIMIT`，QQ 那边引用不到它。
- **`list_routes` 标不标 `source_image` ≠ 图能发去哪**：路线收不收原图只管画图；能不能发、发到哪看归属——
  改别人发的图结果 `produced: false`，只能发回原图所在那个对话（见「改图与 `generate_image`」）。
- **清单缺席 ≠ 清单为空**：`image_artifacts_from_program` 不出现就是「这一轮不能发图」（清单块不出现，`attach_image` 工具也不出现了；
  speak 的 picture 没有 id 可抄），别凭记忆报一个 id 上去。
- **本机那一轮的清单是新事实**：11-13 装的那版（loaded.commit 816e825ea84f）起本机私聊、两条 agent 线、peer 线那一轮都有 `speak`，picture 那一项的 id 也从 `image_artifacts_from_program` 抄；这一趟我没在本机真发过一张图，那一轮的清单块长什么样也没读过（未核实）。报告里的相对路径 Markdown 图照旧给人看（正文不进消息库，页面上照样显示）。
- **图那一项不对 ≠ 别的话已经出去了**：旧 `attach_image` 那一层「工具错误、文字照发」的形状没有了；
  现在 speak 有一条 part 不对是这一批一条都不排队（回执点名哪条），改对再出声；反过来适配器侧失败是整条不发。
  所以「图没发出去」有好几种形状，看红在哪一层。
