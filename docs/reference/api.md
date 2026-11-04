# API reference

Generated from the OpenAPI document by `scripts/render_api_reference.py`; don't edit by hand. Every route is under
the API's origin; `/api/v1` is stable from 1.0 (breaking changes need `/api/v2`). Conventions (problem details,
request ids, cursor pagination, CSRF on cookie sessions, bearer service-account tokens):
[API conventions](api-conventions.md). The full schema: `GET /api/v1/openapi.json`; interactive: `/api/v1/docs`.

AgentOS routes are called through the gateway, `ANY /api/v1/instances/{instance}/os/{path}`, as the signed-in person;
they're described by the runtime's own OpenAPI document and not repeated here.

## access

| Method | Path | Does |
|---|---|---|
| `GET` | `/api/v1/access/bindings` | Role bindings, optionally for one principal, kind, role or instance |
| `POST` | `/api/v1/access/bindings` | Give a person or group a role (or scopes) on an instance |
| `DELETE` | `/api/v1/access/bindings/{binding_id}` | Remove a binding |
| `POST` | `/api/v1/access/explain` | Why someone can or can't do something, and what would grant it |
| `GET` | `/api/v1/access/requests` | Temporary access requests: yours, or the ones you can decide |
| `POST` | `/api/v1/access/requests` | Ask for temporary access |
| `POST` | `/api/v1/access/requests/{request_id}/approve` | Approve a request: creates a binding that expires |
| `POST` | `/api/v1/access/requests/{request_id}/cancel` | Withdraw your own request |
| `POST` | `/api/v1/access/requests/{request_id}/deny` | Deny a request |
| `GET` | `/api/v1/access/roles` | Access roles (built-in and custom) with their scopes and who holds them |
| `POST` | `/api/v1/access/roles` | Create a custom access role |
| `GET` | `/api/v1/access/roles/{role_id}` | One access role |
| `PATCH` | `/api/v1/access/roles/{role_id}` | Save a role (a new version); holders get the new scopes on their next request |
| `DELETE` | `/api/v1/access/roles/{role_id}` | Delete a custom role (409 with its bindings while it is still bound) |
| `POST` | `/api/v1/access/roles/{role_id}/duplicate` | Copy a role as a custom role |
| `GET` | `/api/v1/access/roles/{role_id}/holders` | People, groups and service accounts holding a role |
| `POST` | `/api/v1/access/roles/{role_id}/preview` | What saving this draft would change, and for whom |
| `POST` | `/api/v1/access/roles/{role_id}/reset` | Put a built-in role back to its defaults (a new version) |
| `GET` | `/api/v1/access/roles/{role_id}/versions` | Saved versions of a role, newest first |
| `GET` | `/api/v1/access/scopes` | The scope catalog: AgentOS 3.1 and control-plane scopes |
| `POST` | `/api/v1/access/temporary` | Grant temporary access directly (Owners, Administrators) |

## approvals

| Method | Path | Does |
|---|---|---|
| `GET` | `/api/v1/approvals/routes` | Org-wide routing rules (needs settings:write) |
| `POST` | `/api/v1/approvals/routes` | Add an org-wide routing rule (needs settings:write) |
| `GET` | `/api/v1/approvals/routes/by-group/{group_id}` | Routing rules naming a group, on any instance |
| `PUT` | `/api/v1/approvals/routes/{route_id}` | Change a routing rule |
| `DELETE` | `/api/v1/approvals/routes/{route_id}` | Remove a routing rule |
| `GET` | `/api/v1/instances/{instance}/approvals` | Approvals by tab and filters, newest first (needs approvals:read) |
| `GET` | `/api/v1/instances/{instance}/approvals/count` | Pending approvals on the instance (the nav badge; live updates arrive as approvals.count events) |
| `GET` | `/api/v1/instances/{instance}/approvals/counts` | How many approvals each tab holds (needs approvals:read) |
| `GET` | `/api/v1/instances/{instance}/approvals/policy` | Whether expiry stops runs on this instance, and its TTL |
| `PUT` | `/api/v1/instances/{instance}/approvals/policy` | Change the expiry policy (Instance admin; audited) |
| `GET` | `/api/v1/instances/{instance}/approvals/routes` | Routing rules of the instance, then the org-wide ones |
| `POST` | `/api/v1/instances/{instance}/approvals/routes` | Route approvals to members or roles |
| `GET` | `/api/v1/instances/{instance}/approvals/{approval_id}` | One approval with its context and timeline; records that you viewed it (needs approvals:read) |
| `POST` | `/api/v1/instances/{instance}/approvals/{approval_id}/decide` | Approve or reject a paused run's approval, then continue the run (needs approvals:write) |

## assistant

