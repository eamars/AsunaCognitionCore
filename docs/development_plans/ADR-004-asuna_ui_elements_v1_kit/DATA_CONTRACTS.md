# Minimal Data Contracts (UI-oriented)

These are presentation contracts, not a required storage redesign.
Codex may adapt names to existing APIs, but should preserve the concepts.

## Conversation summary item
```ts
interface ConversationSummary {
  id: string;
  title: string;
  channelType: 'local' | 'qq_dm' | 'qq_group' | 'temporary' | 'favorite' | string;
  subtitle?: string;
  unreadCount?: number;
  updatedAt?: string;
  groupLabel?: string; // e.g. 今天 / 昨天 / 更早
}
```

## Message item
```ts
interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  authorLabel?: string;
  text: string;
  createdAt?: string;
}
```

## Assistant reply with internal trace
```ts
interface AssistantReplyTrace {
  replyId: string;
  finalMessage: ChatMessage;
  internalSteps?: InternalStep[];
}

interface InternalStep {
  id: string;
  type: string;        // e.g. role_thought, action_plan, tool_call, tool_result
  actor?: string;      // e.g. Gemma, Qwen
  label: string;
  summary?: string;
  createdAt?: string;
  status?: 'ok' | 'error' | 'running' | 'skipped' | string;
  payload?: unknown;
}
```

## Inspector record
```ts
interface InspectorRecord {
  id: string;
  kind: 'memory' | 'preference' | 'group_preference' | 'relationship' | string;
  title: string;
  description?: string;
  source?: string;
  badge?: string;
  createdAt?: string;
  tags?: string[];
  excerpt?: string;
  fields?: Array<{ key: string; label?: string; value: string }>;
}
```

## Important note
These are intentionally minimal.
Do not force backend rewrites only to match these exact names.
Adapt existing Asuna/DSH data into this shape at the UI boundary.
