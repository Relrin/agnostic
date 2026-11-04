# Google Workspace: sign-in and group sync

Google doesn't push SCIM to custom applications. People sign in with Google (OIDC), and groups are read from the
Admin SDK Directory API every 15 minutes by a read-only service account. Without the service account, Google users
still sign in and groups are managed by hand.

## 1. Sign-in

In Google Cloud, *APIs & Services › Credentials › Create credentials › OAuth client ID* (Web application), redirect
URI `https://<agnostic>/api/v1/auth/sso/google/callback`. Add the provider in Agnostic (preset Google, id `google`)
and list your Workspace domain under *Allowed email domains* if people may join without an invitation. Invited
people (by email or with a copied invite link) join by signing in with Google: the invitation is matched by their
verified email, and accepting with a password is refused while SSO is enforced.

## 2. Group sync (optional)

1. In the same Google Cloud project, enable the **Admin SDK API**, create a **service account** and add a JSON key.
2. In the Google Admin console, *Security › Access and data control › API controls › Domain-wide delegation › Add
   new*: the service account's client id, with exactly these scopes (both read-only; Agnostic never changes
   anything in Workspace):

   ```text
   https://www.googleapis.com/auth/admin.directory.group.readonly
   https://www.googleapis.com/auth/admin.directory.user.readonly
   ```

3. In Agnostic, *Organization › Directory sync › Google Workspace*: paste the JSON key (it is sealed and never shown
   again; the page shows the service account's email), the email of a Workspace admin to act as (delegation needs
   one), the customer id (`my_customer` by default) and a group filter (email prefixes such as `support-*`, or text
   the group's email or name contains; empty syncs every group). *Test connection*, then turn the sync on.

The sync creates "Google Workspace" groups and fills them with org members whose email matches a group member;
emails of people who aren't members yet are counted as unmatched (nobody is created). A member whose Google user is
suspended or deleted is deprovisioned. *Sync now* runs it immediately; the card shows the last run, counts and
errors.
