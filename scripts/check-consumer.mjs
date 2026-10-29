import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
assert.ok(process.env.npm_execpath, 'Run via npm run check:consumer');
const tempRoot = resolve(process.env.MAE_CHECK_TMP ?? tmpdir());
const stage = await mkdtemp(join(tempRoot, 'mae-consumer-'));
function npm(args, cwd) {
  const result = spawnSync(process.execPath, [process.env.npm_execpath, ...args], {
    cwd, encoding: 'utf8', timeout: 180_000,
  });
  assert.equal(result.status, 0, `${args.join(' ')}: ${result.error ?? result.stderr}\n${result.stdout}`);
  return result.stdout;
}
try {
  const archive = JSON.parse(npm(['pack', '--json', '--ignore-scripts', '--pack-destination', stage], root))[0];
  await writeFile(join(stage, 'package.json'), JSON.stringify({ private: true, type: 'module' }));
  npm(['install', '--omit=dev', '--ignore-scripts', '--no-fund', join(stage, archive.filename)], stage);
  const lock = JSON.parse(await readFile(join(stage, 'package-lock.json'), 'utf8'));
  assert.deepEqual(Object.keys(lock.packages).sort(), ['', 'node_modules/multiagentic-engineering', 'node_modules/zod']);
  assert.equal(lock.packages['node_modules/zod'].version, '4.6.7');
  const audit = JSON.parse(npm(['audit', '--omit=dev', '--json'], stage));
  assert.equal(audit.metadata.vulnerabilities.total, 0);
  // Resolve from the independent consumer, where development SDKs are absent.
  await writeFile(join(stage, 'smoke.mjs'), `
import assert from 'node:assert/strict';
import plugin from 'multiagentic-engineering';
const hooks = await plugin();
const config = {};
await hooks.config(config);
assert.equal(config.agent['mae-worker'].mode, 'subagent');
assert.equal(hooks.tool.mae_plan.args.path.parse('.plans/test.json'), '.plans/test.json');
assert.equal(hooks.tool.mae_plan.args.path.safeParse(7).success, false);
`);
  const smoke = spawnSync(process.execPath, [join(stage, 'smoke.mjs')], { cwd: stage, encoding: 'utf8', timeout: 30_000 });
  assert.equal(smoke.status, 0, `${smoke.error ?? smoke.stderr}`);
  console.log(JSON.stringify({ node: process.version, production_packages: Object.keys(lock.packages).filter(Boolean), vulnerabilities: audit.metadata.vulnerabilities.total, import_and_registration: 'passed' }, null, 2));
} finally {
  assert.equal(dirname(stage), tempRoot);
  await rm(stage, { recursive: true, force: true });
}
