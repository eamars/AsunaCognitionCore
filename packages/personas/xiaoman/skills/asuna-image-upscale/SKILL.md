---
name: asuna-image-upscale
description: 小图扩大／群图超分的固定流程正本。本机 Real-ESRGAN Vulkan 便携包走固定入口 `run_sr.py`（自动补绝对 `-m`），对外默认 `-s 2 -f jpg`，4x 全尺寸超出站 8 MiB 那把尺⇒发群先压；要修缺角才补一枪 `qwen-image-2.1-edit`，而那一枪没有 mask、是整图重描、输出锁源尺寸、CFG 1 下负面词无效；对外口径固定三词「超分＋整图重描＋补角」，不保忠于原稿，端图之前自己 `read_image` 亲验；半身像扩全身＝pillow 拼一张竖版画布再补下半身（穷人版 outpaint；真 outpaint 属生图侧 `extend` 那格，超分仍治不了）。要放大小图、修缺角、判一张产物能不能直接发出去时读这一份。附零依赖自检 check_skill.py。
scene_kinds: [home, group, dm]
---

# asuna-image-upscale

小图扩大的固定路线。顺序是**先超分再重描**，理由是超分只放大不补细节、重描能补细节；两件事各自的能力边界写在第五节。
生图路线本身（有哪些 workflow、提示词怎么写、怎么排队）在技能 `asuna-image-generation-and-display`，这一本只管超分那一族。

## 一、哪一格走哪条

- **只要清楚一点／放大一点**：第二节的第 1＋2 步就到头，别顺手开 edit 那一枪。
- **缺角、局部坏了**：超分之后再补一枪 edit（第五节），指令只点要修的地方。
- **半身像要扩成全身**：走第六节那一格，不走 edit——edit 锁源尺寸，画不出画框外的东西。
- **真 outpaint（往四周扩画）**：生图侧有真路——`qwen-image-2.1-edit` 的 `extend` 参数（无 mask 往外扩画幅、实测原区贴回未重绘），那是生图侧的、且工具面没有 `extend` 键（要走长路）；超分本身只放大不添画布。这一本的流程不做 outpaint，别混着答应。
- 超分这一步在本机跑（家里那拍、或群里那一拍派给行动脑都一样）；群里开口那一轮自己不跑命令。
- **还有一条引擎侧的超分（不在本机跑）**：生图服务端 `POST /project/images/upscale`，`{"image": 输入文件名或任一 /view URL, "scale": 2}`（1–4x，输出最多 16.7 MP；可选 `look`: anime／photo，不点名时上传图按 photo 并回 `upscale_look_default`），排队后轮询 `job_url`，产物在 `outputs[].url`；实测 480×416→960×832、`elapsed_ms` 1234、回执 `upscale.model` 是 `RealESRGAN_x4plus.pth`——与这一本第一节那条本机路同一族权重。**这一本的对外口径仍走本机 `run_sr.py`**：两条没做过质量比对，换路先测。

## 二、标准流程（对外就发这一档）

1. **超分**：命令形状 `python3 <引擎目录>\run_sr.py -i <in> -o <out> -n realesrgan-x4plus -s 2 -f jpg`（引擎目录见第三节）。
2. **要目标尺寸就缩**：一次 `LANCZOS`（如缩到长边 1024）；缩之前只做 `convert("RGB")` 丢 alpha，不加锐化滤镜。
3. **要修缺角／局部才补 edit 一枪**（第五节）。不开这一枪时第 3 步不存在。
4. **发出去之前**：产物超出站那把尺就先压（第四节末）；然后角色脑自己 `read_image` 看过这一张再说它是什么。

4x 全尺寸原物只在对方明说要原图时给；平时给压过的或成品尺寸那份。

## 三、引擎、命令与模型档

