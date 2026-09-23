import BasicCompactionEngine from '@deepseek-ai/dsh-compaction-basic';
import { BlockAssembler, createUserMessage } from '@deepseek-ai/dsh-llm';

// Only the native engine's documented summarizer hook is overridden. Selection,
// validation, tool pairing, replacement, and durable brackets remain native DSH.
export default class AsunaCompaction extends BasicCompactionEngine {
  async summarize(input, agent, signal) {
    const target = agent.session.requestHeader()?.config ?? agent.options;
    const cap = agent.options.maxTokens ?? 4096;
    const instruction = 'ASUNA_COMPACTION_V1\n压缩以上完整经历，不扮演新的社交事件，不产生新承诺或关系分数。保留当前身份、scope、人物与关系事实、事实/猜测/更正的区别、未公开的意愿、关键独白短引及来源、已公开与未送达的区别、任务ID/意图版本/授权/证据/副作用回执/未完成项。不得把执行摘要写成人物感受，不补造缺失事实。保留关键原文和来源标识，尽量简短，只输出摘要正文。';
    const options = { provider: target.provider, model: target.model,
      messages: [...input.messages, createUserMessage({ source: { kind: 'plugin', plugin: 'asuna-compaction' }, content: [{ type: 'text', text: instruction }] })],
      ...(input.tools === undefined ? {} : { tools: [...input.tools] }),
      maxTokens: cap, sessionId: agent.session.id, purpose: 'compaction', signal };
    const assembler = new BlockAssembler();
    for await (const chunk of this.ctx.llm.stream(options)) assembler.push(chunk);
    if (assembler.finish.kind === 'error' || assembler.finish.kind === 'aborted') {
      throw Object.assign(new Error(assembler.finish.failure.message), { code: assembler.finish.failure.code });
    }
    if (assembler.finish.kind !== 'stop') throw new Error('ASUNA_SUMMARY_INCOMPLETE:' + assembler.finish.kind);
    const rawOutput = assembler.blocks();
    if (rawOutput.some(b => !['text', 'reasoning'].includes(b.type))) throw new Error('ASUNA_SUMMARY_NON_TEXT');
    const summary = rawOutput.filter(b => b.type === 'text');
    if (!summary.some(b => b.text.trim())) throw new Error('ASUNA_SUMMARY_EMPTY');
    return { summary, rawOutput, llmStreamCall: true, provider: target.provider, model: target.model,
      maxTokens: cap, ...(assembler.usage === undefined ? {} : { usage: assembler.usage }) };
  }
}
