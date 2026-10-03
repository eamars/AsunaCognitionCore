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
  if (typeof ctx.attachments?.saveImage !== 'function')
    return { ...value, image: undefined, visual: 'unavailable:ATTACHMENT_SERVICE_MISSING' };
  try {
    const image = await ctx.attachments.saveImage({
      data: new Uint8Array(Buffer.from(inline.data, 'base64')), mediaType: inline.media_type,
      name: typeof value.ref === 'string' ? value.ref : undefined,
    });
    return { ...value, image, visual: 'attached' };
  } catch (error) {
    return { ...value, image: undefined, visual: `unavailable:${error.code || error.message || error}` };
  }
}
