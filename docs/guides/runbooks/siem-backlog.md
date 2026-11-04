# Runbook: SIEM backlog

## Symptoms

- A destination in *Organization › SIEM streaming* shows *Failing*; Owners and Administrators got a notification.
- *System › Background work* lists `SIEM: <name>` as error, with the last error.
- Your SIEM stopped receiving Agnostic events.

Nothing is lost while a destination fails: each destination has a cursor that only advances after the destination
accepted a batch. The backlog is everything after the cursor.

## Confirm

*Test delivery* on the destination shows the error the destination returns. Common ones:

| Error | Cause |
|---|---|
| connection refused, timeout | the receiver is down, or a firewall or NetworkPolicy blocks the worker |
| certificate verify failed | the receiver's CA isn't trusted: add it to the destination (syslog) or `AGNOSTIC_TLS__CA_FILE` |
| 401 / 403 | the token or signing secret changed on the receiver |
| 413 | batches too large for the receiver: lower `AGNOSTIC_AUDIT__DELIVERY_BATCH` (500 by default) |

## Fix

1. Fix the receiver, the network path or the credentials (edit the destination; secrets are kept unless you enter
   new ones).
2. *Test delivery* until it succeeds.
3. The worker resumes from the cursor on its next run and catches up in batches, in order. *Pause* stops delivery
   without losing the position, for planned receiver maintenance.

To skip a backlog you don't want delivered (for example after pointing a destination at a new SIEM), delete the
destination and create a new one: a new destination starts at the newest event.

## Verify

The destination turns *OK*, *System › Background work* shows it ok with a recent last event, and the receiver gets
events in order. Deduplicate on the event `id`: delivery is at least once.
