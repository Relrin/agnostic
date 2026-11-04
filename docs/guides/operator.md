# Operator guide

Operators run agents, supervise what they do and recover when something fails. Everything here happens on one
instance at a time: pick it in the instance switcher. What you can see and do depends on your role on that instance;
when something is refused, the page says which permission is missing and who can grant it.

## Home

The overview of the instance: runs, sessions, error rate, p95 latency and cost for the last 24 hours, 7 or 30 days;
what needs attention (pending approvals, an error spike, failing schedules); the agents, teams and workflows; recent
activity. *Ask your OS* answers questions about the instance in plain language when AI features are on.

## Chat

Pick an agent, team or workflow (and a version), and send a message. Runs stream as they happen: tool calls with
their arguments and durations, team members, workflow steps. Runs belong to the instance's durable queue, so a closed
tab, a dropped connection or a restarted API doesn't stop them; reopening the session resumes the stream.

When a run pauses for a person (a tool that needs approval, a workflow review step), the approval appears inline.
Approve, reject with a note, or edit the arguments, and the run continues.

## Sessions

Every conversation, with its runs, messages, tool calls, state and metrics. Filter by user, component or time;
rename or delete sessions you are allowed to change.

## Approvals

The inbox of runs paused for a person: pending, expiring, decided. Routes decide who hears about which approvals
(per tool, component, people or groups); reminders and expiry are set per instance. Each approval shows the run's
context and a timeline (paused, routed, viewed, decided, continued). Rejecting needs a note, which the requester sees.
Notifications arrive in the app, by email, in Slack or through webhooks, per your preferences in *Account*.

## Scheduler

Cron schedules as sentences ("Every 30 minutes, 08:00–18:59, Monday to Friday"), with the next runs in their time
zone and in UTC and a warning when daylight saving moves them. *Run now* triggers one; disabling asks for a reason.
Failed runs notify the schedule's owner.

## Queue

The durable queue's health and its workers. For a failed job: *Resume from checkpoint* continues an agent or team run
without repeating earlier tool calls, *Requeue* tries once more with the same run id, *Cancel* stops it. These need
`queue:operate` and are audited.

## Traces and metrics

*Traces* shows every run as a span waterfall and lines it up with the last successful run of the same component,
pointing out where they differ ("took 4× longer in `search_knowledge`", "the tool returned an error").
*Metrics* shows runs, tokens and estimated cost from your price table, per component and model, with CSV export.
*Evaluations* run datasets against component versions and compare them case by case.

## Context

| Page | Shows |
|---|---|
| Memory | what agents remember per user, likely duplicates, which input created a memory; edit, delete or optimize |
| Knowledge | knowledge bases, their content and status, which agents use them; add files, URLs or text and test retrieval |
| Learnings | what agents learned, per user and type |
| File system | the files agents read and wrote, with the run that wrote each |

## When something goes wrong

- A runtime doesn't answer: [instance unreachable](runbooks/instance-unreachable.md).
- Jobs fail: [failed jobs](runbooks/job-dead-letters.md).
- Every error message has a request id: give it to your administrator, who finds it in the logs and the audit log.
