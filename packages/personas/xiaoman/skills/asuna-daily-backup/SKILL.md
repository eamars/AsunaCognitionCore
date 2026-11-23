---
name: asuna-daily-backup
description: 我每天一趟的库备份四步固定脚本（导出、恢复演练、推 NAS、保留），脚本随这本技能发布放在同一目录，不再每天在任务工作区现写。四步参数化：保留份数走参数（本机 2、NAS 7），恢复演练的靶子节号每次现读一个当天之前没被改过的节，不写死。围栏写在脚本注释里，Mongo 只读、NAS 只在自己的子目录里动、删本机旧份之前先核 NAS 有同日同 sha 的那份、NAS 只认局域网那台、用户态 SMB 走凭据名 nas-smb，措辞只到 SMB 读回一致。要跑日更备份、或判一份备份算不算做完时读这一份。附零依赖自检 check_skill.py。
scene_kinds: [home]
---

# asuna-daily-backup

日更备份四步的固定脚本。以前每天在任务工作区现写，11-17 那趟的导出脚本事后找不到了，11-18 那五份同样随时会没；现在脚本跟着技能走，派活只交参数。

## 一、脚本在哪、下一趟从哪读

- 脚本在这份技能的目录里：`_bk_common.py`（共用）、`backup_export.py`、`backup_drill.py`、`backup_push.py`、`backup_retain.py`。
- **路径以 `skill` 工具回执里的 `Base directory` 为准，现读，不抄旧号。** 脚本路径照抄那一段（实测这个目录在沙箱里只读可读），输出一律落在 `/task` 的一个工作目录里，别落临时目录。
- **解释器只认 `sys.executable`／`ASUNA_PYTHON` 指的那一枚，别拿 PATH 上裸 `python3` 这个名字赌。** 这两枚在沙箱里不是一回事（11-23 现场复现）：宿主直接起的 `python3` 是 `.venv` 那枚（3.12，`import asuna`／`bson`／`pymongo` 全 True）；而脚本内部再来一发 `subprocess.run(["python3", ...])`，这个名字按 PATH 命中的是 `WindowsApps` 那枚 stub，实跑落到另一枚 3.14 的托管安装，`backup_drill.py` 第 29 行 `from asuna import dbread` 当场 `ModuleNotFoundError: No module named 'asuna'`。11-21、11-23 两跑各栽过一次，都是现场另写一支驱动（`bk1121_run.py`／`_bk1123_run.py`：argv[0] 写的是 `python3` 就换成 `sys.executable`）才过去。
- 一行能照抄的命令形状——外面那枚只当跳板，干活的是里面那枚（11-23 实测：这一发跑 `--help` exit 0；把里面那枚换成裸 `python3`，同一发 exit 1 加上面那条 ModuleNotFoundError）：

  ```sh
  python3 -c "import os,subprocess,sys;sys.exit(subprocess.call([os.environ['ASUNA_PYTHON'], r'<Base directory>\backup_drill.py', '--snapshot', r'<工作目录>\<快照名>.jsonl']]))"
  ```

  自己写驱动也一样：驱动内部一律 `[sys.executable] + argv[1:]`，别再出现字面 `python3`。`ASUNA_PYTHON` 现读得到就用它，读不到用 `sys.executable`；它指向的是 `.venv` 那枚的绝对路径，绝对路径别抄进报告和派活纸。
- 为什么放技能目录不放工作区：技能随包发布、有 ACTIVE 那一版可读；工作区的东西随任务清掉就没了。代价是改脚本要走发布关口，所以每趟派活要写清读的是哪一版（`Base directory` 里那段 64 位号）。
- 凭据只用名字：`nas-smb`（环境变量 `NAS_SMB_USER`／`NAS_SMB_PASS`，值不落文件、不打印）。Mongo 的库地址与库名由程序给那条命令（`ASUNA_MONGO_URI`／`ASUNA_DATABASE`），脚本里不写。

## 二、围栏（脚本注释里也有，改一处四处对齐）