| Method | Path | Does |
|---|---|---|
| `GET` | `/api/v1/assistant/settings` | the org's AI features (needs settings:read) |
| `PUT` | `/api/v1/assistant/settings` | Change AI features: only the fields sent (needs settings:write; a new API key needs a recent sign-in) |
| `POST` | `/api/v1/assistant/settings/check` | Send the configured model one tiny prompt and report what happened |
| `GET` | `/api/v1/assistant/status` | Which AI features work for you right now, and the token budget |
| `GET` | `/api/v1/instances/{instance}/assistant/conversations` | Your conversations on this instance, most recent first |
| `GET` | `/api/v1/instances/{instance}/assistant/conversations/{conversation_id}` | One of your conversations with its messages |
| `DELETE` | `/api/v1/instances/{instance}/assistant/conversations/{conversation_id}` | Delete a conversation |
| `POST` | `/api/v1/instances/{instance}/assistant/explanations` | Queue a generated explanation or suggestion next to a page's own text (reused unless regenerate) |
| `GET` | `/api/v1/instances/{instance}/assistant/messages/{message_id}` | An answer or explanation as it stands |
| `POST` | `/api/v1/instances/{instance}/assistant/messages/{message_id}/cancel` | Stop an answer that is still being written |
| `GET` | `/api/v1/instances/{instance}/assistant/messages/{message_id}/events` | Follow an answer as it is written (text/event-stream; resumes from Last-Event-ID) |
| `POST` | `/api/v1/instances/{instance}/assistant/questions` | Ask your OS: queue a question; follow the answer at …/messages/{message_id}/events |

## audit

| Method | Path | Does |
|---|---|---|
| `GET` | `/api/v1/audit/actions` | The audit vocabulary: every action and its summary template |
| `GET` | `/api/v1/audit/actors` | People and machines in the log over the last 90 days, most active first |
| `GET` | `/api/v1/audit/archives` | Archived months, newest first |
| `POST` | `/api/v1/audit/archives/{month}/restore` | Re-import an archived month (YYYY-MM) for 7 days of searching (runs in the background) |
| `GET` | `/api/v1/audit/events` | Audit events, newest first |
| `GET` | `/api/v1/audit/events/{event_id}` | One audit event |
| `GET` | `/api/v1/audit/export` | Download matching events (up to 10 000; larger ranges answer 413: use POST /audit/exports) |
| `GET` | `/api/v1/audit/exports` | The caller's background exports from the last 24 hours |
| `POST` | `/api/v1/audit/exports` | Start a background export of any size (kept 24 h) |
| `GET` | `/api/v1/audit/exports/{export_id}` | One background export |
| `GET` | `/api/v1/audit/exports/{export_id}/download` | The finished export as CSV or JSONL (stored compressed, decompressed while it streams) |
| `GET` | `/api/v1/audit/policy` | Retention, archive and hash-chain policy (the secret key is never returned) |
| `PUT` | `/api/v1/audit/policy` | Change the policy (only the fields sent) |
| `POST` | `/api/v1/audit/policy/test-write` | Write, read back and delete a small object in the archive bucket (stored settings, overlaid by the body) |
| `GET` | `/api/v1/audit/sinks` | SIEM sinks (secrets left out) |
| `POST` | `/api/v1/audit/sinks` | Add a SIEM sink (streams events from now on) |
| `PATCH` | `/api/v1/audit/sinks/{sink_id}` | Change a sink; enabling it again clears its failing state |
| `DELETE` | `/api/v1/audit/sinks/{sink_id}` | Remove a sink |
| `POST` | `/api/v1/audit/sinks/{sink_id}/test` | Send one synthetic event to the sink now |
| `GET` | `/api/v1/audit/stream-status` | Whether events are streaming to a SIEM, for the header pill |
| `POST` | `/api/v1/audit/verify` | Check the tamper-evidence hash chain over a time range |
| `GET` | `/api/v1/audit/views` | Saved views: the caller's own and the shared ones, with event counts |
| `POST` | `/api/v1/audit/views` | Save the current filters as a view |
| `PATCH` | `/api/v1/audit/views/{view_id}` | Rename, re-filter or move a view |
| `DELETE` | `/api/v1/audit/views/{view_id}` | Delete a view |

## auth

