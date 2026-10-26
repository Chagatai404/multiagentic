# Routing (E3)

Decision record: [ADR-003](ADR-003.md). Routes are explicit operator configuration in
`.engineering/project.yaml` or a `--user-config` file. Without `routing`, selection
is unchanged.

```yaml
provider: codex
role_models:
  reviewer: gpt-5.4            # fallback when no route matches
routing:
  - label: strict-review       # risky work gets the strongest reviewer
    when: {risks: [medium, high], roles: [reviewer]}
    model: gpt-5.4
  - label: cheap-small         # small work uses a smaller model for every role
    when: {complexities: [small]}
    model: gpt-5.4-mini
  - label: claude-complex      # whole complex tasks go to another provider
    when: {complexities: [complex]}
    provider: claude
```

Model names above are placeholders; use names your installed CLI accepts.

| Selection | Order |
|---|---|
| Model (per role call) | `--model` / node `model` → first matching model route → `role_models` → provider default |
| Provider (per task) | `--provider` / node / plan `provider` → first matching provider route → project `provider` |

- Model routes use the classification at the moment of each call; if changed paths
  escalate risk, later roles pick the matching route. Events: `model_routed`,
  `route_skipped` (provider lacks model selection).
- Provider routes use the initial classification only and cannot name roles. Plans
  store the chosen `effective_provider` per node at creation. Event:
  `provider_routed` for `eng run`.
- `eng plan preview` shows each node's provider, role models and route labels.
- Hook- and MCP-submitted tasks keep their existing provider selection.

Compare routes with `eng usage` / `eng plan usage`: `groups` are keyed by selected
provider and model, with outcome counts and native usage coverage. Selected models
are not proof of the model that actually ran; missing usage stays unknown.
