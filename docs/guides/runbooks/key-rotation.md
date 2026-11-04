# Runbook: key rotation

Two kinds of keys rotate: an instance's **JWT signing key** (the runtime verifies tokens with its public half) and
the **master key** (it seals every stored secret). Rotate JWT keys yearly or when one may have leaked; rotate the
master key yearly, when someone who had it leaves, or when it may have leaked.

## An instance's JWT key

1. *Settings › Keys › Rotate* stages a next key. The JWKS document
   (`/.well-known/agnostic/instances/<id>/jwks.json`) lists the active and the next key.
2. Make the runtime trust both:
   - with agnostic-bridge reading the JWKS document: nothing to do;
   - otherwise add the next public key to `JWT_VERIFICATION_KEY` (or the JWKS file) and restart the runtime.
3. *Test connection* still passes (tokens are still signed with the active key).
4. *Activate*. Tokens are signed with the new key from now on.
5. *Test connection*. Then remove the old public key from the runtime's configuration.

If the old key leaked: activate right after the runtime trusts the new key, and remove the old key from the runtime
at once. Tokens signed with it expire within 5 minutes anyway.

**Verify**: *Settings › Keys* shows one active key; `agnostic_gateway_upstream_duration_seconds_count{outcome="error"}`
doesn't rise; the audit log has `instances.keys.stage` and `instances.keys.activate`.

## The master key

1. Create the new key:

   ```bash
   agnostic secrets generate-key       # with a KMS provider configured, it prints the wrapped key
   ```

   Store it with your backups.
2. Set it as `AGNOSTIC_SECRETS__MASTER_KEY` and move the old one into `AGNOSTIC_SECRETS__PREVIOUS_KEYS`. Roll out the
   API and workers.
3. Re-seal everything:

   ```bash
   agnostic secrets rotate
   agnostic secrets status             # "every value uses the current key"
   ```

4. Keep the previous key for at least a day (cached values expire) and until service-account gateway tokens have
   been used once, unless `AGNOSTIC_SERVICE_ACCOUNTS__TOKEN_PEPPER` is set. Then remove it and roll out again.

If the old key leaked, also rotate what it protected that an attacker could use outside Agnostic: instance JWT keys
(above), IdP client secrets, git tokens, SIEM and notification credentials, the archive access key.

**Verify**: `agnostic config check --connect` shows the new `key_id` and `previous=none`; `agnostic secrets status`
exits 0.

Rotating the **KMS key** only (same master key): rotate it in the KMS, then `agnostic secrets wrap-key --to <provider>`
and replace the configured values. Nothing needs re-sealing. Details: [Key management](../admin/key-management.md).
