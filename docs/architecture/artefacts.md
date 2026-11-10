# Artefacts

Artefacts are the files agents produce: reports, HTML pages, data, charts, PDFs, audio and video. People see them
under the run that made them, in a session's Files, and on the instance's **Files** page. They can preview,
download and share them through links that expire and can be revoked. This works the same whether the agent wrote
the file on the runtime host, in an E2B sandbox, or inside an Agno sandbox computer, and whether the agent is an Agno
agent or a coding harness: Claude Code, Codex, Pi, OpenCode.

## Where the files live

Artefacts are run media in AgentOS, stored the way AgentOS already stores run media. The control plane keeps no
copy.

```
agent / harness ── writes ──▶ workspace: a folder │ E2B sandbox │ Agno sandbox checkpoint
        │
        │  publish_artifact tool · run post-hook (reconcile) · capture on harness adapters
        ▼
RunOutput.images / files / audio / videos ── Agno media offload ──▶ media storage (local, S3, GCS)
        │                                                              │
bridge  GET /agnostic/v1/artifacts  (which files a session has)        AgentOS GET /sessions/{id}/media/{key}  (bytes)
        └────────────────────────────── gateway, as the person ────────┘
                                         │
control plane  /api/v1/instances/{i}/artifacts/…  (isolated preview, download)   /api/v1/shares/…  (links)
```

- **Collecting** happens in the runtime, with `agnostic_bridge.artifacts`. A source lists and reads one workspace:
  `DirectorySource` (a folder on the host), `E2BSource` (the E2B SDK), `CheckpointSource` (the workspace archive Agno
  commits after each sandboxed turn). The collector reconciles the source at the end of a run: it lists, reads,
  hashes, and attaches the files whose hash this session has not seen. Tool events only say a file was *probably*
  written, and shell commands write without any event, so reconciling the workspace is what makes the list
  complete. Each version of a file is attached once, to the run that produced it.
- **Storing** is Agno's: an agent with `media_storage=` offloads its run media and keeps only a `MediaReference`
  (storage key, backend, hash) in the session. `AgentOS(media_storage=...)` serves an object only to a caller who
  can read the session, and only if the storage key belongs to that session.
- **Listing** is the bridge's `GET /agnostic/v1/artifacts?session_id=` (and `/recent` across the newest sessions):
  one row per stored object, with what the collector recorded (path, source, hash, revision). `POST
  /agnostic/v1/artifacts/sync` collects from sandbox checkpoints for harness adapters run with `sandbox=`, whose
  turns are stored where no post-hook runs; the web app calls it when a run finishes. A `404` from the listing
  means there is nothing to list from (a runtime without these routes, or a session with no stored runs yet), so the
  web app shows no files, not an error.

## Viewing safely

Everything an agent produced is untrusted, so nothing it wrote runs on the app's origin with the app's privileges.

| Kind | How it is shown |
|---|---|
| Markdown, code, CSV, JSON, text | read as text and rendered by the app (Markdown without raw HTML, code with Shiki) |
| Images, SVG | `<img>`: an SVG loaded as an image runs no script |
| Audio, video | `<audio>` / `<video>` from the artefact route |
| PDF | drawn to canvases by pdf.js; no text or annotation layers, which would write HTML |
| Jupyter notebooks (`.ipynb`) | read-only: Markdown cells, code cells and their saved outputs (text, HTML, images, tracebacks), with Python highlighting and KaTeX math. No kernel is attached, so nothing in the notebook runs; every HTML string the renderer produces is sanitized by DOMPurify first (no scripts, forms, frames, styles or external loads) and only that result gets past the Trusted Types policy. Notebooks up to 25 MiB are read whole |
| HTML | a frame with `sandbox="allow-scripts allow-popups"` (never `allow-same-origin`) |

The artefact route sets the response's real type, worked out from the bytes and not from the name a tool gave.
Every response also carries its own content security policy with `sandbox`:

- **HTML shown inline:** `sandbox allow-scripts allow-popups; default-src 'none'; script-src 'unsafe-inline';
  connect-src 'none'; form-action 'none'; frame-ancestors 'self'`. The page has an opaque origin, so it cannot read
  the app's cookies or storage. It cannot fetch anything, so it cannot call the API or send data out. Only the app
  itself may frame it.
- **Everything else, and every download:** a policy under which nothing runs.

The app's own policy allows exactly this, as `frame-src 'self'` and `media-src 'self' blob:`. Every other response
still sends `frame-ancestors 'none'`, so the artefact routes are the only same-origin pages that can be framed.
Operators who want a separate origin for previews can still put one in front later; the routes do not depend on
being same-origin.

## Sharing

A share link points to one stored object, pinned to its SHA-256 at the moment it is shared. If the agent writes a
new version, that becomes a new artefact; the link keeps showing what was shared, and stops working if the stored
bytes ever differ.

- **Who can open it.** Signed-in members of the organization (the default), or anyone holding the link. Links for
  anyone exist only when an administrator sets `AGNOSTIC_ARTIFACTS__PUBLIC_LINKS=true`.
- **How long.** From five minutes to `AGNOSTIC_ARTIFACTS__MAX_SHARE_DAYS` (30 days by default). A link can be
  revoked at any time, and it stops working at once.
- **The token.** It is random, prefixed `ash_`, and shown once. Only its SHA-256 is stored. Unknown, expired and
  revoked links all answer the same `404`.
- **Who may share.** You can share only what you can read: creating a link reads the file through the gateway as
  you. Sharing needs `artifacts:share`, which members hold. `artifacts:manage` (administrators) can see and revoke
  everyone's links.
- **Opening.** The control plane reads the object as itself, because the person opening the link may hold no
  access to the instance; the link is the grant. Opening is audited (`artifact.share.opened`), as are creating
  and revoking.

## Code

| Where | What |
|---|---|
| `bridge/src/agnostic_bridge/artifacts/` | sources, collector, post-hook, `ArtifactTools`, `capture_artifacts` |
| `bridge/src/agnostic_bridge/_artifacts.py` | `/agnostic/v1/artifacts`, `/recent`, `/sync` |
| `backend/modules/artifacts/` | content route, share links (`art_shares`), audit actions, scopes |
| `frontend/packages/core/src/artifacts/` | data hooks, viewer, PDF view, share dialog, run chips, session list |
| `frontend/modules/artifacts/` | the Files page and the public share page `/s/:token` |
| `runtime/app/agents/report_writer.py` | the reference runtime's demo: a report in seven formats, collected from its workspace |

How to collect from your own agents: [collect artefacts](../how-to/collect-artefacts.md).
