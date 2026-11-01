# Sign-in providers

People sign in to Agnostic with a **local account** (email + password, on by default) or through a **sign-in
provider**: GitHub, GitLab, Google, Okta or any OpenID Connect identity provider (Microsoft Entra ID,
Authentik, Dex, …). Each configured provider adds a button to the sign-in page. Settings are environment variables
(or the same keys in the TOML file); the full list is in
[reference/configuration](../reference/configuration.md#sign-in-identity-module).

## Local accounts

Nothing to configure. `agnostic bootstrap` creates the first Owner with a password, and invited people choose one
when they accept their invitation. This is the simplest setup for a single person or a small team, and the only one
that works without an identity provider.

- Invitations and password resets are sent by email: set `AGNOSTIC_SMTP__URL`, or read the links from the API log.
- Failed sign-ins lock the account for a while (`AGNOSTIC_IDENTITY__LOCKOUT_THRESHOLD` / `__LOCKOUT_MINUTES`);
  passwords need `AGNOSTIC_IDENTITY__PASSWORD_MIN_LENGTH` characters (12).
- To require SSO, set `AGNOSTIC_IDENTITY__LOCAL_LOGIN=false`, but only after an Owner has signed in through a
  provider at least once, so someone can still administer the org.

## How SSO works

Pick an id for the provider (`github`, `okta`, `entra`, …). It names the settings and appears, lower-cased, in the
callback URL you register at the provider:

```text
{AGNOSTIC_HTTP__PUBLIC_URL}/api/v1/auth/sso/<id>/callback
e.g. https://agnostic.localhost.company/api/v1/auth/sso/okta/callback
```

`AGNOSTIC_HTTP__PUBLIC_URL` must be the URL people actually open (behind your reverse proxy), or the provider will
reject the redirect.

```bash
AGNOSTIC_IDENTITY__PROVIDERS__<ID>__PRESET=okta            # github | gitlab | google | okta | oidc
AGNOSTIC_IDENTITY__PROVIDERS__<ID>__CLIENT_ID=...
AGNOSTIC_IDENTITY__PROVIDERS__<ID>__CLIENT_SECRET=...
AGNOSTIC_IDENTITY__PROVIDERS__<ID>__ISSUER=...             # where the preset has no default
AGNOSTIC_IDENTITY__PROVIDERS__<ID>__DISPLAY_NAME=...       # optional button label
```

Every provider uses the authorization-code flow with PKCE. For OIDC providers the control plane reads the
issuer's discovery document and verifies the signed ID token (issuer, audience, nonce). GitHub has no OIDC for
signing people in, so the GitHub preset uses OAuth and reads the profile and the verified primary email from
GitHub's REST API.

### Who gets in

A provider proves who someone is; the org decides whether they may join:

1. Someone who already signed in with this provider, or whose **verified** email belongs to an existing member,
   signs in.
2. Otherwise they need a pending **invitation** to that email address. The invitation sets their org role (and
   any initial access).
3. **Just-in-time provisioning** lets people join without an invitation, as Members (org role) with no direct
   instance access, while seats are left:

   ```bash
   AGNOSTIC_IDENTITY__PROVIDERS__<ID>__JIT_PROVISIONING=true
   AGNOSTIC_IDENTITY__PROVIDERS__<ID>__ALLOWED_EMAIL_DOMAINS=localhost.company,localhost-company.io
   ```

   Leaving `ALLOWED_EMAIL_DOMAINS` empty with JIT on admits **anyone** who can sign in at that provider: never do
   that with a public provider such as GitHub, GitLab.com or Google.

Emails the provider hasn't verified are refused. `__TRUST_UNVERIFIED_EMAIL=true` turns that off for providers that
don't send `email_verified` (see Entra ID below); use it only when the provider only knows addresses your
organisation controls. Every sign-in and refusal is written to the audit log (`auth.login`,
`auth.login_failed` with the reason).

## GitHub

1. GitHub › **Settings › Developer settings › OAuth Apps › New OAuth App** (for an organisation: the
   organisation's settings). Homepage URL: your public URL. Authorization callback URL:
   `{PUBLIC_URL}/api/v1/auth/sso/github/callback`.
2. Generate a client secret.

```bash
AGNOSTIC_IDENTITY__PROVIDERS__GITHUB__PRESET=github
AGNOSTIC_IDENTITY__PROVIDERS__GITHUB__CLIENT_ID=Ov23li0123456789abcd
AGNOSTIC_IDENTITY__PROVIDERS__GITHUB__CLIENT_SECRET=...
# GitHub Enterprise Server:
# AGNOSTIC_IDENTITY__PROVIDERS__GITHUB__BASE_URL=https://github.localhost.company
```

The app asks for `read:user` and `user:email`. The email Agnostic uses is the account's **verified primary**
address, so invite people by that address. Being a member of your GitHub organisation doesn't grant anything by
itself: use invitations, or JIT with your company domains.

## GitLab

1. GitLab › **Edit profile › Applications** (or a group's or the instance's **Applications**) › **Add new
   application**. Redirect URI: `{PUBLIC_URL}/api/v1/auth/sso/gitlab/callback`. Confidential: on. Scopes:
   `openid`, `profile`, `email`.

```bash
AGNOSTIC_IDENTITY__PROVIDERS__GITLAB__PRESET=gitlab
AGNOSTIC_IDENTITY__PROVIDERS__GITLAB__CLIENT_ID=...
AGNOSTIC_IDENTITY__PROVIDERS__GITLAB__CLIENT_SECRET=...
# Self-managed GitLab (gitlab.com needs no issuer):
# AGNOSTIC_IDENTITY__PROVIDERS__GITLAB__ISSUER=https://gitlab.localhost.company
```

## Google

1. Google Cloud console › **APIs & Services › OAuth consent screen**: for a Google Workspace, choose **Internal**
   so only accounts of your organisation can sign in.
2. **Credentials › Create credentials › OAuth client ID**, type **Web application**. Authorized redirect URI:
   `{PUBLIC_URL}/api/v1/auth/sso/google/callback`.

```bash
AGNOSTIC_IDENTITY__PROVIDERS__GOOGLE__PRESET=google
AGNOSTIC_IDENTITY__PROVIDERS__GOOGLE__CLIENT_ID=0123456789-abc.apps.googleusercontent.com
AGNOSTIC_IDENTITY__PROVIDERS__GOOGLE__CLIENT_SECRET=...
AGNOSTIC_IDENTITY__PROVIDERS__GOOGLE__ALLOWED_EMAIL_DOMAINS=localhost.company
```

With exactly one allowed domain, the Google account chooser is limited to that Workspace domain (the `hd`
parameter). That only preselects accounts: who gets in is still decided by invitations and, with JIT, by
`ALLOWED_EMAIL_DOMAINS`.

## Okta

1. Okta admin console › **Applications › Create App Integration** › **OIDC - OpenID Connect**, **Web
   Application**. Sign-in redirect URI: `{PUBLIC_URL}/api/v1/auth/sso/okta/callback`. Grant type: Authorization
   Code.
2. **Assignments**: assign the people or groups who may use Agnostic. Okta refuses everyone else before they reach
   Agnostic.

```bash
AGNOSTIC_IDENTITY__PROVIDERS__OKTA__PRESET=okta
AGNOSTIC_IDENTITY__PROVIDERS__OKTA__ISSUER=https://localhost-company.okta.com/oauth2/default
AGNOSTIC_IDENTITY__PROVIDERS__OKTA__CLIENT_ID=0oa0123456789abcd
AGNOSTIC_IDENTITY__PROVIDERS__OKTA__CLIENT_SECRET=...
AGNOSTIC_IDENTITY__PROVIDERS__OKTA__JIT_PROVISIONING=true
AGNOSTIC_IDENTITY__PROVIDERS__OKTA__ALLOWED_EMAIL_DOMAINS=localhost.company
```

The issuer is your authorization server: `https://<org>.okta.com/oauth2/default` (or another custom server), or
`https://<org>.okta.com` for the org authorization server.

## Other OpenID Connect providers

The `oidc` preset works with any provider that publishes `/.well-known/openid-configuration` under its issuer and
puts `email` in the ID token (or the userinfo endpoint).

```bash
AGNOSTIC_IDENTITY__PROVIDERS__<ID>__PRESET=oidc
AGNOSTIC_IDENTITY__PROVIDERS__<ID>__DISPLAY_NAME=Localhost Company SSO
AGNOSTIC_IDENTITY__PROVIDERS__<ID>__ISSUER=...
AGNOSTIC_IDENTITY__PROVIDERS__<ID>__CLIENT_ID=...
AGNOSTIC_IDENTITY__PROVIDERS__<ID>__CLIENT_SECRET=...
# AGNOSTIC_IDENTITY__PROVIDERS__<ID>__SCOPES=openid,profile,email   # the default
```

| Provider | Issuer | Notes |
|---|---|---|
| Microsoft Entra ID | `https://login.microsoftonline.com/<tenant-id>/v2.0` | App registration › **Web** platform with the callback URL, a client secret, and the `email` optional claim on the ID token. Use the tenant-specific issuer (not `common`). Entra doesn't send `email_verified`, so sign-in also needs `__TRUST_UNVERIFIED_EMAIL=true`: acceptable for a single tenant whose addresses your admins manage. |
| Authentik | `https://authentik.localhost.company/application/o/<app-slug>/` | OAuth2/OpenID provider with a confidential client and the `email` scope mapping; bind the application to the groups who may sign in. |
| Dex | Dex's `issuer` setting, e.g. `https://dex.localhost.company/dex` | Add Agnostic as a `staticClients` entry with the callback URL in `redirectURIs`. Whether emails count as verified depends on the connector. |

Use one id per provider (`entra`, `authentik`, …) to offer several at once.

## Check the setup

- The sign-in page lists every enabled provider; `__ENABLED=false` hides one without deleting its settings.
- A provider is contacted only when someone clicks its button, so a configuration mistake shows up there: the
  browser lands back on `/login?error=<code>` and the API log has an `identity.sso_provider_error` line with the
  detail (for example "can't read …/.well-known/openid-configuration", or an issuer mismatch).
- `error=not_invited`: the email isn't a member and has no pending invitation, and JIT is off or the domain isn't
  allowed. `seats_full`: JIT would exceed the org's seat limit. `email_unverified`: the provider says the address
  isn't verified. `provider_denied`: the person cancelled, or the provider refused them (Okta assignments,
  Authentik bindings).
