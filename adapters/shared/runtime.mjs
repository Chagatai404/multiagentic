import { mkdir, open, rename, unlink, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { contained, loadPlan } from '../../skills/multiagentic-engineering/scripts/files.mjs';

export async function saveState(file, state) {
  const temp = `${file}.${randomUUID()}.tmp`;
  try {
    await writeFile(temp, `${JSON.stringify(state, null, 2)}\n`, { flag: 'wx', mode: 0o600 });
    await rename(temp, file);
  } finally { await unlink(temp).catch(e => { if (e.code !== 'ENOENT') throw e; }); }
}

export async function projectLock(root, action) {
  const directory = await contained(root, '.plans', true);
  await mkdir(directory, { recursive: true });
  const lockPath = join(directory, '.mae-dispatch.lock');
  let lock;
  try { lock = await open(lockPath, 'wx', 0o600); }
  catch (error) {
    if (error.code === 'EEXIST') throw new Error('Dispatch lock exists. Inspect active/unknown workers before manually removing it.');
    throw error;
  }
  try {
    await lock.writeFile(JSON.stringify({ pid: process.pid, started: new Date().toISOString() }));
    return await action();
  } finally { await lock.close(); await unlink(lockPath); }
}

// Called only from the user's Pi slash command, never registered as a model tool.
export async function authorize(root, path) {
  return projectLock(root, async () => {
    const { state, stateFile, view } = await loadPlan(root, path);
    if (view.stopped) throw new Error('Resolve open decisions or reconcile running/blocked work before authorizing');
    state.authorization = { source: 'user-command', plan_digest: view.plan_digest, at: new Date().toISOString() };
    await mkdir(dirname(stateFile), { recursive: true });
    await saveState(stateFile, state);
    return view.plan_digest;
  });
}

export async function dispatch(root, path, runWorker, signal) {
  return projectLock(root, async () => {
    const { plan, state, stateFile, view } = await loadPlan(root, path);
    if (state.authorization?.source !== 'user-command' || state.authorization.plan_digest !== view.plan_digest) {
      throw new Error('User must review this plan and run /mae-approve PATH first');
    }
    if (!view.packets.length) throw new Error('No ready wave; inspect blocked work, verification, or completion');
    if (signal?.aborted) throw new Error('Dispatch cancelled');
    for (const p of view.packets) state.tasks[p.task_id] = {
      status: 'running', attempts: (state.tasks[p.task_id]?.attempts ?? 0) + 1,
      summary: '', evidence: [],
    };
    await saveState(stateFile, state); // Durable before any model work.
    const results = await Promise.all(view.packets.map(async p => {
      const controller = new AbortController();
      const abort = () => controller.abort();
      signal?.addEventListener('abort', abort, { once: true });
      if (signal?.aborted) abort();
      const timer = setTimeout(abort, plan.limits.worker_timeout_seconds * 1000);
      try {
        if (controller.signal.aborted) throw new Error('Worker cancelled');
        const output = await runWorker(p, controller.signal);
        if (controller.signal.aborted) throw new Error('Worker cancelled or timed out; inspect partial edits');
        if (typeof output.summary !== 'string' || !output.summary.trim()) throw new Error('Worker returned no handoff');
        if (output.summary.length > plan.limits.report_chars) throw new Error('Worker report exceeds limit; inspect partial edits and request a compact handoff');
        return { id: p.task_id, status: 'completed', summary: output.summary, usage: output.usage ?? null };
      } catch (error) {
        return { id: p.task_id, status: 'blocked', summary: String(error.message ?? error).slice(0, plan.limits.report_chars), usage: null };
      } finally { clearTimeout(timer); signal?.removeEventListener('abort', abort); }
    }));
    for (const { id, ...result } of results) Object.assign(state.tasks[id], result);
    await saveState(stateFile, state);
    return { plan_digest: view.plan_digest, results, next: 'Inspect edits and checks; record verified evidence before dependent dispatch.' };
  });
}
