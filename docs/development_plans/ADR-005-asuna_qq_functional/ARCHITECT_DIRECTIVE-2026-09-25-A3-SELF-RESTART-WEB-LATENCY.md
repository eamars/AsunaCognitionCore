# Asuna Web 性能与 Runtime Restart 联合修复

## 0. 严重度与目标

本项为 **P1 / High availability + UI performance**。

已观察：

- development publish 后 RuntimeHost 激活可等待约 15 分钟；
- Web 在宿主冷启动阶段长时间不可用或停在读取状态；
- 浏览器打开 Asuna UI 后整体内存观察约 3.5 GB；
- 页面交互和反馈明显迟缓；
- 手工刷新后有时才能恢复内容。

这不是 A2 功能错误。

这次目标是同时解决：

1. RuntimeHost restart 不应杀掉整个 Web shell；
2. Asuna UI 的 state 获取和渲染成本必须与**当前可见数据量**相关，而不能与整个 scene 历史量相关；
3. live streaming 必须是增量流，不得重复发送不断增长的完整 provider body；
4. 浏览器内存应稳定，不得在 idle / streaming / periodic refresh 中持续增长；
5. 不为此建立新的 UI framework、metrics platform、缓存平台或 HA 系统。

---

# 1. 先做一次非常小的定位，不先重构

开始前记录当前工作树和当前运行版本。

不要用 GitHub 版本覆盖当前 local tree；GitHub main 只用于对照上一版本。

只做一轮 baseline profile。

## 1.1 区分 DSH shell 和 Asuna workbench

分别打开：

### A

正常 DSH 中的 Asuna panel。

### B

直接打开：

`http://127.0.0.1:8765/asuna/`

也就是 Asuna iframe 实际页面。

比较：

- renderer/tab memory；
- JS heap；
- 首次可交互时间；
- idle 后 memory；
- `/state` 请求情况。

目的：

判断 3.5 GB 主要来自：

```text
DSH outer shell
Asuna iframe/workbench
or both
```

不要因此改写 DSH upstream。

---

## 1.2 浏览器只记录几项数据

使用现有 Chrome/浏览器 DevTools、现有 browser tooling 或 CDP。

不要安装性能平台。

记录：

```text
initial JS heap
initial tab/renderer memory if available

5 min idle 后 heap/memory

一次普通 state 请求：
- response bytes
- server/request duration

一次长 action / streaming：
- /stream received bytes
- peak heap
- stream settle 后 heap

当前 /state request frequency
```

同时记录 Network 中：

```text
/asuna/api/state
/asuna/api/stream
```

的调用次数和 transferred size。

不需要做多轮 benchmark。

---

# 2. 删除 Context UI 后，立即删除 full-scene snapshot 扫描

架构师已经裁定：

> 用户级 Context 管理删除；左栏只保留 scene/channel navigation。

因此 UI snapshot 不再需要为了：

```text
context groups
historical context titles
current vs historical context selection
```

读取整个 scene。

当前上一版本 `_snapshot()` 的模式：

```text
find ALL episodes in scene
find ALL messages in scene
group all rows by character_context
then select last 12 rows
```

必须删除。

## 新语义

聊天页只查询：

```text
selected scene
+ requested page boundary
+ visible recent message page
+ currently active task lineage needed for display
```

普通第一页只读当前最近一页。

沿当前 pagination：

```text
beforeSeq
hasMore
```

继续即可。

不要把整个 message collection materialize 到 Python 后再切片。

数据库 query 本身：

```text
sort scene_seq desc
limit visible-page size
```

然后再恢复为显示顺序。

如果一个 episode 跨 page boundary，需要多取该 episode 所需少量相关 rows 可以，但不能退回 full-scene scan。

## 同样不要全量读取 episodes

只取：

```text
visible message episode ids
+
active task owner episode ids
```

所对应的 episode。

---

# 3. `/state` 必须成为轻量 projection

`GET /state` 不应该每 2 秒发送：

- 大量完整 audit payload；
- 完整 tool payload；
- 完整 provider projection；
- 100 条带全部字段的 Mongo documents；
- 未展开的诊断详情。

