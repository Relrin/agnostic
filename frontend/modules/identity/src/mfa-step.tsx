// The second sign-in step: an authenticator code, a security key or a recovery code. When the org requires a
// second factor and the person has none yet, they enroll one here (and get their recovery codes once).
import {
  authLoginMfaMutation,
  authLoginTotpSetupMutation,
  authLoginWebauthnOptionsMutation,
  describeError,
  isProblem,
  problemCode,
  type LoginMfaRequest,
  type MfaRequired,
  type TotpSetupOut,
} from "@agnostic/api";
import { webauthnAvailable, webauthnCreate, webauthnError, webauthnGet } from "@agnostic/core";
import { Button, Callout, CodeBlock, Field, Input, SegmentedControl } from "@agnostic/ui";
import { useMutation } from "@tanstack/react-query";
import { KeyRound } from "lucide-react";
import { useState, type SubmitEvent } from "react";

function failure(error: unknown, kind: "code" | "recovery"): string | undefined {
  if (!error) return undefined;
  if (problemCode(error) === "mfa_invalid")
    return kind === "recovery"
      ? "That recovery code isn't right, or it was already used."
      : "That code isn't right. Check the time on your device and try the next one.";
  if (isProblem(error)) return describeError(error).reason;
  return webauthnError(error);
}

function CodeInput({
  label,
  hint,
  value,
  onChange,
  error,
  recovery = false,
}: {
  label: string;
  hint?: string;
  value: string;
  onChange: (value: string) => void;
  error: string | undefined;
  recovery?: boolean;
}) {
  return (
    <Field label={label} hint={hint} error={error}>
      {({ id, describedBy, invalid }) => (
        <Input
          id={id}
          mono
          required
          inputMode={recovery ? "text" : "numeric"}
          autoComplete="one-time-code"
          aria-describedby={describedBy}
          aria-invalid={invalid || undefined}
          value={value}
          onChange={(event) => {
            onChange(event.target.value);
          }}
        />
      )}
    </Field>
  );
}

export function MfaStep({
  challenge,
  onSignedIn,
  onRestart,
}: {
  challenge: MfaRequired;
  /** Called once signed in (after the recovery codes were seen, when enrolling). */
  onSignedIn: () => void;
  onRestart: () => void;
}) {
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);
  const verify = useMutation({
    ...authLoginMfaMutation(),
    onSuccess: (data) => {
      if (data.recovery_codes && data.recovery_codes.length > 0) setRecoveryCodes(data.recovery_codes);
      else onSignedIn();
    },
  });
  const expired = problemCode(verify.error) === "mfa_challenge_expired";
  const send = (body: Omit<LoginMfaRequest, "challenge">) => {
    verify.mutate({ body: { challenge: challenge.challenge, ...body } });
  };

  if (recoveryCodes) {
    return (
      <div className="flex flex-col gap-4">
        <Callout tone="insight" title="Two-step verification is on">
          Save these recovery codes somewhere safe, like a password manager. Each signs you in once if you
          lose your second factor. They won't be shown again.
        </Callout>
        <CodeBlock title="Recovery codes" code={recoveryCodes.join("\n")} />
        <Button variant="primary" size="36" onClick={onSignedIn}>
          I've saved them, continue
        </Button>
      </div>
    );
  }

  if (expired) {
    return (
      <div className="flex flex-col gap-4">
        <Callout tone="danger" title="Sign-in took too long">
          Start again with your email and password.
        </Callout>
        <Button variant="primary" size="36" onClick={onRestart}>
          Back to sign-in
        </Button>
      </div>
    );
  }

  return challenge.enroll ? (
    <Enroll challenge={challenge} send={send} verify={verify} onRestart={onRestart} />
  ) : (
    <Verify challenge={challenge} send={send} verify={verify} onRestart={onRestart} />
  );
}

type StepProps = {
  challenge: MfaRequired;
  send: (body: Omit<LoginMfaRequest, "challenge">) => void;
  verify: { isPending: boolean; error: unknown; reset: () => void };
  onRestart: () => void;
};

