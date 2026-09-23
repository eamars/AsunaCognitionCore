/**
 * Illustrative NATIVE SLOT registration, based on the fixed DSH public contract.
 * Not a full plugin: the existing Asuna projection must already supply this node.
 * Do not create new durable events, fake sessions, or change model outputs for it.
 */
import { createElement } from 'react';
import type { Context } from '@deepseek-ai/cordis';
import type { ChatNodeViewProps } from '@deepseek-ai/dsh-client-ui-chat/client';
import type { ComponentProps } from 'react';
import { NativeMessageContent } from './NativeMessageContent';
import type { MessageView } from './NativeMessageContent';

declare module '@deepseek-ai/dsh-client-ui-chat/client' {
  interface ChatNodeDataMap {
    'asuna-message': MessageView;
  }
}

type ContentProps = ComponentProps<typeof NativeMessageContent>;

/**
 * Pass existing DSH locale/part-renderer integrations. No fake import of ChatView.
 * The adapter is display-only, and must not call a model to render a node.
 */
export function registerAsunaContent(
  ctx: Context,
  existing: {
    readonly markdownLabels: ContentProps['markdownLabels'];
    readonly fileMentions?: ContentProps['fileMentions'];
    readonly pathImages?: ContentProps['pathImages'];
    readonly renderNativePart: ContentProps['renderNativePart'];
  },
): void {
  const View = ({ node }: ChatNodeViewProps<'asuna-message'>) => createElement(
    NativeMessageContent,
    { key: node.key, value: node.data, ...existing },
  );

  // Use a distinct business node kind; do not replace the generic DSH assistant renderer.
  // The native Chat owner declares this slot, so wait for its declaration.
  ctx.slots.inject('conversation.chat.node', () => ctx.slots.register(
    { name: 'conversation.chat.node', key: 'asuna-message' },
    View,
  ));
}

/**
 * The corresponding event-definition lives in the EXISTING projection boundary:
 * - match the actual source event using its own stable ID/association;
 * - consume the already-assembled native content instead of parsing provider SSE;
 * - preserve context.key through live and durable replacement;
 * - emit renderer data only; no runtime task-state mutation;
 * - use the native definition's publication cadence when that definition is needed.
 *
 * Registering the renderer alone is not a data-source integration and produces
 * nothing without a real matching node. This example intentionally does not invent
 * backend event names or claim to implement the multi-lane scene binding.
 */
