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
