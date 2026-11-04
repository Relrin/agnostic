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

## Groups and provisioning

| IdP | People | Groups |
|---|---|---|
| Okta, Entra ID | SCIM 2.0 push to `/scim/v2/Users` | SCIM push to `/scim/v2/Groups` |
| Keycloak, or any IdP with a groups claim | sign-in with JIT or invitation | the `groups` claim or SAML attribute, at every sign-in |
| Google Workspace | OIDC sign-in | Directory API sync every 15 minutes (read-only service account) |
| none | local accounts and invitations | manual groups |

Mapping rules carry IdP groups into the groups you bind roles to. Deprovisioning (SCIM `active=false`, a delete, a
suspended Google user) ends the person's sessions and removes their bindings at once. The only active Owner can't be
deprovisioned.

## Step-by-step guides

The repository has detailed setup guides for common IdPs. They are contributor documentation, so they are not shown
in the product's *Help*:

- [Sign-in providers](../../how-to/sign-in-providers.md): every setting and the callback URLs
- [Okta](../../how-to/idp/okta.md), [Microsoft Entra ID](../../how-to/idp/entra-id.md),
  [Google Workspace](../../how-to/idp/google-workspace.md), [Keycloak](../../how-to/idp/keycloak.md)

The callback URLs derive from `AGNOSTIC_HTTP__PUBLIC_URL`: set it to the address people use before registering the
application in the IdP.
