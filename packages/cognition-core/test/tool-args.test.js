import test from 'node:test';
import assert from 'node:assert/strict';
import { argsRefusal, describeViolation } from '../src/tool-args.js';

// A tool definition as role_tools.session_specs hands it to the plugin (the author-facing parameter map).
const SPEC = { name: 'feel', description: '记一笔心情', parameters: {
  op: { type: 'string', description: '操作；record 记一笔，close 了结', required: true, enum: ['record', 'close', 'void'] },
  open: { type: 'boolean', description: '这一笔是不是还挂着' },
  parts: { type: 'array', items: { type: 'object', additionalProperties: false, properties: { text: { type: 'string', required: true } } } },
} };

test('a call that fits its schema is not refused', () => {
  assert.equal(argsRefusal('feel', SPEC, { op: 'record', open: true }), undefined);
});

test('a missing field is named with the field\'s own description, and the fix follows', () => {
  const text = argsRefusal('feel', SPEC, {});
  assert.match(text, /^feel 的参数不对：缺 op（操作）/);
  // DSH's own line stays verbatim at the end (her condition): what she quotes is what the Host said.
  assert.match(text, /照 feel 的说明改好再调用一次。（原话：invalid arguments: missing required property "op"）$/);
  assert.doesNotMatch(text, /INVALID_ARGS/);
});

test('a wrong value says what it may be, in her words', () => {
  const text = argsRefusal('feel', SPEC, { op: 'drop', open: 'yes' });
  assert.match(text, /op 只能是 record、close、void 之一/);
  assert.match(text, /open 要是true 或 false/);
});

test('a nested violation keeps its path and an unknown line passes through unchanged', () => {
  const text = argsRefusal('feel', SPEC, { op: 'record', parts: [{}] });
  assert.match(text, /缺 parts\[0\]\.text/);
  assert.equal(describeViolation('something DSH may say one day', SPEC), 'something DSH may say one day');
});

test('no arguments at all reads as the missing required fields', () => {
  assert.match(argsRefusal('feel', SPEC, undefined), /缺 op/);
});

// ADR-108 D4b: what the guard and DSH's own validation see is the DECLARED schema (tool_schema.py), which passes every
// shape the worker repairs and refuses only what it cannot. These cases are the shapes of tool_schema.REQUIRED_FILLED,
// JSON_FIELDS and the dropped enums, under DSH's real defineTool and validateArgs; `execute` must receive the call as
// she wrote it, because the worker repairs the copy it checks.
import { defineTool } from '@deepseek-ai/dsh-tools';

const DECLARED = { name: 'write_document', description: '写文档', parameters: {
  doc: { type: 'string', description: '文档；不写时按 section 找' },                 // required in the strict schema, not here
  from: { type: 'string', description: '它从哪来（只能是：主人定的、别人说的）' },        // its enum is in the description
  parts: { type: 'json', description: '一个列表，每条一个对象' },
  text: { type: 'string', required: true, description: '便条' },                       // the program cannot infer this one
  n: { type: 'integer', description: '数' },
} };

function run(args) {
  const seen = [];
  const tool = defineTool({ name: DECLARED.name, description: DECLARED.description, parameters: DECLARED.parameters,
    output: { schema: { type: 'json' }, render: () => [] }, execute: async received => { seen.push(received); return {}; } });
  return { tool, seen, call: () => tool.execute(args, {}) };
}

for (const [name, args] of [
  ['a field the program fills in, absent', { text: 'x' }],
  ['parts written as a string holding a list', { text: 'x', parts: '[{"text":"好"}]' }],
  ['parts as a list with a key the strict schema does not declare', { text: 'x', parts: [{ text: '好', quote: '3' }] }],
  ['a value outside any list, because no field declares an enum', { text: 'x', from: '随便写的' }],
  ['a key nobody declared (the root is open)', { text: 'x', surprise: 1 }],
]) {
  test('the declared schema passes ' + name + ', and execute receives it unchanged', async () => {
    const { call, seen } = run(args);
    assert.equal(argsRefusal('write_document', DECLARED, args), undefined, 'the guard lets it through');
    await call();
    assert.deepEqual(seen, [args]);
  });
}

for (const [name, args, violation] of [
  ['a field the program cannot infer, absent', {}, /missing required property "text"/],
  ['a wrong type', { text: 'x', n: '3' }, /"n" must be an integer/],
  ['a list where text is a string', { text: ['x'] }, /"text" must be a string/],
]) {
  test('the declared schema still refuses ' + name + ', by the guard in her words and by DSH', async () => {
    const { call, seen } = run(args);
    assert.match(argsRefusal('write_document', DECLARED, args) ?? '', /的参数不对/);
    await assert.rejects(call(), error => violation.test(String(error.message ?? error)));
    assert.deepEqual(seen, [], 'the tool never ran');
  });
}
