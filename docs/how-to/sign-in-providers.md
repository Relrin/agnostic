# Sign-in providers

People sign in with a **local account** (email + password, on by default) or through a **sign-in provider**: GitHub,
GitLab, Google, Okta, any OpenID Connect IdP (Microsoft Entra ID, Authentik, Dex, …) or SAML 2.0. Each enabled
provider adds a button to the sign-in page. Code: `backend/modules/identity` (`settings.py`, `domain/providers.py`,
`application/signin.py`); who may join is decided by `backend/modules/org`. Provider settings are environment
variables (or the same keys in TOML); the full list is in
[reference/configuration](../reference/configuration.md#sign-in-identity-module).

## Local accounts and invitations

Nothing to configure. `agnostic bootstrap` creates the first Owner with a password; everyone else is invited
(*People › Invite*, `POST /api/v1/invitations`):

| Delivery | What happens |
|---|---|
| *Send by email* (`delivery: "email"`, default) | the link is emailed; needs `AGNOSTIC_SMTP__URL` (without it, emails go to the API log) |
| *Create link only* (`delivery: "link"`) | no email; copy the link from the dialog and share it yourself |

- The response carries `accept_url` once (only the token's SHA-256 hash is stored) and `email_sent`. A failed send
  still returns the link.
- On a pending invitation, *Copy new link* (`POST /api/v1/invitations/{id}/link`, audit `invitations.link`) issues a
  new link and the old one stops working; *Resend* (only when email is configured) emails a new link.
- Invitations expire after 7 days. `GET /api/v1/org` reports `email_delivery` so the UI knows whether to offer email.
- The invitee opens the link and chooses a password. With SSO enforced or `AGNOSTIC_IDENTITY__LOCAL_LOGIN=false`
  that is refused (`sso_required` / `local_login_disabled`): they sign in through the provider instead and are
  matched to the invitation by verified email.

Failed sign-ins lock the account (`AGNOSTIC_IDENTITY__LOCKOUT_THRESHOLD` / `__LOCKOUT_MINUTES`); passwords need
`AGNOSTIC_IDENTITY__PASSWORD_MIN_LENGTH` characters (12). Turn local login off, or enforce SSO
([below](#enforcing-sso-and-mfa)), only after an Owner has signed in through a provider at least once.

## How SSO works

Pick an id for the provider (`github`, `okta`, `entra`, …). It names the settings and appears, lower-cased, in the
callback URL you register at the provider:

```text
{AGNOSTIC_HTTP__PUBLIC_URL}/api/v1/auth/sso/<id>/callback
```

`AGNOSTIC_HTTP__PUBLIC_URL` must be the URL people actually open (behind your reverse proxy), or the provider rejects
the redirect.

```bash
AGNOSTIC_IDENTITY__PROVIDERS__<ID>__PRESET=okta            # github | gitlab | google | okta | oidc
AGNOSTIC_IDENTITY__PROVIDERS__<ID>__CLIENT_ID=...
AGNOSTIC_IDENTITY__PROVIDERS__<ID>__CLIENT_SECRET=...
AGNOSTIC_IDENTITY__PROVIDERS__<ID>__ISSUER=...             # where the preset has no default
AGNOSTIC_IDENTITY__PROVIDERS__<ID>__DISPLAY_NAME=...       # optional button label
```

Every provider uses the authorization-code flow with PKCE. For OIDC the control plane reads the issuer's discovery
document and verifies the signed ID token (issuer, audience, nonce). GitHub has no OIDC for people, so its preset
uses OAuth and reads the profile and verified primary email from the REST API.

### Who gets in

1. Someone who signed in with this provider before, or whose **verified** email belongs to a member, signs in.
2. Otherwise they need a pending, unexpired **invitation** to that email; it sets their org role, initial access and
   groups.
3. **Just-in-time provisioning** lets people join without an invitation, as Members with no direct instance access,
   while seats are left:

   ```bash
   AGNOSTIC_IDENTITY__PROVIDERS__<ID>__JIT_PROVISIONING=true
   AGNOSTIC_IDENTITY__PROVIDERS__<ID>__ALLOWED_EMAIL_DOMAINS=localhost.company,localhost-company.io
   ```

   JIT with an empty `ALLOWED_EMAIL_DOMAINS` admits **anyone** who can sign in at that provider: never do that with
   a public provider (GitHub, GitLab.com, Google).

Unverified emails are refused. `__TRUST_UNVERIFIED_EMAIL=true` turns that off for providers that don't send
`email_verified` (Entra ID); use it only when the provider knows only addresses your organisation controls. Sign-ins
and refusals are audited (`auth.login`, `auth.login_failed` with the reason).

## Presets

| Preset | Register at the provider | Settings beyond id and secret |
|---|---|---|
| `github` | **Settings › Developer settings › OAuth Apps** (or the organisation's); callback URL as above. Scopes `read:user`, `user:email` | `__BASE_URL` for GitHub Enterprise Server (github.com needs none) |
| `gitlab` | **Applications** (profile, group or instance); confidential; scopes `openid`, `profile`, `email` | `__ISSUER` (or `__BASE_URL`, the *GitLab URL* in the app) for self-managed GitLab: its URL, e.g. `https://gitlab.example.com` (gitlab.com needs none) |
| `google` | Cloud console: OAuth consent screen (**Internal** for a Workspace), then an OAuth client ID of type **Web application** | `__ALLOWED_EMAIL_DOMAINS`; with exactly one domain the account chooser is limited to it (`hd`) |
| `okta` | **Applications › Create App Integration › OIDC › Web Application**, grant type Authorization Code; assign the people or groups who may use Agnostic | `__ISSUER`: `https://<org>.okta.com/oauth2/default` (or another custom server), or `https://<org>.okta.com` |
| `oidc` | any provider with `/.well-known/openid-configuration` under its issuer that puts `email` in the ID token or userinfo | `__ISSUER`; `__SCOPES` (default `openid,profile,email`) |

GitHub uses the account's **verified primary** address, so invite people by that address; membership of your GitHub
organisation grants nothing by itself. Google's `hd` only preselects accounts: invitations and JIT domains still
decide who gets in.

### Self-managed GitLab

1. In GitLab, open **Admin › Applications** (or a group's or your profile's **Applications**) and add an application:
   - redirect URI `<PUBLIC_URL>/api/v1/auth/sso/<id>/callback`, the same URL the provider dialog shows;
   - **Confidential** on;
   - scopes `openid`, `profile`, `email`.
2. Set the *GitLab URL* (`__BASE_URL`) to the instance's `external_url`, for example `https://gitlab.example.com`, or
   `https://example.com/gitlab` under a relative URL root.

That URL is also the OIDC issuer. Agnostic reads `<GitLab URL>/.well-known/openid-configuration`, and sends people to
the authorize endpoint that document names. A typo in scheme, host or path shows up as "discovery issuer … != …".

Changing the GitLab URL takes effect on the next sign-in. Clearing it switches back to gitlab.com.

To map GitLab groups to directory groups, Agnostic reads the full list from GitLab's userinfo (`groups`). The ID
token only carries `groups_direct`, which is used when userinfo isn't reachable.

Agnostic only returns to relative paths after sign-in, so the web app and the API must be served from the same origin
as `PUBLIC_URL`. The reverse proxy in the deploy bundle and the dev server's `/api` proxy both do that.

Generic OIDC providers:

| Provider | Issuer | Notes |
|---|---|---|
| Microsoft Entra ID | `https://login.microsoftonline.com/<tenant-id>/v2.0` | **Web** platform with the callback URL, a client secret, the `email` optional claim. Tenant-specific issuer, not `common`. Needs `__TRUST_UNVERIFIED_EMAIL=true`. |
| Authentik | `https://authentik.localhost.company/application/o/<app-slug>/` | OAuth2/OpenID provider, confidential client, `email` scope mapping; bind the application to the allowed groups |
| Dex | Dex's `issuer`, e.g. `https://dex.localhost.company/dex` | a `staticClients` entry with the callback URL in `redirectURIs`; email verification depends on the connector |

Use one id per provider to offer several at once.

## Check the setup

- `__ENABLED=false` hides a provider without deleting its settings.
- A provider is contacted only when someone clicks its button. On a mistake the browser lands on
  `/login?error=<code>` and the API log has an `identity.sso_provider_error` line with the detail (discovery document
  unreadable, issuer mismatch, …).
- `not_invited`: not a member, no pending invitation, and JIT is off or the domain isn't allowed. `seats_full`: JIT
  would exceed the seat limit. `email_unverified`: the provider says the address isn't verified. `provider_denied`:
  the person cancelled, or the provider refused them (Okta assignments, Authentik bindings).

## Providers in the app, and SAML

Owners and Administrators can add providers in *Organization › Authentication* without a restart: OIDC (every preset
above) and **SAML 2.0**. Providers from settings appear there read-only. Changing sign-in settings asks for a recent
sign-in (or your password or second factor).

For SAML, add the provider, then copy its **SP entity ID** (`{PUBLIC_URL}/api/v1/auth/sso/<id>/metadata`, which also
serves the SP metadata) and **ACS URL** (`{PUBLIC_URL}/api/v1/auth/sso/<id>/acs`) into the IdP. Give Agnostic the
IdP's metadata URL (or the metadata XML, or its entity ID, SSO URL and signing certificate) and map the email, name
and groups attributes. Responses or assertions must be signed (SHA-256 or stronger); encrypted assertions and
IdP-initiated sign-in are not supported.

Groups asserted at sign-in (an OIDC `groups` claim or the SAML groups attribute) keep the person's IdP groups in
sync. Per-IdP walkthroughs, including SCIM: [Okta](idp/okta.md), [Entra ID](idp/entra-id.md),
[Keycloak](idp/keycloak.md), [Google Workspace](idp/google-workspace.md).

## Enforcing SSO and MFA

- **Enforce SSO** turns off passwords for everyone except one **break-glass** Owner, kept for when the IdP is down.
  Each break-glass sign-in is audited (`auth.break_glass`) and Owners are notified. Enforcing needs an enabled SSO
  provider and a break-glass Owner with a password. Invitees then join through SSO, not with a password.
- **Session lifetime**: idle and absolute limits for everyone, instead of the settings defaults.
- **MFA policy** (password sign-ins only; the IdP handles MFA for SSO):

  | Policy | Effect |
  |---|---|
  | Off | nobody can add a second factor (existing ones are still asked for) |
  | Optional (default) | anyone may add an authenticator app or a security key in *Account*, and is then asked for it |
  | Required for local accounts | every password sign-in needs a second factor; people without one set it up while signing in |
  | Required for admins | the same, for Owners and Administrators |

  Authenticator apps use TOTP (RFC 6238); security keys and passkeys use WebAuthn. Ten single-use recovery codes are
  issued with the first factor.
