# Control: approvals, notifications, scheduler, queue

Everything that waits, repeats or retries. AgentOS stays the source of truth (`agno_approvals`, `agno_schedules`,
`agno_jobs`); the control plane keeps only what AgentOS has no place for: routing, views, expiry policy, disable
reasons, notification channels and preferences.

## Modules

`…` is `/api/v1/instances/{instance}`.

| Module | Owns |
|---|---|
| `approvals` | `…/approvals` (tabs, filters, counts, detail, decide, routes, policy), org-wide `/approvals/routes`; `apr_*` tables; `approvals.watch` |
| `notifications` | `GET /events` (SSE), `/notifications` (inbox, unread count, read, channels, defaults, event types), `/me/notification-preferences`; `ntf_*` tables; `notifications.deliver`; the `Notifier` facade |
| `scheduler` | `…/schedules` (CRUD, enable, disable with a reason, trigger, runs, preview, status, endpoint check); `sch_notes`; `scheduler.watch_failures` |
| `queue` | `…/queue/summary`, `overview`, `workers`, `jobs` (+ resume, requeue, cancel); no tables |

Frontend: `modules/approvals`, `modules/scheduler`, `modules/queue`; the bell in
`apps/web/src/shell/notification-bell.tsx`; personal preferences in `modules/account`; org channels, defaults and
approval expiry in `modules/settings`.

## Approvals

Under user isolation AgentOS shows non-admins only their own approvals, so the inbox reads **as the control plane**
(`InstancesFacade.system_call`) after checking `approvals:read`. Deciding goes through the person with delegated
elevation ([operate](operate-and-realtime.md#deciding-an-approval)); rejecting needs a note. AgentOS can't filter by
tool or text, so the inbox scans the newest `scan_limit` approvals and filters itself (`truncated` says when).
Opening one records a view and publishes `approval.viewed`.

![Approval lifecycle: pending, routed, approved or rejected, expired, resumed; the watcher and expiry policy](images/approval-lifecycle.svg)

- **Routing** is advisory: a route (tool, optional component kind and ids) names members, groups and access roles,
  forced personal channels and org channels. Instance routes beat org-wide ones; with no match, everyone with
  `approvals:write` is told in-app. Who may resolve stays `approvals:write`, enforced by AgentOS.
- **Expiry**: AgentOS 3.1 sets no `expires_at` on agent and team approvals, so the effective expiry is
  `expires_at`, else the workflow step's `timeout_at`, else `created_at` + `approval_ttl_hours` (`0` = never).
  Enforcement is per instance and **off by default**; on, workflows continue without a decision (`on_timeout`
  applies) and agent and team approvals are rejected with `resolution_data.expired = true` (`approvals.expired`).
- **The watcher** (`approvals.watch`, every minute) routes and notifies new approvals (`approval.created`), reminds
  once before expiry (`approval.expiring`), and enforces expiry; each step is recorded once in `apr_events`.

## Notifications

`Notifier.notify(NotificationRequest)` fans out to the recipients' **bell** (`ntf_inbox`, live via
`notification.created`), their **personal channels** (their preference, else the org default, else the catalog
default, plus route-forced ones; quiet hours hold email and Slack, never the bell; Slack is a DM from the org bot),
and subscribed **org channels**.

Each email, Slack message or webhook call is a delivery row retried by `notifications.deliver`. Channel secrets are
sealed. Webhooks carry `X-Agnostic-Event` and `X-Agnostic-Signature: sha256=<HMAC>`. Slack buttons are links into
Agnostic, never callbacks, so people decide under their own scopes.

Event types are in `notifications/domain/catalog.py`: approvals, `schedule.failed`, `evals.regression`, access
grants and requests, privileged service accounts, break-glass sign-ins, audit archive and SIEM failures, and
`conflict.detected` (catalogued; nothing publishes it).

### Domain events

Notifications depends on access, so access can't call it. Modules publish facts instead:
`DomainEvents.publish("access.privileged_grant", payload)` after the commit queues `kernel.domain_event`, which runs
every `EventHandlerSpec` for that name (at least once each). Evals publishes `evals.regression` the same way.

## Scheduler

Schedules are read and written **as the person** through the gateway, so AgentOS checks `schedules:*` and the
target's run scope. Added on top: last runs and failure streak, the cron as a sentence, `…/schedules/preview` (next
runs in the schedule's timezone and UTC, with daylight-saving notes), a disable reason (`sch_notes`), Instance admin
for custom endpoints (audited `target=custom`), and `scheduler.watch_failures` announcing each failed run once
(`schedule.failed`, via the bridge's event feed when present).

## Queue

AgentOS lets only admins at `/queue/*`. Holders of `queue:operate` (Operators and Instance admins) go through
delegated elevation; everyone else with access sees counts only (`…/queue/summary`).

- **Workers**: the bridge's `/agnostic/v1/workers` answers for one replica; the control plane remembers each report
  and adds workers known only from `locked_by`.
- **Recovery**: *Resume from checkpoint* (`continue_from=<message_index>`, agents and teams), *Requeue* (one more
  attempt, same run id), *Cancel*; audited `queue.resume`, `queue.requeue`, `queue.cancel`.

## Realtime

| Event | Channel | Effect |
|---|---|---|
| `approval.created`, `.viewed`, `.resolved` | instance (`approvals:read`) | refetch inbox, counts, detail |
| `schedule.failed` | instance (`schedules:read`) | refetch schedules |
| `notification.created`, `.read` | the person | update the bell |

`just up` starts a Slack mock next to Mailpit; the reference `refund-review` workflow's review step times out after a
day, to exercise expiry.
