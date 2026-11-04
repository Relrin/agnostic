# Configure AI features

Ask your OS and the AI explanations are off until an admin chooses a model in **Organization › AI features**
(`settings:write`). Nothing is sent anywhere before that.

## Choose a provider

| Provider | Model | Endpoint | Key |
|---|---|---|---|
| vLLM | as served, e.g. `Qwen/Qwen3-32B` | the OpenAI-compatible base URL, e.g. `http://vllm.internal:8000/v1` | usually none |
| Ollama | e.g. `qwen3:8b` | e.g. `http://ollama.internal:11434` | none |
| OpenAI-compatible endpoint | as the server names it | its base URL (LiteLLM, LM Studio, llama.cpp, a gateway) | if it asks for one |
| Azure OpenAI | the deployment name | the resource URL, e.g. `https://acme.openai.azure.com`, plus the API version | yes |
| OpenAI, Anthropic | e.g. `gpt-5`, `claude-sonnet-5-5` | empty (or a proxy) | yes |

Pick a model with good tool calling: the assistant answers by calling tools. Summaries and suggestions use the same
model unless you name another (`provider:model`). **Test connection** sends the saved model one tiny prompt.

Changing the API key asks for a recent sign-in. The key is stored encrypted and never shown again.

## Air-gapped installs

Run vLLM or Ollama inside the network and point the endpoint at it. The control plane makes no other outbound
calls for these features (agno's telemetry is turned off). For development, `just ai-up` starts Ollama from the dev
Compose file and pulls `qwen3:8b`; use endpoint `http://localhost:11434`.

## What the model sees

A question, the results of the tools it calls, page context and attachments. Tools run as the person asking, so the
model never sees what that person can't. Two switches strip more:

- **Leave out tool arguments**: arguments runtimes passed to tools (search queries, customer ids).
- **Leave out end-user messages**: what people typed into your agents (run inputs, session messages).

The audit log records every question (`assistant.ask`) and explanation (`assistant.explain`) with the tools and
sources used; turn on **Keep the question text in the audit log** to keep the question too.

## Who can use it, and how much

`assistant:use` is held by Members, Administrators and Owners; remove it with a custom role to keep someone out.
Set an organization budget and a per-person budget (tokens per calendar month, UTC) and a per-person rate limit.
Local servers that don't report token counts are counted by text length (about four characters a token).
Conversations are deleted after the retention you set (default 90 days).

## Turn it off

Switch **AI features** off: the feature disappears from every page; settings stay. To remove the module entirely,
set `AGNOSTIC_MODULES__DISABLED=assistant`; its tables stay until you drop them.

## Try it with the dev stack

```bash
just ai-up
```

```bash
RUNTIME_FAULTS=web_search=timeout just runtimes
```

```bash
just seed --trigger-daily-brief
```

Then configure Ollama in Organization › AI features and ask "Why did daily-brief fail last night?" on Home. The
opt-in Q&A suite checks a model against seeded data: `just test-assistant`.
