import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { load, findings, describe } from '../src/private-words.js';

async function list(t, text) {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'private-words-'));
  t.after(() => fs.rm(dir, { recursive: true, force: true }));
  await fs.mkdir(path.join(dir, 'private'));
  await fs.writeFile(path.join(dir, 'private', 'personal-words.txt'), text);
  return dir;
}

test('the list is read as private_words.py reads it: comments, blank and malformed lines are not entries', async t => {
  const saved = process.env.ASUNA_PRIVATE_WORDS; delete process.env.ASUNA_PRIVATE_WORDS;
  t.after(() => { if (saved === undefined) delete process.env.ASUNA_PRIVATE_WORDS; else process.env.ASUNA_PRIVATE_WORDS = saved; });
  const dir = await list(t, '# header\n\ngroup|示例交流群|a placeholder group\nnot a category|x|y\nperson|Exampleperson|why|with a bar\naccount||empty\n');
  const entries = load(dir);
  assert.deepEqual(entries.map(entry => [entry.line, entry.category, entry.word]),
    [[3, 'group', '示例交流群'], [5, 'person', 'Exampleperson']]);
  assert.equal(load(path.join(dir, 'missing')), null);
});

test('a listed word is found by line and category, a Latin word only as a whole word, never echoed', () => {
  const entries = [{ line: 3, category: 'group', word: '示例交流群' }, { line: 5, category: 'person', word: 'Exampleperson' }];
  const found = findings('改了技能\n在示例交流群里试过\nEXAMPLEPERSON 看过；Examplepersons 不算', entries);
  assert.deepEqual(found, [{ line: 2, kind: 'listed', category: 'group', entry: 3 },
    { line: 3, kind: 'listed', category: 'person', entry: 5 }]);
  const words = describe(found);
  assert.match(words, /第 2 行有名单上的词（group 类，名单第 3 行）/);
  assert.doesNotMatch(words, /示例交流群|Exampleperson/i);
});

test('a number shaped like a QQ or group number is found; hashes, commit ids, restart ids, sizes and times are not', () => {
  const found = findings('主人私聊 qq:1234567890:dm:987654321\n群 12345678 里', []);
  assert.deepEqual(found.map(item => [item.line, item.digits]), [[1, 10], [1, 9], [2, 8]]);
  assert.doesNotMatch(describe(found), /1234567890|987654321|12345678/);
  const clean = ['sha256 c71f0ce00bec95b07744e116345e33d8cbbe08cef896382cf907bf4b51a2cd51', '短号 a3abbb47 和 5713aab7',
    'restart-20261022104708', '1870321 B，2295817B，70800 字节，1792678014629 ms', '09:13:47、10-23、v4.18.0、0.5.0',
    '1.5 秒，3.14159265，12345 只有五位'];
  for (const line of clean) assert.deepEqual(findings(line, []), [], line);
});
