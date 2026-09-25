import { defineTool } from '@deepseek-ai/dsh-tools';

export const name = 'asuna-controlled-tools';
// DSH 只放行这里声明过的 ctx 服务。attachImage 要读 ctx.attachments，所以 'attachments'
// 必须一起列进来：只写 ['tools'] 时，真宿主上每一次 read_image 都如实抛
// `cannot get property "attachments" without inject`（2026-09-25 实测）——字节已经拉回来了，
// 图却没进模型请求。离线自检用假 ctx 装载本插件，照不出这道运行时闸门，故自检补一条断言。
export const inject = ['tools', 'attachments'];

// 看图（read_image）的最后一棒。宿主已经按元数据把字节真实拉回来并 base64 编码；
// 这里按 DSH 原生附件机制存成 durable attachment（ctx.attachments.saveImage），
// 再投影成 ImageBlock —— 这一步之后图片才是这一轮模型请求里的视觉输入。
//
// 附件服务没挂载或保存失败时如实标 unavailable 并说明原因：不把一坨 base64 当文本
// 塞进上下文，也不留下「看起来看过」的假象。会话日志里存的是 attachment 引用，
// 不是 base64（persist-before-event，与 DSH 自己的图片路径同一套规则）。
export function imageBlock(value) {
  const attachment = value ? value.image : undefined;
  if (!attachment || typeof attachment !== 'object' || typeof attachment.attachmentId !== 'string') return undefined;
  return { type: 'image', attachment };
}

export function asunaRender(_args, value) {
  const image = imageBlock(value);
  if (image === undefined) return [{ type: 'text', text: JSON.stringify(value) }];
  // 图片本体走 image 块；元数据走文本块，base64 早已不在 value 里。
  const meta = { ...value, image: undefined };
  return [image, { type: 'text', text: JSON.stringify(meta) }];
}

export async function attachImage(ctx, value) {
  const inline = value ? value.image : undefined;
  if (!inline || typeof inline.data !== 'string' || typeof inline.media_type !== 'string') return value;
  const store = ctx ? ctx.attachments : undefined;
  if (!store || typeof store.saveImage !== 'function') {
    return { ...value, image: undefined, visual: 'unavailable:ATTACHMENT_SERVICE_MISSING' };
  }
  try {
    const ref = await store.saveImage({
      data: new Uint8Array(Buffer.from(inline.data, 'base64')),
      mediaType: inline.media_type,
      name: typeof value.ref === 'string' ? value.ref : undefined,
    });
    return { ...value, image: ref, visual: 'attached' };
  } catch (error) {
    const code = (error && (error.code || error.message)) || String(error);
    return { ...value, image: undefined, visual: `unavailable:${code}` };
  }
}

export function apply(ctx, config) {
  for (const spec of config.tools) {
    ctx.tools.register(defineTool({
      name: spec.name, description: spec.description, parameters: spec.parameters,
      output: { schema: { type: 'json' }, render: asunaRender },
      async execute(args, exec) {
        if (!exec.agent) throw new Error('NO_OWNING_AGENT');
        const response = await fetch(config.url + '/tool', {
          method: 'POST', signal: exec.signal,
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + process.env.ASUNA_BROKER_TOKEN },
          body: JSON.stringify({ session: exec.agent.session.id, call_id: exec.callId, tool: spec.name, args }),
        });
        const value = await response.json();
        if (!response.ok) throw new Error(JSON.stringify(value));
        return await attachImage(ctx, value);
      },
    }));
  }
}