function Verify({ challenge, send, verify, onRestart }: StepProps) {
  const methods = challenge.methods;
  const [mode, setMode] = useState<"totp" | "recovery">(methods.includes("totp") ? "totp" : "recovery");
  const [code, setCode] = useState("");
  const [keyError, setKeyError] = useState<unknown>(undefined);
  const options = useMutation(authLoginWebauthnOptionsMutation());

  const keyAvailable = methods.includes("webauthn") && webauthnAvailable();
  const signWithKey = async () => {
    setKeyError(undefined);
    verify.reset();
    try {
      const request = await options.mutateAsync({ body: { challenge: challenge.challenge } });
      send({ webauthn: await webauthnGet(request) });
    } catch (error) {
      setKeyError(error);
    }
  };

  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (mode === "recovery") send({ recovery_code: code.trim() });
    else send({ code: code.replace(/\s+/g, "") });
  };

  return (
    <div className="flex flex-col gap-4">
      {(methods.includes("totp") || methods.includes("recovery_code")) && (
        <form className="flex flex-col gap-4" onSubmit={submit}>
          {mode === "totp" ? (
            <CodeInput
              label="Authenticator code"
              hint="The 6-digit code from your authenticator app."
              value={code}
              onChange={setCode}
              error={keyError ? undefined : failure(verify.error, "code")}
            />
          ) : (
            <CodeInput
              label="Recovery code"
              hint="One of the codes you saved when you turned on two-step verification."
              value={code}
              onChange={setCode}
              error={keyError ? undefined : failure(verify.error, "recovery")}
              recovery
            />
          )}
          <Button type="submit" variant="primary" size="36" disabled={verify.isPending || code.trim() === ""}>
            {verify.isPending ? "Checking…" : "Verify"}
          </Button>
        </form>
      )}
      {keyAvailable && (
        <Button
          variant="secondary"
          size="36"
          disabled={options.isPending || verify.isPending}
          onClick={() => {
            void signWithKey();
          }}
        >
          <KeyRound aria-hidden />
          Use a security key
        </Button>
      )}
      {keyError !== undefined && <Callout tone="danger">{failure(keyError, "code")}</Callout>}
      <div className="flex flex-wrap gap-x-4">
        {methods.includes("recovery_code") && methods.includes("totp") && (
          <Button
            variant="link"
            onClick={() => {
              setMode(mode === "totp" ? "recovery" : "totp");
              setCode("");
              verify.reset();
            }}
          >
            {mode === "totp" ? "Use a recovery code" : "Use your authenticator app"}
          </Button>
        )}
        <Button variant="link" onClick={onRestart}>
          Sign in as someone else
        </Button>
      </div>
    </div>
  );
}

function Enroll({ challenge, send, verify, onRestart }: StepProps) {
  const canKey = challenge.methods.includes("webauthn") && webauthnAvailable();
  const canTotp = challenge.methods.includes("totp");
  const [method, setMethod] = useState<"totp" | "webauthn">(canTotp ? "totp" : "webauthn");
  const [setup, setSetup] = useState<TotpSetupOut | null>(null);
  const [code, setCode] = useState("");
  const [keyError, setKeyError] = useState<unknown>(undefined);
  const totpSetup = useMutation({
    ...authLoginTotpSetupMutation(),
    onSuccess: setSetup,
  });
  const options = useMutation(authLoginWebauthnOptionsMutation());

  const registerKey = async () => {
    setKeyError(undefined);
    verify.reset();
    try {
      const creation = await options.mutateAsync({ body: { challenge: challenge.challenge } });
      send({ webauthn: await webauthnCreate(creation), label: "Security key" });
    } catch (error) {
      setKeyError(error);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <Callout tone="availability" title="Set up two-step verification">
        Your org requires a second factor for password sign-in. Add one now to continue.
      </Callout>
      {canTotp && canKey && (
        <SegmentedControl
          label="Second factor"
          value={method}
          options={[
            { value: "totp", label: "Authenticator app" },
            { value: "webauthn", label: "Security key" },
          ]}
          onValueChange={(value) => {
            setMethod(value);
            verify.reset();
          }}
        />
      )}
      {method === "totp" &&
        (setup ? (
          <form
            className="flex flex-col gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              send({ code: code.replace(/\s+/g, ""), label: "Authenticator app" });
            }}
          >
            <p className="text-[13px] text-fg-secondary">
              Add an account in your authenticator app with this setup key (or open the otpauth link on a
              device that has the app), then enter the code it shows.
            </p>
            <CodeBlock title="Setup key" code={setup.secret} />
            <CodeBlock title="otpauth link" code={setup.otpauth_uri} />
            <CodeInput
              label="Code from the app"
              value={code}
              onChange={setCode}
              error={failure(verify.error, "code")}
            />
            <Button
              type="submit"
              variant="primary"
              size="36"
              disabled={verify.isPending || code.trim() === ""}
            >
              {verify.isPending ? "Checking…" : "Turn on and sign in"}
            </Button>
          </form>
        ) : (
          <Button
            variant="primary"
            size="36"
            disabled={totpSetup.isPending}
            onClick={() => {
              totpSetup.mutate({ body: { challenge: challenge.challenge } });
            }}
          >
            Set up an authenticator app
          </Button>
        ))}
      {method === "webauthn" && (
        <Button
          variant="primary"
          size="36"
          disabled={options.isPending || verify.isPending}
          onClick={() => {
            void registerKey();
          }}
        >
          <KeyRound aria-hidden />
          Register a security key
        </Button>
      )}
      {totpSetup.error && <Callout tone="danger">{describeError(totpSetup.error).reason}</Callout>}
      {(keyError !== undefined || (method === "webauthn" && Boolean(verify.error))) && (
        <Callout tone="danger">{failure(keyError ?? verify.error, "code")}</Callout>
      )}
      <Button variant="link" className="self-start" onClick={onRestart}>
        Sign in as someone else
      </Button>
    </div>
  );
}
