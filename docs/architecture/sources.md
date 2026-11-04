# Code sources: repositories and local folders synced with Studio

Studio and repositories edit the same components (`backend/modules/sources`, `frontend/modules/sources`). Pulled
changes become drafts, publishes write back as pull requests or commits, and edits on both sides merge field by
field. Nothing moves until someone pulls or commits; AgentOS's current version stays the source of truth.

![Code sources sync: repository, git worker and path mappings; pull as drafts, field-level merge and conflicts; write back as a pull request; webhooks, mirrors, local folders](images/code-sources-sync.svg)

## Concepts

| Concept | What it is | Table |
|---|---|---|
| Connection | org-wide access to a git host: GitHub App, a GitHub/GitLab/Gitea/Forgejo token, or a deploy key (sealed) | `src_connections` |
| Source | one repository branch, or a local folder, synced with one instance | `src_sources` |
| Path mapping | globs → `agents`, `teams`, `workflows`, `registry` (read-only) or `ignored` (wins over the rest) | `src_path_mappings` |
| Sync policy | pull `on_demand` / `on_push_as_drafts`; publish `open_pr` / `commit_direct` / `no_write_back`; templates; "block publish until the PR merges" | `src_sync_policies` |
| File binding | file ↔ component with the commit, version, blob and config last agreed (the merge base) | `src_file_bindings` |
| Change, conflict, PR | a file moving one way; a field changed on both sides; a write-back under review | `src_changes`, `src_conflicts`, `src_pull_requests` |

Each source also has a registry convention (how the repository imports registry objects), used to read and write
code.

## Incoming

A fetch (button, push webhook, periodic, or a change on disk) updates the mirror; each mapped file whose blob
changed is parsed through `StudioFacade.read_code` (never executed) and becomes a change with an outcome (new draft,
new component, conflict, parse problem, removed). A file that already reads as Studio's newest version just moves
the binding, which is how a merged PR lands. **Pull** creates drafts, never published.

When the open draft changed since the last sync, the new draft is a three-way merge against the binding's config:
one-sided changes apply, different changes conflict at their path (`instructions[2]`); lists of named items align by
name, others merge diff3-style. Conflicts are resolved one by one (Keep Studio, Keep repo, merged value), then the
pull merges again and writes Studio's fields into the file (`StudioFacade.write_code`, with an equivalence check).

## Outgoing

- For each writable binding whose component has a newer version, the file is edited to say it (the version's own
  code, else a libcst transformation keeping comments, else generated code).
- **Commit & PR** writes one commit into the mirror's object store (no work tree), authored by the person and
  committed by `AGNOSTIC_SOURCES__COMMITTER_*`, then pushes a branch with a pull request, or the source branch.
- On `studio.published`, sources with a write-back policy commit the published version as the publisher.
- PRs are tracked by webhook and a periodic check; a close puts changes back as outgoing.
- With "block publish until the PR merges", sources provide Studio's `PublishHold`: publishing answers
  `409 publish_held` until the repository says that version.

## Webhooks, jobs, mirrors

- `POST /hooks/{github,gitlab,gitea,forgejo}` are mounted at the root without sessions; a delivery must be signed
  with a matching source's secret, else `401` and nothing is stored. Deliveries are deduplicated
  (`src_webhook_deliveries`); a push queues one fetch.
- All git work runs on the `git` queue, one job per source at a time (`lock = sources:{id}`); only workers on that
  queue need git and the mirrors volume.
- Mirrors are bare partial clones (`--filter=blob:none`) in `AGNOSTIC_SOURCES__MIRRORS_DIR`, with a per-mirror quota
  and a daily gc.
- Local folders: `development` instances only, under `AGNOSTIC_SOURCES__LOCAL_ROOTS`; a folder digest is the
  "commit", `watchfiles` triggers fetches, write-backs go to disk.

## Security

- git runs through its CLI (`infrastructure/git_cli.py`) with no system or global config, hooks, credential helpers
  or prompts; credentials go in per-call `GIT_CONFIG_*` variables, never the command line; errors are redacted.
- Repository code is parsed with libcst, never imported or executed.
- Scopes: `components:read` to read; `components:write` to fetch, pull, commit and resolve; `studio:sources:write`
  / `:delete` / `:read` for sources, connections and the webhook log.
- Audited: `sources.connection.*`, `sources.source.*`, `sources.fetch`, `sources.pull`, `sources.commit`,
  `sources.pr.*`, `sources.conflict.resolve`.

## API

Connections live under `/api/v1/studio/connections` (verify, repos, branches, GitHub App install and callback).
Sources live under `/api/v1/instances/{instance}/studio/sources`: `/{id}` plus `scan`, `activate`, `fetch`,
`changes` (+ diff), `pull`, `outgoing/refresh`, `commit-preview`, `commit`, `pull-requests/refresh`,
`conflicts/{id}/resolve`, `deliveries`; `/conflicts/count` (the sidebar dot) and `/local-roots`. The editor's source
bar reads `…/studio/components/{component}/source`.
