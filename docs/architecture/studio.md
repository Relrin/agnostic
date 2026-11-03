# Studio: registry, agent, team and workflow editors, code round-trip, versions, publishing and promotion

Studio lets builders create and change agents, teams and workflows, in a form, on a canvas or in code. Configs live in AgentOS
`/components` ([ADR-005](../adr/0005-studio-on-agentos-components.md)): each component has numbered config versions,
drafts can change, published versions can't, and one published version is current. Studio composes only what the
instance registered in its `Registry(...)`, so a config never contains code: tools, models, schemas, knowledge,
memory managers and learning machines are referenced by name.

## Packages and modules

| Backend | Owns |
|---|---|
| `agnostic-spec` | Typed `AgentConfig` / `TeamConfig` / `WorkflowConfig` (`agnostic_spec.v3_1`) in agno's `to_dict()` shape, with `extra="allow"` everywhere; the workflow step tree (`Step`, `Steps`, `Parallel`, `Condition`, `Loop`, `Router`, `HumanReview`) and which review options each node type supports; field metadata for the form and the inspector (section, label, help, widget, the default agno leaves out); `iter_refs` (every registry reference with its field path); semantic rules; the JSON Schema served to the form |
| `agnostic-cel` | CEL as workflows use it: a parser, a type checker per node context (Condition, Router, Loop) with Router exhaustiveness, and a small evaluator; stdlib only |
| `agnostic-codegen` | Config → Python (`generate`), `ruff format` / `ruff check` as a subprocess, span maps, gutter marks and unified diffs; Python → config (`parse_source`, libcst) and form edits applied to existing code (`transform`); `python -m agnostic_codegen DIR` writes the golden `.py` files |
| `studio` module | `/studio/registry`, `/studio/components` (index, create, detail, archive/restore), configs (save draft, new draft, discard, publish, set current, the code of a code-backed draft), `publish-check`, `diff`, `validate`, `codegen`, `parse`, `transform`, `workflows/validate`, `cel/evaluate`, `step-stats`, `step-runs`, `canvas-layout`, `promotions`, `test-runs`; org-wide `/studio/schema/{kind}`, `/studio/templates`, `/studio/cel/check` and `/studio/cel/contexts`; tables `studio_component_meta`, `studio_version_meta`, `studio_registry_index`, `studio_promotions`, `studio_canvas_layouts`, `studio_code_documents` |
| `observe` | `StepStats.for_workflow(…)`: its facade, average duration, runs and failures per step name from a workflow's traces |
| `evals` | `EvalGates.check(instance, component, version, label)`: its first facade, judging gates by the newest batch of exactly that version |
| `gateway` | `GatewayFacade.elevated_stream` (a streamed elevated request) and `invalidate` (drop an instance's cached responses) |
| `sources` module | code sources on top of `StudioFacade` (`agnostic_studio.facade`): component state, code read and written with a repository's registry convention, drafts created from repository files, bindings; it provides Studio's `PublishHold` port and reacts to `studio.published` (see [code sources](sources.md)) |

The control plane never imports agno. agno's own checks run in the instance through the bridge:
`POST /agnostic/v1/components/validate` (strict `from_dict` against the live registry),
`POST /agnostic/v1/cel/evaluate` (agno's own CEL evaluation),
`POST /agnostic/v1/components/normalize`, `GET /agnostic/v1/introspect/components` and
`GET /agnostic/v1/registry/{type}/{name}/source` (see [AgentOS runtime and client](agentos-runtime-and-client.md)).

| Frontend | Owns |
|---|---|
| `@agnostic/studio` | the draft document (`useDraftDocument`, code-backed drafts included), the schema-driven form, the editable code pane, the test pane, the versions drawer and the diff, publish, promote and conflict dialogs, the component index |
| `modules/registry` | `studio/registry/:type?/:name?` |
| `modules/studio-agents`, `modules/studio-teams` | the index pages and the editors (`studio/agents/:id`, `studio/teams/:id`, `?layout=form\|split\|code`) |
| `modules/studio-workflows` | the workflow index and the builder (`studio/workflows/:id`, `?view=canvas\|code&node=`) |
| `@agnostic/editor` | CodeMirror views and editors: read-only code with change marks, line focus and notes; editable code with diagnostics and code-owned lines; the CEL expression editor |

## The draft document

The editor holds one config document. The form edits it; the code pane is a projection of it:

1. Every edit updates the document and schedules an autosave 2 s after the last change.
2. Autosave is `PATCH …/configs/{v}` with the **revision** the editor loaded. The revision changes on every save, from
   Studio or straight on AgentOS. A mismatch is `409 version_conflict` carrying who saved, when, and their config; the
   conflict dialog loads theirs or saves yours over it. AgentOS's own `guard.latest_version` is sent too, so a new
   version created meanwhile also conflicts.
3. 250 ms after the last edit the document goes to `POST /studio/codegen` with the base version's config. The answer
   is the formatted code, the span map (`instructions[2]` → line and columns), gutter marks against the base, the
   approval notes for tools that need approval, and the ruff status.

Configs are stored with only the values agno would write: absent fields and agno's own defaults are left out
(`search_knowledge: true` disappears), unknown keys from newer agno versions are kept.

## Code ⇄ form

Until someone edits the code, it is generated from the config. The first edit makes the draft **code-backed**: the
person's code is the artifact, kept in `studio_code_documents` next to the draft with the hash of the config it reads
as.

- **Code → config.** 300 ms after typing stops, `POST /studio/parse` reads the module with libcst: the
  `Agent`/`Team`/`Workflow(...)` bound to a module-level name (by `id=` when the file has several), its literal
  arguments (implicitly concatenated strings and simple module-level names such as `investigate = Parallel(...)`
  included), registry attributes however the registry module is imported (`tools.x`, `registry.tools.x`,
  `from app.registry.tools import x`), components and functions from their modules, `TeamMode.x`, `HumanReview(...)`
  and the workflow primitives. References resolve against the draft's own config first (so a tool reads back exactly
  as it is stored), then the registry and the stored components. Anything else (a call, an f-string, a lambda, a hook)
  is a located diagnostic and its field is **code-owned**: the config leaves it out, the form shows it read-only with
  "Edit in code", and nothing in the code is dropped. Code that doesn't parse leaves the form at the last version that
  did.
- **Form → code.** On a code-backed draft a form or canvas edit is `POST /studio/transform`: only the changed arguments
  are rewritten (a value replaced in place, a keyword inserted where the generator would put it or removed, list items
  added or dropped while untouched items keep their comments), edits reach module-level names (renaming a step of
  `investigate = Parallel(...)` edits that assignment; a selector split over lines stays split), imports are added and
  dropped as needed, and the human's layout is never reformatted. The result is read back and must say exactly the
  edited config (`equivalent`), or the edit is refused and the form returns to what the code says.
- **Saving.** `PATCH …/configs/{v}` takes the code with the config and checks the code reads as it before storing
  both; `code: ""` stops keeping code for the draft ("Use generated code"). A draft saved elsewhere since shows its code
  as stale.

Parsing, edits and CEL run on **source workers**: a spawn-context process pool (`AGNOSTIC_STUDIO__SOURCE_WORKERS`,
default 2) with a timeout per job (`AGNOSTIC_STUDIO__SOURCE_TIMEOUT_SECONDS`, default 10 s) and size limits (256 kB of
source, 4 kB of CEL). A job past its timeout takes its pool down; the next job starts a fresh one.
`AGNOSTIC_STUDIO__SOURCE_ISOLATION=inline` runs them on a thread instead (the test suite does). None of them imports or
executes the code it reads.

## Workflows

The builder edits the step tree: every canvas action is a tree operation (insert, move, wrap, unwrap, remove, paste),
so every canvas state is a workflow agno can load, and each one is undoable. The layout (ELK, layered top-down, Steps,
Loops and Parallels as compound nodes, Condition and Router branches joining at the next step) runs in a worker; only
what a person moved is kept, in `studio_canvas_layouts`, as offsets from the automatic layout.

- **Configs.** agno writes workflows in full (every key of every step, a complete `human_review`), and so does
  `WorkflowConfig.dump()`, whatever the canvas set. Steps keep no `step_id` unless someone gives one: agno keys a
  step's pin by its id or name, so names are unique (a rule) and pins stay stable.
- **Generated code** hoists like the design: containers that are a Router's choices become module-level variables, a
  selector too long for its line becomes a constant split at its ternaries (`ROUTE_BY_CATEGORY = (...)`).
- **Validation** (`POST /studio/workflows/validate`, and the publish check): shape, registry (executors exist as
  components or registry entries, functions are registered), rules (unique names and step ids, exactly one executor per
  Step, Router choices, Condition steps, Loop limits, review options per node type, nothing paused inside a Parallel,
  output vs iteration review, nesting ≤ 10), **CEL** (each expression type-checked in its context; a Router's every
  literal result must be a choice, a non-literal one is a warning that exhaustiveness can't be proved), then agno's
  strict load. The toolbar's sentence counts every Step and every container ("12 steps · valid").
- **CEL.** `POST /studio/cel/check` (org-wide) types an expression; `GET /studio/cel/contexts` lists each context's
  variables, functions and macros for completion and hover. `POST …/cel/evaluate` tries one on a sample: through the
  bridge's `cel/evaluate` agno evaluates it as a run would (`evaluator: "agno"`); without the bridge, or without
  cel-python on the instance, Agnostic's evaluator answers and says so.
- **Pins.** Saves pin each step's stored agent, team or workflow (`step_agent` / `step_team` / `step_workflow` links,
  keyed as agno keys them, `#else` per else branch); executors defined in code get none.
- **Runs.** `…/test-runs` runs the draft (as for agents); its step events light the canvas up. `…/step-stats` averages
  each step's duration from the workflow's traces (observe, cached); `…/step-runs?step=` lists a step's latest results
  from recent runs.

## Validation

`POST /studio/validate` and the publish check run four layers: the **shape** (the typed model), **registry
references** against the instance's registry (a discovered tool can't be attached; a tool that needs approval is
noted), Studio's **rules** (members unique, legacy team flags beside `mode`, history settings that do nothing…), and
**agno's strict load** through the bridge when it is installed.

