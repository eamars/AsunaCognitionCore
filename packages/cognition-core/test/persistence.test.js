import test from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { ASUNA_EVENTS } from '../src/persistence.js';

test('every Asuna event the plugin appends to a session is written ignorable', () => {
  // DSH refuses to read a session log holding an event type it does not know unless the writer marked it ignorable
  // (persistence.js marks the ones listed): one missing type makes every session it lands in unreadable.
  const dir = new URL('../src/', import.meta.url);
  const appended = new Set();
  for (const name of readdirSync(dir).filter(file => file.endsWith('.js')))
    for (const [, type] of readFileSync(new URL(name, dir), 'utf8').matchAll(/append\(\s*'(asuna\/[a-z-]+)'/g)) appended.add(type);
  assert.ok(appended.size >= 3, 'found the appends: ' + [...appended]);
  for (const type of appended) assert.ok(ASUNA_EVENTS.has(type), type + ' is appended but not marked ignorable');
});
