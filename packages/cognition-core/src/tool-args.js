/** Her tool calls whose arguments do not fit the tool's schema are refused in her words, before DSH's own validation
 * would answer `invalid arguments: missing required property "op"` in English with no fix (ADR-076 R3). The guard in
 * index.js asks here with the session's own tool definition (role_tool_specs): one clause per violation — a missing
 * field with the field's own description beside it, a wrong value with what it may be — and what to do next. The
 * check is DSH's (`validateArgs`), so the two layers never disagree on what is valid; only the words are the house's.
 * The code stays out of her words (ADR-060). */
import { validateArgs } from '@deepseek-ai/dsh-tools';

const TYPES = {
  'a string': '一段文字', 'a number': '数字', 'a finite JSON number': '数字', 'an integer': '整数', 'a boolean': 'true 或 false',
  'an object': '一个对象（{字段: 值}）', 'an array': '一个列表', 'a lossless JSON value': '能写成 JSON 的值',
  'a lossless JSON object': '一个对象（{字段: 值}）', 'a dense lossless JSON array': '一个列表',
};
const HEAD = 40;

/** The first clause of a field's description, as the tool lists it, to say what the missing field is for. */
function described(spec, field) {
  const text = spec?.parameters?.[field]?.description;
  if (typeof text !== 'string' || !text.trim()) return '';
  const head = text.split(/[。；;\n]/)[0].trim();
  return head ? `（${head.length > HEAD ? head.slice(0, HEAD) + '…' : head}）` : '';
}

/** One of DSH's violation lines, in her words. */
export function describeViolation(violation, spec) {
  let m = /^missing required property "(.+)"$/.exec(violation);
  if (m) return `缺 ${m[1]}${described(spec, m[1])}`;
  m = /^"(.+)" must be one of (\[.*\])$/.exec(violation);
  if (m) {
    let values;
    try { values = JSON.parse(m[2]); } catch { values = undefined; }
    return `${m[1]} 只能是 ${Array.isArray(values) ? values.map(String).join('、') : m[2]} 之一`;
  }
  m = /^"(.+)" must be (an? .+)$/.exec(violation);
  if (m) return `${m[1]} 要是${TYPES[m[2]] ?? m[2]}`;
  return violation;
}

/** The refusal for a call whose arguments fail `spec`'s parameter schema, or undefined when they pass. DSH's own line
 * (`ToolArgsError`'s message, `invalid arguments: …`) stays verbatim at the end: she quotes tool errors literally and
 * must not take the translation for the program's words (her condition, 2026-10-19). */
export function argsRefusal(name, spec, args) {
  const violations = validateArgs(spec?.parameters ?? {}, args === undefined ? {} : args);
  if (!violations.length) return undefined;
  return `${name} 的参数不对：${violations.map(v => describeViolation(v, spec)).join('；')}。照 ${name} 的说明改好再调用一次。`
    + `（原话：invalid arguments: ${violations.join('; ')}）`;
}