## Registry and used-by index

`GET /studio/registry` pages through `GET /registry`, normalizes each entry (one-line meta, details, JSON Schema or
parameters, approval flag) and adds the bridge's `source` answer for tools: `declared` is agno's
`Registry.tool_is_declared`, so a tool AgentOS only discovered on a component defined in code shows as
**DISCOVERED** and can't be attached. Without the bridge, every tool shows as registered.

The used-by index scans every stored config that is current or a draft, and every component defined in code (the
bridge's `introspect`, otherwise the agent and team details), then stores one row per entry in
`studio_registry_index`. It is rebuilt when a save, publish or promotion invalidates it, and at most every 10 minutes
otherwise. "Refresh registry" drops the gateway's cached responses and rebuilds it at once.

## Publishing

`GET …/publish-check?version=` returns the validation layers, every eval gate judged on that exact version,
whether the person may publish and override, and the outcome sentence ("v4 becomes current on prod-agentos,
replacing v3; the API serves it from the next request."). `POST …/configs/{v}/publish`:

- fails with `422` while validation fails (no override for that);
- fails with `409 gate_blocked` while a gate blocks, unless the request has an `override_reason` **and** the person
  holds `evals:gates:override` (Owners and Administrators). The override is audited as `evals.gate.override`;
- fails with `409 publish_held` while something outside Studio holds the publish back (`PublishHold`; a code source
  waiting for its pull request to merge), with the reason in the publish check's `hold`, which also says what
  publishing writes back (`hold.write_back`: "Opens a pull request studio/support-triage-v4 into main");
- publishes with `guard.current_version`, records who published and the change summary, and audits `studio.publish`
  with the field-level diff against the previous current version, then announces `studio.published` (component,
  version, publisher) to the modules that subscribe.

`POST …/configs/{v}/set-current` rolls back to another published version (`components.set_current`, with an optional
reason). New drafts copy a version's config and its member pins (`components.configs.create`).

## Testing a draft

AgentOS runs a draft version only for its owner or an admin. `POST …/components/{id}/test-runs`
(`{message, version, session_id?}`) uses delegated elevation ([ADR-014](../adr/0014-delegated-elevation.md)): the
person must hold `components:write` and may run the component, and the run streams back through
`GatewayFacade.elevated_stream` with a single-use admin token whose `sub` is still the person. The Test pane runs the
draft this way and, with "Compare with vN", the current version through the gateway side by side. When elevation is
turned off for the instance the request is refused with the reason.

## Teams

Members are stored as `[{"type": "agent", "agent_id": …}]`; the versions they are pinned at go in the config's
`links` (`link_kind: member`, `child_component_id`, `child_version`, `position`). A save pins each stored member at
the version the editor sent, or at its current version; members defined in code get no link. The editor explains the
mode three ways: the cards, the one-liner, and the numbered flow written from the actual members and settings.

## Promotion

`POST …/components/{id}/promotions {target, version?, include_children}` is a dry run: every registry reference of
the version must exist on the target (read fresh, not from the gateway cache), and every pinned member must exist
there or move with it. The report is stored in `studio_promotions`. `POST …/promotions/{id}/apply {publish}` re-checks,
copies pinned members first, creates the component (or a new draft) on the target with `promoted_from` in its version
metadata, audits `studio.promote`, and with `publish` publishes through the same gates as any publish on the target.
Promotion needs `studio:promote` on both instances and `components:write` on the target.

## Model parameters

Temperature and other model parameters come from **registered model presets**
([ADR-012](../adr/0012-model-parameters-in-studio.md)): the instance registers, for example,
`MockModel(id="mock-precise", temperature=0.2)`, and the form's model picker lists presets with their parameters
read-only. AgentOS names model registry entries by their `id`, so every preset needs its own id.

## Golden fixtures

`backend/tests/golden/agno-3.1/{agents,teams,workflows}/*.json` are agno's own `to_dict()` output for the reference
runtime's components plus fixtures that cover every field Studio edits (`golden-full-workflow` uses every primitive and
review option); `prototype/ticket-router.json` is the design's ticket router, built in code exactly as the design
reads. The `.py` next to each is the code Studio generates for it. `just golden` rewrites both. The unit suite checks
that every config round-trips through the typed model unchanged, generates exactly its `.py`, and reads back from that
code as the same config; that the ticket router's generated code is the design's code modulo formatting; and that
human-styled code (comments, helper variables, other import styles) parses and keeps its comments through edits. The
contract suite stores agent and workflow configs as components on a live runtime and checks that they read back,
normalize and validate (and, for workflows, run).
