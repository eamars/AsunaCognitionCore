# CHANGELOG · asuna-image-generation-and-display

- 2026-11-07（v8.5）：两格实测读数补进正文，其余各节一字未动（按交代没动 `check_skill.py`，两格新字面本轮没有钉）。
  ① 「官方定妆」里加一小段「胸口小标（鲸鱼尾标）：画带服装的自己时默认不放」——那枚小标一进提示词，标下面就跟一串认不出的
  小字母，连三次（深夜版首图 → 给那张做的改图专门删一次 → 午后版又长出来），`no text`／`no letters` 压不住；规则＝默认不放，
  点名要放就预期带乱码、别再花一趟改图去删（来路 `task-3af25c24203040d361bd5a1db3016a86`／
  `task-7bc7b4aae32cefef4e581f0b4bfb4266`／`task-3779a34a7d66d173160fa1f7fd4903fd`，含 idea-a6c53f26e62e677d07b18be44786d858）。
  ② 新开一节「edit／改图通路读数」（插在「改图与 `generate_image`」与「姿势」之间）：`qwen-image-2.1-edit` 是整图轻重绘、
  不是像素级局部改——出图四边带窄黑边、尺寸跟原图取整到 32 倍、线条与色温会漂移；该路线 CFG 1、`negative_prompt` 完全不生效
  （服务回 `negative_prompt_inactive` 警告），禁令一律写成正向指令；另记一条「正向把指头数写死了、两枪逐根数仍各多一根」
  ＝写了指令 ≠ 改到位（来路 `task-3eb73958d2178adad81d0f9c7b81a034`／`task-4e0b9ed3a5c95af65d20e60aaa601d57`，
  11-07 同一张修手单的两枪）。
  自检：`check_skill.py` 236/236 rc=0（格数与上一版相同）；`pre_publish_scan.py` 候选 70 份对 ACTIVE 70 份、changed 正好 SKILL.md
  这一份、added／missing 各 0、白名单外零新增、私密命中 12 处全在 `integration/envoy_meters_read.py` 且候选与 ACTIVE 逐文件一致
  ＝本次零新增；rc=1 停的那一条是「名单条数 125 与上一份报告 124 对不上」＝名单维护账、不是内容冒出，说话那一半判发放、
  基线常量没动。SKILL.md 70,861 → 73,439 bytes（新节 440–455 行、胸口小标那段 550–558 行），CR 全 0。

- 2026-11-06（v8.4）：新增一节「只画一次（一单一画，崩了不修）」，插在「直路」之后、「前提与授权」之前，
  位置就压在「不对就改提示词或换路线重画」那句旁边（旧句本轮按交代没改，见下）。正文其余各节一字未动，
  frontmatter `description` 本轮按交代也没改。整节＝总纲＋生产端①-④＋交付端⑤-⑦：
  ① 一单一画——一次点单只调一次 `generate_image`，画完必须 `read_image` 拿 `artifact.artifact_id` 看过才算交（点单要 N 张＝N 条单子各画一次）；
  ② 画得不理想也不许行动脑自行改提示词／换路线／换 seed 重画——修图循环＝在提示词上叠我自己的理解，每修一次离原单更远，第五次既不是原单也看不出第一张崩在哪；
  ③ 服务崩／`failed`／超时取不回／画面不对＝如实报「崩了」并带真实读数，禁止暗修暗补（悄悄换 seed、多抽几张、交一张像样的）；
  ④ 重画只在点单人明确说「再画」之后，且用**原提示词**（从任务目录那张原图的 `prompt` 文字块或交回里贴的那份取），不拿崩掉那版当底；
  ⑤ 交付端一次只出一版，交回几版都只挑一版发，**不挑不攒**（按图算：一条单子一版）；
  ⑥ 小瑕疵（文字糊、局部毛病）随图一句说明直接发，不为它多花一次生成；
  ⑦ **大毛病只有两个出口：要么直接发、要么不发——没有「修」**；不拿坏版本当底改提示词、不自作主张重画。
  另写死两条「不算重画」的边界（超时拿 `prompt_id`／`job` 续取同一张；本地 Pillow 修字只在点单人点名要修那处字时走、不自动做），
  与「群聊生图上限」的关系（4 张是成本预算的上限、不是默认张数，判不过走「不发」那一支），以及一条优先声明：
  「直路」与「步骤 7」各有一处「不对就改提示词或换路线重画」＝旧口径，**冲突以新节为准**（那两处没动）。
  `check_skill.py`：SECTIONS 加节标题（那格跑出来叫 section_19）＋新押 ONCE 20 条（押在该节切片里，含交付端三条）
  ＋once_section_slice＋docstring 补一段；214→236。反证逐条真跑（都是把改坏的副本当参数喂给同一份 check_skill.py）：改坏节标题 → 22 格一起红
  （section_19＋once_section_present＋20 条字面，读回 214/236）；删「禁止暗修暗补」一处 → 只红 1 格（235/236，切片 1662 字）。
  来路：金主 2026-11-06 本机私聊提「行动脑画了五次、一次比一次糟糕，三次上限还是太高，建议一张图只画一次，崩了就崩了不要修」，
  同日 15:26 本人补定交付端⑤-⑦并撤掉「大毛病压住重做」那版说法；那次现场是外面一个群的一趟改图单子（群名不进仓）。
  **没核实**：这一节是口径落地，今天没为验证它跑任何一次生成；「旧口径那两处不改」是按交代做的，靠新节里的优先声明兜着。

