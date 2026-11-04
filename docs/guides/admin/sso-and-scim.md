# Sign-in, SSO and SCIM

People sign in with a local account, or through your identity provider with OIDC, SAML 2.0 or GitHub. Groups come
from the IdP (SCIM, a groups claim, or Google Workspace sync) or are managed by hand. Owners and Administrators
configure all of it in *Organization › Authentication* and *Organization › Directory sync*.

## Sign-in

| Method | Notes |
|---|---|
| Local accounts | on by default (`AGNOSTIC_IDENTITY__LOCAL_LOGIN`); argon2id passwords of 12+ characters; 5 failed sign-ins lock an email for 15 minutes |
| OIDC | discovery, authorization code with PKCE, `state` and `nonce`, the ID token verified against the provider's keys |
| SAML 2.0 | HTTP-Redirect requests, signed Response or Assertion, audience, recipient, validity and replay checks |
| GitHub | OAuth plus the verified primary email (GitHub has no OIDC sign-in) |

Who may join: someone with a pending invitation for their verified email, or, with JIT provisioning, anyone whose
email domain is in the provider's allow-list.

- **Enforce SSO** turns password sign-in off for everyone except one break-glass Owner, whose every password sign-in
  is audited and announced to the other Owners.
- **MFA policy** for password sign-ins: `off`, `optional`, `required_local` (every local account) or
  `required_admins` (Owners and Administrators). SSO sign-ins rely on the IdP's own MFA.

Providers can also be set through settings (`AGNOSTIC_IDENTITY__PROVIDERS__<ID>__*`), in which case they show
read-only in the app.

## Invitations

*People & groups › Invite people* sets the email, the org role and any initial access, then **Send by email** (needs
SMTP; the link is shown to you too, and stays usable if the email fails) or **Create link only** (share it yourself;
the only option without SMTP).

The link is shown once (only its hash is stored), works once and expires after 7 days. Pending invitations hold a
seat. *Copy new link* and *Resend* (with SMTP) issue a new link that replaces the old one and restarts the expiry;
*Revoke* cancels the invitation. These need `org:members:write` and are audited (`invitations.create`, `.link`,
`.resend`, `.revoke`, `.accept`).

The invitee opens the link and chooses a password. When SSO is enforced or local login is off, a password is
refused: the invitee signs in through the IdP and is matched to the invitation by verified email.

## Groups and provisioning

| IdP | People | Groups |
|---|---|---|
| Okta, Entra ID | SCIM 2.0 push to `/scim/v2/Users` | SCIM push to `/scim/v2/Groups` |
| Keycloak, or any IdP with a groups claim | sign-in with JIT or invitation | the `groups` claim or SAML attribute, at every sign-in |
| Google Workspace | OIDC sign-in | Directory API sync every 15 minutes (read-only service account) |
| none | local accounts and invitations | manual groups |

SCIM tokens are created in *Organization › Directory sync › SCIM › New token* (shown once); the IdP's SCIM base URL
is `{public URL}/scim/v2`. Mapping rules carry IdP groups into the groups you bind roles to. Deprovisioning (SCIM
`active=false`, a delete, a suspended Google user) ends the person's sessions and removes their bindings at once. The
only active Owner can't be deprovisioned.

## Registering Agnostic in your IdP

Every URL derives from `AGNOSTIC_HTTP__PUBLIC_URL`: set it to the address people use before registering the
application. `<id>` is the provider id you choose in Agnostic (`okta`, `entra`, …).

| What | URL |
|---|---|
| OIDC / GitHub redirect (callback) URI | `{public URL}/api/v1/auth/sso/<id>/callback` |
| SAML SP entity ID (also serves the SP metadata) | `{public URL}/api/v1/auth/sso/<id>/metadata` |
| SAML ACS URL | `{public URL}/api/v1/auth/sso/<id>/acs` |

For SAML, add the provider in Agnostic first to get its URLs, then give Agnostic the IdP's metadata URL (or the
metadata XML) and map the email, name and groups attributes. Assertions must be signed (SHA-256 or stronger);
encrypted assertions and IdP-initiated sign-in aren't supported.

| IdP | Notes |
|---|---|
| Okta | OIDC web app, issuer `https://<your-org>.okta.com`; add a groups claim to the ID token to send groups at sign-in; SCIM with header auth and `userName` as the unique identifier |
| Microsoft Entra ID | issuer `https://login.microsoftonline.com/<tenant-id>/v2.0` (not `common`); add the `email` optional claim; Entra doesn't send `email_verified`, so set `__TRUST_UNVERIFIED_EMAIL=true` for a tenant whose addresses your admins manage; SCIM from an enterprise application |
| Google Workspace | OAuth client (web application); for group sync, a service account with domain-wide delegation and the read-only scopes `admin.directory.group.readonly` and `admin.directory.user.readonly` |
| Keycloak | issuer `https://<keycloak>/realms/<realm>`; a `groups` client scope with a Group Membership mapper (full path off) |
