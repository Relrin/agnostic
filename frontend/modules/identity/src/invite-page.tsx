import {
  describeError,
  invitationsAcceptInvitationMutation,
  invitationsPreviewInvitationOptions,
  type ProblemDetails,
} from "@agnostic/api";
import { ORG_ROLE_LABELS, withQueryFn } from "@agnostic/core";
import { Button, Callout, Field, Input, LoadingRows } from "@agnostic/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useParams } from "@tanstack/react-router";
import { useState, type SubmitEvent } from "react";

import { PublicPage, SsoButtons, useSignInOptions } from "./shared";

/** `/invite/$token`: join with a password, or with SSO using the invited email. */
export function InvitePage() {
  // The app's router isn't registered for type inference in modules, so params are read loosely.
  const params = useParams({ strict: false }) as unknown as Record<string, string | undefined>;
  const token = params.token ?? "";
  const preview = useQuery({
    ...withQueryFn(invitationsPreviewInvitationOptions({ path: { token } })),
    retry: false,
  });
  const options = useSignInOptions();
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");

  const accept = useMutation({
    ...invitationsAcceptInvitationMutation(),
    onSuccess: () => {
      window.location.assign("/");
    },
  });

  if (preview.isPending) {
    return (
      <PublicPage title="Invitation">
        <LoadingRows rows={3} label="Loading the invitation" />
      </PublicPage>
    );
  }
  if (preview.isError) {
    return (
      <PublicPage title="This invitation can't be used">
        <Callout tone="danger">{describeError(preview.error).reason}</Callout>
      </PublicPage>
    );
  }

  const invitation = preview.data;
  const failure: ProblemDetails | null = accept.error;
  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    accept.mutate({ path: { token }, body: { display_name: name || null, password } });
  };
  const providers = options.data?.providers ?? [];

  return (
    <PublicPage
      title={`Join ${invitation.org_name}`}
      intro={`${invitation.invited_by} invited ${invitation.email} as ${ORG_ROLE_LABELS[invitation.org_role]}.`}
    >
      {providers.length > 0 && (
        <>
          <p className="text-[13px] text-fg-secondary">
            Sign in with your organization's identity provider using {invitation.email}:
          </p>
          <SsoButtons providers={providers} next="/" />
        </>
      )}
      {invitation.has_account ? (
        <Callout tone="availability">
          An account for {invitation.email} exists. <a href="/login">Sign in</a> to accept.
        </Callout>
      ) : options.data?.local_login !== false ? (
        <form onSubmit={submit} className="flex flex-col gap-4">
          <Field label="Your name">
            {({ id }) => (
              <Input
                id={id}
                autoComplete="name"
                value={name}
                onChange={(event) => {
                  setName(event.target.value);
                }}
              />
            )}
          </Field>
          <Field
            label="Choose a password"
            hint="At least 12 characters."
            error={failure?.field === "password" ? describeError(failure).reason : undefined}
          >
            {({ id, describedBy, invalid }) => (
              <Input
                id={id}
                type="password"
                required
                autoComplete="new-password"
                aria-describedby={describedBy}
                aria-invalid={invalid || undefined}
                value={password}
                onChange={(event) => {
                  setPassword(event.target.value);
                }}
              />
            )}
          </Field>
          {failure && failure.field !== "password" && (
            <Callout tone="danger">{describeError(failure).reason}</Callout>
          )}
          <Button type="submit" variant="primary" size="36" disabled={accept.isPending}>
            {accept.isPending ? "Joining…" : "Accept and join"}
          </Button>
        </form>
      ) : null}
    </PublicPage>
  );
}