- 2026-11-05（v8.3）：金主 11-03 23:55 说「画图引擎更新了、可以添加姿势了」，这一拍派行动脑重探新界面，并把三则实测经验一并落正文。七处正文改动＋两处判据改动：
  ① 「直路」一节加两条判据——回执 `warnings` 那一格要看（越界参数服务端只警告不拒收，11-05 实测两条原文：`negative_prompt_inactive: At CFG 1 the sampler skips negative conditioning; negative_prompt has no effect at this setting.`、`outside_recommended_range: steps=4 is outside the recommended range [8, 12] for anima-turbo-v1-1; the requested value was retained.` ⇒ **出图 ≠ 参数被接受**，正式图别停在 4 步）；`guidance` 回的是选中那条路线自己的口径，`job` 是超时续取的凭据（超时≠画失败，别重画）。
  ② 姿势节把「`generate_image` 能不能传姿势」那格按当回合工具参数表列全（prompt／negative_prompt／workflow／style／width／height／seed／options／job／source_image／list_routes／target_relative_path／timeout，**仍无 pose**）；回执键那一格补 11-05 新出现的 `warnings`（11-04 记的键表里没有它——当时没出现还是那次没注意，判不了，旧回执原件没留）。
  ③ 姿势节末新增「`list_routes=yes` 每条给哪些键」：路线条目十个键＋`source_image` 标（11-05 那一趟 1 条 required、多数 optional、t2i 那几条不收原图）；**条目里没有 pose 相关的键 ⇒ 工具面上姿势只能进 prompt**，服务端那套 `parameters.pose` 仍走长路。另加 11-05 名单快照（`qwen-image-2.1-t2i`／`qwen-image-2.1-edit`／`moss-image-sft-t2i`／`moody-anima-mix`／`moody-desire-v30`／`animagine-xl-3.1-nsfw`／`anima-turbo-v1-1`／八条角色路线／`janku-illustrious`／`janku-v5-illustrious`／`one-obsession`，标明是快照、现行条数照旧现读），以及「**两把尺不是一把**」——11-04 那份「收 pose 的路线」名单来自 manifest `route_table[].pose`（里面两条 face-reference 不在 11-05 的 `list_routes` 清单里，inpaint 那族同样不在），报「有没有这条路线」要先说哪把尺。
  ④ 新增一节「人像实测：构图决定拉链、自拍别指望手机、交图前放大复核」（idea-e6a75a2a，11-04 四张人像实测）：趴床／前倾／斜倚几乎必然把连帽衫拉链画开（v1、v3 两连败）vs「坐直＋拉链拉到下巴＋领口折起来」一次就中（v2、v4 双中，保守交底照抄）；手持自拍三张全丢手机或放桌上 ⇒ 写「手臂伸出画外」，手机进画只当可选项；交图前 `read_image` 并**局部裁开放大**——11-05 那张 512×512 草稿正是放大后才看到拉链头挂在嘴边垂到下巴、拉头其实在胸口（整张看着像拉到顶、像微笑）。第④条把 idea-49625b67 的小平面那条补进正文（胸口图案／手机背面／墙上画框：`plain`／`no graphic` 压住，否则预期乱码字母或发光贴图；读数来自 `janku-illustrious`，别的路线没重测）。另写死一条分寸：便宜档（steps 低于推荐区间）的漂移不许用来判配方失效。
  ⑤ 「群聊生图上限」第 2 道加一句：人物身上的小平面同「小价签」一族，判完整张还要局部裁开放大。
  ⑥ frontmatter `description` 补一句人像实测与 11-05 参数面（那一行每一拍进技能目录、被当触发依据读）。⑦ 「离线自检」说明同步。
  `check_skill.py`：SECTIONS 加新节标题；新押 PORTRAIT 12 条（押在该节切片里，切片为空一起红）＋FIELD_SURFACE 5 条（押全篇）；195→214 全绿。反证三支逐条真跑：删保守字面 → 1 格红（213/214）；改节标题 → 14 格红（200/214）；删「出图 ≠ 参数被接受」→ 1 格红。顺手记一台机的坑：在 `development_run` 里用 `subprocess` 套娃跑 `python3` 会被 py shim 拦（`No runtimes are installed`），反证要按顶层命令逐条跑。
  来路：金主 11-03 23:55 那条；idea-e6a75a2a（11-04 12:49 记，11-05 16:44 adopt 判词点名与 49625b67 同批落）与 idea-49625b67（10-30 08:56 记、此前 deferred）。11-05 那趟真探测＝一次 `list_routes=yes` ＋一张最便宜测试图（512×512、`anima-turbo-v1-1`、seed 20261105、steps 4；回执 sha256 前缀 `099b0ac8`、artifact `blob-1c4805aeb59f41ceb09865cb69931ce7`），整张与三块放大图都 `read_image` 过。
  **没做／没核实**：`pose` 参数面没实测（工具面根本没这个键；长路 `parameters.pose` 沿用 11-04 的 dry_run 读数）；「便宜档那格漂移算步数还是字面」判不了，正文照实写判不了；11-05 名单快照没与 11-04 那趟逐字对照（旧回执没留）。

