# Collect artefacts from your agents

Files your agents write show up in Agnostic as artefacts (see [architecture](../architecture/artefacts.md)) once two
things are in place on the runtime: **media storage** to keep them, and **a collector** that brings them out of the
workspace or sandbox into the run.

## 1. Give AgentOS media storage

Use one storage object for the agents and for AgentOS: its media route only serves objects of the storage it was
given.

```python
from agno.media.storage.local import LocalMediaStorage   # or S3MediaStorage(bucket=...), GCSMediaStorage(...)

storage = LocalMediaStorage(base_path="/var/lib/agentos/media")
agent_os = AgentOS(agents=[...], db=db, media_storage=storage)
app = install(agent_os)  # agnostic-bridge: adds /agnostic/v1/artifacts
```

In production use S3-compatible storage (MinIO works) with a private bucket. Local storage only works when every
replica shares the folder.

## 2. Collect what the agent writes

### An Agno agent writing to a folder

```python
from agnostic_bridge.artifacts import ArtifactTools, DirectorySource, collect_artifacts

def workspace(run_context):  # one folder per session
    return DirectorySource(f"/srv/workspaces/{run_context.session_id}")

agent = Agent(
    tools=[..., ArtifactTools(workspace)],                       # the model may publish a file explicitly
    post_hooks=[collect_artifacts(workspace, include=("outputs/**",))],  # and everything new under outputs/ is collected
    media_storage=storage,
)
```

### An Agno agent with E2B

Collect before the sandbox goes away: E2B deletes a sandbox's files with it.

```python
from agno.tools.e2b import E2BTools
from agnostic_bridge.artifacts import ArtifactTools, E2BSource, collect_artifacts

e2b = E2BTools()
outputs = E2BSource(tools=e2b, root="/home/user/outputs")
agent = Agent(
    tools=[e2b, ArtifactTools(outputs)],
    instructions="Save every chart and table you make under /home/user/outputs.",
    post_hooks=[collect_artifacts(outputs)],
    media_storage=storage,
)
```

### Claude Code and Codex through Agno's adapters

```python
from agno.agents.claude import ClaudeAgent
from agnostic_bridge.artifacts import capture_artifacts

coder = capture_artifacts(
    ClaudeAgent(name="coder", cwd="/srv/repo", allowed_tools=["Read", "Write", "Edit", "Bash"]),
    media_storage=storage,
    root="outputs",             # what to collect, relative to the workspace
)
```

- **Run on the host** (no `sandbox=`): the adapter's `cwd` is reconciled just before each run is stored.
- **Run with `sandbox=DockerSandbox(...)`**: the computer may be paused or destroyed after the turn, but Agno commits
  the workspace to a checkpoint. The bridge reads `workspace/outputs/` from that checkpoint when the control plane
  syncs the session (`POST /agnostic/v1/artifacts/sync`), which the web app does when a run finishes. Give the
  sandbox a shared `checkpoints=` store when you run more than one replica.

The same works for `CodexAgent`.

### Pi and OpenCode as coding agents

`PiAgent` and `OpenCodeAgent` (see [Run coding agents in sandboxes](run-coding-agents.md)) work with
`capture_artifacts` too: the files under `root` are read from the session's live sandbox just before each run is
stored, so they are kept after the sandbox is paused or destroyed.

### Other harnesses

Point a source at the folder the harness works in, and run the collector when its turn ends:

```python
from agnostic_bridge.artifacts import ArtifactCollector, DirectorySource

collector = ArtifactCollector(DirectorySource("/srv/pi-workspace"), include=("outputs/**", "**/*.md"))
media = await collector.collect(session_state)   # Agno Image/File/Audio/Video, ready for RunOutput
```

The collector does not trust a harness's tool events, such as Pi's `tool_execution_end` for `write`/`edit`, or
OpenCode's `file.edited` event: it reconciles the folder itself. Those events are still a good moment to run it.

### A source of your own

Implement `ArtifactSource` for any place files land, such as an OpenCode server (`GET /session/:id/diff`, then
`GET /file/content?path=`) or Daytona (`sandbox.fs.list_files`, `sandbox.fs.download_file`):

```python
class OpenCodeSource:
    kind = "opencode"

    def __init__(self, client, session_id: str) -> None:
        self.client, self.session_id, self.root = client, session_id, ""

    async def list(self) -> list[SourceEntry]: ...                 # paths relative to the project
    async def read(self, path: str, *, limit: int) -> bytes: ...   # refuse files over `limit`
```

Return paths relative to the root, and refuse anything that leaves it; `clean_relative()` does that check.

## 3. Check it

- `GET /agnostic/v1/capabilities` reports `features.media_storage` (`local`, `s3`, …).
- After a run, the session's Files (Chat → Session details, or Sessions → Files) lists what was stored, and the
  instance's **Files** page lists the newest across sessions.
- The reference runtime's `report-writer` agent shows the whole flow without keys: ask it to "write a report on
  support volume".

Limits per run: 50 files, 25 MB each and 100 MB in total (pass `max_files=`, `max_file_bytes=`,
`max_total_bytes=` to change them). Files over a limit are skipped and logged, never truncated. The control plane
serves files up to `AGNOSTIC_ARTIFACTS__MAX_CONTENT_MB` (50 MB).
