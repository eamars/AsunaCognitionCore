import test from 'node:test';
import assert from 'node:assert/strict';
import { asunaLogExporter, formatted } from '../src/log-sink.js';

test('Asuna lines reach the sink with their time and level; other plugins\' lines do not', () => {
  const written = [];
  const exporter = asunaLogExporter(text => written.push(text));
  const at = Date.UTC(2026, 9, 21, 1, 2, 3);
  exporter.export({ ts: at, type: 'info', args: ['Asuna compaction: summary request thinks at "high" in s'] });
  exporter.export({ ts: at, type: 'warn', args: ['Asuna: tier.fell not recorded: %s', 'timeout'] });
  exporter.export({ ts: at, type: 'info', args: ['loader: plugin ready'] });
  assert.deepEqual(written, [
    '2026-10-21T01:02:03.000Z info Asuna compaction: summary request thinks at "high" in s\n',
    '2026-10-21T01:02:03.000Z warn Asuna: tier.fell not recorded: timeout\n',
  ]);
});

test('a line an Asuna package\'s logger writes is kept whatever its text, and says whose it is', () => {
  const written = [];
  const exporter = asunaLogExporter(text => written.push(text));
  const at = Date.UTC(2026, 9, 27, 0, 0, 0);
  exporter.export({ ts: at, type: 'warn', name: 'asuna-cognition-core', args: [new Error('AutoReconnect: reset')] });
  exporter.export({ ts: at, type: 'warn', name: 'asuna-napcat-qq', args: ['Asuna: adapter line'] });
  exporter.export({ ts: at, type: 'warn', name: 'asunax', args: ['not ours'] });
  exporter.export({ ts: at, type: 'warn', name: 'loader', args: ['Error: someone else\'s'] });
  assert.equal(written.length, 2);
  assert.match(written[0], /^2026-10-27T00:00:00\.000Z warn \[asuna-cognition-core\] Error: AutoReconnect: reset/);
  assert.equal(written[1], '2026-10-27T00:00:00.000Z warn Asuna: adapter line\n');
});

test('the sink takes errors, information and warnings, not debug lines', () => {
  // The Host's logger levels: error 0, info 1, warn 2, debug 3.
  assert.equal(asunaLogExporter(() => {}).levels.default, 2);
});

test('arguments are filled in as the Host\'s logger fills them', () => {
  assert.equal(formatted(['Asuna %d of %s', 3, 'tries']), 'Asuna 3 of tries');
  assert.equal(formatted(['Asuna state', { ready: true }]), 'Asuna state {"ready":true}');
  assert.match(formatted([new Error('Asuna broke')]), /^Error: Asuna broke/);
});
