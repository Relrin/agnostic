import {
  describeError,
  onboardingCompleteOnboardingMutation,
  onboardingOnboardingStatusOptions,
  type ProblemDetails,
} from "@agnostic/api";
import { withQueryFn } from "@agnostic/core";
import { Button, Callout, Field, Input } from "@agnostic/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type SubmitEvent } from "react";

import { PublicPage, useSearchParam } from "./shared";

/** `/onboarding?token=…`: name the org and create the first Owner with the link from `agnostic bootstrap`. */
export function OnboardingPage() {
  const token = useSearchParam("token");
  const status = useQuery(withQueryFn(onboardingOnboardingStatusOptions()));
  const [orgName, setOrgName] = useState<string | undefined>(undefined);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");

  const complete = useMutation({
    ...onboardingCompleteOnboardingMutation(),
    onSuccess: () => {
      // A full load: the shell starts fresh with the new session, on "Connect your first instance".
      window.location.assign("/instances");
    },
  });

  if (status.data?.owner_exists) {
    return (
      <PublicPage title="Already set up" intro="This installation has an Owner.">
        <Button asChild variant="primary" size="36">
          <a href="/login">Sign in</a>
        </Button>
      </PublicPage>
    );
  }
  if (!token) {
    return (
      <PublicPage title="Set up Agnostic" intro="You need the one-time setup link.">
        <Callout tone="availability">
          Run <code className="font-mono">agnostic bootstrap --org-name "Localhost Company"</code> on the
          server; it prints a link to this page, valid for 24 hours.
        </Callout>
      </PublicPage>
    );
  }

  const mismatch = confirm.length > 0 && confirm !== password;
  const failure: ProblemDetails | null = complete.error;
  const passwordError = failure?.field === "password" ? describeError(failure).reason : undefined;
  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (mismatch) return;
    complete.mutate({
      body: {
        token,
        org_name: orgName ?? status.data?.org_name ?? null,
        email,
        display_name: name,
        password,
      },
    });
  };

  return (
    <PublicPage title="Set up your org" intro="Name the org and create the first Owner account.">
      <form onSubmit={submit} className="flex flex-col gap-4">
        <Field label="Org name" hint="Shown in the sidebar. You can change it later.">
          {({ id, describedBy }) => (
            <Input
              id={id}
              required
              aria-describedby={describedBy}
              value={orgName ?? status.data?.org_name ?? ""}
              onChange={(event) => {
                setOrgName(event.target.value);
              }}
            />
          )}
        </Field>
        <Field label="Your name">
          {({ id }) => (
            <Input
              id={id}
              required
              autoComplete="name"
              value={name}
              onChange={(event) => {
                setName(event.target.value);
              }}
            />
          )}
        </Field>
        <Field label="Email">
          {({ id }) => (
            <Input
              id={id}
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(event) => {
                setEmail(event.target.value);
              }}
            />
          )}
        </Field>
        <Field label="Password" hint="At least 12 characters. A passphrase works well." error={passwordError}>
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
        <Field label="Confirm password" error={mismatch ? "The passwords don't match." : undefined}>
          {({ id, describedBy, invalid }) => (
            <Input
              id={id}
              type="password"
              required
              autoComplete="new-password"
              aria-describedby={describedBy}
              aria-invalid={invalid || undefined}
              value={confirm}
              onChange={(event) => {
                setConfirm(event.target.value);
              }}
            />
          )}
        </Field>
        {complete.error && !passwordError && (
          <Callout tone="danger">{describeError(complete.error).reason}</Callout>
        )}
        <Button type="submit" variant="primary" size="36" disabled={complete.isPending || mismatch}>
          {complete.isPending ? "Creating…" : "Create Owner and continue"}
        </Button>
      </form>
    </PublicPage>
  );
}
