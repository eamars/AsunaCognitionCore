/** Save images before exposing their durable native attachment references. */
export function imageBlock(value) {
  const attachment = value?.image;
  if (typeof attachment?.attachmentId !== 'string') return undefined;
  return { type: 'image', attachment };
}

export function asunaRender(_args, value) {
  const image = imageBlock(value);
  if (!image) return [{ type: 'text', text: JSON.stringify(value) }];
  return [image, { type: 'text', text: JSON.stringify({ ...value, image: undefined }) }];
}

export async function attachImage(ctx, value) {
  const inline = value?.image;
  if (typeof inline?.data !== 'string' || typeof inline.media_type !== 'string') return value;
  // A result is JSON: the inline bytes are dropped, never set to undefined, so the reason reaches her.
  const { image: _bytes, ...rest } = value;
  const unseen = reason => ({ ...rest, visual: `unavailable:${reason}`,
    note: `图拉到了，但没能成为这回合能看的附件（${reason}）：这回合看不到它，用同一个 ref 重试也一样；`
      + '要么不看这张图继续，要么照实说没看到（行动里写进报告）。' });
  if (typeof ctx.attachments?.saveImage !== 'function') return unseen('ATTACHMENT_SERVICE_MISSING');
  try {
    const image = await ctx.attachments.saveImage({
      data: new Uint8Array(Buffer.from(inline.data, 'base64')), mediaType: inline.media_type,
      name: typeof value.ref === 'string' ? value.ref : undefined,
    });
    return { ...value, image, visual: 'attached' };
  } catch (error) {
    return unseen(error.code || error.message || String(error));
  }
}
