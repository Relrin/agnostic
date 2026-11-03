import {
  authLoginMutation,
  authRequestPasswordResetMutation,
  describeError,
  meGetMeQueryKey,
  onboardingOnboardingStatusOptions,
  problemCode,
  type MfaRequired,
} from "@agnostic/api";
import { withQueryFn } from "@agnostic/core";
import { Button, Callout, Field, Input } from "@agnostic/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useState, type SubmitEvent } from "react";

import { MfaStep } from "./mfa-step";
import { PublicPage, SSO_ERRORS, SsoButtons, safeNext, useSearchParam, useSignInOptions } from "./shared";

function isMfaRequired(data: unknown): data is MfaRequired {
  return typeof data === "object" && data !== null && "challenge" in data && "methods" in data;
}

/**
 * `/login`: the configured SSO providers and email + password (local accounts), then a second factor when the
 * account has one or the org requires it. With SSO enforced the password form folds into "Break-glass sign-in".
 */
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
  const [breakGlass, setBreakGlass] = useState(false);
  const [challenge, setChallenge] = useState<MfaRequired | null>(null);

  const signedIn = async () => {
    await queryClient.invalidateQueries({ queryKey: meGetMeQueryKey() });
    await navigate({ to: next });
  };
  const login = useMutation({
    ...authLoginMutation(),
    onSuccess: async (data) => {
      if (isMfaRequired(data)) {
        setChallenge(data);
        setPassword("");
        return;
      }
      await signedIn();
    },
  });
  const reset = useMutation(authRequestPasswordResetMutation());

  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (forgot) reset.mutate({ body: { email } });
    else login.mutate({ body: { email, password } });
  };

  const providers = options.data?.providers ?? [];
  const ssoEnforced = options.data?.sso_enforced === true;
  const localLogin = options.data?.local_login ?? true;
  const ssoRequired = problemCode(login.error) === "sso_required";
  // Password sign-in is folded away when the org signs in with SSO; the break-glass Owner can still open it.
  const passwordHidden = (ssoEnforced || !localLogin || ssoRequired) && !breakGlass;
  const error = login.error && !ssoRequired ? describeError(login.error).reason : undefined;

  if (challenge) {
    return (
      <PublicPage title="Two-step verification" intro={`Signing in as ${email}.`}>
        <MfaStep
          challenge={challenge}
          onSignedIn={() => void signedIn()}
          onRestart={() => {
            setChallenge(null);
            login.reset();
          }}
        />
      </PublicPage>
    );
  }

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
      {ssoRequired && (
        <Callout tone="availability" title="Your org signs in with SSO">
          Passwords are turned off for your account. Continue with your identity provider.
        </Callout>
      )}
      {!forgot && <SsoButtons providers={providers} next={next} />}
      {!forgot && providers.length > 0 && !passwordHidden && (
        <div className="flex items-center gap-3 text-[12px] text-fg-muted">
          <span className="h-px flex-1 bg-border" />
          or
          <span className="h-px flex-1 bg-border" />
        </div>
      )}
      {passwordHidden ? (
        <Button
          type="button"
          variant="link"
          className="self-start text-[12.5px]"
          onClick={() => {
            setBreakGlass(true);
            login.reset();
          }}
        >
          Break-glass sign-in
        </Button>
      ) : (
        <form onSubmit={submit} className="flex flex-col gap-4">
          {(ssoEnforced || !localLogin) && (
            <p className="text-[12.5px] text-fg-muted">
              Only the org's break-glass Owner can sign in with a password while SSO is required. Every use is
              alerted.
            </p>
          )}
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
