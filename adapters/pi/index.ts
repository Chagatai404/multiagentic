import { relative, sep } from 'node:path';
import { Type } from 'typebox';
import {
  createAgentSession, createEditTool, createWriteTool, DefaultResourceLoader,
  getAgentDir, SessionManager, SettingsManager,
  type ExtensionAPI, type ExtensionContext, type ToolDefinition,
} from '@earendil-works/pi-coding-agent';
import { loadPlan, writablePath } from '../../skills/multiagentic-engineering/scripts/files.mjs';
import { owns } from '../../skills/multiagentic-engineering/scripts/core.mjs';
import { authorize, dispatch } from '../shared/runtime.mjs';
import { workerPrompt } from '../shared/prompts.mjs';

type Packet = { task_id: string; owns: string[]; report_chars: number };

export function createOwnedTools(cwd: string, ownedPaths: string[]): ToolDefinition[] {
  return [createEditTool(cwd), createWriteTool(cwd)].map(base => ({
    name: base.name, label: base.label, description: base.description, parameters: base.parameters,
    async execute(id, params, abortSignal, onUpdate) {
      if (!params || typeof params !== 'object' || !('path' in params) || typeof params.path !== 'string') throw new Error('Missing file path');
      const target = await writablePath(cwd, params.path);
      const path = relative(cwd, target).split(sep).join('/');
      if (!owns(ownedPaths, path)) throw new Error(`Outside task ownership: ${path}`);
      // Execute the exact canonical path we checked, not SDK-specific shorthand.
      return base.execute(id, { ...params, path: target } as never, abortSignal, onUpdate);
    },
  }));
}

async function runWorker(ctx: ExtensionContext, packet: Packet, signal: AbortSignal) {
  if (!ctx.model) throw new Error('Select a Pi model before dispatch');
  const settingsManager = SettingsManager.inMemory({ compaction: { enabled: false }, retry: { enabled: false } });
  const resourceLoader = new DefaultResourceLoader({
    cwd: ctx.cwd, agentDir: getAgentDir(), settingsManager,
    noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true,
    appendSystemPrompt: [workerPrompt],
  });
  await resourceLoader.reload();
  const customTools = createOwnedTools(ctx.cwd, packet.owns);
  const { session } = await createAgentSession({
    cwd: ctx.cwd, model: ctx.model, thinkingLevel: ctx.thinkingLevel,
    settingsManager, resourceLoader, sessionManager: SessionManager.inMemory(ctx.cwd),
    tools: packet.owns.length ? ['read', 'grep', 'find', 'ls', 'edit', 'write'] : ['read', 'grep', 'find', 'ls'],
    customTools,
  });
  const abort = () => { void session.abort(); };
  signal.addEventListener('abort', abort, { once: true });
  try {
    if (signal.aborted) throw new Error('Worker cancelled');
    await session.prompt(JSON.stringify(packet));
    const last = [...session.messages].reverse().find(m => m.role === 'assistant');
    if (!last || last.stopReason === 'error' || last.stopReason === 'aborted') throw new Error('Pi worker failed or was aborted');
    return { summary: session.getLastAssistantText() ?? '', usage: session.getSessionStats() };
  } finally {
    signal.removeEventListener('abort', abort);
    session.dispose();
  }
}

export default function multiagenticEngineering(pi: ExtensionAPI) {
  pi.registerCommand('mae', {
    description: 'Co-plan independent engineering slices',
    handler: async args => {
      pi.sendUserMessage(`Use the multiagentic-engineering skill. Plan with me before implementation. ${args}`);
    },
  });
  pi.registerCommand('mae-approve', {
    description: 'Authorize a reviewed plan revision for native worker dispatch',
    handler: async (args, ctx) => {
      try {
        if (!args.trim()) throw new Error('Usage: /mae-approve .plans/name.json');
        const hash = await authorize(ctx.cwd, args.trim());
        ctx.ui.notify(`Plan authorized (${hash.slice(0, 12)}). Ask the agent to execute it.`, 'info');
      } catch (error) { ctx.ui.notify(String(error), 'error'); }
    },
  });
  pi.registerTool({
    name: 'mae_plan', label: 'Engineering plan',
    description: 'Validate a plan and return a bounded ready wave of independent task packets; no execution.',
    parameters: Type.Object({ path: Type.String() }),
    async execute(_id, { path }, _signal, _update, ctx) {
      const { view } = await loadPlan(ctx.cwd, path);
      return { content: [{ type: 'text', text: JSON.stringify(view) }], details: {} };
    },
  });
  pi.registerTool({
    name: 'mae_dispatch', label: 'Engineering workers',
    description: 'Run the next ready wave of a user-authorized plan inside Pi using fresh SDK sessions. Never spawns a CLI. Parent verifies edits and runs checks.',
    parameters: Type.Object({ path: Type.String() }),
    async execute(_id, { path }, signal, _update, ctx) {
      const result = await dispatch(ctx.cwd, path, (p: Packet, s: AbortSignal) => runWorker(ctx, p, s), signal);
      return { content: [{ type: 'text', text: JSON.stringify(result) }], details: {} };
    },
  });
}
