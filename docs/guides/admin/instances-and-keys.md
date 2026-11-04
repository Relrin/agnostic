# Instances and keys

An instance is one AgentOS runtime the control plane manages. The control plane never holds a shared admin key for
it: it signs a short-lived JWT for every call, carrying exactly the caller's scopes, and AgentOS enforces them.

## Connect a runtime

*Instances › Connect* walks through four steps:

1. **Probe** the URL: DNS, TCP, TLS, then `GET /info` (AgentOS id, agno version, auth mode, user isolation).
2. **Connect** registers the instance and generates an RS256 key pair (3072-bit). The private key is sealed with
   the master key and never leaves the API; only signed tokens do.
3. **Trust**: give the runtime the public key and the expected audience and issuer. *Settings › Connection* shows
   the snippet:

   ```python
   Authorization(algorithm="RS256", verify_audience=True, audience="<os_id>", issuer="<public url>")
   ```

   with `JWT_VERIFICATION_KEY` set to the public key (or `JWT_JWKS_FILE`). The reference runtime takes
   `JWT_VERIFICATION_KEY` and `RUNTIME_JWT_ISSUER` (see [Bridge and runtime](../bridge-and-runtime.md)).
4. **Test connection** repeats the probe, then sends a `config:read` token (a 401 means a key or audience mismatch,
   and the step says which) and a token with no scopes (it must be refused, or AgentOS isn't enforcing scopes).

Tokens live 5 minutes by default (`AGNOSTIC_INSTANCES__TOKEN_TTL_SECONDS`, 30–3600) and carry `iss` (the public URL,
or `AGNOSTIC_INSTANCES__ISSUER`), `aud` (the AgentOS id), `sub` (the person's id or email, per instance) and
`scopes`. Health is polled every minute, `/config` and the capability matrix every five minutes.

Runtimes started with `OS_SECURITY_KEY` instead of JWT verification can be connected too: the key is sealed like
any other secret, but such runtimes have no per-user permissions, so only Instance admins can use them through the
gateway.

## Rotate an instance's keys

Rotation is two steps, so the runtime never sees a token it can't verify:

1. *Settings › Keys › Rotate* stages a **next** key. The JWKS document at
   `/.well-known/agnostic/instances/<id>/jwks.json` now lists the active and the next key.
2. Make the runtime trust the next key: with `agnostic-bridge` it reads the JWKS document; without it, add the next
   public key to `JWT_VERIFICATION_KEY` and restart.
3. *Activate* the next key. Tokens are signed with it from now on; the old key is retired.

*Cancel* drops a staged key. See also the [key rotation runbook](../runbooks/key-rotation.md).

## TLS to runtimes

Each instance has its own TLS options in *Settings › Connection*:

| Option | Does |
|---|---|
| Verify TLS | on by default; off encrypts without checking the certificate (development only) |
| CA bundle | PEM certificates trusted for this runtime only, in addition to the system store |
| Client certificate | a certificate chain and its private key presented to the runtime (mutual TLS) |

`AGNOSTIC_TLS__CA_FILE` adds your organization's CA certificates to the trust of **every** outbound HTTPS call:
runtimes, identity providers, object storage, SIEM webhooks, KMS and git hosts. Use it when they sit behind a
private CA or a TLS-inspecting proxy, and per-instance bundles for exceptions.

### Client certificates (mutual TLS)

When a proxy in front of the runtime requires client certificates, paste the certificate chain and its unencrypted
private key (PEM) in *Settings › Connection › Client certificate*, or send them when connecting
(`client_cert_pem`, `client_key_pem`). Both are checked to load and belong together. The key is sealed with the
master key, never shown again, and opened only when a connection is set up. *Remove* sends both fields empty.
Replacing or removing it is audited (`instances.update`, field `client_certificate`).

`agnostic config check --connect` and the System page's endpoint checks report the TLS mode of each runtime
(`tls=mutual`, `verified` or `unverified`).

## Direct mode

By default browsers reach runtimes only through the gateway. An instance can instead let browsers call it directly
with a short-lived token: see [Direct mode](direct-mode.md).
