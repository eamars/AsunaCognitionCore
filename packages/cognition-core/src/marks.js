/** What Asuna writes at the head of what it puts into her conversation, so a message says whose it is (ADR-108 D3).
 *
 * DSH's adapter sends every user-role message as text and drops its `source`, so a live line, a program notice, a
 * checkpoint and the runtime context differ only by the text. A person's line has its label line, which is its mark.
 * Everything else Asuna writes into her conversation starts with one of these, written when the message is written, so the
 * session file and the Web page show what she reads. The words are program text for her: 你 is her. Bump MARKS_VERSION with
 * any change to them. */
export const MARKS_VERSION = 1;

/** The first line of a stage, repair or restore notice. */
export const PROGRAM_MARK = '〔程序〕';

/** The first line of a checkpoint's body: what it is, what its numbers mean. */
export const CHECKPOINT_MARK = '〔摘要〕下面是压缩器把这个对话较早的一段整理成的检查点：条目末尾的〔编号〕是它出自的那一行，没有编号的是压缩器的转述。';

/** A notice's text, marked as the program's: the mark is the message's own first line. */
export const marked = text => PROGRAM_MARK + '\n' + text;

// A copy of the head the model wrote into its own output (it saw the earlier checkpoint's).
const COPIED_HEAD = /^\s*〔摘要〕[^\n]*\n?/;

/** A checkpoint's summary blocks with the head first. A copy of the head at the start of the model's own text is
 * removed, so a checkpoint never carries it twice. Only the final summary is headed, never the interim one a span too
 * large for one request is summarized through (compaction.js `inSteps`). */
export function withCheckpointHead(summary) {
  const blocks = summary.map(block => ({ ...block }));
  const first = blocks.find(block => block.type === 'text' && typeof block.text === 'string');
  if (first) first.text = first.text.replace(COPIED_HEAD, '');
  return [{ type: 'text', text: CHECKPOINT_MARK + '\n' }, ...blocks];
}