## `/state` 第一层只返回

### Conversation

```text
scene metadata
send/read state
visible message page
message id
role
text
time
delivery state
turn status
trace summary/count
```

### Runtime

```text
ready / restarting
model state
send availability
```

### Scene navigation

当前允许的 scene/channel summary。

不要再返回 Context navigation。

---

# 4. Trace 改成 summary-first / detail-on-demand

当前 `internalSteps` 会把 trace step payload 跟着每次 `/state` 一起下发。

改为：

消息 snapshot 只包含类似：

```text
traceCount
errorCount
steps:
  id
  type
  actor/lane
  label
  status
  createdAt
  short summary
```

**不要默认包含完整 `payload`。**

用户展开某一个 trace step 后，才通过一个窄的 authorized detail endpoint 读取：

```text
full tool result
full error payload
provider diagnostic metadata
```

已有 provider diagnostic/raw response lazy-read 语义继续复用。

不要在初始页面加载 raw provider response。

不要为了这一步建设通用 Audit API。

只需要当前 scene 已授权 event 的 detail read。

---

# 5. Inspector 必须与聊天 state 分离

右栏 inspector 继续保留。

但它不应该跟随每一个 2 秒 chat refresh 重建 100 条完整 records。

## 改成

### Inspector list

只返回：

```text
id
kind
title
description
createdAt
short excerpt/badge
```

### Inspector detail

用户点击某记录时才获取完整 fields。

Search 默认只在 list summary 上操作。

不要再执行：

```js
JSON.stringify(完整 record)
```

来完成每个 render 的搜索匹配。

如果需要检索更深内容，以后另议；本轮不是 memory-search UI 项目。

---

# 6. 停止每 2 秒 full-state polling

上一版本：

```js
async function poll() {
    await refresh()
    setTimeout(poll, 2000)
}
```

并且：

```js
JSON.stringify(next)
```

比较整个 snapshot。

删除这种运行方式。

## 第一版采用简单策略

### 立即 refresh 的事件

- 页面首次打开；
- scene 切换；
- 用户 send 成功；
- manual refresh；
- live stream settlement；
- RuntimeHost 从 restarting → ready；
- model config apply 完成。

### 有 active/pending work

允许较短 fallback polling，例如当前量级。

### idle

降低为慢 fallback，只用于防止遗漏外部 scene 更新。

不要持续每两秒传整个 state。

如果当前已有可靠事件可以通知 durable state dirty，优先用它。

但不要为了完全 event-driven 再建设一套 event bus。

---

# 7. 不再对整个 state 做 JSON.stringify diff

下面的模式删除：

```js
const signature = JSON.stringify(next)
if (signature !== revision) render()
```

Server 应提供一个非常轻的 snapshot revision，或者客户端只比较明确的 revision 字段。

revision 可以由当前已有事实组合产生，例如：

```text
visible scene latest sequence/revision
visible task/audit revision
memory inspector revision
model revision
runtime state
```

具体采用现有最方便的 stable revision。

不要为了这个建立 RevisionService。

即使暂时不能得到统一 revision：

> 一个小且 bounded 的 snapshot 直接 keyed update

也比每 2 秒 stringify 整棵对象好。

---

# 8. Live stream 必须改成真正 delta

这是本轮高优先级修复。

不要通过 `/stream` 重复发送：

```text
到目前为止完整 provider response
```

不要让每一个 token/chunk 都复制此前所有文本。

## 使用已有 ProviderProxy decode point

当前 provider proxy 已经能够解析：

```text
delta.content
delta.reasoning_content
```

因此 live projection 只发：

```text
call/display key
lane
phase
field
delta text
sequence
status event
```

例如：

```text
start
text delta
text delta
...
end
```

浏览器只 append delta。

总网络量与最终流文本量应接近 O(n)，不能 O(n²)。

---

# 9. Raw provider response 不参与 live chat

Raw provider response 只用于：

> collapsed diagnostic detail

并保持 lazy read。

不要：

