import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import opencode from '../../adapters/opencode/index.mjs';

test('OpenCode registers native agent configuration without overwriting user choices',async()=>{
 const hooks=await opencode();const custom={description:'user-owned',mode:'subagent'};
 const config={agent:{'mae-worker':custom},skills:{paths:['/user/skills']},command:{mae:{template:'user choice'}}};
 await hooks.config(config);await hooks.config(config);
 assert.equal(config.agent['mae-worker'],custom);assert.equal(config.skills.paths.length,2);
 assert.equal(config.agent['mae-reviewer'].permission.edit,'deny');assert.equal(config.command.mae.template,'user choice');
 assert.ok(hooks.tool.mae_plan);assert.equal(hooks.tool.mae_dispatch,undefined);
});

test('OpenCode tool preserves SDK schema and plan execution contracts', async t => {
 const directory=await mkdtemp(join(tmpdir(),'mae-opencode-'));
 t.after(()=>rm(directory,{recursive:true,force:true}));
 await mkdir(join(directory,'.plans'));
 const example=await readFile(new URL('../../skills/multiagentic-engineering/assets/plan.example.json',import.meta.url),'utf8');
 await writeFile(join(directory,'.plans','test.json'),example);
 const {tool}=await opencode();const plan=tool.mae_plan;
 assert.equal(plan.args.path.parse('.plans/test.json'),'.plans/test.json');
 assert.equal(plan.args.path.safeParse(42).success,false);
 const view=JSON.parse(await plan.execute({path:'.plans/test.json'},{directory}));
 assert.deepEqual(view.packets.map(packet=>packet.task_id),['health','version']);
 await writeFile(join(directory,'.plans','invalid.json'),'{}');
 await assert.rejects(plan.execute({path:'.plans/invalid.json'},{directory}));
 await assert.rejects(plan.execute({path:'../escape.json'},{directory}));
});
