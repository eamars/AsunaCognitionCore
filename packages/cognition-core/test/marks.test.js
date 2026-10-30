// ADR-108 D3 and A11: what Asuna writes into her conversation says whose it is, and her requests carry no deployment detail.
import test from 'node:test';
import assert from 'node:assert/strict';
import { Context } from '@deepseek-ai/cordis';
import { createScope, scopeOf } from '@deepseek-ai/dsh-scope';
import SystemPrompt, { renderContextSections, renderContextSnapshot } from '@deepseek-ai/dsh-system-prompt';
import { CognitionCore } from '../src/index.js';
import { withoutWorkingDirectory } from '../src/contexts.js';
import { CHECKPOINT_MARK, PROGRAM_MARK, marked, withCheckpointHead } from '../src/marks.js';

const notice = stage => CognitionCore.prototype.message.call({}, stage, undefined).content[0].text;

test('a notice on the character lane starts with the program\'s mark and a line break; the action brain\'s does not', () => {
  const stage = lane => ({ lane, phase: 'TURN', token: 't', text: '{"event":{}}' });
  assert.equal(notice(stage('character')), PROGRAM_MARK + '\n{"event":{}}');
  assert.equal(notice({ ...stage('character'), phase: 'REPAIR', text: '你刚才没有写出要说的话' }), PROGRAM_MARK + '\n你刚才没有写出要说的话',
    'a repair notice is the program\'s too');
  assert.equal(notice(stage('executor')), '{"event":{}}', 'the action brain\'s notices are not hers to read');
  assert.equal(marked('x'), '〔程序〕\nx');
});

test('a checkpoint\'s summary gets its head once, and a copy of it in the model\'s output is removed', () => {
  const body = '## 对话脉络\n- 聊了周末';
  const headed = withCheckpointHead([{ type: 'text', text: body }]);
  assert.deepEqual(headed.map(block => block.text), [CHECKPOINT_MARK + '\n', body]);
  const copied = withCheckpointHead([{ type: 'text', text: CHECKPOINT_MARK + '\n' + body }]);
  assert.deepEqual(copied.map(block => block.text), [CHECKPOINT_MARK + '\n', body], 'never twice');
  assert.deepEqual(withCheckpointHead([{ type: 'text', text: '  \n〔摘要〕随便写的一行\n' + body }]).map(block => block.text),
    [CHECKPOINT_MARK + '\n', body], 'whatever the model wrote on that line');
  assert.equal(withCheckpointHead([{ type: 'text', text: body }])[1].text, body);
  assert.deepEqual(withCheckpointHead([]).map(block => block.text), [CHECKPOINT_MARK + '\n'], 'an empty summary is still headed');
  const original = [{ type: 'text', text: CHECKPOINT_MARK + '\n' + body }];
  withCheckpointHead(original);
  assert.equal(original[0].text, CHECKPOINT_MARK + '\n' + body, 'the model\'s blocks are not changed in place');
});

// DSH registers the working directory as a required context, which suppression keeps; a context of the same name
// registered through the agent's scope shadows it for that scope (DSH's own scoped-context spec).
async function mintScope(ctx, name) {
  let scope;
  await ctx.plugin(Object.assign(inner => { scope = createScope(inner, { name }); }, { inject: ['systemPrompt'] }));
  return scope;
}
async function snapshot(ctx, scope) {
  const key = scopeOf(scope.ctx);
  return renderContextSnapshot(ctx.systemPrompt.refreshContext(await ctx.systemPrompt.assemble({ scope: key }), { scope: key }));
}

test('her requests carry no working directory although DSH keeps it as a required context; the action brain\'s do', async t => {
  const ctx = new Context();
  t.after(() => ctx.fiber.dispose());
  await ctx.plugin(SystemPrompt, {});
  const prompt = ctx.systemPrompt;
  prompt.context({ name: 'working-directory:current', order: prompt.getContextOrder('WORKING_DIRECTORY'), required: true,
    interpolate: false, text: 'Current working directory: "/somewhere/on/this/machine".' });
  prompt.context({ name: 'sandbox:policy', order: prompt.getContextOrder('SANDBOX_POLICY'), text: 'Sandbox: workspace-write.' });
  const lanes = {};
  for (const lane of ['character', 'executor']) {
    const scope = await mintScope(ctx, lane);
    scope.ctx.systemPrompt.suppressRuntimeContext();          // as the plugin does in every lane (index.js)
    withoutWorkingDirectory(scope.ctx.systemPrompt, lane);
    lanes[lane] = await snapshot(ctx, scope);
  }
  assert.equal(lanes.character, '', 'nothing of the deployment reaches her request');
  assert.match(lanes.executor, /Current working directory: "\/somewhere\/on\/this\/machine"\./);
  assert.doesNotMatch(lanes.executor, /Sandbox/, 'the optional contexts stay suppressed in every lane');
  const bare = await mintScope(ctx, 'unsuppressed-control');
  assert.match(await snapshot(ctx, bare), /Current working directory/, 'without the blank the required context does arrive');
  assert.deepEqual(renderContextSections(await ctx.systemPrompt.assemble()).map(section => section.name),
    ['working-directory:current', 'sandbox:policy'], 'the global registrations are untouched');
});
