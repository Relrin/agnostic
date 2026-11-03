# Control: approvals, notifications, scheduler, queue

Everything that waits, repeats or retries. **Approvals** is an inbox of runs paused for a person, with routing,
reminders and expiry. **Notifications** tells people about it in the app (the bell), by email, in Slack or through
a webhook. **Scheduler** shows AgentOS cron schedules as sentences with DST-aware previews and their run history.
**Queue** shows the durable queue's health and workers and recovers failed runs from checkpoints.

AgentOS stays the source of truth: approvals live in `agno_approvals`, schedules in `agno_schedules`, jobs in
`agno_jobs`. The control plane keeps only what AgentOS has no place for (routing, views, expiry policy, the reason a
person disabled a schedule, notification channels and preferences).

## Modules

| Backend | Owns |
|---|---|
| `approvals` | `GET …/approvals` (tabs, filters), `…/approvals/counts`, `…/approvals/{id}` (context, timeline; records a view), `…/approvals/{id}/decide`, `…/approvals/routes`, `/approvals/routes` (org-wide), `…/approvals/policy`; tables `apr_routes`, `apr_views`, `apr_events`, `apr_policies`; the `approvals.watch` job |
| `notifications` | `GET /events` (SSE), `/notifications` (inbox, unread count, read), `/notifications/channels` (+ test), `/notifications/defaults`, `/notifications/event-types`, `/me/notification-preferences`; tables `ntf_channels`, `ntf_defaults`, `ntf_preferences`, `ntf_quiet_hours`, `ntf_inbox`, `ntf_deliveries`; the `notifications.deliver` job; the `Notifier` facade |
| `scheduler` | `…/schedules` (CRUD, enable, disable with a reason, trigger, runs), `…/schedules/preview`, `…/schedules/status`, `…/schedules/endpoint-check`; table `sch_notes`; the `scheduler.watch_failures` job |
| `queue` | `…/queue/summary`, `…/queue/overview`, `…/queue/workers`, `…/queue/jobs` (+ detail, resume, requeue, cancel) |
| kernel | `DomainEvents` and the `kernel.domain_event` job: modules announce events, other modules handle them |

`…` is `/api/v1/instances/{instance}`.

| Frontend | Owns |
|---|---|
| `modules/approvals`, `modules/scheduler`, `modules/queue` | the pages |
| `apps/web` shell | the bell (`notification-bell.tsx`) |
| `modules/account` | personal notification preferences and quiet hours |
| `modules/settings` | Settings › Approvals (org TTL, instance expiry policy), Settings › Notifications (org channels, defaults) |
| `@agnostic/ui` | `Popover`, `Timeline`, `SlotBar`, `ArgsDiff`, `CronFields`, `Countdown`; `Switch` gained `hideLabel` |
| `@agnostic/core` | `useUnreadNotifications`; realtime handling of `approval.*`, `schedule.failed`, `notification.*` |

## The approvals inbox

Under user isolation AgentOS shows a non-admin only their own approvals, so an operator's inbox would be empty. The
inbox reads approvals **as the control plane** (`InstancesFacade.system_call`) after checking `approvals:read`
itself, the same way the pending-count badge does. Deciding still goes through the person with delegated elevation
(see [Operate and realtime](operate-and-realtime.md)); rejecting needs a note, which the requester sees.

AgentOS filters by status, type, source and user but not by tool or free text, and knows nothing about expiry, so the
inbox scans the newest `scan_limit` approvals of a tab and filters the rest itself. Lists say when that window cut
them short (`truncated`).

The detail adds a **context** excerpt (the run's input and the agent's last words, from `GET
/sessions/{id}/runs/{run}`), the **timeline** (paused, routed, viewed, decided or expired, run continued), and
whether the caller can resolve. Opening it records a view (once per person) and publishes `approval.viewed`.

### Routing

A route says who hears about which approvals: a tool, optionally a component kind and ids, and the **members and
access roles** it reaches, plus personal channels to force (Slack, email) and org channels to post to. Routes of the
instance win over org-wide ones; the most specific matching routes apply. Routed people who can't read approvals on
the instance are left out. With no matching route, everyone holding `approvals:write` there gets an in-app
notification.

Routing is advisory: it decides who is told, never who may resolve. That stays `approvals:write`, through AgentOS.

### Expiry

AgentOS 3.1 sets no `expires_at` on agent and team approvals and never marks one expired; a workflow `HumanReview`
`timeout` is only checked when someone continues the run. The control plane computes an **effective expiry**:

1. the approval's own `expires_at`,
2. else the workflow step's `timeout_at` (from the approval's requirements),
3. else `created_at` + the org's `approval_ttl_hours` (or the instance's override); `0` means never.

Approvals past their expiry show as *expired*. What happens to the run is decided per instance (Settings ›
Approvals, Instance admin, **off by default** to stay faithful to AgentOS):

- off: nothing; the run stays paused until someone continues it, and the inbox says so;
- on: the watcher stops the run the way AgentOS would. A workflow is continued without a decision, so AgentOS
  applies the step's `on_timeout` (cancel by default). An agent or team approval is resolved `rejected` with
  `resolution_data.expired = true` and the run continued with the rejection. Audited as `approvals.expired`.

