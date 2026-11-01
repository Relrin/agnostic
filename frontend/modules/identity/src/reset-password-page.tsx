import { authConfirmPasswordResetMutation, describeError } from "@agnostic/api";
import { Button, Callout, Field, Input } from "@agnostic/ui";
import { useMutation } from "@tanstack/react-query";
import { useState, type SubmitEvent } from "react";

import { PublicPage, useSearchParam } from "./shared";

/** `/reset-password?token=…`: choose a new password; every session is signed out. */
export function ResetPasswordPage() {
  const token = useSearchParam("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const reset = useMutation(authConfirmPasswordResetMutation());
  const mismatch = confirm.length > 0 && confirm !== password;

  if (reset.isSuccess) {
    return (
      <PublicPage
        title="Password changed"
        intro="You were signed out everywhere. Sign in with the new password."
      >
        <Button asChild variant="primary" size="36">
          <a href="/login">Sign in</a>
        </Button>
      </PublicPage>
    );
  }

  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!mismatch) reset.mutate({ body: { token, password } });
  };
  return (
    <PublicPage title="Choose a new password">
      <form onSubmit={submit} className="flex flex-col gap-4">
        <Field label="New password" hint="At least 12 characters.">
          {({ id, describedBy }) => (
            <Input
              id={id}
              type="password"
              required
              autoComplete="new-password"
              aria-describedby={describedBy}
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
        {reset.error && <Callout tone="danger">{describeError(reset.error).reason}</Callout>}
        <Button type="submit" variant="primary" size="36" disabled={reset.isPending || mismatch || !token}>
          Change password
        </Button>
      </form>
    </PublicPage>
  );
}
