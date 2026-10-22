/** The deployment's "keep out" list (src/asuna/private_words.py keeps it; this reads it the same way) and what it
 * finds in a text that will become public: words on the list, and digit runs shaped like a QQ or group number.
 * A finding names the line and the category, never the word or the number. */
import fs from 'node:fs';
import path from 'node:path';

const CATEGORIES = new Set(['person', 'group', 'account', 'site', 'host', 'email', 'other']);   // private_words.CATEGORIES

/** The list's path: ASUNA_PRIVATE_WORDS, otherwise <data>/private/personal-words.txt (as private_words.path()). */
export function listPath(dataRoot) {
  return process.env.ASUNA_PRIVATE_WORDS || path.join(dataRoot, 'private', 'personal-words.txt');
}

/** [{line, category, word}] of the well-formed entries, or null when the deployment has no list. */
export function load(dataRoot) {
  let text;
  try { text = fs.readFileSync(listPath(dataRoot), 'utf8'); } catch { return null; }
  const entries = [];
  text.split(/\r?\n/).forEach((raw, index) => {
    const line = raw.trim();
    if (!line || line.startsWith('#')) return;
    const parts = line.split('|');
    if (parts.length < 3) return;
    const category = parts[0].trim(), word = parts[1].trim();
    if (CATEGORIES.has(category) && word) entries.push({ line: index + 1, category, word });
  });
  return entries;
}

const latin = word => /^[\x00-\x7f]*$/.test(word);
const escape = word => word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/** A Latin word matches as a whole word, ignoring case; other text matches where it appears (private_words.pattern). */
function pattern(word) {
  return latin(word) ? new RegExp(`(?<![A-Za-z0-9_])${escape(word)}(?![A-Za-z0-9_])`, 'i') : new RegExp(escape(word));
}

// A QQ number or group number is 5–11 digits; 7–11 standing alone are flagged. Longer runs (restart ids, epoch
// milliseconds), runs inside a hex token (hashes, short commit ids) and runs followed by a unit (byte counts, times)
// are not numbers of anyone.
const DIGITS = /(?<![0-9A-Za-z.])(\d{7,11})(?![0-9A-Za-z.])(?!\s*(?:B|KB|KiB|MB|MiB|GB|bytes?|字节|ms|秒|s\b|%))/g;

/** What a text that will be public carries from the list or in number shape: [{line, kind, category?, entry?, digits?}]. */
export function findings(text, entries) {
  const found = [];
  String(text ?? '').split(/\r?\n/).forEach((line, index) => {
    for (const entry of entries ?? []) {
      if (pattern(entry.word).test(line)) found.push({ line: index + 1, kind: 'listed', category: entry.category, entry: entry.line });
    }
    for (const match of line.matchAll(DIGITS)) found.push({ line: index + 1, kind: 'number', digits: match[1].length });
  });
  return found;
}

/** Her words for what was found: which line of the text, which category and list line, or how many digits. */
export function describe(found) {
  return found.map(item => item.kind === 'listed'
    ? `第 ${item.line} 行有名单上的词（${item.category} 类，名单第 ${item.entry} 行）`
    : `第 ${item.line} 行有一串 ${item.digits} 位数字，形状像 QQ 号或群号`).join('；');
}
