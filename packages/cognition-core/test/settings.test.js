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


test('applied settings reach a conversation already open: it is reopened between its turns, never during one', async () => {
  const live = new Map(), resumed = [];
  const open = (id, options) => {
    const agent = { id, options, session: { header: {}, snapshotEvents: () => [], surface: { nodes: [] } } };
    const handle = { agent, dispose: async () => { live.delete(id); core.disposed(agent); } };   // as DSH emits it
    live.set(id, agent);
    return handle;
  };
  const ctx = { get: () => undefined,
    agents: { get: id => live.get(id),
      resume: async ({ resumeSessionId, agentOptions }) => { resumed.push(agentOptions.model); return open(resumeSessionId, agentOptions); } },
    sessionPersistence: { stat: async () => true },
    agentPresets: { mount: async () => {} },
    workspaceRegistry: { create: async () => ({ attachSession: async () => {} }), unarchiveSession: async () => {} } };
  const route = model => ({ persona: 'p', routes: { character: { provider: 'x', model, reasoningEffort: 'high', maxTokens: 10 } } });
  let core;
  core = new CognitionCore(ctx, route('old'));
  core.personas.set('p', { preset: 'role' });
  core.channelOf = () => undefined;
  const stage = { session_id: 's1', lane: 'character', binding: { scene_id: 'x', cwd: '.' } };
  const first = await core.ensureAgent(stage);
  core.lifecycle.state = 'ready';
  core.worker = { call: async () => {} };
  core.validateSettings = async () => {};
  core.restart = async () => {};
  await core.applySettings(route('new'));
  core.state('s1').current = { token: 't' };                  // her turn is running: it keeps its agent
  assert.equal(await core.ensureAgent(stage), first);
  core.state('s1').current = null;
  const turn = core.state('s1');                              // the turn holds its state before the agent reopens
  const reopened = await core.ensureAgent(stage);
  assert.equal(core.states.get('s1'), turn, 'closing the old agent kept the stage state of the turn reopening it');
  assert.notEqual(reopened, first);
  assert.deepEqual(resumed, ['old', 'new']);
  assert.equal(core.retired.has(first), true, 'the closed agent cannot clear the stage of the turn that reopened it');
  assert.equal(await core.ensureAgent(stage), reopened, 'reopened once, not at every turn');
});

test('a conversation that handed work to the action brain is reopened too once that work is done, and its finished action session with it', async () => {
  const live = new Map();
  const open = (id, options, parent) => {
    const agent = { id, options, session: { id, header: parent ? { parentSession: parent } : {}, snapshotEvents: () => [], surface: { nodes: [] } } };
    const handle = { agent, dispose: async () => { live.delete(id); core.disposed(agent); } };
    live.set(id, agent);
    return handle;
  };
  const ctx = { get: () => undefined,
    agents: { get: id => live.get(id), resume: async ({ resumeSessionId, agentOptions, parentAgent }) => open(resumeSessionId, agentOptions, parentAgent?.id) },
    sessionPersistence: { stat: async () => true },
    agentPresets: { mount: async () => {} },
    workspaceRegistry: { create: async () => ({ attachSession: async () => {} }), unarchiveSession: async () => {} } };
  const route = model => ({ persona: 'p', routes: { character: { provider: 'x', model }, action: { provider: 'x', model } } });
  let core;
  core = new CognitionCore(ctx, route('old'));
  core.personas.set('p', { preset: 'role' });
  core.channelOf = () => undefined;
  const stage = { session_id: 'role', lane: 'character', binding: { scene_id: 'x', cwd: '.' } };
  const first = await core.ensureAgent(stage);
  const action = { session_id: 'act', lane: 'executor', binding: { scene_id: 'x', cwd: '.' } };
  const child = await core.ensureAgent(action, first);
  core.lifecycle.state = 'ready';
  core.worker = { call: async () => {} };
  core.validateSettings = async () => {};
  core.restart = async () => {};
  await core.applySettings(route('new'));
  core.state('act').current = { token: 'a' };                 // the task is still running: the conversation waits
  assert.equal(await core.ensureAgent(stage), first);
  core.state('act').current = null;                           // the task is done; its session is still open
  const reopened = await core.ensureAgent(stage);
  assert.notEqual(reopened, first, 'a finished action session no longer keeps the conversation from reopening');
  assert.equal(core.retired.has(child), true, 'the finished action session closed with it');
  assert.equal(core.handles.has('act'), false);
});

