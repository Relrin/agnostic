# Code sources: repositories and local folders synced with Studio

Studio and repositories edit the same agents, teams and workflows. Pulled changes arrive as drafts, publishes write
back as pull requests (or commits), and edits made in both places merge field by field. Nothing moves until someone
pulls or commits. The runtime's source of truth stays the AgentOS component's current published version; git is a
sync peer.

## Concepts

| Concept | What it is | Where |
|---|---|---|
| Connection | how Agnostic reaches a git host, for the whole org: a GitHub App installation (preferred), a GitHub, GitLab, Gitea or Forgejo token, or a deploy key; secrets sealed with the master key | `src_connections` |
| Source | one repository branch (or a local folder) synced with one instance | `src_sources` |
| Path mapping | globs → `agents`, `teams`, `workflows`, `registry` (read-only) or `ignored`; defaults `agents/*.py`, `teams/*.py`, `workflows/*.py`, `registry.py`, `tests/, utils/` | `src_path_mappings` |
| Registry convention | how the repository imports registry objects (`from app.registry import tools, models`), per source | `src_sources.convention`, copied to `studio_component_meta.convention` |
| Sync policy | pull `on_demand` or `on_push_as_drafts`; publish `open_pr`, `commit_direct` or `no_write_back`; branch and commit templates (`studio/{component}-v{version}`, `{component}: {summary}`); "block publish until the PR merges" | `src_sync_policies` |
| File binding | a file ↔ a component, with the commit, version, blob and config they last agreed on (the merge base) | `src_file_bindings` |
| Change | one file moving one way, with its outcome, diff counts and the lines it brings in | `src_changes` |
| Conflict | one field changed on both sides (`instructions[2]`), both values and who wrote them, and how it was resolved | `src_conflicts` |
| Pull request | a write-back under review, with the components and versions it carries | `src_pull_requests` |

Globs: `*` stays inside a folder, `**` crosses folders, a trailing `/` is everything under a folder, `a, b` lists
several. An `ignored` mapping always wins; otherwise the first match does.

## Incoming: repository → Studio

1. **Fetch** (the Fetch button, a push webhook, the periodic fetch for sources without a webhook, or a change on disk
   for local folders) updates the source's bare mirror and lists the files at the new head.
2. Every mapped file whose blob differs from its binding is read (`components_in` finds the components a new file
   defines) and parsed through Studio (`StudioFacade.read_code`, with the source's convention; nothing is executed).
3. Each file becomes an incoming change with an **outcome**: a new draft ("Becomes draft v9 of ticket-router, next
   to your draft v8"), a new component, a conflict, a parse problem, or a removed file. A file that already reads as
   Studio's newest (or current) version moves the binding instead and leaves no change behind; that is how a merged
   pull request lands.
4. **Pull** turns the selected changes into new drafts, never published, code-backed by the file. With the
   `on_push_as_drafts` policy, a push pulls conflict-free changes on its own.

The outcome sentence is written per reader, so the same change says "your draft v8" to the draft's author and "Maya
Chen's draft v8" to everyone else.

### Merging with Studio's draft

When the component's open draft changed since the last sync, the new draft is a three-way merge of the file and that
draft, with the binding's synced config as the base (the current published version for a file bound without one):

- a field changed on one side only takes that change; Studio's carried changes are listed as `auto_merged`;
- a field changed the same way on both sides is fine;
- a field changed differently on both sides is a **conflict** at its path;
- lists whose items carry a name or id (workflow steps, router choices, team members) are aligned by it; other
  lists merge by position, diff3-style, so one side appending an instruction and the other editing another both
  survive, and the same instruction edited on both sides conflicts at `instructions[2]`.

Conflicts are resolved one by one (Keep Studio, Keep repo, or a merged value from the merge dialog). Pulling a
change with open conflicts is refused; when every conflict is resolved, the pull merges again against the draft as
it is then (refusing if the draft changed in a way that conflicts anew), applies the resolutions, writes Studio's
carried fields into the file with an equivalence check (`StudioFacade.write_code`), and creates the draft. The
sidebar's conflict dot is the count of open conflicts on the instance (`sources.conflicts` realtime events keep it
current).

## Outgoing: Studio → repository

- **Outgoing changes** are worked out per writable binding: the component's newest version, when it says something
  the bound file doesn't. The file is edited to say the version (the version's own code when it is code-backed,
  otherwise a libcst transformation of the repository file that keeps comments and formatting, falling back to
  generated code), with its line endings kept and a summary ("temperature 0.7 → 0.2, one new instruction"). A file
  that changed in the repository too waits until the incoming change is pulled.