- live 保存完整 raw SSE body 给浏览器；
- 每个 chunk 更新完整 `body_utf8`；
- 把 raw wire JSON 作为实际 message stream。

角色脑/行动脑当前实际文本使用 semantic：

```text
content
reasoning_content
```

以及最终 durable DSH/Asuna records。

这同时符合已有 ADR-006 要求：

> raw provider response 不替代真实 MONOLOGUE / assistant content。

---

# 10. UiStreamHub 不保留大 body

如果当前 local tree 仍有类似：

```python
call['body_utf8'] += ...
```

并且 snapshot 返回完整 call：

删除该模型。

UiStreamHub 只需要保留：

```text
call metadata
last sequence
status
极少量未结算 delta / display state
```

durable output 一旦落库：

> 浏览器 refresh durable state → live buffer 丢弃。

不要把 settled 大文本保留 300 秒。

如确实需要短暂 reconnect continuity：

只保留已经生成的**semantic visible text**一次，不保存原始 provider wire body，更不能每次 retransmit 全文。

---

# 11. DOM 更新改成 keyed in-place

不要在普通状态变化时：

```js
messages.replaceChildren()
```

重建全部可见 conversation。

保持：

```text
message.id → DOM node
step.id/displayKey → DOM node
record.id → DOM node
```

已有节点原地更新。

新 message append。

历史分页 prepend。

已不在当前 page 的 node 删除。

Live text 只更新对应当前 message/step 的 text node。

不要引入 React/Vue 或新的 virtual-DOM framework来解决这个问题。

当前原生 DOM 可以完成。

---

# 12. 清理浏览器侧永久增长集合

检查至少：

```text
expanded Set
liveCalls
selected record
scene-specific cached nodes
EventSource listeners
model UI temporary state
```

scene 切换、消息从当前 page 移除、RuntimeHost replacement 后：

不再可见的 key 必须可以释放。

EventSource 重连前继续确保旧 source 真正 close。

Runtime restart 后不能同时留下：

```text
old stream
+
new stream
```

---

# 13. RuntimeHost restart 与 UI shell 解耦

沿上一份架构裁定执行。

正常 development publish：

```text
DSH Web shell / browser page
    长寿命保持

UiBridge
    长寿命保持

RuntimeHost
    replaceable
```

RuntimeHost restart 时：

```text
runtimeState = restarting
canSend = false
```

页面仍可读已经加载的聊天。

新 RuntimeHost ready 后：

```text
bridge rebind
runtimeState = ready
refresh lightweight state
reconnect live observation if needed
canSend = true
```

用户不需要 F5。

---

# 14. 不要用自动 reload 修复

禁止把当前问题修成：

```js
location.reload()
setInterval(refresh page)
连接失败 5 秒后刷新 iframe
重启后 hard reload
```

这只能隐藏 lifecycle 和 memory leak。

---

# 15. Runtime restart 等待边界仍按上一裁定

development publish 后：

- 不杀当前 in-flight role/action work；
- durable queued work 不阻止 restart；
- restart pending 后不继续启动新的 queued action；
- 当前 in-flight 结束立即 restart；
- action task completion 本身也是 restart recheck point；
- queued work 由新 RuntimeHost recovery。

不要等待整个队列永远变空。

---

# 16. Cold-start timing 继续做，但与 Browser profile 同一轮完成

只增加已有日志中的少量阶段 timing：

```text
restart.pending
restart.blocked
restart.requested

host.stop.started
host.stop.finished

host.start.started

lane.character.start/ready
lane.executor.start/ready
lane.summary.start/ready

host.recovery.start/ready
host.channels.ready
host.integration.ready
host.schedule.ready
runtime.ready
web.ready
```

同时记录 browser baseline。

只跑一次正常 restart。

不要建设 metrics infrastructure。

---

# 17. 性能验收口径

不要求追求某个跑分。

但下面几项必须成立。

## Memory

### 空闲稳定性

页面加载完成后 idle 10 分钟：

> JS heap / renderer memory 不应持续单调增长。

允许 GC 波动。

不能出现类似：

```text
500 MB
→ 1.2 GB
→ 2 GB
→ 3 GB
```