1. Mongo 只读：只调 `count_documents`／`find`／`buildInfo`／`serverStatus`，没有写、drop、建索引。导出前后各报一次写计数器，读不到就写读不到。
2. NAS 只在 `xiaoman-backups` 这个子目录里动，别人的条目一律不碰，删也只认 `xiaoman-asuna-backup-` 前缀。
3. 删本机旧份之前，先核 NAS 上有同一天、同字节数、同 sha 的那份；核不过，本机一份都不删。
4. NAS 只认局域网那台：`--nas-host` 必须是私网 IPv4 字面，不是就拒，不解析域名。地址不写进技能，由派活交代给。
5. 用户态 SMB，`pyspnego` 强制内置 NTLM。不走盘符、不走系统 UNC：`Z:` 和 UNC 经操作系统一律 `WinError 5`。
6. 措辞只到「SMB 读回一致」：sha 是我这头对 NAS 返回的字节算的，不许写「NAS 自己校验过」，也不写「验证了正确性」。

## 三、四步

`<PY>` ＝ 第一节写死的那一枚：宿主直接起的第一发可以就是 `python3`；一旦被包进驱动脚本或 subprocess，换 `os.environ['ASUNA_PYTHON']`（现读不到就 `sys.executable`），别留裸 `python3`。

```sh
# 1 导出（默认三张表 journal_entries state_heads state_revisions）
<PY> <Base directory>\backup_export.py --out <工作目录> [--colls 表1 表2 ...]

# 2 恢复演练（靶子现读；要指定就带 --seq，报告里会标「手指定」）
<PY> <Base directory>\backup_drill.py --snapshot <工作目录>\<快照名>.jsonl [--slug work_log] [--seq N]

# 3 推 NAS，再在新进程里复核一遍
<PY> <Base directory>\backup_push.py --snapshot <快照> --nas-host <私网IP> [--pylibs <依赖目录>]
<PY> <Base directory>\backup_push.py --snapshot <快照> --nas-host <私网IP> --verify-only [--extra <NAS文件名> ...]

# 4 保留（本机 2、NAS 7 是默认值；先不带 --do 看拟删清单）
<PY> <Base directory>\backup_retain.py --workdir <工作目录> --nas-host <私网IP> --keep-local 2 --keep-nas 7 [--do]
```

- 第 3 步的 `--pylibs` 默认是当前目录下的 `pylibs`（装着 `smbprotocol`、`pyspnego`）；包数和版本现读，不抄旧值。
- 第 4 步不带 `--do` 只报不删。带了 `--do` 也是先核再删：本机侧每一份要删的都先和 NAS 同名文件逐字节比 sha，一份没过就一份不删，NAS 侧也不动。
- 星期日那一份要在第 3 步之前先改名，本机与 NAS 才同名；改法见第七节那七条。

**删除段的报法（11-23 定，替掉派活纸上「被删 sidecar 的 sha 当场抓」那种前提不成立的说法）**

- 本机侧报**两把 sha**：那份快照的 sha（`--do` 那趟脚本自己就印「已删本机 <名字> | size=… | sha=…」），加它旁边 `<快照名>.jsonl.export-summary.json` **文件自身**的 sha。后一把脚本不报（它只印「并删本机 <文件名>」），要在带 `--do` 之前自己现算，删完补不回来。
- 本机**根本没有** `.sha256` 这一枚：`backup_export.py` 只落 `<快照名>.jsonl.export-summary.json`，`.sha256` 是第 3 步 `backup_push.py` 写在 NAS 那枚快照旁边的。11-23 现读本机工作目录：快照 3 枚、`.export-summary.json` 3 枚、`.sha256` 0 枚（当天删除前那份全列也是 0 枚，sidecar 那栏只列出 export-summary）。所以「被删 sidecar 的 sha」在本机侧没有对象，别照它报。
- NAS 侧 sidecar **永远不作为独立删除候选**：`backup_retain.py` 的删除候选只认 `xiaoman-asuna-backup-*.jsonl`（`mine()` 过滤）。但它也不是跟着快照一直活着——保留策略删掉某枚 NAS 快照时，脚本紧跟着把它的 `.sha256` 一起删（现读脚本：第 125 行 `smbclient.remove(np_)` 删快照，第 128 行 `smbclient.remove(np_ + ".sha256")` 删它的 sidecar；删掉印「并删它的 sidecar」，删不动印「sidecar 没删（本来可能没有）」），**不留孤儿 sidecar**。
- 所以 NAS 侧的报告分两句，别写成 sidecar 一定活着：**这一轮没被删的那些快照**，它们的 sidecar 报「还在＋它自身 sha」（读回来算，别拿快照那把冒充）；**这一轮被删的那一枚**，sidecar 随快照一起没了，报「随快照一起删了」，脚本不报它的 sha——那把要在带 `--do` 之前自己现读，事后补不回来。
- 本机侧那两枚后缀照旧：`backup_retain.py` 的本机删除循环（现读第 114 行）带着 `.sha256` 与 `.export-summary.json` 两个后缀，本机没有 `.sha256` 就对它什么也不做，只删得掉 `.export-summary.json`（它自身那把 sha 见上面第一条，删前自己算）。

