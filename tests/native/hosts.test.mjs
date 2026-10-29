import test from 'node:test';
import assert from 'node:assert/strict';
import opencode from '../../adapters/opencode/index.mjs';

test('OpenCode registers native agent configuration without overwriting user choices',async()=>{
 const hooks=await opencode();const custom={description:'user-owned',mode:'subagent'};
 const config={agent:{'mae-worker':custom},skills:{paths:['/user/skills']},command:{mae:{template:'user choice'}}};
 await hooks.config(config);await hooks.config(config);
 assert.equal(config.agent['mae-worker'],custom);assert.equal(config.skills.paths.length,2);
 assert.equal(config.agent['mae-reviewer'].permission.edit,'deny');assert.equal(config.command.mae.template,'user choice');
 assert.ok(hooks.tool.mae_plan);assert.equal(hooks.tool.mae_dispatch,undefined);
});
