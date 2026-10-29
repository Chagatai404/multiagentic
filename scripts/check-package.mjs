import assert from 'node:assert/strict';
import { readFile, readdir, stat } from 'node:fs/promises';
import { resolve, dirname, join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { inspect } from '../skills/multiagentic-engineering/scripts/core.mjs';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const read=p=>readFile(join(root,p),'utf8');
const json=async p=>JSON.parse(await read(p));
const pkg=await json('package.json');
for(const path of ['plugin.json','.claude-plugin/plugin.json','.codex-plugin/plugin.json']) {
 const manifest=await json(path); assert.equal(manifest.name,pkg.name);assert.equal(manifest.version,pkg.version);
}
assert.equal((await json('.codex-plugin/plugin.json')).skills,'./skills/');
assert.equal((await json('.claude-plugin/marketplace.json')).plugins[0].source,'./');
assert.equal((await json('.agents/plugins/marketplace.json')).plugins[0].source.path,'./');
let metadataChars=0;
for(const name of await readdir(join(root,'skills'))) {
 const body=await read(`skills/${name}/SKILL.md`);
 const front=body.match(/^---\n([\s\S]*?)\n---\n/);assert.ok(front,`${name}: frontmatter`);
 assert.match(front[1],new RegExp(`^name: ${name}$`,'m'));assert.match(front[1],/^description: .+/m);
 metadataChars+=front[1].length;assert.ok(body.length<12000,`${name}: lazy-load references`);
 for(const match of body.matchAll(/\]\(([^)]+)\)/g)) {
  if(!/^(https?:|#)/.test(match[1])) assert.ok((await stat(join(root,'skills',name,match[1]))).isFile());
 }
}
for(const path of ['skills/interview/LICENSE','skills/ste/LICENSE','skills/multiagentic-engineering/LICENSE']) assert.match(await read(path),/Permission is hereby granted/);
assert.ok(metadataChars<2000,'skill routing metadata exceeds 2,000 characters');
const plan=await json('skills/multiagentic-engineering/assets/plan.example.json');
const view=inspect(plan);
// Native runtime must never launch an agent CLI or depend on Python eng.
async function files(dir) { const out=[];for(const e of await readdir(join(root,dir),{withFileTypes:true}))out.push(...(e.isDirectory()?await files(`${dir}/${e.name}`):[`${dir}/${e.name}`]));return out; }
for(const f of [...await files('adapters'),...await files('skills/multiagentic-engineering/scripts')]) {
 assert.doesNotMatch(await read(f),/child_process|\bexecSync\b|\bspawnSync\b|\beng trigger\b/);
}
assert.ok(process.env.npm_execpath,'Run via npm run check:package');
const packed=spawnSync(process.execPath,[process.env.npm_execpath,'pack','--dry-run','--json','--ignore-scripts'],{cwd:root,encoding:'utf8'});
assert.equal(packed.status,0,packed.stderr);
const entries=JSON.parse(packed.stdout)[0].files.map(f=>f.path);
for(const f of ['plugin.json','.claude-plugin/plugin.json','.claude-plugin/marketplace.json','.codex-plugin/plugin.json','.agents/plugins/marketplace.json','adapters/pi/index.ts','adapters/opencode/index.mjs','skills/multiagentic-engineering/scripts/core.mjs','skills/interview/LICENSE','skills/ste/LICENSE','docs/NATIVE_PLUGINS.md','docs/ORCA.md','skills/multiagentic-engineering/references/orca.md'])assert.ok(entries.includes(f),`missing packed file: ${f}`);
assert.ok(!entries.some(f=>f.startsWith('src/eng/')||f.startsWith('node_modules/')));
console.log(JSON.stringify({package:pkg.name,version:pkg.version,packed_files:entries.length,skill_metadata_characters:metadataChars,example_packet_characters:view.packets.map(p=>JSON.stringify(p).length),live_hosts:'not tested'},null,2));