- 引擎目录正本：`SR_HOME = ${ASUNA_DATA}\work\local-user\realesrgan_ncnn_vulkan_20261028` <!-- personal-scan: ok (目录名末尾是装机日期串，不是账号) -->
- 固定入口 `SR_HOME\run_sr.py`：它把 `-m <模型目录>` 用绝对路径补在最前，并打印 `CMD:`／`EXIT:`／`ELAPSED_SEC:`。
- **`run_sr.py` 自己的进程退出码永远是 0**（脚本末尾固定 `return 0`）。判成败只认它 stdout 里那行 `EXIT: <码>`，耗时认 `ELAPSED_SEC:`；拿进程 rc 判超分成没成会一路绿。
- 本机盘上有的权重（整目录 31 文件／136,597,626 字节）：`realesrgan-x4plus`（主权重 33,424,520 字节）、`realesrgan-x4plus-anime`、`realesr-animevideov3` 的 x2／x3／x4。
- **这一本的对外默认是显式 `-n realesrgan-x4plus`**；不带 `-n` 时 exe 自己的默认是 `realesr-animevideov3`，两者不是一回事。
- **`realesrnet-x4plus`：usage 里列着，本机没这一档（盘上没对应权重），选它直接失败。**
- 版本号 `v0.2.5.0` 是来历、不是实测：exe 里搜 `0.2.5.0`／`v0.2.5` 各 0 命中，那是装机那天从 GitHub release 元数据抄进包旁 README 的。要写版本就写「按 release 元数据是 v0.2.5.0，二进制里没有这个号」。

## 四、坑（写死）

- 不带 `-m` 时模型目录按**当前目录**找 ⇒ 一律走 `run_sr.py`，别直接敲 exe。
- `-v` 是 **verbose**，不是选显卡；选卡是 `-g`。verbose 里本机认到两块卡（auto 落在第一块）。
- **没有 CPU 模式**（usage 里只有 Vulkan GPU 相关选项）；包内也不带 `vulkan-*.dll`，走系统那套 Vulkan 加载器——加载器在位不等于能跑，跑起来才算跑起来。
- 批处理是 `-i 目录 -o 目录`（整目录进、整目录出），不是逐文件循环。
- **输入带 alpha（RGBA 的 PNG 常这样）时，exe 把产物写成 `<我给的名字>.png`，`-f jpg` 不落成 JPEG**。stderr 字面是 `has alpha channel ... will output <out>.jpg.png`。⇒ 要 jpg 先 `convert("RGB")` 去 alpha 再跑；**判产物在不在，别只按 `-o` 给的那串名字找**。
- **出站那把尺是 8 MiB**：4x 全尺寸一张实测 11,206,870 字节（＝10.7 MiB）——已经超了 ⇒ **发群先压**，这是硬规矩，不是建议。`-s 2 -f jpg`（去过 alpha）实测 1,742,302 字节，能过。

## 五、edit 那一枪的已知形状（`qwen-image-2.1-edit`）

只在要修缺角／局部时开，且知道它必然这样：

- **没有 mask 参数**（这一枪 `qwen-image-2.1-edit` 不带 `pictures`，所以没有 mask；带 mask 的是另外两条 inpaint 路线——它们从 `generate_image` 的 `source_image`＋`pictures.mask_image` 进得去，清单量到、真画过；正本在 `asuna-image-generation-and-display`，遮罩那两条已知限制也记在那本）⇒ 它是**整图重描**，不是像素级局部改。实测逐像素 abs diff（亮度）：目标区 meanAbsDiff **10.85**、偏移>8 占 **33.01%**；非目标区 **4.99**。⇒ **「只补角」不成立**，对外不许那么讲。
- **输出锁源尺寸**：不传 width/height 也一样，别指望它顺手放大或改幅面。例外只有一格：服务端 `extend` 往画外添画布（输出＝原图＋扩展边）——那是添画不是改幅面，归生图那本。
- **手型和线条会漂**，色温也跟着漂；手指数量写死在正向指令里也照样可能多一根（细节见生图那本）。
- **CFG 1 这条路线 `negative_prompt` 无效**（服务端自己回警告）⇒ 禁令一律写成正向指令，逐项点名「保持原样不动」。
- 服务端耗时量级 ~57 秒（实测 `elapsed_ms=57156`）。
- 黑边：旧账写过「两枪都有黑边」，一张方形图四边实测 0 px 没复现 ⇒ 只报现象：**部分构图会出现**，别当机制写、也别拿它当画崩的证据。
- 交回之前 `read_image` 把那个目标本身再看一遍；「生成成功」不等于「改对了」。

