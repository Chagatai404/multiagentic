import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import extension, { createOwnedTools } from '../../adapters/pi/index.ts';

test('real Pi SDK imports and extension registers separate user approval and model tools',()=>{
 const commands=new Map(),tools=new Map();
 extension({registerCommand:(name,command)=>commands.set(name,command),registerTool:tool=>tools.set(tool.name,tool)});
 assert.deepEqual([...commands.keys()],['mae','mae-approve']);
 assert.deepEqual([...tools.keys()],['mae_plan','mae_dispatch']);
 assert.equal(tools.has('mae_approve'),false);
});
test('real Pi write/edit tools enforce assigned paths before mutation',async t=>{
 const root=await mkdtemp(join(tmpdir(),'mae-tools-'));t.after(()=>rm(root,{recursive:true,force:true}));
 const tools=createOwnedTools(root,['src/owned.txt']);const write=tools.find(x=>x.name==='write');const edit=tools.find(x=>x.name==='edit');
 await write.execute('1',{path:'src/owned.txt',content:'before'},undefined,undefined,{});
 assert.equal(await readFile(join(root,'src/owned.txt'),'utf8'),'before');
 await edit.execute('2',{path:'src/owned.txt',edits:[{oldText:'before',newText:'after'}]},undefined,undefined,{});
 assert.equal(await readFile(join(root,'src/owned.txt'),'utf8'),'after');
 await assert.rejects(write.execute('3',{path:'src/sibling.txt',content:'bad'},undefined,undefined,{}),/Outside task ownership/);
 await assert.rejects(readFile(join(root,'src/sibling.txt')),/ENOENT/);
});