## 四、恢复演练的靶子：现读，不写死

旧做法把靶子写死成一个节号，哪天那一节被改了或换了口径，演练就在比一个会变的东西。现在 `backup_drill.py` 每次现读：

- 在活库 `journal_entries` 里取 `slug` 下 `created_at` 早于今天本地 00:00 的最近 20 条（按 `created_at` 倒序）；
- 挑第一条 `revision == 1` 且 `updated_at` 与 `created_at` 相差不到 1 秒的那一节。
- 「不可变」是现读时的证据（建出来后没被改过），不是库的保证；挑中的节号要在报告里照抄。
- 实测（11-18）：从没改过的行 `updated_at` 与 `created_at` 也差几微秒，所以判据不能写成「两者相等」——第一版写成相等，20 行全判不合格，是现场跑出来的。
- 候选里一条合格的都没有就停下报，不拿别的节号凑。
- 读回快照必须 `bson.json_util.loads`；直接拿 `seq == 数字` 比会判成找不到，因为 int32 在快照里是 `{"$numberInt": ...}`。

## 五、报告怎么写

- 数从脚本输出抄，带来源：写侧 sha、本进程重读 sha、NAS 读回 sha（第一把同会话、第二把新会话）逐个列，不互相借壳。
- 导出时刻用快照 meta 里的 `taken_at_local`，不用计划时刻。
- 引脚本输出被截断就是没读到，分段重打，不按「这段该长什么样」补中段。
- 没跑的格写没跑：推 NAS 与保留是写 NAS 的步骤，没真跑就不报「已推」。

## 六、哪些段真跑过、哪一段至今没真跑过

- **NAS 写侧天天在真跑，不是「第一趟」。** 现读今天 push log 里 NAS 那批条目的 mtime：11-17 到 11-23 每天各一枚快照加一枚 sidecar，七天连续（`2026-11-17 11:48:53` → `2026-11-23 12:31:56`，今天那枚 sidecar 12:32:01）；今天这趟 sidecar 读回字节 `013b1c29…`，脚本自己印「里面那把 == 第一把: True」。写侧的规矩照旧：第一把与第二把 SMB 读回 sha 都要与本机那把逐字一致、目录前后 stat，两把都过才报「已推」，措辞只到「SMB 读回一致」。
- **NAS 侧删除至今没真跑过一次。** 今天这趟（快照 `xiaoman-asuna-backup-2026-11-23T1231.jsonl`，`--do = True`）脚本印的是 `NAS 我的快照（6 枚计入，保留上限 7）` 与 `NAS 拟删: []`（weekly 那枚不计入），带 `--do` 只删了本机那一枚（`本机拟删: ['xiaoman-asuna-backup-2026-11-20T1149.jsonl']`）。所以 `backup_retain.py` 那段「执行：NAS 保留 N 份」的删除循环到今天只过了语法和参数面：**第一次真删 NAS 的那趟盯整份输出**——先不带 `--do` 看拟删清单，带了再逐枚核 NAS 读回 sha 与本机同名那份一致，删完在收尾列目录里确认那枚真不在了、它的 sidecar 也随它一起没了。
- 本机侧删除是真跑过的：今天这趟带 `--do` 删掉了 11-20 那枚，删前本机与 NAS 两份的 size 与 sha 逐字节比过（日志里 `SMB 读回一致=True`，那是围栏 3 那道核），删后本机列目录里没有它。
- 11-18 现场验过：导出、恢复演练（含现读靶子）、保留的只读列目录与拟删清单、私网守卫。