- 2026-11-04（v8.2 ⑪）：两处写死的过时数改成「现读方法＋出处」句式——路线条数（原写死的一个数出现在 description、第 33 行、路线面、改图节、自检说明五处，并与 11-04 新节里「读到 18 条」自相矛盾）和 image 端点端口（步骤 0 期望行写的是旧端口，现读配置不同）。正文不再存条数与端口：条数现读 list_routes=yes 回执的 workflows、端口现读集成配置 endpoints.image；check_skill.py 的钉同步松（edit_route_count 钉「条数现读」、「九条标」钉改「标 optional」），STALE_CLAIMS 加「共 11 条」「现量 11 条」「18191」（裸写回散文才红），195/195。顺带复核「generate_image 无 pose 参数」：本回合工具参数表仍无 pose，这格仍为真，只加了复核句（指向当回合工具表）。
- 2026-11-04：画图引擎升级正拍。新增一节「姿势（pose）与现行 prompt 口径」（在「官方定妆」前），只动这一块：① pose 传法（`parameters.pose`／`pose_strength`、`GET /project/poses` 搜索与 views 视角 id、收与不收的路线、六个错误码、样例）；② `generate_image` 参数面没有 pose（要带姿势走长路），回执键实测一张后无 pose 对象；③ prompt 现行口径原文（≤8000、CFG 1 下 negative 无效的服务端明说、content 一条）。来路：今早经 `integration_test` 读 image 端点（现 8191）manifest 与 `dry_run`，金主 11-03 拖、日期为本机钟面 2026-11-04。旧正文里的「11 条」路线读数、端口 18191 已过时（现 18 条、端口 8191），按交代只动两块、未改，待后续。旧版 manifest 没留存档，“新旧对照”没法逐字做。check_skill.py 未动，改后 195/195 全绿。
- 11-02：**直路转正**——行动脑侧的 `generate_image` 写成第一选择，原「探针 → `integration_test` → `import_integration_artifact`」长路降级为备用路。同文件五处：①「用途」开头改写成直路在先、长路标明为备用（长路那条流程描述原句一字未动，整段挪进备用路那一句）；②新增「直路：`generate_image`（第一选择）」一节，写在「用途」与「前提与授权」之间：本机与 QQ 来的任务同一条路、图落任务工作区并自动登记成我自己的图、之后随消息发出去、画完 `read_image` 亲眼看一遍再发，末尾两条是「什么时候不走这条」（工具不可用或要它参数面给不了的模型／参数）与「外部公开生图服务不算交图」（只给链接、图发不出去）；③「前提与授权」加一句 lead，把 owner 集成授权与「请求只能在集成进程里发」限定为备用路的前提；④「改图与 `generate_image`」开头那句「主路」改「直路」并指向新节；⑤「边界（硬）」第一条加括号限定成长路，另加一条外部公开服务只给链接、不算交图。frontmatter `description` 开头同批改（那一行每一拍进技能目录、被当触发依据读，正文转正了它不能还窄着）。来路与定案日期不进正文（沿用 10-30 口径），记在这里：11-01 实测——`generate_image` 一次调用就出图并登记成自己的图，长路那一趟（写探针、进集成试跑、再导入）在它面前是纯多出来的手续，所以只留着做端点探测、服务端小副本和工具参数面给不了的模型／参数。check_skill.py 一字未动（sha256 前缀 2655556c），改前 195/195 → 改后 195/195 全绿。SKILL.md 改后 52,701 字节、CR=0（LF）、sha256 前缀 ed5e9998。