- **Commit & PR** writes the files as one commit straight into the mirror's object store (no work tree), authored by
  the person and committed by `AGNOSTIC_SOURCES__COMMITTER_*`, then pushes either a new branch from the template with
  a pull request into the source branch (the review requirement comes from branch protection: "1 review from
  Platform required"), or the source branch itself (`commit_direct`). Local folders are written in place.
- **On publish**, Studio announces `studio.published`; sources with a write-back policy commit the published version
  the same way, as the publisher.
- **Pull requests** are tracked by webhook and by the periodic check. A merge queues a fetch; the merged file reads as
  the version, so the binding moves to the merge commit and that version. A closed pull request puts its changes back
  as outgoing.
- **Holding a publish back**: with "block publish until the PR merges", Studio's publish check reports
  `hold.held` ("Waiting for PR #12 to merge · 1 review from Platform required") and publishing answers
  `409 publish_held` until the repository says that version. Sources provide Studio's `PublishHold` port; without the
  sources module Studio never holds a publish.

## Webhooks

`POST /hooks/github`, `/hooks/gitlab`, `/hooks/gitea` and `/hooks/forgejo` are mounted at the root, outside the API
schema and without a session. A delivery is matched to sources by provider and repository and must be signed with a
source's secret (`X-Hub-Signature-256`, `X-Gitea-Signature` / `X-Forgejo-Signature`, `X-Gitlab-Token`); otherwise
it is refused with `401` and nothing is stored. Deliveries are deduplicated per source (`src_webhook_deliveries`,
kept `AGNOSTIC_SOURCES__DELIVERY_RETENTION_DAYS`); a push to the source branch queues one fetch however many arrive,
and a pull request event queues a status check. Activating a source registers the webhook with a fresh secret when
the connection can (a GitHub App delivers its own webhooks, signed with the app's secret).

## Jobs and mirrors

Everything that touches git runs on the `git` queue, one job at a time per source (`lock = sources:{id}`):
`sources.scan`, `sources.fetch`, `sources.compute_incoming`, `sources.pull_as_drafts`, `sources.prepare_outgoing`,
`sources.commit_and_pr`, `sources.refresh_pr_status`, and the periodic `sources.fetch_all`,
`sources.refresh_all_pr_status` and `sources.gc`. Only workers serving that queue need git and the mirrors volume.

Mirrors are bare partial clones (`--filter=blob:none`) in `AGNOSTIC_SOURCES__MIRRORS_DIR`, one per source: trees come
with every fetch and file contents only when a mapped file is read, so diffing stays scoped to the mappings in large
monorepos. Each mirror has a quota (`MIRROR_QUOTA_MB`, the source turns `over_quota`), the daily gc packs mirrors,
removes the mirrors of deleted sources and prunes old deliveries. See [ADR-027](../adr/0027-git-through-the-git-cli.md)
for how git is run.

## Local folders

A local source is a folder mounted into Agnostic and the instance (a hot-reloading development runtime). It is
allowed only for `development` instances and only under `AGNOSTIC_SOURCES__LOCAL_ROOTS`. Its "commit" is a digest of
the folder, changes on disk are watched (`watchfiles`, one process at a time) and queue a fetch, and write-backs go
straight to disk; the runtime reloads the file and the next refresh of its config reflects it.

## Security

- Connection secrets and webhook secrets are envelope-encrypted with the master key; GitHub App installation tokens
  are cached sealed until shortly before they expire.
- The GitHub App needs contents (read & write), pull requests (read & write) and metadata (read).
- Credentials reach git through `GIT_CONFIG_*` environment variables of one invocation, never a command line or a
  config file; git runs without system or global config, hooks, credential helpers or prompts, and only with the
  protocols sources use; git's error output is redacted before it is stored or logged.
- Repository code is parsed (libcst), never imported or executed.
- Who may do what: reading sources, changes and conflicts needs `components:read`; fetching, pulling, committing
  and resolving conflicts need `components:write`; connecting and configuring sources needs
  `studio:sources:write`, disconnecting `studio:sources:delete`, and connections and the webhook log
  `studio:sources:read` (Owners and Administrators hold the `studio:sources:*` scopes).
- Every change is audited: `sources.connection.*`, `sources.source.*`, `sources.fetch`, `sources.pull`,
  `sources.commit`, `sources.pr.open|merged|closed`, `sources.conflict.resolve`.

## API

| Route | What it does |
|---|---|
| `GET/POST /api/v1/studio/connections`, `GET/PATCH/DELETE …/{id}`, `POST …/{id}/verify` | connections |
| `GET …/{id}/repos`, `GET …/{id}/branches?repo=` | the repositories and branches a connection can see |
| `GET …/{id}/github/install`, `GET /api/v1/studio/connections/github/callback` | the GitHub App installation flow |
| `GET/POST /api/v1/instances/{instance}/studio/sources`, `GET/PATCH/DELETE …/{id}` | sources (the cards) |
| `GET …/{id}/scan`, `POST …/{id}/activate` | the initial scan report and binding the files |
| `POST …/{id}/fetch`, `GET …/{id}/changes`, `PATCH …/changes/{change}`, `GET …/changes/{change}/diff` | changes |
| `POST …/{id}/pull` | pull incoming changes as drafts |
| `POST …/{id}/outgoing/refresh`, `GET …/{id}/commit-preview`, `POST …/{id}/commit` | outgoing changes, Commit & PR |
| `POST …/{id}/pull-requests/refresh`, `POST …/{id}/conflicts/{conflict}/resolve`, `GET …/{id}/deliveries` | pull requests, conflicts, webhook log |
| `GET …/studio/sources/conflicts/count` | the sidebar dot |
| `GET …/studio/components/{component}/source` | the editor's source bar |

## Frontend

`modules/sources` is the Code sources page (`studio/sources?source=`): source cards with their chips, the path
mapping editor, the sync policy, and the Changes panel (Fetch; incoming rows with include checkboxes, diff counts,
the commit and the outcome; outgoing rows with the commit composer; conflict cards with both sides; pull requests),
plus the Connect source wizard. `@agnostic/studio` adds the source bar above the code pane (repository, branch, file,
`↓ 7c2e1f0 · Sam Rivera · 2 h ago`, `↑ 1 uncommitted · …`, Pull, Commit & PR…), the incoming-commit chip in the
editor headers, the merge dialog, and gutter marks for the lines the last pull brought in.
