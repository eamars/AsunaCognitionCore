// DSH 0.2.2 services finish starting in an async init (Service.init) that ctx.plugin runs; a test that constructs one
// directly, to pass config accessors as the Host does, runs it here, as DSH's own test harnesses do.
import { Service } from '@deepseek-ai/cordis';

export async function start(service) {
  await service[Service.init]?.();
  return service;
}
