# Studio: editors, code round-trip, publishing and promotion

Studio edits agents, teams and workflows in a form, on a canvas or in code. Configs live in AgentOS `/components`,
so the runtime stays the source of truth: numbered config versions, mutable drafts, immutable published versions,
one current. Studio composes only what the instance registered in its `Registry(...)`, referenced by name, so a
config never contains code.

![Studio component lifecycle: draft with autosave, validate, test run, publish with gates and overrides, promote to another instance](images/studio-component-lifecycle.svg)

## Code

| Where | Owns |
|---|---|
| `agnostic-spec` | typed `AgentConfig` / `TeamConfig` / `WorkflowConfig` (`agnostic_spec.v3_1`, agno's `to_dict()` shape, `extra="allow"`), the workflow step tree, form field metadata, `iter_refs`, rules, the form's JSON Schema |
| `agnostic-cel` | workflow CEL: parser, per-context type checker with Router exhaustiveness, evaluator; stdlib only |
| `agnostic-codegen` | config → Python (`generate`, ruff, span maps, gutter marks); Python → config (`parse_source`, libcst); form edits on existing code (`transform`) |
| `studio` module | `…/studio/registry`, `…/studio/components` and their configs, `publish-check`, `diff`, `validate`, `codegen`, `parse`, `transform`, `workflows/validate`, `cel/evaluate`, `step-stats`, `step-runs`, `canvas-layout`, `promotions`, `test-runs`; org-wide `/studio/schema/{kind}`, `/studio/templates`, `/studio/cel/check`, `/studio/cel/contexts`; `studio_*` tables; `StudioFacade`, the `PublishHold` port |
| `@agnostic/studio` | draft document (`useDraftDocument`), schema-driven form, code and test panes, versions, diff, publish, promote and conflict dialogs, source bar |
| `modules/studio-agents`, `studio-teams`, `studio-workflows`, `registry` | the editors (`?layout=form\|split\|code`), the workflow builder (`?view=canvas\|code&node=`), the registry page |

`…` is `/api/v1/instances/{instance}`. Studio doesn't import agno; agno's own checks run in the instance through the
[bridge](agentos-runtime-and-client.md#agnostic-bridge) (validate, normalize, CEL, introspection, registry source).

## The draft document

- Each edit schedules an autosave 2 s later: `PATCH …/configs/{v}` with the loaded **revision** and AgentOS's
  `guard.latest_version`. A mismatch is `409 version_conflict` with who saved; the dialog loads theirs or overwrites.
- 250 ms after an edit, `POST …/studio/codegen` returns formatted code, the span map, gutter marks, approval notes
  and ruff status.
- Configs store only what agno would write (no agno defaults); unknown keys from newer agno versions are kept.

## Code ⇄ form

The first code edit makes a draft **code-backed**: its code is kept in `studio_code_documents` with the hash of the
config it reads as.

- **Code → config** (`…/studio/parse`): libcst reads the `Agent`/`Team`/`Workflow(...)`, its literal arguments,
  module-level names and registry attributes however imported. Anything else (a call, an f-string, a lambda) is a
  diagnostic and its field is **code-owned**: read-only in the form, never dropped.
- **Form → code** (`…/studio/transform`): only changed arguments are rewritten, comments and layout kept. The result
  must read back as exactly the edited config, or the edit is refused.
- Parsing, transforms and CEL run in a spawn-context process pool (`AGNOSTIC_STUDIO__SOURCE_WORKERS`, 2) with a
  timeout (`__SOURCE_TIMEOUT_SECONDS`, 10) and size limits; `__SOURCE_ISOLATION=inline` uses a thread (tests).
  Nothing imports or executes the code it reads.

## Workflows

- The canvas is a projection of the step tree (`graph.ts`): components with typed ports (Message, Data, Route), a
  Router's choices and a Condition's true / else as their own output ports, Steps / Loop / Parallel as group frames,
  the workflow's input and output, and drop zones for empty lanes. The layout (ELK, left to right, ports at the rows
  the node draws them), the canvas and the Langflow export all read that one projection.
- Canvas actions are tree operations (insert, move, wrap, unwrap, remove, paste), so every state loads in agno and
  undoes. Only manual moves and sticky notes are stored (`studio_canvas_layouts`: `{positions, notes}`, positions as
  offsets from the ELK layout); notes never reach the config or the code.
- **Langflow flow JSON** (`langflow.ts`), both ways. Export writes `ChatInput` / `ChatOutput` at the ends, a
  `genericNode` per step (settings as template fields, ports as outputs), groups as Langflow group nodes with their
  steps in `node.flow`, notes as `noteNode`, and edges with Langflow's œ-encoded handles; every node also carries its
  config and tree path in `metadata.agnostic`, so a flow exported here imports back exactly. A flow made in Langflow
  imports as Steps, in the topological order of its message connections, with no executor yet; tool and model
  connections and fan-out come back as warnings. Import replaces the draft's steps as one undoable edit and lays the
  canvas out again.
- Step names are unique (a rule), so agno's per-step pins stay stable; saves pin each step's stored executor
  (`step_agent` / `step_team` / `step_workflow` links).
- Validation: shape, registry, rules (one executor per Step, Router choices, Loop limits, review options, nothing
  paused inside a Parallel, nesting ≤ 10), CEL type checks in context, then agno's strict load.
- CEL: `/studio/cel/check` and `/studio/cel/contexts` for the editor; `…/studio/cel/evaluate` runs agno's evaluator
  through the bridge, else `agnostic-cel`'s, and says which.
- `…/test-runs` (the builder's Playground) lights the canvas with step events, follows the running step, and keeps
  each step's output for its node and the inspector; `…/step-stats` and `…/step-runs` come from traces (observe).

## Validation and the registry

`…/studio/validate` and the publish check run four layers: shape, registry references (discovered tools can't be
attached; approval tools are noted), Studio's rules, and agno's strict load when the bridge is installed.
`…/studio/registry` normalizes `GET /registry` and marks tools AgentOS only discovered as **DISCOVERED** (the
bridge's `declared`). The used-by index (`studio_registry_index`) is rebuilt on save, publish or promotion, at most
every 10 minutes otherwise, or by "Refresh registry".

## Publishing

`GET …/publish-check?version=` returns validation, every eval gate judged on that exact version, permissions, any
`hold`, and the outcome sentence. `POST …/configs/{v}/publish` fails with `422` on validation errors, `409
gate_blocked` unless an `override_reason` comes from someone with `evals:gates:override` (audited
`evals.gate.override`), and `409 publish_held` while a `PublishHold` holds it. Otherwise it publishes with
`guard.latest_version` (AgentOS's config PATCH checks only that half, and refuses `guard.current_version` with a
`400`), audits `studio.publish` with the field-level diff, and announces `studio.published`. `…/set-current` rolls
back to another published version, guarded by `guard.current_version`.

## Test runs, teams, promotion

- **Test runs**: AgentOS runs a draft only for its owner or an admin, so `…/components/{id}/test-runs` uses
  delegated elevation (needs `components:write` and the run scope) and streams through
  `GatewayFacade.elevated_stream`; "Compare with vN" runs the current version beside it.
- **Teams**: members are `[{"type": "agent", "agent_id": …}]`, pinned versions in the config's `links`
  (`link_kind: member`).
- **Promotion**: `…/promotions {target, version?, include_children}` is a dry run (registry references and pinned
  members must exist on the target or move along), stored in `studio_promotions`; `…/promotions/{id}/apply
  {publish}` re-checks, copies members, creates the component or draft with `promoted_from`, audits
  `studio.promote`, and publishes through the target's gates. Needs `studio:promote` on both instances.
- **Model parameters** come from registered model presets (`MockModel(id="mock-precise", temperature=0.2)`), each
  with its own `id`.

## Golden fixtures

`backend/tests/golden/agno-3.1/{agents,teams,workflows}/` holds agno's `to_dict()` of the reference components plus
fixtures covering every field Studio edits, each with the `.py` Studio generates (`just golden` rewrites both);
`prototype/ticket-router.*` is a hand-styled workflow for the parser tests. Unit tests check every config
round-trips through the typed model and the generated code; the contract suite stores them on a live runtime.
