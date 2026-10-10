/** The language of the names the program gives what DSH shows as plain text: her rhythm tasks in the task page and the
 * scheduler session's title. DSH translates only its own shipped names, so these follow the language of the browser
 * that last opened the Web UI (client.js reports it, and again on a switch). The words are this package's own
 * (locale/<language>.json, `asuna.titles`); a language without a file falls back to English. The choice is kept
 * beside the worker's data so a start uses it before any browser reports. */
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';

const LOCALES = new URL('../locale/', import.meta.url);
const FILE = 'ui-language.json';

/** The words for a language id such as `zh-CN`: its base language when the package has it, else English. */
export async function languageWords(locale) {
  const base = String(locale ?? '').toLowerCase().split(/[-_]/)[0];
  for (const language of [base, 'en']) {
    if (!/^[a-z]{2,8}$/.test(language)) continue;
    try {
      const titles = JSON.parse(await readFile(new URL(language + '.json', LOCALES), 'utf8')).asuna?.titles;
      if (titles) return { language, titles };
    } catch { /* no file for this language */ }
  }
  throw new Error('ASUNA_LOCALE_MISSING: the package has no English titles');
}

/** The language last reported, or English. */
export async function savedLanguage(dataRoot) {
  try { return JSON.parse(await readFile(path.join(dataRoot, FILE), 'utf8')).language ?? 'en'; }
  catch { return 'en'; }
}

/** A browser reported its language: keep it, give the worker the words (it renames her rhythm tasks) and rename the
 * scheduler session. Returns the language used. */
export async function applyLanguage(core, locale) {
  const { language, titles } = await languageWords(locale);
  const changed = JSON.stringify(titles) !== JSON.stringify(core.uiTitles);
  core.uiTitles = titles;
  if (!changed) return { language };
  await writeFile(path.join(core.ctx.asunaFloor.dataRoot, FILE), JSON.stringify({ language }) + '\n');
  await core.ready();
  await core.worker.call('ui.titles', { titles });
  await core.schedules.retitle?.();
  return { language };
}
