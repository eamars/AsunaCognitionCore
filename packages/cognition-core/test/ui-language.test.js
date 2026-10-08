import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { applyLanguage, languageWords, savedLanguage } from '../src/ui-language.js';

test('names follow a supported language; anything else is English', async () => {
  assert.equal((await languageWords('zh')).titles.presence, '心跳');
  assert.equal((await languageWords('zh-CN')).language, 'zh');
  assert.equal((await languageWords('en-US')).titles.presence, 'Heartbeat');
  for (const other of ['fr', '', undefined, '../en', 'x'.repeat(40)]) assert.equal((await languageWords(other)).language, 'en');
  for (const language of ['en', 'zh']) {
    const { titles } = await languageWords(language);
    assert.deepEqual(Object.keys(titles).sort(), ['presence', 'schedules', 'self_development', 'self_development_night', 'settlement']);
  }
});

test('a reported language is kept for the next start and handed to the worker once', async () => {
  const dataRoot = await mkdtemp(path.join(os.tmpdir(), 'asuna-ui-language-'));
  const calls = [], retitled = [];
  const core = { ctx: { asunaFloor: { dataRoot } }, ready: async () => {},
    worker: { call: async (method, args) => calls.push([method, args.titles.presence]) },
    schedules: { retitle: async () => retitled.push(core.uiTitles.schedules) } };
  assert.equal(await savedLanguage(dataRoot), 'en');
  assert.deepEqual(await applyLanguage(core, 'zh-TW'), { language: 'zh' });
  await applyLanguage(core, 'zh');
  assert.equal(await savedLanguage(dataRoot), 'zh');
  assert.deepEqual(calls, [['ui.titles', '心跳']]);
  assert.deepEqual(retitled, ['Asuna 定时提醒']);
  await applyLanguage(core, 'de');
  assert.deepEqual(calls.at(-1), ['ui.titles', 'Heartbeat']);
});

test('every remote method takes plain named parameters, as DSH\'s gateway requires', async () => {
  // Regression: uiLanguage({ locale }) was refused at runtime (gateway/signature-invalid) and the language never arrived.
  const { AsunaApi } = await import('../src/api.js');
  const source = (await import('node:fs')).readFileSync(new URL('../src/api.js', import.meta.url), 'utf8');
  const names = JSON.parse(source.match(/for \(const name of (\[[^\]]+\])\)/)[1].replaceAll("'", '"'));
  assert.ok(names.includes('uiLanguage'));
  for (const name of names) {
    const params = AsunaApi.prototype[name].toString().match(/^[^(]*\(([^)]*)\)/)[1];
    assert.ok(params.split(',').every(p => /^\s*[A-Za-z_$][\w$]*\s*$|^\s*$/.test(p)), name + '(' + params + ')');
  }
});