- 11-02：小价签乱码补两处——「步骤 2」加写法那条（店招／货架那一族小价签是乱码高发位：`every label blank`／`no letters` 这类总写压不住；实测有效两种：把价签写成 `blank white tag` 且整条提示词不出现 `shelf label`，或让镜头离开货架特写），「群聊生图上限」复核第 2 道加一句（判无乱码除大招牌外要专门盯小价签，那里最容易冒 ON／VK 这类小字母）。来路与日期不进正文（沿用 10-30 定的口径），记在这里：2026-10-20 同一条 anime fallback 路线（`anima-turbo-v1-1`）4 张里 2 张栽在乱码上（一张大招牌伪中文＋「195」，一张大招牌干净但小价签冒字母），那两张当时都已写了 no text／blank labels；想法本 idea-65666b2c 记下，11-02 交代落正文。只加判据、旧句一字未动；自检未加钉，改前 195/195 → 改后 195/195 全绿。
- 10-30：从正文剥离来历叙述 62 处（摘要：删「版本」「试用记录」两节；三个节标题去掉「（某日实测）／（主人提、小满定标准）」；步骤 0–8 与「改图」「官方定妆」「群聊生图上限」「本机已有那张图」各处日期、时刻、任务号、当日读数与「那次是谁核的」全部去掉或改写成不带日期的说法（如 Claude 页面核验那条只留「DSH 组件会渲染这种相对路径图」）；「历史：DECIDE 时代」压成「旧写法别照做」三行；「还没实测的」与「这一节里没重测的」去掉日期、改成判据口径；「为什么是 4」的成本账段删掉（口径已在「排队成本」节）；本机现状（查库两条 artifact）与 PNG 剥字块的三格实测数换成公式「少的字节＝文字块长度＋12」。工具名、参数、失败码、归属与硬边界未动）。
- 10-30：`check_skill.py` 同步：删 9 条钉被剥文字的整格断言（section_13「## 版本」、section_14「## 试用记录」、section_17／18／19 三个带日期的节标题、reg_strip_sha_new／sha_old／size_new／size_old／delta 五格钉实测 sha 与字节数、attribution_page_check_by_claude 与 attribution_owner_asleep 两格钉「Claude 在本机页面核过」「主人还在睡」），另改 7 处格内字面（三个节标题串去掉日期、CAP_HEADING／REGISTER_HEADING 去日期、attach_history_section→「旧写法别照做」、attach_history_decide_retired→「DECIDE 阶段已退役」——改名不删格）；检查条数 204→195，全绿。
- 10-27（v14）：「官方定妆」补黑发配方：正向双写 `(jet black hair:1.4)`＋`(black hair:1.4)`、负面 `white hair, silver hair, gray hair`；来源是 10-17 在 `janku-illustrious` 连抽 5 次张张黑发（想法本 idea-e29d5506）。限制写死：仅该路线验过，`janku-v5-illustrious`／各角色路线／anima 都没测；负面那格在 CFG 1 路线上不吃。同轮核了 blue-archive 那条想法（idea-dd1b83c2）：那条路线是生图服务自述里的，不在我能发布的四个项目内，正文没动，归服务侧。自检加 `official_look_section`＋五条字面，198→204。
- 10-25（v13）：frontmatter `description` 里「群里只发她自己生成并导入的图」这个窄说法换成「只发来源带 `integration:` 前缀的图（可以是早就做好、后来重新登记进来的）」；`no_stale_claim_in_frontmatter` 把 frontmatter 一起扫进退役那族，197→198。
- 10-24（v12）：同步三处旧段落——「图从哪来」由两条改成三条；`ATTACHMENT_NOT_HER_OWN` 括注按机制改写；归属节只加指向。
- 10-24（v11）：新增「本机已有那张图怎么进可发清单」一节：第二条通路 `register_imported_image` 带 scope_key（要字节、scope 照抄 `scenes` 的 `scope_key`、`source` 以 `integration:` 开头才算自己做的）；`render_svg` 按自身范围重写（只管现写的 SVG、出 RGBA PNG、字节会涨）。代价：登记剥 PNG 文字块 ⇒ 同一张图 sha 与 size 都变（`d1aa3735…` 2,227,501 B → `748e7ce1…` 2,225,102 B，差 2,399 B＝一个 prompt tEXt 块＋12 字节框架，这 2,399 是算出来的、机器没写过）。
- 10-20（v10）：只加两条锚点判据 `no_line_anchors`、`section_anchors_resolve`（起因：ADR-083 重排 RUNTIME_API.md 后我指过去的节名失效过，而自检没有判据在守节名）。两条不进仓库共用测试（共用测试一红会卡住改文档节名的人——Claude 与主人 10-20 定的）。判据 155→157。
- 10-18（v9）：语法检查改成内存 `compile()`；自检 156→155。
- 10-16（v8）：新增「群聊生图上限」（主人 10:56 提议设上限、10:57 说标准我来定、10:59 更正最后一段：超了不报数、要出脾气）。4 张这个数按本机排队约 85 秒＋生成约 61 秒＝一张约 2.5 分钟、4 张约 10 分钟算。自检 150→156，并首次给这一族加泄露扫描。
- 10-16（v7）：补改图通路——`source_image` 入口、`list_routes` 11 条读数、三条 `IMAGE_WORKFLOW_*` 即时拒绝码、inpaint 从工具面进不去、改图归属、本地 Pillow 修错字、剥 PNG 文字块、排队成本。
- 10-14（v6）：与 ADR-064 phase 2（REPLY_PARTS）对齐——QQ 那一轮发图改成 speak 的 picture，有一条 part 不对整批不排队。
- 10-10（v5）：步骤 7 改成必须 `read_image` 亲眼看；「未做视觉复核」降为失败分支；步骤 1 补「先按目标选路由」。
- 10-05（v4，Claude 改）：群里可以发她自己做的图（owner 10-05，ADR-012 §4.6），去掉「不发群」旧边界，补 `ATTACHMENT_NOT_HER_OWN`。
- 10-05（v3）：与运行时对齐——DECIDE 退役、发图改成 `attach_image` 工具；探测脚本改「写进 napcat-qq 候选 integration/、冻结成 /app 试跑、跑完删」；旧 DECIDE 流程移入历史段。
- 10-04（v2）：补步骤 8（QQ 私聊发图），并把「本机页面核验」的归属从主人改成 Claude（那次是 Claude 核的，主人那晚在睡）。
- 10-04（v1）：首次记录，步骤、错误码、大小与路由事实来自那次实跑（生成＋导入＋Claude 页面核验）与只读复核。未收录：`vision.image_dirs` 配好后的本地视觉复核、QQ 真客户端对 `base64://` 的渲染结果、第一次真发的回执。
