# Context: memory, knowledge, learnings and files

The **Memory**, **Knowledge**, **Learnings** and **File system** pages are thin UIs over AgentOS's context routes,
called through the gateway as the person (scopes, user isolation, `gateway.request` audit). The `context` module (no
tables) adds what AgentOS can't do: duplicates, provenance, filtered counts and audited bulk actions.

## Code

`…` is `/api/v1/instances/{instance}`.

| Where | Owns |
|---|---|
| `context` | `…/memories/duplicates`, `…/memories/{id}/source`, `…/memories/optimize`, `…/knowledge/bases`, `…/knowledge/content`, `…/learnings/counts`, `…/learnings/delete-user`, `…/files/provenance`, `POST /context/data-subject-requests` |
| `gateway` | route policies for context routes; uploads stream with `AGNOSTIC_GATEWAY__MAX_UPLOAD_MB` |
| agnostic-bridge | `GET /agnostic/v1/files/provenance` |
| frontend | `modules/memory`, `knowledge`, `learnings`, `files`, hidden when the capability is off; `contextHandlers()` in `@agnostic/testing` |

Tunables are `AGNOSTIC_CONTEXT__*` (`context/settings.py`).

## Memory

- **Likely duplicates**: word trigrams (as `pg_trgm`) over the user's newest `MAX_DUPLICATE_SCAN` (500) memories;
  pairs at or above `DUPLICATE_THRESHOLD` (0.35) flag the one that adds less.
- **"Generated from this input"** is a best-effort match: the newest run of the memory's user and component that
  started before the memory was written (two minutes of slack).
- **Optimize** previews AgentOS's summarize strategy (`apply: false`); applying runs the model again, so wording can
  differ. Audited with counts.

## Knowledge

- Bases come from `/config.knowledge`, with entry counts, vector databases and **Used by**.
- Content filters and counters scan the newest `MAX_CONTENT_PAGES` (10) × 100 rows, since AgentOS can't filter; the
  page says how many it searched.
- Uploads use `XMLHttpRequest` for progress and stream end to end; "skip existing" is enforced by the page.

## Learnings

- Counts per type are one `limit=1` query each (`meta.total_count`).
- **Delete for a user** needs the id typed again (checked server-side), then `DELETE /learnings/users/{user}`.
- A **data subject request** (org-wide) repeats that on every instance where the caller holds `learnings:delete`.

## File system

Listings, previews and search use AgentOS's read-only `/filesystem/*` routes (3.1 has no write routes, so the page
has none). **Where this came from** reads file-tool `TOOL` spans: inside AgentOS through the bridge, else the
viewer's newest `PROVENANCE_TRACES` (50) traces through the gateway, labelled best effort. It shows the last
successful write, *partial* when that run failed, and readers since.

## Audit actions

`context.memories.optimized`, `context.learnings.user_deleted`, `context.data_subject.requested`; other writes are
`gateway.request`.