| Method | Path | Does |
|---|---|---|
| `GET` | `/api/v1/auth/admin/policy` | The org's authentication policy |
| `PUT` | `/api/v1/auth/admin/policy` | Change the authentication policy: enforce SSO, break-glass Owner, session lifetimes, MFA |
| `GET` | `/api/v1/auth/admin/providers` | Sign-in providers: from settings (read-only) and managed here |
| `POST` | `/api/v1/auth/admin/providers` | Add an OIDC / OAuth 2 or SAML provider (needs a recent sign-in or step-up) |
| `GET` | `/api/v1/auth/admin/providers/{provider_id}` | One sign-in provider |
| `PATCH` | `/api/v1/auth/admin/providers/{provider_id}` | Change a provider (needs a recent sign-in or step-up) |
| `DELETE` | `/api/v1/auth/admin/providers/{provider_id}` | Delete a provider and its account links (needs a recent sign-in or step-up) |
| `GET` | `/api/v1/auth/admin/providers/{provider_id}/saml-metadata` | SAML service-provider metadata to import at the IdP |
| `POST` | `/api/v1/auth/login` | Sign in with email and password |
| `POST` | `/api/v1/auth/login/mfa` | Finish signing in with a second factor (or enroll one) |
| `POST` | `/api/v1/auth/login/mfa/totp/setup` | While signing in: set up an authenticator app (when required) |
| `POST` | `/api/v1/auth/login/mfa/webauthn/options` | While signing in: WebAuthn request options (or creation options when enrolling) |
| `POST` | `/api/v1/auth/logout` | Sign out of this browser |
| `POST` | `/api/v1/auth/password/reset` | Email a password-reset link (always accepted, so accounts can't be discovered) |
| `POST` | `/api/v1/auth/password/reset/confirm` | Choose a new password with a reset token; signs out every session |
| `GET` | `/api/v1/auth/providers` | How people can sign in: password and/or SSO providers |
| `POST` | `/api/v1/auth/sso/{provider}/acs` | SAML assertion consumer service: the IdP posts SAMLResponse and RelayState here |
| `GET` | `/api/v1/auth/sso/{provider}/callback` | Where the SSO provider sends people back (redirects into the app) |
| `GET` | `/api/v1/auth/sso/{provider}/metadata` | This installation's SAML service-provider metadata for an enabled SAML provider (public) |
| `GET` | `/api/v1/auth/sso/{provider}/start` | Start signing in with an SSO provider (redirects to it) |
| `GET` | `/api/v1/auth/step-up` | How recently you confirmed it's you, and how you can |
| `POST` | `/api/v1/auth/step-up` | Confirm it's you (password, authenticator code or security key) before a sensitive change |
| `POST` | `/api/v1/auth/step-up/webauthn/options` | WebAuthn request options for a step-up |

## context

| Method | Path | Does |
|---|---|---|
| `POST` | `/api/v1/context/data-subject-requests` | Delete one person's learnings on every instance where you hold learnings:delete |
| `GET` | `/api/v1/instances/{instance}/files/provenance` | Which runs wrote and read a workspace file (exact with agnostic-bridge, otherwise best effort) |
| `GET` | `/api/v1/instances/{instance}/knowledge/bases` | Knowledge bases with entry counts, vector databases and the agents and teams that read them |
| `GET` | `/api/v1/instances/{instance}/knowledge/content` | Knowledge content filtered by status, type and text, with status and type counts (needs knowledge:read) |
| `GET` | `/api/v1/instances/{instance}/learnings/counts` | Learning records per type (needs learnings:read) |
| `POST` | `/api/v1/instances/{instance}/learnings/delete-user` | Delete one user's learnings, or one type of them, after typing the user id (needs learnings:delete) |
| `GET` | `/api/v1/instances/{instance}/memories/duplicates` | Likely duplicate memories of one user (trigram similarity; needs memories:read) |
| `POST` | `/api/v1/instances/{instance}/memories/optimize` | Preview (apply=false) or apply the summarize optimization of a user's memories (needs memories:write) |
| `GET` | `/api/v1/instances/{instance}/memories/{memory_id}/source` | The run a memory most likely came from: its session and the input the user sent (best effort) |

## directory

| Method | Path | Does |
|---|---|---|
| `GET` | `/api/v1/directory/google` | Google Workspace sync: config (without the key) and the last run |
| `PUT` | `/api/v1/directory/google` | Configure Google Workspace sync (omitted fields stay as they are) |
| `POST` | `/api/v1/directory/google/sync` | Run the Google Workspace sync now |
| `POST` | `/api/v1/directory/google/test` | Check that the service account can read the directory |
| `GET` | `/api/v1/directory/groups` | Groups with their member counts and where they come from |
| `POST` | `/api/v1/directory/groups` | Create a manual group |
| `GET` | `/api/v1/directory/groups/{group_id}` | A group and its members |
| `PATCH` | `/api/v1/directory/groups/{group_id}` | Rename a group or change its description |
| `DELETE` | `/api/v1/directory/groups/{group_id}` | Delete a group and its role bindings |
| `PUT` | `/api/v1/directory/groups/{group_id}/members/{user_id}` | Add someone to a group (or change their role in it) |
| `DELETE` | `/api/v1/directory/groups/{group_id}/members/{user_id}` | Remove someone from a manual group |
| `GET` | `/api/v1/directory/mapping-rules` | IdP group → Agnostic group mapping rules |
| `POST` | `/api/v1/directory/mapping-rules` | Add the members of an IdP group to a manual group (applied at once) |
| `DELETE` | `/api/v1/directory/mapping-rules/{rule_id}` | Delete a mapping rule and the memberships it made |
| `GET` | `/api/v1/directory/scim` | SCIM endpoint, last sync, counts and the tokens that still work |
| `POST` | `/api/v1/directory/scim/tokens` | Create the SCIM token (shown only in this response) |
| `DELETE` | `/api/v1/directory/scim/tokens/{token_id}` | Revoke a SCIM token |
| `POST` | `/api/v1/directory/scim/tokens/{token_id}/rotate` | Issue a new SCIM token; the old one keeps working for 24 hours or until revoked |
| `GET` | `/api/v1/directory/settings` | Directory sync settings (deprovisioning behaviour) |
| `PUT` | `/api/v1/directory/settings` | Change the deprovisioning behaviour |

## evals

| Method | Path | Does |
|---|---|---|
| `POST` | `/api/v1/instances/{instance}/eval-batches` | Evaluate a component version on a dataset: one eval run per case, in the background |
| `GET` | `/api/v1/instances/{instance}/eval-batches/{batch_id}` | An evaluation with its cases and progress |
| `POST` | `/api/v1/instances/{instance}/eval-batches/{batch_id}/cancel` | Stop an evaluation between cases |
| `GET` | `/api/v1/instances/{instance}/eval-batches/{batch_id}/compare` | Case-by-case comparison with another evaluation of the same dataset |
| `GET` | `/api/v1/instances/{instance}/eval-datasets` | Eval datasets (org-wide; needs evals:read on this instance) |
| `POST` | `/api/v1/instances/{instance}/eval-datasets` | Create a dataset, optionally with its cases |
| `GET` | `/api/v1/instances/{instance}/eval-datasets/{dataset_id}` | A dataset with its cases |
| `PATCH` | `/api/v1/instances/{instance}/eval-datasets/{dataset_id}` | Rename or describe a dataset |
| `DELETE` | `/api/v1/instances/{instance}/eval-datasets/{dataset_id}` | Delete a dataset (past evaluations keep their case snapshots) |
| `POST` | `/api/v1/instances/{instance}/eval-datasets/{dataset_id}/cases` | Append cases |
| `PATCH` | `/api/v1/instances/{instance}/eval-datasets/{dataset_id}/cases/{case_id}` | Change a case |
| `DELETE` | `/api/v1/instances/{instance}/eval-datasets/{dataset_id}/cases/{case_id}` | Delete a case |
| `POST` | `/api/v1/instances/{instance}/eval-datasets/{dataset_id}/import` | Import cases from CSV or JSONL text |
| `GET` | `/api/v1/instances/{instance}/eval-gates` | Publish gates with what each would do right now |
| `PUT` | `/api/v1/instances/{instance}/eval-gates` | Create or change the gate for a component and dataset (needs evals:gates:write) |
| `DELETE` | `/api/v1/instances/{instance}/eval-gates/{gate_id}` | Remove a publish gate |
| `GET` | `/api/v1/instances/{instance}/eval-results` | The newest finished evaluation per dataset for one component version |
| `GET` | `/api/v1/instances/{instance}/evals/capabilities` | Whether drafts and pinned versions can be evaluated here (needs agnostic-bridge) |
| `GET` | `/api/v1/instances/{instance}/evaluations` | Evaluations table: dataset batches run here plus AgentOS eval runs created elsewhere |

## gateway

| Method | Path | Does |
|---|---|---|
| `GET` | `/api/v1/gateway/policies` | The route policy table: which scopes each AgentOS route needs |
| `POST` | `/api/v1/instances/{instance}/token` | Direct mode: a short-lived token to call the runtime from the browser |

## instances

| Method | Path | Does |
|---|---|---|
| `GET` | `/api/v1/instances` | Connected AgentOS instances |
| `POST` | `/api/v1/instances` | Connect wizard, step 2: register an instance and its key pair |
| `POST` | `/api/v1/instances/probe` | Connect wizard, step 1: discover what is at an endpoint (nothing is saved) |
| `GET` | `/api/v1/instances/{instance}` | One instance (by id or slug) |
| `PATCH` | `/api/v1/instances/{instance}` | Change an instance's name, environment, endpoint, TLS, keys, network mode or elevation |
| `DELETE` | `/api/v1/instances/{instance}` | Delete the instance record (the runtime keeps running; its tokens stop being minted) |
| `GET` | `/api/v1/instances/{instance}/capabilities` | The capability matrix (07 §3) |
| `GET` | `/api/v1/instances/{instance}/config` | The runtime's /config, as last fetched (needs config:read there) |
| `POST` | `/api/v1/instances/{instance}/discover` | Read /info again (version, auth mode, isolation) |
| `GET` | `/api/v1/instances/{instance}/health` | Reachability, latency, version drift and capabilities |
| `GET` | `/api/v1/instances/{instance}/keys/public` | Public keys, the config snippet and the JWKS location |
| `POST` | `/api/v1/instances/{instance}/keys/rotate` | Rotate the key pair: stage a next key, then activate it |
| `POST` | `/api/v1/instances/{instance}/keys/verify` | Verify a token against this instance's keys |
| `POST` | `/api/v1/instances/{instance}/test` | Test connection: DNS, TLS, AgentOS, version, token, enforced scopes |

## invitations

| Method | Path | Does |
|---|---|---|
| `GET` | `/api/v1/invitations` | Pending invitations |
| `POST` | `/api/v1/invitations` | Invite someone by email |
| `DELETE` | `/api/v1/invitations/{invitation_id}` | Revoke an invitation |
| `POST` | `/api/v1/invitations/{invitation_id}/resend` | Send the invitation again with a fresh link |
| `POST` | `/api/v1/invitations/{token}/accept` | Accept an invitation with a password; signs you in |
| `GET` | `/api/v1/invitations/{token}/preview` | What an invitation link is for (no sign-in needed) |

## jwks

| Method | Path | Does |
|---|---|---|
| `GET` | `/.well-known/agnostic/instances/{instance_id}/jwks.json` | Public keys of an instance (current and next), JWKS |

## me

| Method | Path | Does |
|---|---|---|
| `GET` | `/api/v1/me` | The signed-in person: profile, org role, preferences |
| `PATCH` | `/api/v1/me` | Change your name, locale, time zone or preferences |
| `GET` | `/api/v1/me/access` | Your effective access, on an instance or org-wide |
| `GET` | `/api/v1/me/mfa` | Your second factors and the org's MFA policy |
| `POST` | `/api/v1/me/mfa/recovery-codes` | Replace your recovery codes (shown once; needs a recent sign-in or step-up) |
| `POST` | `/api/v1/me/mfa/totp/confirm` | Confirm the authenticator app with a code from it |
| `POST` | `/api/v1/me/mfa/totp/setup` | Start setting up an authenticator app (pending until confirmed) |
| `POST` | `/api/v1/me/mfa/webauthn/options` | WebAuthn creation options for a new security key or passkey |
| `POST` | `/api/v1/me/mfa/webauthn/verify` | Register the security key or passkey |
| `DELETE` | `/api/v1/me/mfa/{factor_id}` | Remove a second factor (needs a recent sign-in or step-up) |
| `GET` | `/api/v1/me/sessions` | Your signed-in browsers |
| `DELETE` | `/api/v1/me/sessions/{session_id}` | Sign out a browser |

## members

| Method | Path | Does |
|---|---|---|
| `GET` | `/api/v1/members` | Members of the org with their org roles |
| `POST` | `/api/v1/members/bulk` | Change the org role of, add to a group, or remove several members |
| `GET` | `/api/v1/members/export.csv` | Members as CSV: email, name, org role, groups, joined, last active |
| `GET` | `/api/v1/members/{user_id}` | One member |
| `PATCH` | `/api/v1/members/{user_id}` | Change a member's org role |
| `DELETE` | `/api/v1/members/{user_id}` | Remove someone from the org (signs them out) |

## notifications

| Method | Path | Does |
|---|---|---|
| `GET` | `/api/v1/events` | Realtime control-plane events for the signed-in person (text/event-stream) |
| `GET` | `/api/v1/me/notification-preferences` | Which channels each event reaches you through, and quiet hours |
| `PUT` | `/api/v1/me/notification-preferences` | Change your notification channels or quiet hours |
| `GET` | `/api/v1/notifications` | Your notifications (the bell), newest first |
| `GET` | `/api/v1/notifications/channels` | Org notification channels (needs notifications:write) |
| `POST` | `/api/v1/notifications/channels` | Add a Slack, email or webhook channel |
| `GET` | `/api/v1/notifications/channels/{channel_id}` | One channel with its recent deliveries |
| `PATCH` | `/api/v1/notifications/channels/{channel_id}` | Change a channel (secrets left out are kept) |
| `DELETE` | `/api/v1/notifications/channels/{channel_id}` | Remove a channel |
| `POST` | `/api/v1/notifications/channels/{channel_id}/test` | Send a test message now and report the outcome |
| `GET` | `/api/v1/notifications/defaults` | Org default channels per event type (needs notifications:write) |
| `PUT` | `/api/v1/notifications/defaults` | Change org default channels (needs notifications:write; audited) |
| `GET` | `/api/v1/notifications/event-types` | Everything that can be notified, with its default channels |
| `POST` | `/api/v1/notifications/read` | Mark some or all of your notifications read |
| `GET` | `/api/v1/notifications/unread-count` | How many of your notifications are unread (the bell badge) |

## observe

| Method | Path | Does |
|---|---|---|
| `GET` | `/api/v1/instances/{instance}/metrics/export.csv` | Usage and estimated cost per component as CSV |
| `GET` | `/api/v1/instances/{instance}/metrics/summary` | Metrics page: daily aggregates, per-component usage, model usage and estimated cost |
| `GET` | `/api/v1/instances/{instance}/overview` | Home: what needs attention, KPIs, runs per day, model usage, primitives and recent activity |
| `GET` | `/api/v1/instances/{instance}/price-table` | The effective price table: org defaults with this instance's overrides |
| `PUT` | `/api/v1/instances/{instance}/price-table` | Replace this instance's price overrides (needs metrics:write); returns the effective table |
| `GET` | `/api/v1/instances/{instance}/traces/span-stats` | Slowest span types: average duration per span name over the newest traces of a window (needs traces:read) |
| `GET` | `/api/v1/instances/{instance}/traces/{trace_id}/comparison` | Compare a trace with the last successful run of the same component: aligned spans and a diagnosis |
| `GET` | `/api/v1/price-table` | The org's default price table |
| `PUT` | `/api/v1/price-table` | Replace the org's default price table (needs org:write) |

## onboarding

| Method | Path | Does |
|---|---|---|
| `POST` | `/api/v1/onboarding/complete` | Create the first Owner with the setup link from `agnostic bootstrap` |
| `GET` | `/api/v1/onboarding/status` | Whether the installation still needs its first Owner |

## org

| Method | Path | Does |
|---|---|---|
| `GET` | `/api/v1/org` | The org: profile, seats, settings and your org role |
| `PATCH` | `/api/v1/org` | Change the org profile or org settings |

## queue

| Method | Path | Does |
|---|---|---|
| `GET` | `/api/v1/instances/{instance}/queue/jobs` | Durable jobs, newest first (queue:operate or Instance admin) |
| `GET` | `/api/v1/instances/{instance}/queue/jobs/{job_id}` | One job with its attempts and checkpoints |
| `POST` | `/api/v1/instances/{instance}/queue/jobs/{job_id}/cancel` | Cancel a queued or running job's run (audited) |
| `POST` | `/api/v1/instances/{instance}/queue/jobs/{job_id}/requeue` | One more attempt with the same run id (audited) |
| `POST` | `/api/v1/instances/{instance}/queue/jobs/{job_id}/resume` | Continue a failed run from a checkpoint; earlier tool calls aren't repeated (audited) |
| `GET` | `/api/v1/instances/{instance}/queue/overview` | Queue health, config and workers (queue:operate or Instance admin) |
| `GET` | `/api/v1/instances/{instance}/queue/summary` | Job counts for anyone with access to the instance |
| `GET` | `/api/v1/instances/{instance}/queue/workers` | Replicas with heartbeats and slots (queue:operate or Instance admin) |

## scheduler

| Method | Path | Does |
|---|---|---|
| `GET` | `/api/v1/instances/{instance}/schedules` | Schedules with their latest runs (needs schedules:read) |
| `POST` | `/api/v1/instances/{instance}/schedules` | Create a schedule (schedules:write; a custom endpoint needs Instance admin) |
| `GET` | `/api/v1/instances/{instance}/schedules/endpoint-check` | What an endpoint targets, and whether the instance's OpenAPI document knows it |
| `POST` | `/api/v1/instances/{instance}/schedules/preview` | A cron expression as a sentence, its next runs, DST notes |
| `GET` | `/api/v1/instances/{instance}/schedules/status` | Whether the scheduler runs, and what you may do here |
| `GET` | `/api/v1/instances/{instance}/schedules/{schedule_id}` | One schedule with its recent runs |
| `PATCH` | `/api/v1/instances/{instance}/schedules/{schedule_id}` | Change a schedule (schedules:write) |
| `DELETE` | `/api/v1/instances/{instance}/schedules/{schedule_id}` | Delete a schedule (schedules:delete) |
| `POST` | `/api/v1/instances/{instance}/schedules/{schedule_id}/disable` | Disable a schedule, with a reason (schedules:write) |
| `POST` | `/api/v1/instances/{instance}/schedules/{schedule_id}/enable` | Enable a schedule (schedules:write) |
| `GET` | `/api/v1/instances/{instance}/schedules/{schedule_id}/runs` | Run history of a schedule, newest first |
| `POST` | `/api/v1/instances/{instance}/schedules/{schedule_id}/trigger` | Run a schedule now (schedules:write) |

## search

| Method | Path | Does |
|---|---|---|
| `GET` | `/api/v1/search` | Command-palette search over people, instances, agents, teams and workflows |

## service-accounts

| Method | Path | Does |
|---|---|---|
| `GET` | `/api/v1/service-accounts` | Service accounts: scopes, instances, who created them, last use, expiry |
| `POST` | `/api/v1/service-accounts` | Create a service account, its grants and tokens (each token is returned once) |
| `POST` | `/api/v1/service-accounts/preview` | The principal, privileged scopes and CLI command of a create form, without creating |
| `GET` | `/api/v1/service-accounts/{account}` | One service account (id, name or sa:<name>) with its scopes and tokens |
| `DELETE` | `/api/v1/service-accounts/{account}` | Delete a service account: revoke every token (natively on each instance) and remove its grants |
| `POST` | `/api/v1/service-accounts/{account}/tokens` | Issue a token, or rotate the current one (gateway: 24 h grace; native: revoke and recreate) |
| `DELETE` | `/api/v1/service-accounts/{account}/tokens/{token}` | Revoke a token now (by id or prefix) |

## sources

| Method | Path | Does |
|---|---|---|
| `GET` | `/api/v1/instances/{instance}/studio/components/{component_id}/source` | Where the component is synced (source bar) |
| `GET` | `/api/v1/instances/{instance}/studio/sources` | Code sources synced with the instance |
| `POST` | `/api/v1/instances/{instance}/studio/sources` | Connect a repository or local folder (scans it) |
| `GET` | `/api/v1/instances/{instance}/studio/sources/conflicts/count` | Open conflicts on the instance (the sidebar dot) |
| `GET` | `/api/v1/instances/{instance}/studio/sources/local-roots` | Folders local sources may point into |
| `GET` | `/api/v1/instances/{instance}/studio/sources/{source_id}` | One source |
| `PATCH` | `/api/v1/instances/{instance}/studio/sources/{source_id}` | Change the branch, path mappings, sync policy or registry convention |
| `DELETE` | `/api/v1/instances/{instance}/studio/sources/{source_id}` | Disconnect (components stay in Studio) |
| `POST` | `/api/v1/instances/{instance}/studio/sources/{source_id}/activate` | Bind the scanned files and start syncing |
| `GET` | `/api/v1/instances/{instance}/studio/sources/{source_id}/changes` | Incoming and outgoing changes, conflicts and pull requests |
| `PATCH` | `/api/v1/instances/{instance}/studio/sources/{source_id}/changes/{change_id}` | Include or leave out a change |
| `GET` | `/api/v1/instances/{instance}/studio/sources/{source_id}/changes/{change_id}/diff` | The file before and after the change |
| `POST` | `/api/v1/instances/{instance}/studio/sources/{source_id}/commit` | Commit & open a pull request |
| `GET` | `/api/v1/instances/{instance}/studio/sources/{source_id}/commit-preview` | The branch, message and review requirement of a commit |
| `POST` | `/api/v1/instances/{instance}/studio/sources/{source_id}/conflicts/{conflict_id}/resolve` | Keep Studio's value, the repository's, or a merge |
| `GET` | `/api/v1/instances/{instance}/studio/sources/{source_id}/deliveries` | Recent webhook deliveries |
| `POST` | `/api/v1/instances/{instance}/studio/sources/{source_id}/fetch` | Fetch now and work out incoming changes |
| `POST` | `/api/v1/instances/{instance}/studio/sources/{source_id}/outgoing/refresh` | Work out what Studio has that the repository doesn't |
| `POST` | `/api/v1/instances/{instance}/studio/sources/{source_id}/pull` | Pull incoming changes as drafts (never published) |
| `POST` | `/api/v1/instances/{instance}/studio/sources/{source_id}/pull-requests/refresh` | Check the source's open pull requests now |
| `GET` | `/api/v1/instances/{instance}/studio/sources/{source_id}/scan` | The initial scan: files, parse results, matches and proposed bindings |
| `GET` | `/api/v1/studio/connections` | Connections to git hosts |
| `POST` | `/api/v1/studio/connections` | Connect a git host |
| `GET` | `/api/v1/studio/connections/github/callback` | Where GitHub returns after the app was installed |
| `GET` | `/api/v1/studio/connections/{connection_id}` | One connection |
| `PATCH` | `/api/v1/studio/connections/{connection_id}` | Change a connection (secrets only when given) |
| `DELETE` | `/api/v1/studio/connections/{connection_id}` | Remove |
| `GET` | `/api/v1/studio/connections/{connection_id}/branches` | Branches of a repository |
| `GET` | `/api/v1/studio/connections/{connection_id}/github/install` | Where to install the GitHub App |
| `GET` | `/api/v1/studio/connections/{connection_id}/repos` | Repositories the connection can see |
| `POST` | `/api/v1/studio/connections/{connection_id}/verify` | Check the connection's credentials |

## studio

| Method | Path | Does |
|---|---|---|
| `POST` | `/api/v1/instances/{instance}/studio/cel/evaluate` | Try a CEL expression on a sample: agno evaluates it through the bridge, else Agnostic does |
| `POST` | `/api/v1/instances/{instance}/studio/codegen` | Generated Python with span map, gutter marks, notes and ruff |
| `GET` | `/api/v1/instances/{instance}/studio/components` | Agents, teams or workflows: stored in Studio and defined in code |
| `POST` | `/api/v1/instances/{instance}/studio/components` | Create a component with draft v1 (blank, from a template, duplicated or imported) |
| `GET` | `/api/v1/instances/{instance}/studio/components/{component_id}` | A component with its versions, its open draft and its current version |
| `PATCH` | `/api/v1/instances/{instance}/studio/components/{component_id}` | Rename, describe, label or assign an owner group |
| `DELETE` | `/api/v1/instances/{instance}/studio/components/{component_id}` | Archive (409 lists the dependents) |
| `GET` | `/api/v1/instances/{instance}/studio/components/{component_id}/canvas-layout` | What was moved, collapsed or zoomed on the workflow canvas |
| `PUT` | `/api/v1/instances/{instance}/studio/components/{component_id}/canvas-layout` | Keep the canvas layout of a version |
| `POST` | `/api/v1/instances/{instance}/studio/components/{component_id}/configs` | A new draft from a version (default: the current one), member pins included |
| `GET` | `/api/v1/instances/{instance}/studio/components/{component_id}/configs/{version}` | One version with its config |
| `PATCH` | `/api/v1/instances/{instance}/studio/components/{component_id}/configs/{version}` | Save a draft (409 when someone else saved it first) |
| `DELETE` | `/api/v1/instances/{instance}/studio/components/{component_id}/configs/{version}` | Discard a draft |
| `GET` | `/api/v1/instances/{instance}/studio/components/{component_id}/configs/{version}/code` | The code of a code-backed draft, if it keeps one |
| `POST` | `/api/v1/instances/{instance}/studio/components/{component_id}/configs/{version}/publish` | Publish a draft; failed gates need override_reason and evals:gates:override |
| `POST` | `/api/v1/instances/{instance}/studio/components/{component_id}/configs/{version}/set-current` | Make a published version current (rollback) |
| `GET` | `/api/v1/instances/{instance}/studio/components/{component_id}/diff` | Field-level and code diff between two versions |
| `GET` | `/api/v1/instances/{instance}/studio/components/{component_id}/promotions` | Recent promotions of this component to other instances |
| `POST` | `/api/v1/instances/{instance}/studio/components/{component_id}/promotions` | Dry run: does every registry reference and pinned member exist on the target? |
| `GET` | `/api/v1/instances/{instance}/studio/components/{component_id}/publish-check` | Validation and eval gates for publishing a version |
| `POST` | `/api/v1/instances/{instance}/studio/components/{component_id}/restore` | Restore an archived component |
| `GET` | `/api/v1/instances/{instance}/studio/components/{component_id}/step-runs` | A step's latest results from the workflow's recent runs |
| `GET` | `/api/v1/instances/{instance}/studio/components/{component_id}/step-stats` | Average duration, runs and failures per step, from the traces |
| `POST` | `/api/v1/instances/{instance}/studio/components/{component_id}/test-runs` | Run a draft version and stream its events (delegated elevation; needs components:write and run) |
| `POST` | `/api/v1/instances/{instance}/studio/parse` | Code read back into a config, with what can't be stored located |
| `POST` | `/api/v1/instances/{instance}/studio/promotions/{promotion_id}/apply` | Create the drafts on the target (and publish) |
| `GET` | `/api/v1/instances/{instance}/studio/registry` | Everything Studio can compose with, with used-by counts |
| `POST` | `/api/v1/instances/{instance}/studio/registry/refresh` | Re-read the registry and rebuild the used-by index |
| `GET` | `/api/v1/instances/{instance}/studio/registry/{entry_type}/{name}` | One registry entry and where it's used |
| `POST` | `/api/v1/instances/{instance}/studio/transform` | A form edit applied to existing code, keeping its comments and layout; checked to read back as the edit |
| `POST` | `/api/v1/instances/{instance}/studio/validate` | Shape, registry references, rules and agno's strict load |
| `POST` | `/api/v1/instances/{instance}/studio/workflows/validate` | Workflow validation (structure, executors, CEL, agno's strict load) with the step count |
| `POST` | `/api/v1/studio/cel/check` | Type and exhaustiveness check of a CEL expression in its context |
| `GET` | `/api/v1/studio/cel/contexts` | Variables, functions and macros per context, for completion |
| `GET` | `/api/v1/studio/schema/{kind}` | JSON Schema of a config, with the form's sections and field metadata |
| `GET` | `/api/v1/studio/templates` | Starting points for new agents, teams and workflows |

## system

| Method | Path | Does |
|---|---|---|
| `POST` | `/api/v1/system/checks` | Probe every endpoint now (database, cache, master key, SMTP, IdPs, runtimes, …) |
| `GET` | `/api/v1/system/docs` | The user guides bundled with this installation |
| `GET` | `/api/v1/system/docs/{path}` | One bundled guide (Markdown) |
| `GET` | `/api/v1/system/features` | Control-plane features that are switched on |
| `GET` | `/api/v1/system/info` | Version and what this installation bundles |
| `GET` | `/api/v1/system/jobs/failed` | Failed background jobs (newest first) |
| `DELETE` | `/api/v1/system/jobs/{job_id}` | Discard a failed job |
| `POST` | `/api/v1/system/jobs/{job_id}/retry` | Run a failed job again |
| `GET` | `/api/v1/system/modules` | Enabled and disabled modules with what they contribute |
| `GET` | `/api/v1/system/status` | System overview: versions, job queues, cache, instance polling, backlogs |
| `GET` | `/healthz` | Healthz |
| `GET` | `/readyz` | Readyz |
