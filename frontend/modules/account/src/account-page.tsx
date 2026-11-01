import {
  authLogoutMutation,
  describeError,
  meGetMeQueryKey,
  meListMySessionsOptions,
  meListMySessionsQueryKey,
  meRevokeMySessionMutation,
  meUpdateMeMutation,
  type MeOut,
} from "@agnostic/api";
import { ORG_ROLE_LABELS, useMe, withQueryFn } from "@agnostic/core";
import {
  Badge,
  Button,
  Callout,
  ErrorState,
  Field,
  Input,
  LoadingRows,
  PageIntro,
  Switch,
} from "@agnostic/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type SubmitEvent } from "react";

function ProfileForm({ me }: { me: MeOut }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(me.display_name);
  const [timezone, setTimezone] = useState(me.timezone ?? "");
  const update = useMutation({
    ...meUpdateMeMutation(),
    onSuccess: (data) => {
      queryClient.setQueryData(meGetMeQueryKey(), data);
    },
  });
  const dirty = name !== me.display_name || timezone !== (me.timezone ?? "");
  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    update.mutate({ body: { display_name: name, timezone } });
  };
  return (
    <form onSubmit={submit} className="flex max-w-xl flex-col gap-4">
      <Field label="Name">
        {({ id }) => (
          <Input
            id={id}
            value={name}
            onChange={(event) => {
              setName(event.target.value);
            }}
          />
        )}
      </Field>
      <Field label="Email" hint="Your email comes from your account; ask an administrator to change it.">
        {({ id, describedBy }) => <Input id={id} value={me.email} readOnly aria-describedby={describedBy} />}
      </Field>
      <Field label="Time zone" hint="IANA name, e.g. Europe/Lisbon. Empty uses the browser's.">
        {({ id, describedBy }) => (
          <Input
            id={id}
            mono
            value={timezone}
            aria-describedby={describedBy}
            onChange={(event) => {
              setTimezone(event.target.value);
            }}
          />
        )}
      </Field>
      {update.error && <Callout tone="danger">{describeError(update.error).reason}</Callout>}
      <div>
        <Button type="submit" variant="primary" disabled={!dirty || update.isPending}>
          {update.isPending ? "Saving…" : "Save profile"}
        </Button>
      </div>
    </form>
  );
}

function Preferences({ me }: { me: MeOut }) {
  const queryClient = useQueryClient();
  const update = useMutation({
    ...meUpdateMeMutation(),
    onSuccess: (data) => {
      queryClient.setQueryData(meGetMeQueryKey(), data);
    },
  });
  const apiHints = me.preferences.api_hints === true;
  return (
    <div className="flex max-w-xl flex-col gap-4">
      <Switch
        label="API hints"
        description="Show the API call behind each screen, so you can script what you click."
        checked={apiHints}
        disabled={update.isPending}
        onCheckedChange={(checked) => {
          update.mutate({ body: { preferences: { api_hints: checked } } });
        }}
      />
    </div>
  );
}

function Sessions() {
  const queryClient = useQueryClient();
  const sessions = useQuery(withQueryFn(meListMySessionsOptions()));
  const revoke = useMutation({
    ...meRevokeMySessionMutation(),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: meListMySessionsQueryKey() });
    },
  });
  if (sessions.isPending) return <LoadingRows rows={2} label="Loading sessions" />;
  if (sessions.isError) return <ErrorState reason={describeError(sessions.error).reason} />;
  return (
    <ul className="flex max-w-3xl flex-col divide-y divide-divider-row rounded-card border border-border bg-surface">
      {sessions.data.map((session) => (
        <li key={session.id} className="flex items-center gap-3 px-4 py-3">
          <div className="flex min-w-0 flex-1 flex-col gap-0.5">
            <span className="truncate text-[13.5px]">{session.user_agent ?? "Unknown browser"}</span>
            <span className="text-[12px] text-fg-muted">
              {session.method === "password" ? "Password" : session.method.replace("sso:", "SSO · ")} ·{" "}
              {session.ip ?? "unknown address"} · since {new Date(session.created_at).toLocaleString()}
            </span>
          </div>
          {session.current ? (
            <Badge tone="success">This browser</Badge>
          ) : (
            <Button
              size="30"
              variant="destructive-text"
              disabled={revoke.isPending}
              onClick={() => {
                revoke.mutate({ path: { session_id: session.id } });
              }}
            >
              Sign out
            </Button>
          )}
        </li>
      ))}
    </ul>
  );
}

/** `/account`: profile, preferences, how you sign in, and your signed-in browsers. */
export function AccountPage() {
  const me = useMe();
  const logout = useMutation({
    ...authLogoutMutation(),
    onSettled: () => {
      window.location.assign("/login");
    },
  });
  return (
    <div className="mx-auto flex w-full max-w-[1320px] flex-col gap-8 px-8 pt-6 pb-10">
      <PageIntro
        title="Account"
        actions={
          <Button
            variant="outline"
            onClick={() => {
              logout.mutate({});
            }}
          >
            Sign out
          </Button>
        }
      >
        Your profile and preferences in this control plane.
      </PageIntro>
      {me.isPending ? (
        <LoadingRows rows={4} label="Loading your account" />
      ) : me.isError ? (
        <ErrorState reason={describeError(me.error).reason} />
      ) : (
        <>
          <section aria-labelledby="profile" className="flex flex-col gap-3">
            <h2 id="profile" className="text-[15px] font-semibold">
              Profile
            </h2>
            <ProfileForm me={me.data} />
          </section>
          <section aria-labelledby="signin" className="flex flex-col gap-3">
            <h2 id="signin" className="text-[15px] font-semibold">
              Signing in
            </h2>
            <p className="text-[13px] text-fg-secondary">
              {me.data.org_role ? `${ORG_ROLE_LABELS[me.data.org_role]} · ` : ""}
              {me.data.has_password ? "Password" : "No password"}
              {me.data.sso_providers.length > 0 ? ` · SSO: ${me.data.sso_providers.join(", ")}` : ""}
            </p>
          </section>
          <section aria-labelledby="preferences" className="flex flex-col gap-3">
            <h2 id="preferences" className="text-[15px] font-semibold">
              Preferences
            </h2>
            <Preferences me={me.data} />
          </section>
          <section aria-labelledby="sessions" className="flex flex-col gap-3">
            <h2 id="sessions" className="text-[15px] font-semibold">
              Signed-in browsers
            </h2>
            <Sessions />
          </section>
        </>
      )}
    </div>
  );
}
