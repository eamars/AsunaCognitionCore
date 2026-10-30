# CHANGELOG · asuna-image-generation-and-display

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
