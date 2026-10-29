import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { validatePlan, inspect, emptyState, digest, owns } from '../../skills/multiagentic-engineering/scripts/core.mjs';
const example = JSON.parse(await readFile(new URL('../../skills/multiagentic-engineering/assets/plan.example.json', import.meta.url)));
const plan = () => structuredClone(example);

test('ready wave excludes consumers; only verified evidence unlocks integration', () => {
 const p=plan(), s=emptyState(p);
 assert.deepEqual(inspect(p,s).ready,['health','version']);
 for(const id of ['health','version']) s.tasks[id]={status:'completed',attempts:1,summary:'Implemented',evidence:[]};
 assert.deepEqual(inspect(p,s).ready,[]);
 for(const id of ['health','version']) Object.assign(s.tasks[id],{status:'verified',evidence:['tests pass; diff inspected']});
 const view=inspect(p,s); assert.deepEqual(view.ready,['integration']);
 assert.equal(view.packets[0].dependencies.length,2); assert.equal(view.complete,false);
});
test('reject cycles, missing deps, duplicate IDs and prototype names', () => {
 for(const mutate of [p=>p.tasks[0].depends_on=['integration'],p=>p.tasks[0].depends_on=['absent'],p=>p.tasks[1].id='health',p=>p.tasks[0].id='constructor']) {
  const p=plan();mutate(p);assert.throws(()=>validatePlan(p));
 }
});
test('reject concurrent ownership and read/write races, permit ordered overlap', () => {
 const p=plan();p.tasks[1].owns=['src/features/health/'];assert.throws(()=>validatePlan(p),/Overlapping/);
 p.tasks[1].owns=['src/ui/'];p.tasks[1].reads=['src/features/health/route.ts'];assert.throws(()=>validatePlan(p),/Overlapping/);
 p.tasks[1].depends_on=['health'];assert.doesNotThrow(()=>validatePlan(p));
});
test('case-insensitive prefixes respect segment boundaries', () => {
 assert.equal(owns(['src/API/'],'SRC/api/x.ts'),true);
 assert.equal(owns(['src/api/'],'src/apix/x.ts'),false);
 const p=plan();p.tasks[1].owns=['SRC/FEATURES/HEALTH/ROUTE.TS'];assert.throws(()=>validatePlan(p),/Overlapping/);
});
test('reject escaping, ambiguous, coordination and git paths', () => {
 for(const path of ['../a','/tmp/a','C:/a','src\\a','src//a','./src','src/*','.plans/','.git/config','.git']) {
  const p=plan();p.tasks[0].owns=[path];assert.throws(()=>validatePlan(p),path);
 }
});
test('plan changes invalidate state; object key ordering does not', () => {
 const p=plan(),s=emptyState(p);p.goal='different';assert.throws(()=>inspect(p,s),/stale/);
 assert.equal(digest({b:1,a:2}),digest({a:2,b:1}));
});
test('no verified state without evidence or verified prerequisites', () => {
 const p=plan(),s=emptyState(p);s.tasks.integration={status:'verified',attempts:1,summary:'done',evidence:[]};
 assert.throws(()=>inspect(p,s));s.tasks.integration.evidence=['claimed pass'];assert.throws(()=>inspect(p,s),/dependency/);
});
test('running and blocked stop scheduling; bounded retry requires explicit pending', () => {
 const p=plan();p.limits.max_attempts=2;const s=emptyState(p);
 for(const status of ['running','blocked']) {s.tasks.health={status,attempts:1,summary:'inspect first',evidence:[]};assert.deepEqual(inspect(p,s).ready,[]);}
 s.tasks.health.status='pending';assert.deepEqual(inspect(p,s).ready,['health','version']);
 s.tasks.health.attempts=2;assert.deepEqual(inspect(p,s).ready,['version']);
});
test('bounds cannot be enlarged silently; requirements are never truncated', () => {
 const p=plan();p.concurrency=4;assert.throws(()=>inspect(p));p.concurrency=2;
 p.tasks[0].objective='x'.repeat(7000);assert.throws(()=>inspect(p),/Packet exceeds/);
 p.tasks[0].objective='ok';p.limits.packet_chars=999;assert.throws(()=>inspect(p));
});

test('unresolved planning decisions block otherwise independent tasks', () => {
 const p=plan();p.open_questions=['Should service status be public or authenticated?'];
 const view=inspect(p);assert.equal(view.stopped,true);assert.deepEqual(view.ready,[]);assert.equal(view.complete,false);
});
