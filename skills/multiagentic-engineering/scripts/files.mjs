import { lstat, readFile, realpath, stat } from 'node:fs/promises';
import { dirname, isAbsolute, relative, resolve, sep } from 'node:path';
import { emptyState, inspect } from './core.mjs';

export async function contained(root, file, allowMissing = false) {
  const base = await realpath(root);
  const target = resolve(base, file);
  const within = p => { const rel = relative(base, p); return rel !== '..' && !rel.startsWith(`..${sep}`) && !isAbsolute(rel); };
  if (!within(target)) throw new Error('Path escapes project');
  let current = target;
  while (true) {
    try {
      const actual = await realpath(current);
      if (!within(actual)) throw new Error('Symlink escapes project');
      break;
    } catch (error) {
      if (error.code !== 'ENOENT' || !allowMissing || current === base) throw error;
      current = dirname(current);
    }
  }
  return target;
}

export async function readJSON(file) {
  if ((await stat(file)).size > 512000) throw new Error('Plan/state exceeds 512 KB');
  return JSON.parse(await readFile(file, 'utf8'));
}

export async function writablePath(root, file) {
  const target = await contained(root, file, true);
  const base = await realpath(root);
  let current = target;
  while (current !== base) {
    try { if ((await lstat(current)).isSymbolicLink()) throw new Error('Worker writes through symlinks are not supported'); }
    catch (error) { if (error.code !== 'ENOENT') throw error; }
    current = dirname(current);
  }
  return target;
}

export async function loadPlan(root, path, statePath) {
  const file = await contained(root, path);
  const plan = await readJSON(file);
  const stateFile = await contained(root, statePath ?? `${file.replace(/\.json$/, '')}.state.json`, true);
  let state;
  try { state = await readJSON(stateFile); }
  catch (error) { if (error.code !== 'ENOENT') throw error; state = emptyState(plan); }
  return { plan, state, file, stateFile, view: inspect(plan, state) };
}