只因为页面开着。

### Recent-history independence

数据库历史增长以后：

> fresh UI 的 browser memory 不应与整个 scene 历史总量近似线性增长。

只和当前 page / inspector 当前 page / live task 有关。

### 3.5 GB

当前观测的约 3.5 GB 必须显著下降。

如果直接 `/asuna/` 已经占绝大多数，则修 workbench。

如果只有嵌入 DSH shell 时异常增大，再单独定位 outer-shell/iframe interaction。

不要猜。

---

## Network

idle 时不得每两秒反复下载相同的大 `/state`。

live stream 总 transferred bytes 必须与最终显示文本同量级，不能随着输出长度二次增长。

---

## Latency

在 RuntimeHost 已 ready、本机 Mongo 正常的情况下：

- 首次 recent-page state 不应需要扫描整个 scene；
- scene 切换不应扫描整个 scene；
- send 后 queued 状态立即可见；
- live delta 到浏览器后立即更新对应 stable message；
- inspector detail 加载不应阻塞聊天刷新。

不需要为了验收规定 100 ms 这种虚假精度。

记录实际 before / after 即可。

---

# 18. 一个很重要的验证

使用一个**执行步骤较多、输出较长**的真实行动任务。

观察：

1. streaming 过程中浏览器 memory；
2. `/stream` transferred bytes；
3. UI 是否越来越卡；
4. settle 后 memory 是否能回落/稳定；
5. 展开一个 trace detail 是否只在这时读取 full payload。

不要制造几十个并发任务。

一个长任务足够暴露 O(n²) 问题。

---

# 19. 删除 Context UI 与本性能修复一起落地

因为它们直接相关。

删除：

- New Context；
- context history list；
- context selection。

左栏只保留 scene/channel navigation。

后端因此也删除：

- 为 UI 构造全部 context group；
- 为 context titles 扫描整个 scene messages；
- historical-context snapshot 分支。

底层 runtime context/session 保留。

不要顺便改 memory / DSH session semantics。

---

# 20. 不做的事情

本轮不要：

- 重写整个 UI；
- 更换前端框架；
- 修改 DSH upstream；
- 建 Redis/cache 服务；
- 建 websocket framework；
- 建 metrics/dashboard；
- 做 UI virtual scrolling framework，除非 bounded recent page 完成后仍有明确需要；
- 重写 inspector 产品功能；
- 重新做 ADR-006 视觉设计；
- 优化 A2 cognition 逻辑；
- 重验所有 QQ 场景。

优先解决：

```text
full history scan
heavy state snapshot
2 sec polling
whole-state stringify
whole DOM replacement
full-body live stream
Web/Runtime lifecycle coupling
```

---

# 21. 实施顺序

严格按下面顺序，避免同时乱改：

### Phase 1 — baseline

一次 browser/network profile。

### Phase 2 — bound data

- 删除 context UI；
- DB query 真分页；
- state 只含 visible page；
- trace detail lazy；
- inspector detail lazy。

先看内存和 `/state` 延迟是否已显著下降。

### Phase 3 — fix live streaming

- semantic delta；
- 不重复 full body；
- keyed message in-place update。

再次看长 action。

### Phase 4 — reduce refresh churn

- 去掉 2s full polling；
- 去掉 whole-state JSON.stringify；
- immediate/event + slow fallback refresh。

### Phase 5 — runtime lifecycle

- Web shell / UiBridge 长寿命；
- RuntimeHost replacement；
- restarting / ready；
- 不需要 browser refresh。

### Phase 6 — one acceptance run

一次 normal publish + 一个长 action。

然后停止。

---

# 22. 完成报告

不要写进仓库新的性能报告。

聊天中只给：

### Before

```text
embedded/direct memory
/state bytes + duration
stream bytes
restart timings
```

### Root causes actually confirmed

只列有测量支持的。

### Changed

列具体文件与行为。

### After

同一组指标。

### Still unknown

如果 outer DSH shell 仍占明显内存，单独列出来，不顺便改 DSH。

达到明显稳定后停止，不追求微优化。