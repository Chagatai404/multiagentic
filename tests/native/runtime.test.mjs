import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, realpath, writeFile, rm, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { authorize, dispatch, projectLock } from '../../adapters/shared/runtime.mjs';
import { loadPlan, writablePath } from '../../skills/multiagentic-engineering/scripts/files.mjs';
const example=JSON.parse(await readFile(new URL('../../skills/multiagentic-engineering/assets/plan.example.json',import.meta.url)));
async function fixture(t) {const root=await mkdtemp(join(tmpdir(),'mae-'));t.after(()=>rm(root,{recursive:true,force:true}));await mkdir(join(root,'.plans'));const path='.plans/test.json';await writeFile(join(root,path),JSON.stringify(example));return {root,path};}
const delay = ms=>new Promise(r=>setTimeout(r,ms));

test('requires user command; dispatch persists running before work, uses concurrent bounded wave',async t=>{
 const {root,path}=await fixture(t);let calls=0, active=0, peak=0;
 await assert.rejects(dispatch(root,path,async()=>{calls++;}),/mae-approve/);assert.equal(calls,0);
 await authorize(root,path);
 const result=await dispatch(root,path,async(packet)=>{
  calls++;active++;peak=Math.max(peak,active);
  const {state}=await loadPlan(root,path);assert.equal(state.tasks[packet.task_id].status,'running');
  await delay(15);active--;return {summary:'changed own file; parent checks needed'};
 });
 assert.equal(calls,2);assert.equal(peak,2);assert.ok(result.results.every(x=>x.status==='completed'));
 const {state,view}=await loadPlan(root,path);assert.equal(state.tasks.health.usage,null);assert.deepEqual(view.ready,[]);
});
test('changed plan cannot reuse user authorization',async t=>{
 const {root,path}=await fixture(t);await authorize(root,path);const p=structuredClone(example);p.goal='changed';await writeFile(join(root,path),JSON.stringify(p));
 await assert.rejects(dispatch(root,path,async()=>assert.fail()),/stale/);
});
test('worker error blocks dependents and retains partial outcome',async t=>{
 const {root,path}=await fixture(t);await authorize(root,path);
 const r=await dispatch(root,path,async p=>{if(p.task_id==='health')throw new Error('partial edit; check failure');return {summary:'ui complete'};});
 assert.equal(r.results[0].status,'blocked');assert.equal(r.results[1].status,'completed');
 assert.equal((await loadPlan(root,path)).view.stopped,true);
 await assert.rejects(dispatch(root,path,async()=>assert.fail()),/No ready/);
});
test('cancellation reaches all workers and never marks completion',{timeout:10_000},async t=>{
 const {root,path}=await fixture(t);await authorize(root,path);const controller=new AbortController();
 let started=0,aborted=0;
 const result=await dispatch(root,path,async(p,signal)=>{
  await new Promise(resolve=>{
   signal.addEventListener('abort',()=>{aborted++;resolve();},{once:true});
   // Cancel only after both real workers have subscribed, independent of I/O speed.
   if(++started===2)controller.abort();
  });return {summary:'partial work'};
 },controller.signal);
 assert.equal(started,2);assert.equal(aborted,2);assert.equal(result.results.length,2);
 assert.ok(result.results.every(x=>x.status==='blocked'));
 const {state}=await loadPlan(root,path);
 assert.equal(state.tasks.health.status,'blocked');assert.equal(state.tasks.version.status,'blocked');
});
test('timeout blocks workers, and oversize reports fail explicitly',async t=>{
 const {root,path}=await fixture(t);const p=structuredClone(example);p.limits.worker_timeout_seconds=1;await writeFile(join(root,path),JSON.stringify(p));await authorize(root,path);
 const result=await dispatch(root,path,async(packet,signal)=>{
  if(packet.task_id==='health')return {summary:'x'.repeat(2000)};
  await new Promise(resolve=>signal.addEventListener('abort',resolve,{once:true}));return {summary:'partial'};
 });assert.ok(result.results.every(x=>x.status==='blocked'));assert.match(result.results[0].summary,/exceeds/);
});
test('project lock prevents concurrent dispatch across plans and preserves unknown locks',async t=>{
 const {root}=await fixture(t);
 await projectLock(root,async()=>{await assert.rejects(projectLock(root,()=>assert.fail()),/lock exists/);});
 await writeFile(join(root,'.plans/.mae-dispatch.lock'),'unknown outcome');
 await assert.rejects(projectLock(root,()=>assert.fail()),/lock exists/);
});
test('paths cannot escape via traversal or symlink; internal write aliases rejected',async t=>{
 const {root,path}=await fixture(t);await assert.rejects(loadPlan(root,'../escape.json'),/escapes/);
 await mkdir(join(root,'real'));await writeFile(join(root,'real/file'),'original');
 try {await symlink(join(root,'real'),join(root,'alias'),'junction');}catch(e){if(e.code==='EPERM'){t.skip('symlinks unavailable');return;}throw e;}
 await assert.rejects(writablePath(root,'alias/file'),/symlink/);
 assert.equal(await writablePath(root,'new/sub/file'),join(await realpath(root),'new/sub/file'));
 await assert.rejects(loadPlan(root,path,'../state.json'),/escapes/);
});

test('Pi cannot authorize a plan with unresolved decisions',async t=>{
 const {root,path}=await fixture(t);const p=structuredClone(example);p.open_questions=['Access policy undecided'];
 await writeFile(join(root,path),JSON.stringify(p));await assert.rejects(authorize(root,path),/Resolve open decisions/);
});
