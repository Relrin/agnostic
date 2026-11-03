# Studio: registry, agent and team editors, versions, publishing and promotion

Studio lets builders create and change agents and teams without writing code. Configs live in AgentOS
`/components` ([ADR-005](../adr/0005-studio-on-agentos-components.md)): each component has numbered config versions,
drafts can change, published versions can't, and one published version is current. Studio composes only what the
instance registered in its `Registry(...)`, so a config never contains code: tools, models, schemas, knowledge,
memory managers and learning machines are referenced by name.

## Packages and modules

| Backend | Owns |
|---|---|
| `agnostic-spec` | Typed `AgentConfig` / `TeamConfig` (`agnostic_spec.v3_1`) in agno's `to_dict()` shape, with `extra="allow"` everywhere; field metadata for the form (section, label, help, widget, the default agno leaves out); `iter_refs` (every registry reference with its field path); semantic rules; the JSON Schema served to the form |
| `agnostic-codegen` | Config → Python (`generate`), `ruff format` / `ruff check` as a subprocess, the span map read back from the formatted code with `ast`, gutter marks and unified diffs; `python -m agnostic_codegen DIR` writes the golden `.py` files |
| `studio` module | `/studio/registry`, `/studio/components` (index, create, detail, archive/restore), configs (save draft, new draft, discard, publish, set current), `publish-check`, `diff`, `validate`, `codegen`, `promotions`, `test-runs`; org-wide `/studio/schema/{kind}` and `/studio/templates`; tables `studio_component_meta`, `studio_version_meta`, `studio_registry_index`, `studio_promotions` |
| `evals` | `EvalGates.check(instance, component, version, label)`: its first facade, judging gates by the newest batch of exactly that version |
| `gateway` | `GatewayFacade.elevated_stream` (a streamed elevated request) and `invalidate` (drop an instance's cached responses) |

The control plane never imports agno. agno's own checks run in the instance through the bridge:
`POST /agnostic/v1/components/validate` (strict `from_dict` against the live registry),
`POST /agnostic/v1/components/normalize`, `GET /agnostic/v1/introspect/components` and
`GET /agnostic/v1/registry/{type}/{name}/source` (see [AgentOS runtime and client](agentos-runtime-and-client.md)).

| Frontend | Owns |
|---|---|
| `@agnostic/studio` | the draft document (`useDraftDocument`), the schema-driven form, the code pane, the test pane, the versions drawer and the diff, publish, promote and conflict dialogs, the component index |
| `modules/registry` | `studio/registry/:type?/:name?` |
| `modules/studio-agents`, `modules/studio-teams` | the index pages and the editors (`studio/agents/:id`, `studio/teams/:id`, `?layout=form\|split\|code`) |
| `modules/studio-workflows` | the workflow index (the builder comes with the workflow editor) |
| `@agnostic/editor` | the read-only CodeMirror view with change marks, line focus and inline notes |

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
- publishes with `guard.current_version`, records who published and the change summary, and audits `studio.publish`
  with the field-level diff against the previous current version.

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

`backend/tests/golden/agno-3.1/{agents,teams}/*.json` are agno's own `to_dict()` output for the reference runtime's
components plus two fixtures that cover every field Studio edits; the `.py` next to each is the code Studio generates
for it. `just golden` rewrites both. The unit suite checks that every config round-trips through the typed model
unchanged and generates exactly its `.py`; the contract suite stores each agent config as a component on a live
runtime and checks that it reads back, normalizes and validates unchanged.
