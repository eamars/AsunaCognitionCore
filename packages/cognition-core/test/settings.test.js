import test from 'node:test';
import assert from 'node:assert/strict';
import { Config, CognitionCore } from '../src/index.js';
import { assertSecretReferences, editSettings, secretReferences } from '../src/settings.js';
import { redactSecrets } from '@deepseek-ai/dsh-settings';
import { AsunaApi } from '../src/api.js';
import { Context } from '@deepseek-ai/cordis';
import LlmRuntime, { LlmAdapter } from '@deepseek-ai/dsh-llm';

test('settings carry credential references only; Core resolves their values from the credential store', async () => {
  const original = { deployment: { mongo_uri: { $secret: 'ASUNA_MONGO_URI' }, channels: { qq: { token: { $secret: 'ASUNA_CHANNELS_QQ_TOKEN' } } } },
    channelAdmission: 'explicit' };
  assertSecretReferences(original.deployment);
  assert.deepEqual(secretReferences(original.deployment), ['ASUNA_MONGO_URI', 'ASUNA_CHANNELS_QQ_TOKEN']);
  assert.equal(Object.hasOwn(Config.dict, 'secrets'), false, 'no setting holds a secret value');
  const edited = editSettings(original, [{ op: 'set', path: ['channelAdmission'], value: 'automatic' }]);
  assert.deepEqual(edited.deployment, original.deployment);
  assert.equal(original.channelAdmission, 'explicit');
  // A value under any secret-like key is refused, and so is a reference the store could never hold.
  for (const value of [{ nested: { token: 'plaintext' } }, { bot_token: 'plaintext' }, { apiKey: 'plaintext' }])
    assert.throws(() => assertSecretReferences(value), /USE_NATIVE_SECRET_REFERENCE/);
  assert.throws(() => assertSecretReferences({ token: { $secret: 'channels/qq/token' } }), /INVALID_CREDENTIAL_REFERENCE/);
  assert.throws(() => editSettings(original, [{ op: 'set', path: ['__proto__', 'polluted'], value: 1 }]), /INVALID_SETTINGS_EDIT/);
  const stored = { ASUNA_MONGO_URI: 'private-database-credential' };
  const core = new CognitionCore({ get: name => name === 'credentials' ? {
    resolve: async ref => stored[ref] ? { value: stored[ref], source: 'file' } : undefined } : undefined }, original);
  assert.deepEqual(await core.credentialValues(original.deployment), stored, 'a reference with no value is left for the worker to name');
  assert.doesNotMatch(JSON.stringify(redactSecrets(Config, original).value), /private-/);
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

