# Connect a code source

A code source (`backend/modules/sources`) syncs an instance's agents, teams and workflows with a repository branch
or, on a development instance, a local folder. How syncing works: [code sources](../architecture/sources.md).

## 1. Make a connection

Connections are org-wide (*Studio › Code sources › Connect source*, or `POST /api/v1/studio/connections`) and need
`studio:sources:write` (Owners and Administrators).

**GitHub App (recommended).** Create a GitHub App for your organization (github.com or Enterprise Server):

- permissions: *Contents* read & write, *Pull requests* read & write, *Metadata* read; for review requirements,
  *Administration* read (otherwise Studio falls back to repository rules);
- events: *Push* and *Pull request*; webhook URL `https://<agnostic>/hooks/github` with a secret;
- set `AGNOSTIC_SOURCES__GITHUB_APP_SLUG` to the app's slug (or give it per connection).

Create the connection with the app id, the private key and the webhook secret, then *Install on GitHub*: GitHub
returns to Agnostic with the installation and the connection is verified. For Enterprise Server, give the API URL
(`https://ghe.example.com/api/v3`) and the web URL.

**Token.** A GitHub fine-grained token, a GitLab project or group access token (scope `api`), or a Gitea / Forgejo
access token (`write:repository`, `read:user`). Give the server URL for GitLab self-managed, Gitea and Forgejo.
Tokens are sealed with the master key and never shown again.

## 2. Add the source

Pick the repository and branch, then check the defaults:

- **Path mappings**: `agents/*.py`, `teams/*.py`, `workflows/*.py`, `registry.py` (read-only), `tests/, utils/`
  (ignored), relative to the repository's (or folder's) root. Change them for other layouts (`src/**/agents/*.py`).
- **Registry convention**: the package the agents, teams and workflows live in (`app`, so Studio writes
  `from app.agents import …`), and the module the code imports registry objects from (`app.registry` for
  `from app.registry import tools, models`). A local folder's package defaults to the folder's name.
- **Sync policy**: pull on demand or on every push (as drafts); on publish, open a pull request (default), commit
  straight to the branch, or don't write back; optionally block publishing until the pull request merges.

Studio fetches and reads every mapped file and shows the scan: what each file defines, whether it parses, and whether
it is new, the same as Studio's newest version, or different. *Start syncing* binds the files as proposed; files that
differ arrive as incoming changes to pull. When the mappings take no file, the scan says so and lists the Python files
they missed: edit them under *Path mapping* and Studio scans again. A source closed before *Start syncing* stays "scan
ready · not syncing yet"; *Review the scan* on its page picks up from there.

Webhooks are registered when the source starts syncing and Agnostic has a public URL; reverse proxies must route
`/hooks/*` to the API (next to `/api`). Without webhooks, sources are fetched every 15 minutes
(`AGNOSTIC_SOURCES__FETCH_CRON`) and on *Fetch*.

## 3. Workers

Fetching, scanning and committing run on the `git` job queue. Its workers need `git` 2.36 or newer and a volume for
`AGNOSTIC_SOURCES__MIRRORS_DIR`:

```bash
uv run agnostic worker -q git
```

## Local folders (development)

Mount the runtime's app folder into Agnostic too, list it in `AGNOSTIC_SOURCES__LOCAL_ROOTS` (`["/app"]`), and add a
*Local folder* source on a development instance. The source may be any folder inside a root: pick the package folder
itself (`/app`, or `/agents/my_app` when the root holds the package one level down) so the default mappings match.
Changes on disk show up as incoming changes; publishes are written to the folder and the runtime reloads them.

## Try it with the dev Gitea

```bash
just git-up       # Gitea on http://localhost:3000
just gitea-seed   # northwind/agent-platform with the reference runtime's app; prints a token
```

Start the API with `AGNOSTIC_SOURCES__WEBHOOK_BASE_URL=http://host.docker.internal:8000` so the container can
deliver webhooks. Connect the token as a Gitea connection (server `http://localhost:3000`), add the source on a
staging instance and start syncing. Edit `workflows/ticket_router.py` in Gitea: the push arrives as "Becomes draft
vN of ticket-router", and *Pull* makes it a draft. Publish a component and Gitea gets a pull request from
`studio/<component>-v<version>`; merging it moves the binding.

Errors and fixes: [troubleshooting](troubleshooting.md#code-sources).
