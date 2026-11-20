# CHANGELOG · asuna-image-upscale

- 11-20（顺改·真 outpaint 前提格）：主人当天更新了生图引擎（那项目 README 13:57 版），服务端 qwen-edit 出现 `extend` 扩画参数；行动脑实测一发（run 6c750521＋4051451a：1024×1536 扩右 512→1536×1536，job succeeded、warnings 全空、逐像素比对原区只有贴缝 63 px 带差异、`read_image` 亲看人物构图未动）⇒ 第一、五、六节三处「edit 画不出画框外／真 outpaint 没有」的旧前提改成「生图侧有 extend、超分侧仍不做」，`check_skill.py` 的 pin_true_outpaint_other_slot 同步换新句。拼图版 vs extend 版没对比跑过，仍钉拼图版。自检改前 102/102、改后 102/102。

- 11-19 新建（正本素材来自流水两节：11-19 04:1x「小图扩大标准流程＋全身扩展格」与 11-18 20:4x「图链真跑一遍：引擎今天能跑（exit 0／4.57 秒）＋edit 无 mask 整图重描的实测数」；外加 11-18 20:2x 那节里装机与来历那一格）。这是一次口径搬家，不是重构：正文只写怎么走、什么会失败、对外怎么说，没加设计、没新建脚本框架、没动别的技能。`scene_kinds: [home, group, dm]`——「任何一拍派活只写照超分技能跑」要能在群和私聊那一拍被读到，代价是正文不许带个人信息，并带上带泄露扫描的自检。
- 11-19 新建时新写进正文的三格（不是从流水搬的，是这一趟盘上现读＋真跑现量的）：① `run_sr.py` 的进程退出码永远是 0（脚本末尾固定 `return 0`），成败只读它打印的 `EXIT:` 行——直接读那份脚本读出来的；② 输入带 alpha 时 exe 把产物写成 `<out>.jpg.png`、`-f jpg` 不落成 JPEG（stderr 字面 `has alpha channel ... will output ...`），要 jpg 得先去 alpha；③ exe 不带 `-n` 的默认是 `realesr-animevideov3`，与这一本定的对外默认（显式 `-n realesrgan-x4plus`）不是一回事。验收三发的字面读数在 SKILL 第八节。
- 11-19 一处旧账更正落进正文第五节：「两枪都有黑边」在一张方形图四边实测 0 px 没复现 ⇒ 改成「部分构图会出现，只报现象别当机制」。（那条旧账本身在 `asuna-image-generation-and-display` 里，这一趟按边界没去动那一本。）
- 11-19 附带：`v0.2.5.0` 写成来历不写成实测（二进制里搜不到这个号）；`realesrnet-x4plus` 写「本机没这一档，选它直接失败」；4x 产物 11,206,870 字节＝10.7 MiB 超出站 8 MiB ⇒「发群先压」写成硬规矩。