### The watcher

`approvals.watch` runs every minute. Per instance it lists pending approvals and compares them with `apr_events`:
new ones are routed and notified (`approval.created`, with Approve and Reject link buttons in Slack), approvals
within `expiring_lead_minutes` of expiry get one reminder (`approval.expiring`), and expired ones are enforced
where the instance says so. Each step is recorded once, so a replica restart doesn't repeat it.

## Notifications

`Notifier.notify(NotificationRequest)` is the only way in. One request fans out to:

- the **bell** of every recipient (`ntf_inbox`, live through `notification.created` on the person's channel);
- their **personal channels**: their preference for the event type, else the org default, else the catalogue default,
  plus channels a route forces. Quiet hours hold back email and Slack, never the bell. Slack goes to people as a
  direct message from an org Slack bot that may DM (looked up by email);
- **org channels** that subscribe to the event type, or that a route names.

Every email, Slack message and webhook call is a delivery row sent by the `notifications.deliver` job and retried;
the last attempt leaves `failed` with the reason, shown on the channel in Settings. Channel configs (bot tokens,
webhook URLs, signing secrets) are sealed with the master key and shown back only as their last characters.
Webhooks carry `X-Agnostic-Event` and `X-Agnostic-Signature: sha256=<HMAC of the body>`.

**Slack buttons are links.** "Approve" opens the approval in Agnostic (`?intent=approve`), where a signed-in person
decides under their own scopes. There is no interactive callback: a bot clicking for someone would resolve
approvals as the bot.

Events: `approval.created`, `approval.expiring`, `approval.resolved` (to the requester), `schedule.failed`,
`evals.regression` (to whoever started the batch), `access.privileged_grant` (to Owners and Administrators),
`conflict.detected` (catalogued; nothing produces it yet).

### Domain events

Notifications depends on access (to compute recipients), so access can't call it. Modules announce what happened
instead: `DomainEvents.publish("access.privileged_grant", payload)` after the commit queues the
`kernel.domain_event` job, which runs every `EventHandlerSpec` declared for that name with a request-scoped
container. Evals publishes `evals.regression` when a completed batch scores worse than the previous one on the same
component and dataset.

## Scheduler

Schedules are read and written **as the person** through the gateway, so AgentOS checks `schedules:*` and, for a
run endpoint, `<family>:run` on the target. On top of that:

- each schedule comes with its last runs, its failure streak and its cron as a sentence ("Every 30 minutes,
  08:00–18:59, Monday to Friday");
- `POST …/schedules/preview` returns the next runs in the schedule's timezone and in UTC (`croniter` + `zoneinfo`,
  like AgentOS) and notes about daylight saving: "Daylight saving ends Sun 1 Nov in America/New_York: these runs move
  from 12:00 to 13:00 UTC.", and runs that happen twice in a repeated hour;
- disabling takes a reason, kept in `sch_notes` (AgentOS's `disabled_reason` is set by the system only);
- a **custom endpoint** (anything but `POST /{agents|teams|workflows}/{id}/runs`) needs Instance admin, checked
  before anything reaches AgentOS (which enforces the same rule), and is audited with `target=custom`;
- `scheduler.watch_failures` announces each failed run once (`schedule.failed` to the schedule's owner, or to
  `schedules:write` holders), through the bridge's event feed when the instance has it.

## Queue

AgentOS lets only admins at `/queue/*`. The Queue page goes through **delegated elevation** for people holding the
control-plane scope `queue:operate` (Operators and Instance admins by default): the control plane checks the scope,
then sends one single-use admin token, audited as `gateway.elevated`. Instance admins on an instance with elevation
off go as themselves. Everyone else with access to the instance sees counts only (`…/queue/summary`, read as the
control plane), with an explanation.

- **Workers.** Each process knows only its own worker. The bridge's `GET /agnostic/v1/workers` answers for the
  replica that served the call; the control plane keeps what each replica said (heartbeat, slots, deployment) and adds
  workers it only knows from `locked_by` of running jobs.
- **Attempts.** AgentOS keeps no attempt history; the timeline is rebuilt from the job's fields.
- **Recovery.** *Resume from checkpoint* continues the run with `continue_from=<message_index>` (agents and teams;
  workflows don't keep message checkpoints), so earlier tool calls aren't made again. *Requeue* grants one more
  attempt with the same run id (`force` inside `lock_grace_seconds`). *Cancel* stops a queued or running job's run.
  Each is audited (`queue.resume`, `queue.requeue`, `queue.cancel`).

## Realtime

| Event | Channel | Effect in the browser |
|---|---|---|
| `approval.created`, `approval.viewed`, `approval.resolved` | instance (`approvals:read`) | refetch the inbox, counts and detail |
| `schedule.failed` | instance (`schedules:read`) | refetch schedules |
| `notification.created`, `notification.read` | the person | update the bell |

## Development

`just up` starts a Slack mock next to Mailpit (see [Run the reference runtimes](../how-to/reference-runtimes.md)).
The `refund_review` workflow's review step times out after a day, to see step-timeout expiry.
