import { pathToFileURL } from 'node:url';
import { loadPlan } from './files.mjs';

export async function main(args, root = process.cwd()) {
  const [operation, file, taskOrState, stateFile] = args;
  if (!file || !['inspect', 'packet'].includes(operation)) throw new Error('Usage: plan.mjs inspect PLAN [STATE] | packet PLAN TASK [STATE]');
  const { view } = await loadPlan(root, file, operation === 'packet' ? stateFile : taskOrState);
  if (operation === 'inspect') return view;
  const result = view.packets.find(p => p.task_id === taskOrState);
  if (!result) throw new Error('Task is not in the next ready wave');
  return result;
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try { console.log(JSON.stringify(await main(process.argv.slice(2)), null, 2)); }
  catch (error) { console.error(error.message); process.exitCode = 1; }
}