## 七、周留档和探针文件谁清

- **周留 `-weekly` 档有自己的上限：最多 4 份（我这侧的规矩）。脚本不清它。** 含 `weekly` 的名字不进删除候选、也不计入日留份数；超过 4 份时 `backup_retain.py` 只在报告里打一行「周留档 N 份，超过上限 4，未清」，超了怎么办由我手动判断。
- **星期日那一份怎么变成 `-weekly`**（裁决 A，11-22 拍死的形状，一字不改；11-23 起这一格有原文可照，就是下面七条）：
  1. 第 1、2 步（导出、恢复演练）照常跑在普通名字 `xiaoman-asuna-backup-<日期>T<时分>.jsonl` 上：靶子、两把 sha、readout 都在改名之前拿全。
  2. 第 3 步**之前**改名，本机侧只有两枚要跟：`X.jsonl` → `X-weekly.jsonl`，`X.jsonl.export-summary.json` → `X-weekly.jsonl.export-summary.json`。能照抄的形状（Windows 原生沙箱没有 shell 变量展开，走 `-c`；11-23 在 scratch 目录实测 exit 0，改出来的两个名字和 11-22 现场那两枚一字一样。这条只用 `os`，哪一枚解释器都跑得动，第一节那条只针对 `backup_*.py` 的 import）：

     ```sh
     python3 -c "import os;d=r'<工作目录>';a='xiaoman-asuna-backup-<日期>T<时分>';[os.rename(os.path.join(d,x),os.path.join(d,y)) for x,y in ((a+'.jsonl',a+'-weekly.jsonl'),(a+'.jsonl.export-summary.json',a+'-weekly.jsonl.export-summary.json'))]"
     ```

  3. 本机侧没有 `.sha256` 要跟着改名（见第三节那格），别去找它；`.sha256` 那一枚是第 3 步在 NAS 上生成的，本来就带 weekly 名字。
  4. 第 3 步用改完的名字推：`--snapshot <工作目录>\X-weekly.jsonl` → NAS 上得到同名的 `X-weekly.jsonl` 和 sidecar `X-weekly.jsonl.sha256`，本机与 NAS 同名。sidecar 文本形状是「sha＋两个空格＋文件名＋换行」：11-23 现读当天那枚 109 字节（普通日份名字长 42），weekly 名字长 49 → 116 字节，NAS 上 11-22 那枚正是 116 —— 这一条是拿长度对出来的推断，不是当场读到的 sidecar 正文。
  5. **不留同日普通日份**：改完名之后，本机与 NAS 上当天就只有 weekly 这一枚，不再另存普通日份。
  6. **保留段当天一份都不删**：weekly 的名字不进删除候选、也不计日份；`drop` 取的是名字升序最前面（最旧）的几枚，当天那份排最后，正常情况下选不中。带 `--do` 之前照旧先看拟删清单里有没有今天的日期。
  7. 一处已知的走样，照实报、不改形状：改名只动文件名，`export-summary.json` 里面 `"file"`／`"path"` 两栏仍是改名前那个名字（11-22 那枚现读就是这样：文件名带 `-weekly`，里面写 `...2026-11-22T1149.jsonl`）。报告里点一句，别当成对不上。
- 这一格还是靠腿，没进脚本：`backup_retain.py` 每趟照旧印一行「（-weekly 改名不在本脚本里）」，上面七条要执行腿照着做；真要它进脚本得动代码，本趟没动。
- **NAS 上的 `probe-<日期>.txt` 不清。** 脚本每跑一次留一枚，11-18 我数到 3 枚，没有人清、也没有规矩要清；要清由我手动，只动 `xiaoman-backups` 里 `probe-` 开头的那几枚。
