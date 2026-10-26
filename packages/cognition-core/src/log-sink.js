/** Asuna's own log lines, kept. The Host's logger keeps a plugin's messages in memory only (a ring of the newest
 * thousand, gone at each restart), so a line such as a summary request's reasoning level or a worker restart's reason
 * reached no file. This exporter writes Asuna's lines to the Host's stderr, which the supervisor keeps in
 * `restart/host.log`: every line an Asuna package's logger writes (its name starts with `asuna`), whatever its text,
 * and any line that starts with `Asuna`. A line that does not say it is Asuna's carries its logger's name. Every other
 * plugin's lines are left as they were. */
export const PREFIX = 'Asuna';
const OWN_LOGGER = /^asuna(-|$)/;
// The Host's logger levels: error 0, info 1, warn 2, debug 3; an exporter takes every message at or below its level.
const UP_TO_WARN = 2;

/** A message's arguments as one line of text, `%s`, `%d` and `%o` filled in the way the Host's own logger does. */
export function formatted(args) {
  const rest = [...(args ?? [])];
  let head = rest.shift();
  if (head instanceof Error) head = head.stack || head.message;
  else if (typeof head !== 'string') { rest.unshift(head); head = '%o'; }
  const text = String(head).replace(/%([sdo%])/g, (match, char) => {
    if (char === '%') return '%';
    if (!rest.length) return match;
    const value = rest.shift();
    return char === 'd' ? String(Number(value)) : char === 'o' ? shown(value) : String(value);
  });
  return [text, ...rest.map(shown)].join(' ');
}

function shown(value) {
  if (value instanceof Error) return value.stack || value.message;
  if (value && typeof value === 'object') {
    try { return JSON.stringify(value); } catch { return String(value); }
  }
  return String(value);
}

/** The exporter for `ctx.logger.exporter()`: each of Asuna's lines, stamped with its time and level, through `write`. */
export function asunaLogExporter(write) {
  return {
    colors: 0,
    levels: { default: UP_TO_WARN },
    export(message) {
      const text = formatted(message.args), said = text.startsWith(PREFIX);
      if (!said && !OWN_LOGGER.test(message.name ?? '')) return;
      write(new Date(message.ts ?? Date.now()).toISOString() + ' ' + (message.type ?? 'info') + ' '
        + (said ? '' : '[' + message.name + '] ') + text + '\n');
    },
  };
}
