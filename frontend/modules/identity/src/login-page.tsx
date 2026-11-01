import {
  authLoginMutation,
  authRequestPasswordResetMutation,
  describeError,
  meGetMeQueryKey,
  onboardingOnboardingStatusOptions,
} from "@agnostic/api";
import { withQueryFn } from "@agnostic/core";
import { Button, Callout, Field, Input } from "@agnostic/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useState, type SubmitEvent } from "react";

import { PublicPage, SSO_ERRORS, SsoButtons, safeNext, useSearchParam, useSignInOptions } from "./shared";

/** `/login`: email + password (local accounts) and the configured SSO providers. */
export function LoginPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const next = safeNext(useSearchParam("next"));
  const ssoError = useSearchParam("error");
  const options = useSignInOptions();
  const status = useQuery(withQueryFn(onboardingOnboardingStatusOptions()));
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [forgot, setForgot] = useState(false);

  const login = useMutation({
    ...authLoginMutation(),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: meGetMeQueryKey() });
      await navigate({ to: next });
    },
  });
  const reset = useMutation(authRequestPasswordResetMutation());

  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (forgot) reset.mutate({ body: { email } });
    else login.mutate({ body: { email, password } });
  };

  const providers = options.data?.providers ?? [];
  const localLogin = options.data?.local_login ?? true;
  const error = login.error ? describeError(login.error).reason : undefined;

  return (
    <PublicPage
      title={forgot ? "Reset your password" : "Sign in"}
      intro={
        forgot
          ? "We'll email you a link to choose a new password."
          : "Sign in to your organization's control plane."
      }
    >
      {status.data && !status.data.owner_exists && (
        <Callout tone="availability" title="This installation isn't set up yet">
          Run <code className="font-mono">agnostic bootstrap --org-name "…"</code> on the server and open the
          link it prints to create the first Owner.
        </Callout>
      )}
      {ssoError && (
        <Callout tone="danger" title="Sign-in didn't work">
          {SSO_ERRORS[ssoError] ?? "Sign-in failed. Try again."}
        </Callout>
      )}
      {!forgot && <SsoButtons providers={providers} next={next} />}
      {!forgot && providers.length > 0 && localLogin && (
        <div className="flex items-center gap-3 text-[12px] text-fg-muted">
          <span className="h-px flex-1 bg-border" />
          or
          <span className="h-px flex-1 bg-border" />
        </div>
      )}
      {localLogin && (
        <form onSubmit={submit} className="flex flex-col gap-4">
          <Field label="Email">
            {({ id, describedBy }) => (
              <Input
                id={id}
                type="email"
                autoComplete="email"
                required
                value={email}
                aria-describedby={describedBy}
                onChange={(event) => {
                  setEmail(event.target.value);
                }}
              />
            )}
          </Field>
          {!forgot && (
            <Field label="Password" error={error}>
              {({ id, describedBy, invalid }) => (
                <Input
                  id={id}
                  type="password"
                  autoComplete="current-password"
                  required
                  value={password}
                  aria-describedby={describedBy}
                  aria-invalid={invalid || undefined}
                  onChange={(event) => {
                    setPassword(event.target.value);
                  }}
                />
              )}
            </Field>
          )}
          {forgot && reset.isSuccess && (
            <Callout tone="insight">If an account exists for {email}, a reset link is on its way.</Callout>
          )}
          <Button type="submit" variant="primary" size="36" disabled={login.isPending || reset.isPending}>
            {forgot ? "Email me a link" : login.isPending ? "Signing in…" : "Sign in"}
          </Button>
          <Button
            type="button"
            variant="link"
            className="self-start"
            onClick={() => {
              setForgot(!forgot);
              reset.reset();
            }}
          >
            {forgot ? "Back to sign-in" : "Forgot your password?"}
          </Button>
        </form>
      )}
    </PublicPage>
  );
}
