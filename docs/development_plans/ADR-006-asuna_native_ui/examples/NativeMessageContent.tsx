/**
 * ADR-006: content INSIDE an existing native DSH chat node.
 * Not a chat window, not a sidebar, not a transport, not a token reducer.
 * Public component signatures reviewed at dsh-v0.1.5-rc.2.
 * Bind the existing native stream/scene projection before using this example.
 */
import { Fragment, memo, useState } from 'react';
import type { ComponentProps, ReactNode } from 'react';
import {
  CodeBlock,
  DisclosureRow,
  MarkdownText,
  StateDot,
} from '@deepseek-ai/dsh-client-ui-primitives';

type MarkdownProps = ComponentProps<typeof MarkdownText>;

/** A read-only view value, NOT a required API/DB/model-output schema. */
export interface MessagePart {
  /** Original, stable content-block identity; never the growing text itself. */
  readonly key: string;
  /** Determined from a real recorded block; not inferred from prose content. */
  readonly presentation: 'markdown' | 'code' | 'native';
  /** The FULL accumulated value supplied by the existing source assembler. */
  readonly text?: string;
  /** Actual field name when known; omit rather than invent provider fields. */
  readonly sourceLabel?: string;
  readonly language?: string;
  /** An existing attachment/tool node may be passed to its existing renderer. */
  readonly source?: unknown;
}

export interface MessageView {
  /** Stable native node/attempt key, preserved at durable settlement. */
  readonly key: string;
  readonly brainLabel: string;
  readonly messageKind: string;
  readonly statusLabel: string;
  readonly state: 'running' | 'ended' | 'stopped' | 'failed' | 'truncated' | 'waiting';
  /** Ordered by the source; do not group all reasoning before all content. */
  readonly parts: readonly MessagePart[];
  readonly errorText?: string;
  /** Non-content diagnostic JSON only; full provider wire remains in audit. */
  readonly providerDiagnostic?: string;
}

interface Props {
  readonly value: MessageView;
  /** Keep this object stable per locale, as required by native MarkdownText. */
  readonly markdownLabels: MarkdownProps['labels'];
  readonly fileMentions?: MarkdownProps['fileMentions'];
  readonly pathImages?: MarkdownProps['pathImages'];
  /** Use the existing native image/tool/fallback slot. Do not draw a new card. */
  readonly renderNativePart: (part: MessagePart) => ReactNode;
}

/** Already-approved business labels + native primitives; no custom CSS. */
export const NativeMessageContent = memo(function NativeMessageContent({
  value,
  markdownLabels,
  fileMentions,
  pathImages,
  renderNativePart,
}: Props) {
  const [diagnosticOpen, setDiagnosticOpen] = useState(false);
  const streaming = value.state === 'running';
  const hasBody = value.parts.some(part =>
    part.presentation === 'native' || (part.text !== undefined && part.text.length > 0));
  const hasFailure = value.state === 'failed' || value.state === 'truncated' ||
    value.state === 'stopped' || value.errorText !== undefined;

  // No empty brain card while merely waiting. Actual zero-content failure stays visible.
  if (!hasBody && !hasFailure) return null;

  const dot = streaming ? 'ongoing'
    : value.state === 'failed' ? 'error'
    : value.state === 'truncated' || value.state === 'stopped' ? 'warning'
    : value.state === 'waiting' ? 'idle' : 'done';

  return (
    <>
      <DisclosureRow
        icon={<StateDot state={dot} />}
        title={`${value.brainLabel} · ${value.messageKind} · ${value.statusLabel}`}
        open={false}
        expandable={false}
        onToggle={() => { /* non-interactive metadata row */ }}
      />
      {value.parts.map(part => (
        <Fragment key={part.key}>
          {part.sourceLabel ? <small>{part.sourceLabel}</small> : null}
          {part.presentation === 'markdown' ? (
            <MarkdownText
              text={part.text ?? ''}
              streaming={streaming}
              labels={markdownLabels}
              fileMentions={fileMentions}
              pathImages={pathImages}
            />
          ) : part.presentation === 'code' ? (
            <CodeBlock
              code={part.text ?? ''}
              lang={part.language}
              streaming={streaming}
              copyLabel="复制"
              copiedLabel="已复制"
            />
          ) : renderNativePart(part)}
        </Fragment>
      ))}
      {value.errorText !== undefined ? (
        <CodeBlock code={value.errorText} copyLabel="复制" copiedLabel="已复制" />
      ) : null}
      {value.providerDiagnostic !== undefined ? (
        <DisclosureRow
          icon={null}
          title="诊断 · provider 元数据"
          open={diagnosticOpen}
          expandable
          expandOnRowClick
          onToggle={() => setDiagnosticOpen(open => !open)}
        >
          <CodeBlock
            code={value.providerDiagnostic}
            copyLabel="复制诊断"
            copiedLabel="已复制"
          />
        </DisclosureRow>
      ) : null}
    </>
  );
});

/**
 * Parent usage in the existing native keyed node renderer:
 *
 * <NativeMessageContent
 *   key={nativeNode.key}             // NOT text, Date.now(), index, or status
 *   value={view}
 *   markdownLabels={existingLabels} // stable per locale
 *   renderNativePart={existingPartRenderer}
 * />
 *
 * Never maintain a second final-message component at settlement.
 * CodeBlock trims a final newline for DISPLAY; preserve the original raw string
 * in the existing diagnostic source/download. Do not call it a byte-exact export.
 */
