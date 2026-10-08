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

test('an Asuna preset registers its name and description in the saved language, else English', async () => {
  const { default: AsunaPreset } = await import('../src/preset.js');
  const { Service } = await import('@deepseek-ai/cordis');
  const dataRoot = await mkdtemp(path.join(os.tmpdir(), 'asuna-preset-'));
  const register = async language => {
    if (language) await (await import('node:fs/promises')).writeFile(path.join(dataRoot, 'ui-language.json'), JSON.stringify({ language }));
    const registered = [];
    const ctx = { asunaFloor: { dataRoot }, agentPresets: { register: async definition => { registered.push(definition); return () => {}; } } };
    const preset = new AsunaPreset(ctx, { id: 'asuna-action', plugins: [],
      names: { en: 'Action brain', zh: '行动脑' }, descriptions: { en: 'Does the work' } });
    await preset[Service.init]().next();
    return registered[0];
  };
  assert.deepEqual(await register(), { id: 'asuna-action', plugins: [], name: 'Action brain', description: 'Does the work' });
  const zh = await register('zh');
  assert.equal(zh.name, '行动脑');
  assert.equal(zh.description, 'Does the work', 'a description without Chinese words stays English');
  assert.equal((await register('fr')).name, 'Action brain');
});

test('every Asuna preset row names itself in each shipped language', async () => {
  const { readFileSync } = await import('node:fs');
  const yaml = (await import('js-yaml')).default;
  const files = ['../cordis.patch.yml', '../../personas/xiaoman/cordis.patch.yml', '../../personas/kyoyama-kazusa/cordis.patch.yml',
    '../../personas/ichinose-asuna/cordis.patch.yml'];
  for (const file of files) {
    const text = readFileSync(new URL(file, import.meta.url), 'utf8').replaceAll('!!js ', '');   // DSH's expression tag
    const rows = yaml.load(text).flatMap(item => item.insert ?? []);
    assert.ok(!rows.some(row => row.name === '@deepseek-ai/dsh-agent-preset'), file + ' declares a preset without per-language words');
    for (const row of rows.filter(row => row.name === '@asuna/cognition-core/preset')) {
      assert.deepEqual(Object.keys(row.config.names).sort(), ['en', 'zh'], row.config.id);
      if (row.config.descriptions) assert.deepEqual(Object.keys(row.config.descriptions).sort(), ['en', 'zh'], row.config.id);
    }
  }
});

test('the core components listed on the plugin page have a title and description in each shipped language', async () => {
  const { readFileSync } = await import('node:fs');
  for (const name of ['persistence', 'floor', 'preset']) for (const language of ['en', 'zh']) {
    const file = new URL(import.meta.resolve('@asuna/cognition-core/' + name + '/locale/' + language + '.json'));
    const { meta } = JSON.parse(readFileSync(file, 'utf8'));
    assert.ok(meta.title?.trim() && meta.description?.trim(), name + ' ' + language);
  }
});
