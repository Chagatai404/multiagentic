// @ts-check
import { fileURLToPath } from 'node:url';
import { tool } from '@opencode-ai/plugin';
import { loadPlan } from '../../skills/multiagentic-engineering/scripts/files.mjs';
import { workerPrompt, reviewerPrompt } from '../shared/prompts.mjs';

// Native OpenCode Task/subagent tools own delegation and permissions.
/** @type {import('@opencode-ai/plugin').Plugin} */
const MultiagenticEngineering = async () => {
  return {
    config: async legacyConfig => {
      // Plugin 1.19's hook still types Config through SDK v1. These fields are
      // the documented runtime config, checked against the SDK v2 schema.
      const config = /** @type {import('@opencode-ai/sdk/v2').Config} */ (legacyConfig);
      const skillRoot = fileURLToPath(new URL('../../skills/', import.meta.url));
      config.skills ??= {};
      config.skills.paths = [...new Set([...(config.skills.paths ?? []), skillRoot])];
      config.agent ??= {};
      config.agent['mae-worker'] ??= { description: 'Implement one independent engineering packet', mode: 'subagent', prompt: workerPrompt, permission: { task: 'deny' } };
      config.agent['mae-reviewer'] ??= { description: 'Review integrated changes and check evidence', mode: 'subagent', prompt: reviewerPrompt, permission: { edit: 'deny', bash: 'deny', task: 'deny' } };
      config.command ??= {};
      config.command.mae ??= { description: 'Plan and coordinate independent native agents', template: 'Use the multiagentic-engineering skill. Plan with me before implementation. $ARGUMENTS' };
    },
    tool: {
      mae_plan: tool({
        description: 'Validate an engineering plan and return the next independent native-worker packets. Does not execute workers or approve a plan.',
        args: { path: tool.schema.string().describe('Project-relative plan JSON path') },
        async execute({ path }, context) {
          const { view } = await loadPlan(context.directory, path);
          return JSON.stringify(view);
        },
      }),
    },
  };
};
export default MultiagenticEngineering;
