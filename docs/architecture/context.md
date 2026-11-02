# Context: memory, knowledge, learnings and files

Four pages show what agents remember and read: **Memory**, **Knowledge**, **Learnings** and **File system**. They are
thin UIs over the AgentOS context routes. Reads and plain edits go through the gateway passthrough as the signed-in
person, so scopes, user isolation and the audit trail (`gateway.request`) apply as everywhere else. A small `context`
module adds only what AgentOS can't do itself: duplicates, provenance, filtered counts and audited bulk actions.

## Modules

| Backend | Owns |
|---|---|
| `context` | `GET …/memories/duplicates`, `GET …/memories/{id}/source`, `POST …/memories/optimize`, `GET …/knowledge/bases`, `GET …/knowledge/content`, `GET …/learnings/counts`, `POST …/learnings/delete-user`, `GET …/files/provenance`, `POST /context/data-subject-requests`; no tables |
| `gateway` | route policies for every context route; uploads (`POST /knowledge/content`) get `AGNOSTIC_GATEWAY__MAX_UPLOAD_MB` instead of the body limit and stream through |
| agnostic-bridge | `GET /agnostic/v1/files/provenance` (`filesystem:read` + `traces:read`) |

| Frontend | Owns |
|---|---|
| `modules/memory`, `modules/knowledge`, `modules/learnings`, `modules/files` | the pages; each hides when the instance's capability matrix reports `memory`, `knowledge`, `learnings` or `filesystem` off |
| `@agnostic/testing` | `contextHandlers()` and the sample org's context fixtures |

## Memory

- **Users and memories** come from `/user_memory_stats` and `/memories?user_id=&search_content=&topics=`. The topic
  pills are the five most used topics among the loaded memories. A Database select appears when `/config.memory.dbs`
  lists several databases, and its `db_id` goes on every call.
- **Likely duplicates** are computed in the control plane: word trigrams as in PostgreSQL `pg_trgm`, compared pairwise
  over the user's newest `MAX_DUPLICATE_SCAN` memories. Two memories at or above `DUPLICATE_THRESHOLD` are flagged on
  the one that adds less (the shorter, else the older).
- **"Generated from this input"** is matched: AgentOS memory responses carry neither the source input nor the session.
  The control plane reads the sessions of the memory's user and agent (or team), then their runs, and picks the newest
  run that started before the memory was last written (two minutes of slack). The page says it is best effort.
- **Optimize** previews AgentOS's summarize strategy (`POST /optimize-memories`, `apply: false`) as before and after.
  Apply calls it with `apply: true`, which runs the model again, so the saved wording can differ slightly from the
  preview. The page says so. Applying is audited with the counts.

## Knowledge

- **Knowledge bases** come from `/config.knowledge.knowledge_instances`. Each one gets its entry count, its vector
  databases (`/knowledge/config`) and **Used by**: agents and teams whose `knowledge.knowledge_table` (and `db_id`, when
  both name one) match the base.
- **Content** filters (status, type, text in name, description or metadata) and the failed/processing counters are
  computed over the newest `MAX_CONTENT_PAGES` × 100 rows, because AgentOS can't filter content. Past that the page
  says how many rows it searched. While rows are processing, the page polls each one's
  `/knowledge/content/{id}/status` every 3 s.
- **Test retrieval** is `POST /knowledge/search` with metadata filters, top-k and search type. It shows reranking
  scores when the base reranks, and the latency AgentOS reports.
- **Add content**:
  - File is a multipart upload sent with `XMLHttpRequest` for progress. The browser streams from disk and the gateway
    streams on, so large files never sit in memory.
  - URL and Text use `POST /knowledge/content`.
  - Remote browses `/knowledge/{id}/sources/{source}/files` and ingests each picked file with
    `POST /knowledge/remote-content`.
  - "Skip content that already exists" is enforced by the page: AgentOS has no such flag, so files whose name is
    already in the base are skipped or shown as indexed.

## Learnings

- **Counts per type** come from one `GET /learnings?learning_type=…&limit=1` per type (`meta.total_count`), with the
  page's filters.
- Records are edited with `PATCH /learnings/{id}`, which replaces both `content` and `metadata`. The page shows the
  id scheme of each type.
- **Delete learnings for a user** needs the user id typed again. The control plane checks that confirmation too,
  counts the records, then calls `DELETE /learnings/users/{user}?learning_type=` and records
  `context.learnings.user_deleted`.
- **Data subject request** (org-wide) runs the same deletion on every enabled instance where the caller holds
  `learnings:delete`, reports each instance (deleted, skipped, failed) and records
  `context.data_subject.requested`. Memories and sessions are deleted separately.

## File system

- Namespaces, their agents and those agents' access (`full`, `read_only`) come from `/config.filesystem`. Listings,
  previews and search use the read-only `/filesystem/entries|content|search` routes. The volume meter is
  `usage.total_bytes` against `usage.bytes_limit` (the namespace's `max_namespace_bytes`). Upload, rename and delete
  are hidden: AgentOS 3.1 has no write routes, and the page says so.
- **Where this came from**: file tools are traced as `TOOL` spans whose arguments name the path. With agnostic-bridge,
  `GET /agnostic/v1/files/provenance` reads the newest traces (default 200) and their spans in the AgentOS process and
  returns every file-tool call on the path. Isolated callers see their own runs only. Without the bridge, the control
  plane reads the viewer's newest `PROVENANCE_TRACES` traces through the gateway and labels the result best effort.
  Either way the summary is:
  - the last successful write (run, step, tool, time);
  - *partial* when that run ended in error;
  - who read the file since, grouped by component and workflow step.

## Audit actions

`context.memories.optimized`, `context.learnings.user_deleted`, `context.data_subject.requested`. Every other write
(memory and learning edits, knowledge ingestion and edits) is a gateway call and is audited as `gateway.request`.
