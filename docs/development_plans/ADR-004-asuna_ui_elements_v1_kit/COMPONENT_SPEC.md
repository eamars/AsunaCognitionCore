# Component Specification

## 1. Shell layout
### Component: `AsunaWorkbench`
Responsibilities:
- three-column layout
- route / state for selected conversation
- provides shared context for current session and inspector state

## 2. Left sidebar
### `ConversationSidebar`
Shows:
- new session action
- channel/session entries
- recent sessions grouped by recency

Required fields per item:
- id
- label
- channel type (local / qq dm / qq group / temporary / favorite)
- unread count optional
- timestamp optional

## 3. Main chat area
### `ConversationHeader`
Shows:
- title
- context subtitle
- search / overflow actions if available

### `BubbleMessageList`
Renders chat messages in chronological order.
Generic enough for:
- user message
- assistant message
- system note (optional)

### `AssistantReplyCard`
For one assistant reply block, render:
- visible final reply bubble
- optional expandable internal execution section

### `InternalTracePanel`
Render internal steps in a readable ordered form.
Each item should support:
- type
- actor
- timestamp
- summary text
- status
- expandable payload

Recommended actor labels:
- 角色脑
- 行动脑
- 工具调用
- 工具结果
- 系统/协调器（only if actually present)

Do not require all replies to contain all actor types.

Model names must come from configuration or the actual event, never from a role-name constant. The two roles may use the same model.

### Typography
Body English may use the Latin glyphs supplied by the Chinese text font; no separate English font is required. Inline code, fenced code blocks, JSON/tool payloads and code-editing textareas must use a shared monospace font stack. Preserve code whitespace and render content as text, never executable HTML.

### `ComposerBar`
Minimal composer with:
- input
- send
- current mode/session selector if already available

## 4. Inspector panel
### `InspectorPanel`
Tabbed container.
Tabs in V1:
- 记忆
- 偏好
- 群偏好
- 关系

### `RecordList`
Generic list for tab content.
Each record should support:
- title
- category/type
- timestamp
- source tag
- optional badge

### `RecordDetail`
Detail pane for selected record.
Supports generic field/value rendering plus source excerpt.

## 5. Generic rendering requirement
Use a generic record/event schema mapping so new fields can be displayed without redesign.
Avoid one-off components for every future record type.
