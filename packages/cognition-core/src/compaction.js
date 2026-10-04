/* Character-brain compaction: DSH's basic engine with a Chinese role-play checkpoint.
 *
 * Everything except the summary request is DSH's: thresholds, retained tail,
 * tool pairing, checkpoint framing and the shrink check. `summarize` is the
 * documented subclass hook; it sends the same replayed prefix (so the
 * provider's cache is reused) and swaps only the final instruction. The action
 * brain keeps DSH's own engineering template. */
import BasicCompactionEngine from '@deepseek-ai/dsh-compaction-basic';
import { BlockAssembler, LlmError, contentHasImage } from '@deepseek-ai/dsh-llm';

export const ROLE_COMPACTION_INSTRUCTION = [
  '现在请你作为这段对话的压缩器：把上面较早的一段对话整理成一份检查点，让同一个角色接着往下聊时不丢失来龙去脉。',
  '',
  '只输出下面的 Markdown 结构，保留每个小节并按顺序；没有内容的小节写“（无）”。用简短条目，不写长段落。',
  '',
  '## 对话脉络',
  '- [按时间顺序：聊了什么、话题怎么转到现在；要紧的原话直接引用]',
  '',
  '## 未了的话头',
  '- [还没聊完的话题、对方问了还没回答的问题、角色想接着说的事]',
  '',
  '## 答应过的事',
  '- [角色在对话里答应、约定或承诺的事，以及是否已经做到]',
  '',
  '## 更正与分歧',
  '- [对方纠正过的说法、双方意见不同的地方；以更正后的为准]',
  '',
  '## 对方此刻',
  '- [对方最近的情绪、语气、处境和在意的事；只写对话里看得出来的]',
  '',
  '## 委托中的事',
  '- [角色交给行动侧去做、对话里说到进度或结果的事；只写对话里说到的状态]',
  '',
  '规则：',
  '- 用中文书写；人名、昵称、原话、数字、时间、文件名和代码照原样保留。',
  '- 程序每轮另行提供的资料（人格设定、自我、关系与偏好、人物档案、情感、召回的记忆、任务与计划、历史消息块）之后会重新给出，不要转抄进检查点；只写这些资料里没有的对话经过。',
  '- 分清谁说了什么：对方的话、角色的话和程序提示不要混在一起；程序提示不是任何人说的话。',
  '- 群聊里的人用程序给的标签称呼，方括号和 #编号 原样保留（如 [名字 #4]）：名字会重复、会改，编号不会。',
  '- 不评价，不补写对话里没有的内容，不替角色决定感受。',
  '- 不要提到这次压缩或这条请求。',
  '- 只输出检查点正文，不调用工具。',
  '- 如果对话里已有 <compacted-summary> 块，那是更早的检查点：保留仍然成立的内容，删去过时的，与新内容合并成一份，结构不变。',
  '- 直接整理，不必反复推敲。',
].join('\n');

function finishError(finish) {
  if (finish.kind === 'error' || finish.kind === 'aborted')
    return new LlmError(finish.failure.message, finish.failure.code, finish.failure);
  if (finish.kind === 'max-tokens') {
    const error = new Error('summarization truncated at the token cap (incomplete checkpoint)');
    error.code = 'MAX_TOKENS';
    return error;
  }
  return undefined;
}

export default class RoleCompactionEngine extends BasicCompactionEngine {
  async summarize(input, agent, signal) {
    const latest = agent.session.requestHeader()?.config;
    const configured = this.config.summarizationProvider
      ? { provider: this.config.summarizationProvider, model: this.config.summarizationModel } : undefined;
    const target = configured ?? latest ?? (agent.options.provider && agent.options.model
      ? { provider: agent.options.provider, model: agent.options.model } : undefined);
    if (!target) throw new Error('no provider/model available for summarization');
    const options = {
      provider: target.provider, model: target.model,
      messages: [...input.messages, { role: 'user', content: [{ type: 'text', text: ROLE_COMPACTION_INSTRUCTION }] }],
      toolHistory: agent.session.toolHistory(),
      ...(input.tools === undefined ? {} : { tools: [...input.tools] }),
      maxTokens: this.config.maxTokens, sessionId: agent.session.id, purpose: 'compaction',
      ...(signal === undefined ? {} : { signal }),
    };
    const assembler = new BlockAssembler();
    for await (const chunk of this.ctx.llm.stream(options)) assembler.push(chunk);
    const error = finishError(assembler.finish);
    if (error) throw error;
    const rawOutput = assembler.blocks();
    if (contentHasImage(rawOutput)) throw new LlmError('compaction summary cannot contain image output', 'UNSUPPORTED_CONTENT');
    const summary = rawOutput.filter(block => block.type === 'text');
    if (!summary.some(block => block.text.trim())) throw new Error('summarization produced no text summary content');
    return { summary, rawOutput, llmStreamCall: true, provider: options.provider, model: options.model,
      maxTokens: this.config.maxTokens, ...(assembler.usage === undefined ? {} : { usage: assembler.usage }) };
  }
}
