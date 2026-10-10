/** An Asuna agent preset row: DSH's own preset row (@deepseek-ai/dsh-agent-preset) with its name and description
 * declared per language. DSH shows a declared preset name exactly as written, so the row registers the words of the
 * language the program's names follow (ui-language.js, the browser that last opened the Web UI) through DSH's preset
 * registry at start; a language without words uses English. A switch of language shows at the next start. */
import { Service } from '@deepseek-ai/cordis';
import { EntryGroup } from '@deepseek-ai/cordis-plugin-loader';
import z from '@deepseek-ai/schemastery';
import { savedLanguage } from './ui-language.js';

export default class AsunaPreset {
  ctx;
  config;
  static inject = ['agentPresets', 'asunaFloor'];
  /** Child expressions stay as written until their own plugins activate, as in DSH's preset row. */
  static [EntryGroup.key] = true;
  static Config = z.object({
    id: z.string().required(),
    names: z.dict(z.string()).required(),
    descriptions: z.dict(z.string()),
    order: z.number(),
    plugins: z.array(z.any()).required(),
  });

  constructor(ctx, config) { this.ctx = ctx; this.config = config; }

  async *[Service.init]() {
    const language = await savedLanguage(this.ctx.asunaFloor.dataRoot);
    const { names, descriptions, ...definition } = this.config;
    const description = words(descriptions, language);
    yield await this.ctx.agentPresets.register({ ...definition, name: words(names, language),
      ...(description ? { description } : {}) });
  }
}

/** The words for a language, else English, else the first given. */
export function words(table, language) {
  if (!table) return undefined;
  return table[language] ?? table.en ?? Object.values(table)[0];
}
