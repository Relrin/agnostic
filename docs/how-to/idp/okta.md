# Okta: SSO and SCIM provisioning

Okta signs people in (OIDC or SAML) and pushes people and groups to Agnostic over SCIM 2.0, so joining, leaving and
group changes in Okta reach Agnostic within seconds, and a deactivated person loses access immediately.

You need an Okta admin, an Agnostic Owner or Administrator, and Agnostic reachable from Okta over HTTPS (SCIM is a
push from Okta to Agnostic).

## 1. Sign-in

**OIDC (recommended).** In Okta, *Applications › Create App Integration › OIDC – Web Application*:

- Sign-in redirect URI: `https://<agnostic>/api/v1/auth/sso/okta/callback`
- Grant type: Authorization Code; assignments: the people or groups who use Agnostic
- To send groups at sign-in too, add a *Groups claim* (filter "Matches regex" `.*`, or your prefix) to the ID token.

In Agnostic, *Organization › Authentication › Add provider*: kind OIDC, preset Okta, id `okta`, issuer
`https://<your-org>.okta.com` (or your custom authorization server), client id and secret. Settings work too
(`AGNOSTIC_IDENTITY__PROVIDERS__OKTA__*`, see [sign-in providers](../sign-in-providers.md)).

**SAML.** Add a SAML provider in Agnostic with id `okta-saml` and copy its *SP entity ID* and *ACS URL* into Okta
(*Single sign-on URL* = ACS URL, *Audience URI* = SP entity ID, Name ID format EmailAddress). Add attribute
statements `email` and `name` and a group attribute statement `groups`. Paste Okta's *Identity Provider metadata*
URL into Agnostic.

## 2. Provisioning (SCIM)

1. In Agnostic, *Organization › Directory sync › SCIM › New token*, labelled "Okta SCIM" (the label is the actor of
   everything Okta does in the audit log). Copy the token now; it isn't shown again.
2. In the Okta app, *General › Provisioning: SCIM*, then *Provisioning › Integration*:
   - SCIM connector base URL: the endpoint shown in Agnostic (`https://<agnostic>/scim/v2`)
   - Unique identifier field for users: `userName`
   - Supported actions: Push New Users, Push Profile Updates, Push Groups
   - Authentication mode: HTTP Header, with the token from step 1
3. *Provisioning › To App*: enable Create Users, Update User Attributes and Deactivate Users.
4. *Push Groups*: push the groups that should exist in Agnostic (e.g. `support-ai`, `billing`).

People pushed by Okta join the org as Members, or with the role of a pending invitation to their email (an
invitation sent by email or created as a link only; with SSO enforced it is accepted by signing in through Okta, not
with a password). Give access by binding
roles to the synced groups (*People & groups › Groups*), or carry an Okta group into a manual group with a mapping
rule (*Directory sync › Mapping rules*).

## 3. Rotating the token

*Rotate* issues a new token and keeps the old one valid for 24 hours: update Okta within that window. *Revoke* stops
a token at once.

## What deactivation does

Deactivating (or unassigning) someone in Okta sends `active=false`: their account is deprovisioned, their sessions
end, and their role bindings and group memberships are removed. With the *Remove from the org* behaviour (*Directory
sync › Deprovisioning*) they also leave the org; with *Disable* (the default) a reactivation restores their org role.
The only active Owner can't be deprovisioned: Okta gets a 409.
