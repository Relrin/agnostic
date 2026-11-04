# Assistant: Ask your OS and AI explanations

Natural-language help grounded in an instance's own data, on a model the org chooses, with the asking person's
permissions and nothing more. Off until an admin configures a model; removed with
`AGNOSTIC_MODULES__DISABLED=assistant`. Code: `backend/modules/assistant` (the only module that imports agno),
`frontend/packages/assistant`, `frontend/modules/assistant`.

## Concepts

| Concept | What it is | Where |
|---|---|---|
| AI settings | provider and model per feature, endpoint, sealed API key, toggles, budgets, rate limit, redaction, retention | `asst_settings` |
| Feature | `assistant` (Ask your OS, Traces follow-ups, permission questions), `summaries`, `suggestions` | `AiSettings.features` |
| Tool | a read-only `ToolSpec` from a module's `assistant_tools()`, run as the person | `agnostic_kernel.tools`, `api/tools.py` |
| Conversation, message, attachment | a private thread per instance; questions and answers with tool calls, sources, tokens; text or image files | `asst_conversations`, `asst_messages`, `asst_attachments` |
| Usage | tokens per month, person and feature (the budget) | `asst_usage` |
| Explanation kind | what a page asks for, its tools, material and output shape | `domain/explainers.py` |

## Tools

The assistant collects every enabled module's tools at start-up (`ToolCatalog`) and adapts them to agno functions
per answer ([add an assistant tool](../how-to/add-assistant-tool.md)):

| Module | Tools |
|---|---|
| observe | `search_traces`, `get_trace`, `compare_trace`, `get_metrics` |
| gateway | `list_sessions`, `get_session` |
| approvals, scheduler | `list_approvals`; `list_schedules`, `get_schedule_runs` |
| audit, access | `search_audit`; `explain_permission` |
| studio, evals | `get_component_config`, `diff_versions`; `list_eval_results` |

## Asking

`POST /instances/{instance}/assistant/questions` checks `assistant:use`, the rate limit and budgets, stores a
`queued` answer, defers `assistant.answer` (queue `assistant`) and returns 202. The worker rebuilds the person as a
principal, offers only the tools they may use (naming what they can't see), and runs one agno `Agent`. Events go over
`evt:assistant:{message_id}`; the browser follows `GET …/messages/{id}/events` (SSE, `Last-Event-ID`), and settled
answers replay from the database.

![Assistant answer: ask, queued job in the worker, module tools run as the asker, model provider, streamed answer; budgets and redaction](images/assistant-answer.svg)

Tool results reach the model quoted (`<data source="tool:get_trace">…</data>`), redacted and size-limited. Settling
stores content, sources and tokens, adds usage, and audits `assistant.ask` (the question only if the org opts in).
Sources come from the tool handlers, never from model text.

## Explanations and suggestions

`POST /instances/{instance}/assistant/explanations {kind, subject, material?}` gathers facts with the same tools and
asks the model for one thing, with no tools of its own. Kinds: `trace.diagnosis`, `eval.insight`,
`memory.optimization`, `studio.version_summary`, `studio.config_explanation`, `audit.diff` (summaries);
`studio.commit_message`, `studio.release_notes`, `studio.cel` (suggestions); `access.question` (turns a question
into a permission check the person runs). Pages keep their deterministic text; generated text is labelled and never
applied without a click.

## Web app

`@agnostic/assistant` has `useAssistant(feature)`, the answer view, the Ask box, `GeneratedText` and `SuggestButton`;
`modules/assistant` adds the Ask page, nav entry and palette command. Modules declare `requires.features`, so with AI
off nothing outside Organization › AI features mentions it.

## Guardrails

- Read-only tools only; an API test checks that only GETs reach AgentOS.
- Tools run with the person's principal through the gateway or the module's use cases.
- Runtime data is quoted and never treated as instructions.
- No outbound calls without a configured provider; agno telemetry off.
- Budgets, rate limits, retention (`assistant.prune`); answers stuck after a crash are marked failed.
