import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { once } from 'node:events';
import { createServer } from 'node:http';
import { createRequire } from 'node:module';
import { z } from 'zod';

// Exercise the actual SDK dependency copies, including nested installations.
const pluginRequire = createRequire(import.meta.resolve('@opencode-ai/plugin'));
const effectRequire = createRequire(pluginRequire.resolve('effect'));
const toml = effectRequire('toml');
const piRequire = createRequire(import.meta.resolve('@earendil-works/pi-coding-agent'));
const { Agent, Pool, fetch, request } = piRequire('undici');

async function serverFor(t, body = 'sdk response') {
  const server = createServer((_request, response) => response.end(body));
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  t.after(() => new Promise(resolve => {
    server.closeAllConnections();
    server.close(resolve);
  }));
  return `http://127.0.0.1:${server.address().port}/`;
}

for (const kind of ['array', 'set']) {
  test(`Zod rejects oversized ${kind} before validating its elements`, () => {
    let visits = 0;
    const element = z.preprocess(value => { visits++; return value; }, z.string());
    const schema = (kind === 'array' ? z.array(element) : z.set(element)).max(1);
    const input = kind === 'array' ? Array(64).fill(7) : new Set(Array.from({ length: 64 }, (_, i) => i));
    const result = schema.safeParse(input);
    assert.equal(result.success, false);
    assert.equal(result.error.issues.length, 1);
    assert.equal(result.error.issues[0].code, 'too_big');
    assert.equal(visits, 0);
    assert.deepEqual(schema.parse(kind === 'array' ? ['valid'] : new Set(['valid'])), kind === 'array' ? ['valid'] : new Set(['valid']));
    assert.equal(schema.safeParse(kind === 'array' ? [7] : new Set([7])).success, false);
  });
}

test('TOML retains structured settings and rejects oversized integer encodings', () => {
  const settings = toml.parse('name = "sdk"\nenabled = true\n[limits]\nworkers = 2\n[[tasks]]\nid = "first"\n');
  assert.equal(settings.name, 'sdk');
  assert.equal(settings.enabled, true);
  assert.equal(settings.limits.workers, 2);
  assert.equal(settings.tasks[0].id, 'first');
  for (const literal of ['9'.repeat(256), `0x${'f'.repeat(256)}`, `0b${'1'.repeat(256)}`]) {
    assert.throws(() => toml.parse(`value = ${literal}\n`), /64-bit/);
  }
  assert.throws(() => toml.parse('value = [\n'), /./);
});

test('Undici Agent preserves the custom TLS verifier at each origin pool boundary', async t => {
  const url = await serverFor(t);
  const verifyPeer = () => new Error('test verifier');
  let forwarded;
  const agent = new Agent({
    tls: { checkServerIdentity: verifyPeer },
    factory(origin, options) {
      forwarded = options.tls?.checkServerIdentity;
      return new Pool(origin, options);
    },
  });
  t.after(() => agent.destroy());
  const response = await request(url, { dispatcher: agent });
  assert.equal(await response.body.text(), 'sdk response');
  assert.equal(forwarded, verifyPeer);
});

test('Undici verifies uppercase and mixed-case integrity tokens against the received body', async t => {
  const url = await serverFor(t);
  const agent = new Agent();
  t.after(() => agent.destroy());
  const hash = text => createHash('sha256').update(text).digest('base64');
  for (const algorithm of ['SHA256', 'Sha256', 'sha256']) {
    const response = await fetch(url, { dispatcher: agent, integrity: `${algorithm}-${hash('sdk response')}` });
    assert.equal(await response.text(), 'sdk response');
    await assert.rejects(fetch(url, { dispatcher: agent, integrity: `${algorithm}-${hash('tampered')}` }), TypeError);
  }
});
