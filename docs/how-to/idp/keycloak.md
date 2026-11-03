# Keycloak: SSO with groups

Keycloak has no SCIM push, so groups arrive with every sign-in: an OIDC `groups` claim or a SAML `groups` attribute.
People who stop signing in keep their last groups until someone removes them or deprovisions the account; keep
session lifetimes short (*Organization › Authentication*) if that matters.

The development stack ships a ready realm: `docker compose -f deploy/dev/compose.yml --profile sso up -d keycloak`,
then open http://localhost:8080 (admin / admin). Realm `agnostic` has the people maya, priya and jonas (the password
is the name) in the groups `support-ai`, `billing` and `finance`, an OIDC client (`agnostic`) and a SAML client
(`deploy/dev/keycloak/agnostic-realm.json`).

## OIDC

1. *Clients › Create client*: OpenID Connect, client id `agnostic`, client authentication on, standard flow, valid
   redirect URI `https://<agnostic>/api/v1/auth/sso/keycloak/callback`.
2. *Client scopes › Create client scope* `groups` with a *Group Membership* mapper (token claim name `groups`, full
   group path off, added to the ID token and userinfo). Add the scope to the client's default scopes.
3. In Agnostic, add an OIDC provider with id `keycloak`, issuer `https://<keycloak>/realms/<realm>`, the client id
   and its secret (*Credentials* tab).

## SAML

1. In Agnostic, add a SAML provider with id `keycloak-saml` and copy its SP entity ID and ACS URL.
2. In Keycloak, *Clients › Create client*: SAML, client id = the SP entity ID; valid redirect URI and *Assertion
   Consumer Service POST Binding URL* = the ACS URL; sign assertions; Name ID format email.
3. Mappers: *User Property* `email` → `email` and `firstName` → `name`; *Group list* → attribute `groups`, full path
   off.
4. Paste `https://<keycloak>/realms/<realm>/protocol/saml/descriptor` into Agnostic as the metadata URL.

## Groups

The first sign-in creates an "IdP claim" group for each claimed name; later sign-ins add and remove the person's
memberships to match the claim. Bind roles to those groups, or add mapping rules (*Directory sync › Mapping rules*,
source "Sign-in claim", provider `keycloak`) to carry them into manual groups.
