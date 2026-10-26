// ADR-098: the shared case file (tests/fixtures/path_placeholders.json) under node --test, so the plugin's matcher
// and the worker's (pytest tests/test_local_roots.py) cannot drift; and the request rewrite block by block.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { compile, contract, rewriteRequest, rootsAtTheModel, Roots } from '../src/roots.js';

const DOC = JSON.parse(readFileSync(new URL('../../../tests/fixtures/path_placeholders.json', import.meta.url), 'utf8'));

test('every case of the shared file contracts here as it does in the worker', () => {
  const tables = Object.fromEntries(Object.entries(DOC.tables).map(([host, wire]) => [host, compile(wire)]));
  assert.deepEqual(Object.keys(tables).sort(), Object.keys(DOC.hosts).sort());
  for (const item of DOC.cases) {
    const once = contract(tables[item.host], item.input).text;
    assert.equal(once, item.contracted, item.host + ': ' + item.note);
    assert.equal(contract(tables[item.host], once).text, once, 'contracting twice is contracting once: ' + item.note);
  }
});

test('a request is rewritten in its text, reasoning, system text and earlier tool calls; images and ids stay', () => {
  const table = compile(DOC.tables.windows);
  const root = DOC.hosts.windows.workspace;
  const image = { type: 'image', attachment: { attachmentId: 'sha256:abc', name: 'x.png' } };
  const options = Object.freeze({ provider: 'p', model: 'm', sessionId: 's', system: 'at ' + root,
    messages: Object.freeze([
      Object.freeze({ id: 'm1', role: 'system', source: { kind: 'system-prompt' }, content: [{ type: 'text', text: 'src ' + root + '\\src' }] }),
      Object.freeze({ id: 'm2', role: 'assistant', source: { kind: 'model' }, content: [
        { type: 'reasoning', text: 'look in ' + root }, { type: 'tool-call', id: 'c1', name: 'delegate',
          arguments: JSON.stringify({ brief: 'read ' + root + '\\README.md' }) }] }),
      Object.freeze({ id: 'm3', role: 'user', source: { kind: 'user' }, content: [image, { type: 'text', text: 'no path here' }] }),
    ]) });
  const { request, count } = rewriteRequest(table, options);
  assert.equal(count, 4);
  const text = JSON.stringify(request);
  assert.ok(!text.toLowerCase().includes(root.toLowerCase().replaceAll('\\', '\\\\')) && !text.includes(root));
  assert.equal(request.system, 'at ${ASUNA_WORKSPACE}');
  assert.equal(JSON.parse(request.messages[1].content[1].arguments).brief, 'read ${ASUNA_WORKSPACE}\\README.md');
  assert.equal(request.messages[2], options.messages[2], 'a message without a root is the same object');
  assert.equal(request.messages[2].content[0], image);
  assert.equal(request.messages[0].id, 'm1');
  // The same history gives the same request (cache prefixes stay stable), and a request without roots is untouched.
  assert.deepEqual(rewriteRequest(table, options).request.messages, request.messages);
  assert.equal(rewriteRequest(table, request).request, request);
});

async function* chunks(...items) { for (const item of items) yield item; }
async function drain(stream) { const out = []; for await (const item of stream) out.push(item); return out; }

test('a session is hers by its preset as it stands now: switched in it is rewritten, switched out it passes', async () => {
  const root = DOC.hosts.windows.workspace;
  const now = { 'in': 'asuna', out: 'asuna-action' };           // what DSH's agentPreset projection says now
  const made = { 'in': 'asuna-action', out: 'asuna' };          // what each session's header was made with
  let listener;
  const sent = [];
  const ctx = {
    on: (name, fn) => { if (name === 'llm/stream') listener = fn; },
    agents: { get: id => ({ session: { id, header: { agentPreset: made[id] } } }) },
    sessionProjections: { stateOf: (session, key) => key === 'agentPreset' ? now[session.id] : undefined },
    llm: { stream: request => { sent.push(request); return chunks('rewritten'); } },
    logger: { warn() {} },
  };
  const core = { ctx, worker: null, laneOf: agent => ({ asuna: 'character', 'asuna-action': 'action' })[agent.session.header.agentPreset] };
  core.roots = new Roots(core);
  core.roots.take(DOC.tables.windows);
  rootsAtTheModel(core);
  const request = id => ({ sessionId: id, messages: [{ id: 'm', role: 'user', content: [{ type: 'text', text: 'at ' + root }] }] });
  assert.deepEqual(await drain(listener(request('in'), () => chunks('raw'))), ['rewritten'],
    'switched to her preset: rewritten');
  assert.equal(sent[0].messages[0].content[0].text, 'at ${ASUNA_WORKSPACE}');
  assert.deepEqual(await drain(listener(request('out'), () => chunks('raw'))), ['raw'],
    'switched to the action preset: passes as it is');
  clearTimeout(core.roots.timer);
});

test("DSH's DeepSeek adapter still names an image's copy through the fs service's host-path mapping", () => {
  // roots.js contracts that one mapping inside her requests; an upgrade that resolves image paths another way would
  // bring the real root back into her image notes without anything else failing.
  const adapter = readFileSync(new URL(import.meta.resolve('@deepseek-ai/dsh-llm-deepseek')), 'utf8');
  assert.match(adapter, /resolveImageAccess:[^\n]*processPathFromHostPath/);
});