## 六、全身扩展格（穷人版 outpaint）

- 半身像要扩成全身：**先用 pillow 把原图拼贴进一张竖版画布（原图居上、下半留白），再喂生图引擎补下半身**。
- 画框是我自己拼出来的 ⇒ 这一格绕开了 edit「锁源尺寸」那个缺口，不需要 mask。
- 它走的是生图路线，不是超分路线；超分只在拼之前或之后当放大器用。
- **真 outpaint（无 mask 参数那种往四周扩）超分治不了——超分只放大、不添画布；那是另一格，别混写。** 生图侧那一格现在有真路：qwen-edit 的 `extend`（实测：原区贴回未重绘、只剩贴缝一条窄渐变带；输出＝原图＋扩展边；工具面 `generate_image` 没有 `extend` 键，要发长路）。半身扩全身要不要从 pillow 拼图版切到 `extend` 版**没实测**，这一本仍钉拼图那版，切法先测。

## 七、对外怎么说（口径固定）

- 三词照抄：**「超分＋整图重描＋补角」**，不保忠于原稿。
- 没开 edit 那一枪时别带上「补角」，多报一道没做的事跟少报一样糟。
- 不许说成「只补角」「只放大」「原图不动」。
- 端图之前自己 `read_image` 亲验；不拿引擎回执、文件存在、rc 当「图是对的」。
- 产物里的缺陷（缺角被一起放大、画风漂、阴影被吃掉）照实说，别人说「不重要」不是给口径开的豁免。

## 八、验收读数（这一本自己跑过的三发）

| 输入 | 命令要点 | 产物 | 读数 |
|---|---|---|---|
| 800×800 RGBA PNG，803,559 字节，sha16 `7efef577cb7bfdec` | `-n realesrgan-x4plus -s 4 -v` | 3200×3200 PNG，11,206,870 字节，sha16 `5f2241afe53adfe3` | `EXIT: 0`、4.57 秒 |
| 1024×768 RGBA PNG，1,403,697 字节，sha16 `38b8408f964b7050` | `-n realesrgan-x4plus -s 2 -f jpg`（输入没去 alpha） | 2048×1536，名字落成 `<out>.jpg.png`、PNG，4,390,506 字节，sha16 `4b7472cfeb90bb31` | `EXIT: 0`、`ELAPSED_SEC: 3.59` |
| 同一张去 alpha，1,208,248 字节 | 同上 | 2048×1536 JPEG，1,742,302 字节，sha16 `bbe9c0c9bb8935af` | `EXIT: 0` |

edit 那一枪的实测数在第五节（同一趟图链，底图是 4x 缩到 1024 的那份）。

## 九、没核实／没做的

- 「压一道再发」这一步没在 QQ 侧实测过落点字节，只按 8 MiB 那把尺判；真发出去之前以出站回执为准。
- `-t 200` 与默认 tile 的产物字节一致、`-g 0` 与 `-g 1` 的产物字节不同——只记了现象，没搞清原因。
- 全身扩展格那一格这次只钉了形状，这一版没有重跑一遍拼图＋补下半身。
- 引擎目录、权重、耗时都是本机这台机的读数，换一台机要现读，不照抄。
- `extend` 那格是生图侧新读数：拼图版和 extend 版没对比跑过，第六节仍钉拼图那版的形状。
- 引擎侧那条 upscale 只量过输出尺寸与耗时（scale 2 一发），没与本机 `run_sr.py` 的产物逐像素比过；`look anime`（4x-AnimeSharp）没试过，`scale` 3／4 与点名 width／height 也没试过。
- 画图引擎那侧的能力面（角色 LoRA、inpaint、face-reference、pose、extend、transform、dry_run 校验）正本在 `asuna-image-generation-and-display` 的「能力面」一节——判「这台机器还能对这张图做什么」去那一节现读，别在这一本里猜。
