# Builder guide

Studio is where agents, teams and workflows are made and changed, in a form, on a canvas or in code. Their configs
live in the AgentOS instance itself (`/components`): each component has numbered versions, drafts can change,
published versions can't, and one published version is current. Studio composes only what the instance registered
in its `Registry(...)`: tools, models, schemas, knowledge, memory managers and learning machines are referenced by
name, never as code.

## The registry

*Studio › Registry* lists what the instance registered (tools with their parameters and whether they need approval,
model presets, output schemas, knowledge bases, functions…) and which components use each entry. A tool AgentOS
only discovered on a component defined in code shows as **Discovered** and can't be attached until it is registered.
*Refresh registry* re-reads it after a deploy.

Model parameters (temperature, max tokens…) come from registered presets, each with its own id: register
`OpenAIChat(id="gpt-precise", temperature=0.2)` and pick it in the form.

## Editing

- **Form and code.** The form edits the config; the code pane shows the Python it corresponds to, formatted with
  ruff, with the changed lines marked. Editing the code makes the draft *code-backed*: your code is kept as written,
  the form follows it, and fields the form can't express (a call, an f-string, a hook) show read-only with *Edit in
  code*. *Use generated code* drops your code again.
- **Autosave** saves 2 seconds after the last change. If someone else saved meanwhile (in Studio or straight on
  AgentOS), a conflict dialog shows their version and lets you load it or save yours over it.
- **Teams**: members are pinned at a version; the editor explains the team mode with the actual members.
- **Workflows**: the canvas shows the workflow as a flow, read left to right: the workflow's input, a component per
  step with its input and output ports, Router choices and Condition branches leaving from their own ports, Loop,
  Parallel and Steps as frames around their steps, and the output. Drag a component from the sidebar onto a
  connection's **+** (or empty space, to add it at the end); every action keeps the workflow loadable and can be
  undone. Conditions, routers and loops use **CEL** expressions, type-checked as you write them; *Try* evaluates one
  on a sample input (with the bridge, agno evaluates it exactly as a run would). **Playground** runs the draft with a
  test message: steps light up on the canvas as they run, and each step's output opens from its node or the
  inspector's *Output* tab. *Add note* leaves a sticky note for your team (saved with the canvas, never in the
  config). **Share** exports the workflow as Langflow flow JSON and imports one: a flow exported from Studio comes
  back exactly; one made in Langflow comes in as steps in the order it runs, with what doesn't carry over listed.

## Testing

The *Test* pane runs the draft through a single-use elevated token whose subject is still you (AgentOS runs drafts
only for their owner or an admin), and audits it. *Compare with vN* runs the current version side by side. Turning
delegated elevation off for an instance disables draft testing there.

## Validating and publishing

Validation runs four layers: the config's shape, the registry references, Studio's rules (unique names, team
settings that do nothing, workflow rules such as one executor per step and exhaustive routers), and agno's own strict
load through the bridge.

*Publish* shows the outcome first ("v4 becomes current on prod-agentos, replacing v3") and is refused while:

- validation fails;
- an **eval gate** blocks: a minimum average score on a dataset for this component, judged on the newest
  evaluation of exactly this version. People with `evals:gates:override` (Owners and Administrators) can publish
  anyway with a reason; the override is audited;
- a **code source** holds it back until its pull request merges (see below).

Every publish is audited with the field-level diff. *Set current* rolls back to an earlier published version.

## Promotion

*Promote* copies a version to another instance (staging → production): a dry run first checks that every registry
reference exists on the target and that pinned members exist or move along; applying it creates a draft (or
publishes, through the target's gates). It needs `studio:promote` on both instances.

## Code sources

Code sources keep Studio and a git repository (GitHub, GitLab, Gitea, Forgejo) or a local folder in sync for one
instance. Connect a host in *Studio › Code sources* (a GitHub App installation is preferred; tokens and deploy keys
work too), then map paths (`agents/*.py`, `teams/*.py`, `workflows/*.py`, `registry.py`) and set the **registry
convention** the repository uses (`from app.registry import tools, models`).

- **Incoming**: a fetch (button, push webhook, or the periodic fetch) parses changed files (nothing is executed) and
  shows each as a sentence ("Becomes draft v9 of ticket-router, next to your draft v8"). *Pull* turns them into
  drafts, never published. With *on push as drafts*, conflict-free changes are pulled on their own.
- **Merging**: when the component's draft changed in Studio too, the two are merged field by field against the last
  synced version; lists of named items (steps, members) merge by name. A field changed differently on both sides is a
  conflict you resolve one by one (keep Studio, keep repo, or merge).
- **Outgoing**: *Commit & PR* writes the version into the file (keeping your comments and formatting) and opens a
  pull request from a branch named by the template, or commits straight to the branch. Publishing can do this too,
  and can be held until the pull request merges.

## Conventions that keep round-trips clean

- One `Agent`, `Team` or `Workflow` per module-level name, with an `id=`.
- Reference registry objects as attributes (`tools.lookup_order`, `models.gpt_precise`), imported the way the
  source's convention says.
- Keep dynamic code (helpers, f-strings, hooks) in the repository; Studio leaves it untouched and read-only.
