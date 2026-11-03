# Microsoft Entra ID: SSO and SCIM provisioning

Entra ID signs people in (OIDC or SAML) and provisions people and groups over SCIM 2.0 through an enterprise
application. Entra's provisioning service runs in cycles (about every 40 minutes); *Provision on demand* pushes one
person immediately.

## 1. Sign-in

**OIDC.** *App registrations › New registration*, redirect URI (Web)
`https://<agnostic>/api/v1/auth/sso/entra/callback`. Create a client secret. Under *Token configuration*, add the
`email` optional claim and, to send groups at sign-in, a *groups claim*. In Agnostic, add an OIDC provider with id
`entra`, issuer `https://login.microsoftonline.com/<tenant-id>/v2.0`, the client id and the secret.

**SAML.** *Enterprise applications › New application › Create your own application* (non-gallery), then *Single
sign-on › SAML*. The Identifier (Entity ID) and Reply URL (ACS URL) come from the SAML provider you add in Agnostic
(id `entra-saml`). Claims: `email` = `user.mail`, `name` = `user.displayname`, and a group claim named `groups`.
Paste the *App Federation Metadata Url* into Agnostic.

## 2. Provisioning (SCIM)

1. In Agnostic, *Organization › Directory sync › SCIM › New token*, labelled "Entra ID SCIM"; copy the token.
2. In the enterprise application, *Provisioning › Get started*, mode Automatic:
   - Tenant URL: `https://<agnostic>/scim/v2`
   - Secret Token: the token from step 1, then *Test Connection*
3. *Mappings*: keep *Provision Microsoft Entra ID Users* and *Groups*. Agnostic matches people on `userName` (the
   default `userPrincipalName`) and on `externalId`.
4. *Users and groups*: assign the people and groups to provision, then set *Provisioning Status* to On.

Entra's protocol quirks are handled: capitalised PATCH operations (`Replace`), string booleans
(`"active": "False"`) and member removal through `members[value eq "…"]` paths.

## 3. Access and deprovisioning

Bind roles to the provisioned groups, or carry them into manual groups with mapping rules. Unassigning or disabling
someone sends `active=false`; deleting them sends `DELETE`. Both deprovision the account (sessions end, bindings and
group memberships go); `DELETE` also removes the org membership.
