---
name: asuna-turret-frame
description: 炮台（云台，OpenAutoTurret）取帧与姿态读数的正本，归「怎么读这台机器」这一族，不属于生图那本。写死四件事：GET 侧只有五个读口加 WS，控制面全在 POST，只读任务一个 POST 都不发；姿态读数只走 WS 接收或裸 GET 状态口；这台不自报固件版本，认机器只认 camera_id、epoch 和 release 路径，别把另一台设备（OpenTrickler）的身份串贴到它身上；两个入口地址是同一枚流，用 epoch 和 camera_id 现场对照，原位会漂，每次动之前现读当基线、动完回基线并报差值。要读炮台的帧、姿态，或判它是哪一台、动没动时读这一份。附零依赖自检 check_skill.py。
scene_kinds: [home]
---

# asuna-turret-frame

炮台取帧与姿态读数。这一本只管「怎么读」；怎么动它属于控制面，不在这里授权。

## 一、接口面：GET 只有五个读口，控制面全在 POST

- GET 读口只有这五个：`/api/health`、`/api/video`、`/api/video/state`、`/api/selection`、`/api/state`；另有 WebSocket `/ws`。
- **控制面全在 POST。** 只读任务（取帧、读姿态、认机器）一个 POST 都不发；WS 只收不发。动它要交代里明写授权，这一本不授予。
- 取帧：`GET /api/video?camera=<role>&t=<毫秒时刻>`，`role` 实测有 `wide`、`detail` 两路；返回是持续的 MJPEG 流，读到第一帧完整 JPEG（`FFD8FF` 起、按段头 `Content-Length` 截）就断，别整条流读。
- 状态：`GET /api/video/state?camera=<role>`，读 `epoch`、`camera_id`、`frames_published`、`delivered_fps`、宽高。**尺寸别按 1080p 期待：自报分辨率只当设备说法，以真取到的字节为准。** 实测快照口 `/api/video` 送回的是 **640×360**（11-18 22:40 交回那一帧 640×360、31,146 字节，任务 `task-ccf8e1aa3d0aa37de904e175e8c8af24`），而 WS `video_streams` 里 wide 自报 **1920x1080**——两者不一致，判尺寸认字节，不认自报。
- 帧里自嵌一段 `OTA_FRAME` 元数据（`frame_sequence`、`sensor_timestamp_ns`、相机号），有它是设备当前流帧的旁证；没有就写「没有」，不补。
- 来路：11-17／11-18 两趟取帧脚本的字面（现场读过，这一版没有重新对炮台跑一遍）。

## 二、姿态读数：WS 只收，或裸 GET 状态口

- 两条路：`/ws` 只 `recv`；或裸 `GET /api/state`。别的口不拿来读姿态。
- WS 帧里常用的键：`q_yaw_rad`、`q_pitch_rad`（姿态）、`operating_mode`、`fault`、`manual_lease_active`、`telemetry_age_ms`、`camera_id`、`video_streams`；`cmd_ack_seq` 也在里面，它是指令应答序号，只读它不拿来判谁动过。
- **`q_yaw_rad` 会报出大于 2π 的值**（这次读到 **20.688**），不能当夹角直接读；要判朝向就比对两次读数的差，别把绝对值当角度（差值做法见第四节）。同一趟序列里 23:30 那一帧的 yaw 差是 **0.000 rad**（任务 `task-787f53376df72ecc2873540e2c60c6aa`）。
- 「只 GET、零 POST」已两次实测通过：11-18 两趟只读腿的 `POST_COUNT` 都是 0（上一条那枚任务，加 `task-ccf8e1aa3d0aa37de904e175e8c8af24`）。
- 一次读三帧取区间（最小、最大、极差），不拿单帧当姿态。读数带本机读的时刻。**判时刻一律用本机钟，别用这台的 HTTP `Date` 头**：实测它的 `Date` 偏了约 **5 小时**（本机 22:39 时 `Date` 里是 `09:39Z`，按 UTC 换算应当是 `14:39Z`）。

## 三、这台不自报固件版本：认机器只认三样

- 认机器只认 `camera_id` ＋ `epoch` ＋ release 路径。「identity」那一格属于 camera，不属于整机——camera 对上不等于整机对上，整机版本这台读不出来就写「读不出来」。
- **别把另一台设备（OpenTrickler）的设备号和固件版本贴到这台身上。** 那两串（一串 8 位设备号、一串三段点分版本号）是另一台的身份证。11-18 上午贴错过一次：对炮台白跑了 9 条 404、两趟 WS 全文搜，什么都没找到——因为这台根本不报。
- 两个入口地址（一个 IP 形的、一个 mDNS `.local` 主机名形的；具体写法在我的私密名单里，不进技能）是**同一枚流**：用 `epoch` 和 `camera_id` 现场对照，对得上就是同一台，别当两台，也别因为两个地址各读一次就报「两份读数」。

## 四、「原位」会漂

- 每次要动它之前，**现读一遍当基线**（WS 三帧，记 `q_yaw_rad`／`q_pitch_rad`），动完回到基线，再读一遍，**报 yaw、pitch 各自的差值**（弧度，带符号）。
- **不许拿上一次记的那组数当原位。** 实测它会自己漂：11-18 `cmd_ack_seq` 隔一天加了 222，没有读数能说明是谁动的。
- 也不把漂移记成自己干的：基线是现读的，漂在我读之前发生的，归因没有读数就写「归因无读数」，不编动机。
- 没回到基线就写没回到，差值照报，不说「已复位」。

## 五、技能头的坑（写这类技能时）

- frontmatter 的值里不写 ASCII 冒号加空格：装载侧用真 YAML 解析器，`description` 是 plain scalar，值里有它就抛 `YAMLParseError`，整本从行动侧清单里静默消失，而我这侧宽松解析照样报「头合法」（11-17 有一本就是这样整本静默 `continue`）。
- 写完用真 YAML 解析器读一遍（`yaml.safe_load` 取第一个 `---` 到下一个 `---` 之间），本目录 `check_skill.py` 的头检查就是这么做的。

## 六、没验过的

- 这一版没有对炮台实机重跑过读口；第一至第四节的接口与键名来自 11-17／11-18 两趟脚本和我流水里的记录。
- 取帧流的段头格式（`Content-Length` 行）是脚本里照着解出来的，换了固件可能变，读不到帧时写读不到。
