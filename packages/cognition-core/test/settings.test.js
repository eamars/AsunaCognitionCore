import test from 'node:test';
import assert from 'node:assert/strict';
import { Config, CognitionCore } from '../src/index.js';
import { assertSecretReferences, editSettings } from '../src/settings.js';
import { redactSecrets } from '@deepseek-ai/dsh-settings';
import { AsunaApi } from '../src/api.js';
import { Context } from '@deepseek-ai/cordis';
import LlmRuntime, { LlmAdapter } from '@deepseek-ai/dsh-llm';

test('native settings redact credentials and edits preserve secrets omitted by the page', () => {
  const original = { deployment: { mongo_uri: { $secret: 'mongo' }, channels: { qq: { token: { $secret: 'qq' } } } },
    secrets: { mongo: 'private-database-credential', qq: 'private-qq-credential' }, qqAdmission: 'explicit' };
  assertSecretReferences(original.deployment);
  const publicValue = redactSecrets(Config, original).value;
  assert.doesNotMatch(JSON.stringify(publicValue), /private-/);
  const edited = editSettings(original, [{ op: 'set', path: ['qqAdmission'], value: 'automatic' }]);
  assert.deepEqual(edited.secrets, original.secrets);
  assert.equal(original.qqAdmission, 'explicit');
  assert.throws(() => assertSecretReferences({ nested: { token: 'plaintext' } }), /USE_NATIVE_SECRET_REFERENCE/);
  assert.throws(() => editSettings(original, [{ op: 'set', path: ['__proto__', 'polluted'], value: 1 }]), /INVALID_SETTINGS_EDIT/);
});

test('failed validation leaves the current worker and native settings untouched', async () => {
  const core = new CognitionCore({}, { value: 'previous' });
  core.lifecycle.state = 'ready';
  core.worker = { call: async () => assert.fail('old worker must stay available during rejected preflight') };
  core.restart = async () => assert.fail('must not restart');
  core.validateSettings = async () => { throw new Error('INVALID_CONFIGURATION'); };
  await assert.rejects(core.applySettings({ value: 'bad' }), /INVALID_CONFIGURATION/);
  assert.equal(core.config.value, 'previous');
  assert.equal(core.applying, false);
});

test('settings activation pauses ingress and restores the previous configuration after startup failure', async () => {
  const core = new CognitionCore({}, { value: 'previous' }), calls = [];
  core.lifecycle.state = 'ready';
  core.worker = { call: async method => { calls.push(method); } };
  core.validateSettings = async () => {};
  core.restart = async () => { calls.push(core.config.value); if (core.config.value === 'proposed') throw new Error('BOOT_FAILED'); };
  await assert.rejects(core.applySettings({ value: 'proposed' }), /PREVIOUS_CONFIGURATION_RESTORED/);
  assert.deepEqual(calls, ['settings.quiesce', 'proposed', 'previous']);
  assert.equal(core.config.value, 'previous');
});