test('a task handed to the action brain keeps its conversation from reopening, never from a due turn-end compaction', async () => {
  const live = new Map();
  const open = (id, parent) => {
    const agent = { id, session: { id, header: parent ? { parentSession: parent } : {}, snapshotEvents: () => [], surface: { nodes: [] } } };
    live.set(id, agent);
    return { agent, dispose: async () => live.delete(id) };
  };
  const ctx = { get: () => undefined,
    agents: { get: id => live.get(id), resume: async ({ resumeSessionId, parentAgent }) => open(resumeSessionId, parentAgent?.id) },
    sessionPersistence: { stat: async () => true },
    agentPresets: { mount: async () => {} },
    workspaceRegistry: { create: async () => ({ attachSession: async () => {} }), unarchiveSession: async () => {} } };
  const core = new CognitionCore(ctx, { persona: 'p', routes: { character: { provider: 'x', model: 'm' }, action: { provider: 'x', model: 'm' } } });
  core.personas.set('p', { preset: 'role' });
  core.channelOf = () => undefined;
  const role = await core.ensureAgent({ session_id: 'role', lane: 'character', binding: { scene_id: 'x', cwd: '.' } });
  await core.ensureAgent({ session_id: 'act', lane: 'executor', binding: { scene_id: 'x', cwd: '.' } }, role);
  let idle;
  core.turnEnds = { run: async options => { idle = options.idle; } };
  await core.turnEnd(role);
  core.state('act').current = { token: 'task' };              // her task still runs in its own session
  assert.equal(core.idle('role'), false, 'not reopened while the task runs');
  assert.equal(idle(), true, 'but its due compaction may run: the task does not touch this conversation');
  core.state('role').queue.push({ token: 'next' });          // a stage of the conversation itself waits
  assert.equal(idle(), false);
});

// A save is checked against the routes of the draft, never against the ones already in force.
const listing = (...ids) => ({ llm: { listModels: async provider => provider === 'local' ? ids.map(id => ({ id })) : [],
  resolveModelInfo: async () => ({ reasoning: { efforts: [{ id: 'high' }], defaultEffort: 'high' }, inputModalities: [] }) },
  get: () => undefined });
const chosen = { provider: 'local', model: 'm', reasoningEffort: 'high', maxTokens: 1024 };
const saved = (config, routes) => {
  const core = new CognitionCore(listing('m'), config);
  core.personas = new Set(['p']);
  // Past the route check the proposed worker would start; reaching it is passing the check.
  core.workerPython = async () => { throw new Error('PAST_THE_CHECK'); };
  return { core, check: () => core.validateSettings({ persona: 'p', routes, deployment: {} }, 'path') };
};

test('a draft that sets the first routes is accepted although the routes in force are none', async () => {
  await assert.rejects(saved({ routes: {}, deployment: {} }, { character: chosen, action: chosen }).check(), /PAST_THE_CHECK/);
});

test('a draft route whose model the provider does not list is refused although the routes in force are valid', async () => {
  const inForce = { routes: { character: chosen, action: chosen }, deployment: {} };
  await assert.rejects(saved(inForce, { character: { ...chosen, model: 'gone' }, action: chosen }).check(), /MODEL_NOT_CONFIGURED: character/);
  await assert.rejects(saved(inForce, { character: chosen }).check(), /MODEL_NOT_CONFIGURED: action/, 'a draft with a lane missing is not covered by the routes in force');
  await assert.rejects(saved(inForce, undefined).check(), /MODEL_NOT_CONFIGURED: character/, 'nor is a draft with no routes at all');
});

test('without a draft the routes in force are the ones checked (the worker\'s own start)', async () => {
  const { core } = saved({ routes: { character: chosen, action: chosen }, deployment: {} });
  assert.deepEqual(Object.keys(await core.resolveRoutes()), ['character', 'action']);
  await assert.rejects(saved({ routes: {}, deployment: {} }).core.resolveRoutes(), /MODEL_NOT_CONFIGURED: character/);
});
