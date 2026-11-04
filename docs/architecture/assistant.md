# Assistant: Ask your OS and the AI explanations

Natural-language help grounded in an instance's own traces, sessions, schedules, approvals, evaluations,
configuration and the audit log. It runs on a model the org chooses (local or cloud), with the asking person's
permissions and nothing more. It is optional: off until an admin configures a model, and gone entirely with
`AGNOSTIC_MODULES__DISABLED=assistant` ([ADR-013](../adr/0013-assistant-model-provider.md)).

## Concepts

| Concept | What it is | Where |
|---|---|---|
| AI settings | provider and model per feature, endpoint, write-only API key (sealed with the master key), temperature, feature toggles, budgets, rate limit, redaction, audit of question text, retention, the notice under the Ask box | `asst_settings` (one row) |
| Feature | `assistant` (Ask your OS, the Traces "why" follow-ups, free-text permission checks), `summaries` (explanations next to deterministic text), `suggestions` (drafts a person inserts) | `AiSettings.features` |
| Tool | a read-only function a module contributes (`assistant_tools()` → `ToolSpec`), run as the asking person | `agnostic_kernel.tools`, each module's `api/tools.py` |
| Conversation | a person's thread on one instance; nobody else can read it here | `asst_conversations` |
| Message | a question, an answer, or a one-off explanation (no conversation), with tool calls, sources, model, tokens and status | `asst_messages` |
| Attachment | a text file (log, JSON, YAML…) kept as text, or an image for vision models | `asst_attachments` |
| Usage | tokens per month, person and feature: the budget's source of truth | `asst_usage` |
| Explanation kind | what a page asks for (`trace.diagnosis`, `eval.insight`, `studio.cel`, …): the tools to gather, the material it may send, the task and the output shape | `domain/explainers.py` |

## Tools come from the modules that own the data

The assistant doesn't reach into other modules. Each module declares its read-only tools in `assistant_tools()`, as
framework-neutral `ToolSpec`s (name, description, pydantic arguments, the scope needed, a handler). The assistant
collects them at start-up (`ToolCatalog`), and adapts them to agno functions per answer:

| Module | Tools |
|---|---|
| observe | `search_traces`, `get_trace`, `compare_trace`, `get_metrics` |
| gateway | `list_sessions`, `get_session` |
| approvals | `list_approvals` |
| scheduler | `list_schedules`, `get_schedule_runs` |
| audit | `search_audit` (control-plane `audit:read`) |
| access | `explain_permission` |
| studio | `get_component_config`, `diff_versions` |
| evals | `list_eval_results` |

A disabled module takes its tools with it, and a customer module adds tools the same way
([add an assistant tool](../how-to/add-assistant-tool.md)). `agnostic modules list` shows how many each contributes.

## Asking

1. **Accept** (API, `POST /instances/{instance}/assistant/questions`, multipart). The person needs `assistant:use`
   (Members and above have it) and the feature on. A per-person rate limit (Redis window) and the monthly budgets
   (Postgres usage) are checked; attachments are read (text kept, images only for providers that take them). The
   question and an empty answer (`queued`) are stored, the `assistant.answer` job is deferred, and the API answers
   202 with the message id.
2. **Answer** (worker, queue `assistant`). The job claims the message (`queued` → `running`), rebuilds the person as a
   principal and asks the authorizer which tools they may use. Tools they can't use are never offered; the system
   prompt names what they can't see ("traces (needs traces:read)") so the answer says so instead of guessing.
3. **Run.** One agno `Agent` per answer: the configured model, the bound tools, the system prompt, earlier turns of
   the conversation, the question with page context and attachments. Every tool result reaches the model quoted
   (`<data source="tool:get_trace">…</data>`), redacted per the org's settings and cut to a size limit.
4. **Stream.** Each engine event is published on the event bus channel `evt:assistant:{message_id}`: tool started
   and finished (the chips), text deltas, then the sources and a terminal event. Redis keeps the stream for replay;
   with SQLite the in-process bus does the same.
5. **Follow** (API, `GET …/messages/{id}/events`, SSE). The browser follows the answer, resuming with `Last-Event-ID`.
   A settled answer is replayed from Postgres as the same events, so reconnects and late tabs see the whole thing.
6. **Settle.** Content, tool calls, sources, model and tokens are stored; usage is added; `assistant.ask` is audited
   with the tools and sources (the question only if the org opts in). A stopped answer (`…/cancel`) or one past
   `AGNOSTIC_ASSISTANT__ANSWER_TIMEOUT_SECONDS` settles as cancelled or failed with what it had.

Sources are the pages the tools' data came from, collected by the handlers, never parsed from model text.

## Explanations and suggestions

`POST /instances/{instance}/assistant/explanations` takes a kind, a subject (`{"trace_id": …}`) and, for kinds that
allow it, material the page has but the server doesn't (an unsaved draft, an optimization preview). The worker
gathers the kind's facts with the same tools, as the person, and asks the model for one thing with no tools of its
own. The same subject is reused for the same person unless regenerated.

| Kind | Feature | Uses |
|---|---|---|
| `trace.diagnosis` | summaries | `compare_trace`; rewrites the deterministic diagnosis and keeps its facts |
| `eval.insight` | summaries | `list_eval_results` comparing two evaluations |
| `memory.optimization` | summaries | the optimization preview (material) |
| `studio.version_summary` | summaries | `diff_versions` |
| `studio.config_explanation` | summaries | `get_component_config`, or the draft (material) |
| `audit.diff` | summaries | `search_audit` by event id |
| `studio.commit_message`, `studio.release_notes` | suggestions | the changes the dialog shows (material) |
| `studio.cel` | suggestions | the description and the context's symbols; the page checks the expression before "Use" |
| `access.question` | assistant | turns "Can Maya publish support-triage on prod?" into the structured check, which the person runs |

Pages keep showing their deterministic text; generated text is labelled with the model, can be regenerated, and is
never applied without a click.

## In the web app

`@agnostic/assistant` holds what pages share: `useAssistant(feature)` (the feature is on and the person may use it),
the answer stream and view, the Ask box (ghost-text suggestion, Tab accepts, attachments), `GeneratedText` and
`SuggestButton`. The `assistant` module adds the Ask page, the "Ask your OS" nav entry and the palette command (what
was typed becomes the question). Modules declare `requires.features`, read from `GET /api/v1/system/features`, which
merges every enabled module's `features()`. With AI off, nothing outside Organization › AI features mentions it.

## Guardrails

- Read-only: tools only read (an API test runs every tool and checks that only GET requests reach AgentOS); there are
  no write tools.
- As the person: each tool goes through the gateway or the module's own use cases with the person's principal, so
  scopes, user isolation and audit apply as in the browser.
- Prompt injection: runtime data is quoted and the system prompt says it is never instructions.
- No outbound calls without a configured provider; agno's telemetry is off.
- Budgets and rate limits; conversations deleted after the org's retention (`assistant.prune`); answers stuck after
  a worker crash are marked failed.
