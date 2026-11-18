---
name: asuna-daily-backup
description: 我每天一趟的库备份四步固定脚本（导出、恢复演练、推 NAS、保留），脚本随这本技能发布放在同一目录，不再每天在任务工作区现写。四步参数化：保留份数走参数（本机 2、NAS 7），恢复演练的靶子节号每次现读一个当天之前没被改过的节，不写死。围栏写在脚本注释里，Mongo 只读、NAS 只在自己的子目录里动、删本机旧份之前先核 NAS 有同日同 sha 的那份、NAS 只认局域网那台、用户态 SMB 走凭据名 nas-smb，措辞只到 SMB 读回一致。要跑日更备份、或判一份备份算不算做完时读这一份。附零依赖自检 check_skill.py。
scene_kinds: [home]
---

# asuna-daily-backup

日更备份四步的固定脚本。以前每天在任务工作区现写，11-17 那趟的导出脚本事后找不到了，11-18 那五份同样随时会没；现在脚本跟着技能走，派活只交参数。

## 一、脚本在哪、下一趟从哪读

- 脚本在这份技能的目录里：`_bk_common.py`（共用）、`backup_export.py`、`backup_drill.py`、`backup_push.py`、`backup_retain.py`。
- **路径以 `skill` 工具回执里的 `Base directory` 为准，现读，不抄旧号。** 执行腿用 `sandbox_run` 直接 `python3 <Base directory>\backup_export.py ...`（实测这个目录在沙箱里只读可读），输出一律落在 `/task` 的一个工作目录里，别落临时目录。
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

```sh
# 1 导出（默认三张表 journal_entries state_heads state_revisions）
python3 <Base directory>\backup_export.py --out <工作目录> [--colls 表1 表2 ...]

# 2 恢复演练（靶子现读；要指定就带 --seq，报告里会标「手指定」）
python3 <Base directory>\backup_drill.py --snapshot <工作目录>\<快照名>.jsonl [--slug work_log] [--seq N]

# 3 推 NAS，再在新进程里复核一遍
python3 <Base directory>\backup_push.py --snapshot <快照> --nas-host <私网IP> [--pylibs <依赖目录>]
python3 <Base directory>\backup_push.py --snapshot <快照> --nas-host <私网IP> --verify-only [--extra <NAS文件名> ...]

# 4 保留（本机 2、NAS 7 是默认值；先不带 --do 看拟删清单）
python3 <Base directory>\backup_retain.py --workdir <工作目录> --nas-host <私网IP> --keep-local 2 --keep-nas 7 [--do]
```

- 第 3 步的 `--pylibs` 默认是当前目录下的 `pylibs`（装着 `smbprotocol`、`pyspnego`）；包数和版本现读，不抄旧值。
- 第 4 步不带 `--do` 只报不删。带了 `--do` 也是先核再删：本机侧每一份要删的都先和 NAS 同名文件逐字节比 sha，一份没过就一份不删，NAS 侧也不动。
- 删本机旧份时顺手删它旁边的 `.sha256`、`.export-summary.json`（只在工作目录里，且只在这份快照被删时）。

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

## 六、没验过的和没做的

- 11-18 现场验过：导出、恢复演练（含现读靶子）、保留的只读列目录与拟删清单、私网守卫。`backup_push.py` 的写入段和 `backup_retain.py` 的 `--do` 删除段，这一版脚本**没有对 NAS 真写／真删跑过**，只过了语法和参数面；第一趟真用它的人要盯第一份输出。
- 星期日把某份改名加 `-weekly` 的规矩没有脚本化（没有原文可照）；含 `weekly` 的名字一律不进删除候选也不计份数，是保守判断，不是旧规则原文。
- NAS 上每天留一枚 `probe-<日期>.txt`，脚本不清它们，目前也没有规矩说要清。
