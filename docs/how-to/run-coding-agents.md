# Run coding agents in sandboxes

A coding agent is a coding harness, [Pi](https://pi.dev) or [OpenCode](https://opencode.ai), that runs as an
Agnostic agent: you chat with it, see the files it writes and the commands it runs, and its output files become
artefacts of the run. The harness never runs inside AgentOS or the bridge. Each session gets a sandbox of its own
(a Docker container on the runtime's host, or an E2B sandbox), and the harness thinks with a model configured in
Agno.

```
 browser ── control plane ── AgentOS runtime ──────────────────────────────┐
                              │ agnostic_bridge.coding                      │
                              │  PiAgent / OpenCodeAgent                    │
                              │  model proxy   /agnostic/v1/coding/llm/v1 ◀─┼── per-run token
                              │  tool server   /agnostic/v1/coding/mcp    ◀─┼── per-run token
                              └─────────────────────────────────────────────┘
                     sandbox per (agent, session): pi --mode rpc │ opencode run --format json
```

- **The model stays on the runtime.** The harness is configured with one model, `agnostic/agent-model`, served by an
  OpenAI-compatible endpoint on the runtime. Each request becomes one call to the agent's Agno model, so any Agno model
  works (OpenAI, Anthropic, Ollama, a registry preset) and its API key never enters the sandbox.
- **Tools come over MCP.** The agent's Agno tools (functions, toolkits, MCP tools from the tool catalog) are offered
  to the harness as a remote MCP server. Tools that need a person (confirmation, user input, approvals) are left out,
  because nobody can answer inside a sandboxed turn.
- **One token per turn.** Both endpoints accept only a random token minted when the turn starts and revoked when it
  ends. It is bound to one agent, session and run, passed to the harness as an environment variable of that one
  process, and never written to a file or a command line.
- **Sessions stay apart.** Each Agno session has its own sandbox and its own workspace. The harness's own session is
  resumed while the sandbox lives; when the sandbox is gone, the next turn starts a new one with the conversation
  replayed from Agno's history.

## Try it with the reference runtime

1. Start Docker, then build the sandbox image (Pi and OpenCode, pinned in `runtime/sandbox/coding/Dockerfile`):

   ```bash
   just sandbox-image
   ```

2. Start the stack and the runtimes as usual (`just up`, `just dev`, `just runtimes`). With the `docker` CLI on the
   path, each runtime registers `pi-coder` and `opencode-coder`.
3. In Chat, pick **Pi coder** and ask it to "write a hello file". With the default mock model it thinks, writes
   `outputs/hello.md` with the harness's `write` tool, lists the folder with `bash`, and answers; `hello.md` shows up
   as an artefact of the run.
4. Ask again in the same session: the same sandbox answers, and Pi resumes its own session.

To use a real model, set `RUNTIME_CODING_MODEL` before `just runtimes`, as `<provider>:<model id>`:

```bash
RUNTIME_CODING_MODEL=ollama:qwen3:8b just runtimes        # after `just ai-up`
RUNTIME_CODING_MODEL=anthropic:claude-sonnet-4-6 just runtimes   # ANTHROPIC_API_KEY in the runtime's environment
```

| Setting | Default | Does |
|---|---|---|
| `RUNTIME_CODING_ENABLED` | `true` | register the sample coding agents |
| `RUNTIME_CODING_CALLBACK_URL` | `http://host.docker.internal:<port>` | where sandboxes reach this runtime |
| `RUNTIME_CODING_SANDBOX` | `docker` | `docker` or `e2b` |
| `RUNTIME_CODING_IMAGE` | `agnostic-coding:0.1.0` | Docker image of the sandboxes |
| `RUNTIME_CODING_TEMPLATE` | | E2B template built from the same Dockerfile |
| `RUNTIME_CODING_NETWORK` | `isolated` | Docker network of the sandboxes (see Security) |
| `RUNTIME_CODING_MODEL` | `mock` | model the sample agents think with |

## Define a coding agent in your runtime

```python
from agno.models.anthropic import Claude
from agnostic_bridge import install
from agnostic_bridge.artifacts import capture_artifacts
from agnostic_bridge.coding import CodingAgentSpec, CodingConfig, PiAgent, SandboxSpec

coder = capture_artifacts(
    PiAgent(
        id="repo-coder",
        name="Repo coder",
        model=Claude(id="claude-sonnet-4-6"),
        instructions="Write every file the person should get under outputs/.",
        tools=[lookup_order],                      # any Agno tools, offered over MCP
        coding=CodingAgentSpec(
            harness="pi",
            sandbox=SandboxSpec(provider="docker", image="agnostic-coding:0.1.0", memory_mb=4096),
        ),
    ),
    media_storage=storage,                           # the same storage as AgentOS(media_storage=...)
)
agent_os = AgentOS(agents=[coder], db=db, media_storage=storage)
app = install(agent_os, coding=CodingConfig(callback_url="http://host.docker.internal:7777"))
```

`OpenCodeAgent` takes the same arguments. `SandboxSpec` sets the computer each session gets: `cpus`, `memory_mb`,
`workspace_mb`, `pids_limit`, `network`, `turn_timeout_s`, and `idle_pause_s` / `ttl_s` (pause after that long idle,
destroy after that long idle). Settings come from `install(coding=...)` or the environment:
`AGNOSTIC_CODING_CALLBACK_URL`, `AGNOSTIC_CODING_MATERIALIZE`, `AGNOSTIC_CODING_SYNC_INTERVAL`.

## Build one in Studio

New agent → template **Coding agent** gives an agent with a **Coding agent** section: harness, sandbox provider,
image or template, limits and the outputs folder. The settings are stored in the agent's metadata
(`metadata.agnostic.coding_agent`). When it is published, the runtime's bridge builds the coding agent from it, with
the agent's model, instructions and tools, within about ten seconds (straight away when the control plane asks it
to refresh). Draft test runs use the published version, since the sandboxed harness runs only what is published.

## Sandboxes

**Docker** sandboxes are Agno's `DockerSandbox`: uid 1000, read-only root filesystem, all capabilities dropped,
`no-new-privileges`, CPU, memory and process limits, and memory-backed `/workspace` and `/runtime` volumes per
session. Nothing from the host is mounted and the Docker socket never enters a sandbox. An idle sandbox is paused
(files and memory kept) and destroyed after its TTL; a sandbox of a deleted session is destroyed when the runtime
restarts.

**E2B** sandboxes need `pip install 'agnostic-bridge[e2b]'`, `E2B_API_KEY`, and a template built from
`runtime/sandbox/coding/Dockerfile` (`SandboxSpec(provider="e2b", template="...")`). They call back over the
internet, so the callback URL must be reachable from E2B: a public HTTPS address of the runtime, or a tunnel while
developing.

## Security

- The `isolated` Docker network keeps sandboxes away from each other, but they still reach the internet and every
  port the host publishes, the runtime's included. Code a harness runs could call the runtime's API like any other
  client on the host, so keep the runtime's auth on (JWT) outside development. For a tighter boundary, give the
  sandboxes an internal Docker network whose only route out is a relay to the callback paths, and pass its name as
  `network`; or use E2B with egress rules.
- Run grants live in the memory of the replica that started the turn. With several replicas, each needs its own
  callback URL that sandboxes can reach.
- The proxy pins the model: a sandbox cannot pick another model or raise sampling limits, and a turn may make at most
  200 model requests.

## Upgrading the harnesses

Bump `PI_VERSION` or `OPENCODE_VERSION` in `runtime/sandbox/coding/Dockerfile`, rebuild with `just sandbox-image`,
then record their event streams again and run the bridge tests:

```bash
just sandbox-fixtures
```

```bash
cd bridge && uv run pytest tests/test_coding_agent.py
```
