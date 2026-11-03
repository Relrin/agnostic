// Two-step verification: your authenticator apps and security keys, and recovery codes. Second factors apply to
// email + password sign-in (SSO sign-ins rely on the identity provider's MFA).
import {
  describeError,
  meConfirmTotpMutation,
  meGetMyMfaOptions,
  meGetMyMfaQueryKey,
  meRegenerateRecoveryCodesMutation,
  meRemoveFactorMutation,
  meSetupTotpMutation,
  meWebauthnOptionsMutation,
  meWebauthnVerifyMutation,
  type FactorOut,
  type TotpSetupOut,
} from "@agnostic/api";
import {
  formatRelative,
  formatWhen,
  useReauth,
  webauthnAvailable,
  webauthnCreate,
  webauthnError,
  withQueryFn,
  withReauth,
} from "@agnostic/core";
import {
  Badge,
  Button,
  Callout,
  CodeBlock,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  ErrorState,
  Field,
  Input,
  LoadingRows,
  toast,
} from "@agnostic/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Smartphone } from "lucide-react";
import { useState, type SubmitEvent } from "react";

const KIND_LABELS: Record<FactorOut["kind"], string> = {
  totp: "Authenticator app",
  webauthn: "Security key",
};

/** Recovery codes, shown once right after they're made. */
function RecoveryCodesDialog({ codes, onClose }: { codes: string[] | null; onClose: () => void }) {
  return (
    <Dialog
      open={codes !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Save your recovery codes</DialogTitle>
          <DialogDescription>
            Each code signs you in once if you lose your second factor. Keep them somewhere safe, like a
            password manager. They won't be shown again.
          </DialogDescription>
        </DialogHeader>
        {codes && <CodeBlock title="Recovery codes" code={codes.join("\n")} />}
        <DialogFooter>
          <Button variant="primary" onClick={onClose}>
            I've saved them
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function TotpEnrollment({
  setup,
  onDone,
  onCancel,
}: {
  setup: TotpSetupOut;
  onDone: (codes: string[]) => void;
  onCancel: () => void;
}) {
  const reauth = useReauth();
  const [code, setCode] = useState("");
  const [label, setLabel] = useState("");
  const confirm = useMutation({
    ...withReauth(reauth, meConfirmTotpMutation()),
    onSuccess: (data) => {
      onDone(data.recovery_codes);
    },
  });
  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    confirm.mutate({ body: { code: code.replace(/\s+/g, ""), label: label.trim() || null } });
  };
  return (
    <form
      onSubmit={submit}
      aria-label="Add an authenticator app"
      className="flex max-w-xl flex-col gap-4 rounded-card border border-border bg-surface p-4"
    >
      <ol className="flex list-decimal flex-col gap-1 pl-5 text-[13px] text-fg-secondary">
        <li>Open your authenticator app (1Password, Google Authenticator, Authy…) and add an account.</li>
        <li>Paste the setup key, or open the otpauth link on a device that has the app.</li>
        <li>Enter the 6-digit code it shows.</li>
      </ol>
      <CodeBlock title="Setup key" code={setup.secret} />
      <CodeBlock title="otpauth link" code={setup.otpauth_uri} />
      <div className="grid grid-cols-2 gap-3">
        <Field
          label="Code from the app"
          error={confirm.error ? describeError(confirm.error).reason : undefined}
        >
          {({ id, describedBy, invalid }) => (
            <Input
              id={id}
              mono
              required
              inputMode="numeric"
              autoComplete="one-time-code"
              aria-describedby={describedBy}
              aria-invalid={invalid || undefined}
              value={code}
              onChange={(event) => {
                setCode(event.target.value);
              }}
            />
          )}
        </Field>
        <Field label="Name (optional)">
          {({ id }) => (
            <Input
              id={id}
              placeholder="1Password"
              value={label}
              onChange={(event) => {
                setLabel(event.target.value);
              }}
            />
          )}
        </Field>
      </div>
      <div className="flex gap-2">
        <Button type="submit" variant="primary" disabled={confirm.isPending || code.trim() === ""}>
          {confirm.isPending ? "Checking…" : "Turn on"}
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

function SecurityKeyEnrollment({
  onDone,
  onCancel,
}: {
  onDone: (codes: string[]) => void;
  onCancel: () => void;
}) {
  const reauth = useReauth();
  const [label, setLabel] = useState("");
  const [error, setError] = useState<string | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const options = useMutation(withReauth(reauth, meWebauthnOptionsMutation()));
  const verify = useMutation(withReauth(reauth, meWebauthnVerifyMutation()));
  const register = async () => {
    setError(undefined);
    setBusy(true);
    try {
      const creation = await options.mutateAsync({});
      let credential: Record<string, unknown>;
      try {
        credential = await webauthnCreate(creation);
      } catch (cause) {
        setError(webauthnError(cause));
        return;
      }
      const enrolled = await verify.mutateAsync({ body: { credential, label: label.trim() || null } });
      onDone(enrolled.recovery_codes);
    } catch (cause) {
      setError(describeError(cause).reason);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex max-w-xl flex-col gap-4 rounded-card border border-border bg-surface p-4">
      <p className="text-[13px] text-fg-secondary">
        Use a hardware key (YubiKey, Titan) or a passkey on this device. Your browser asks you to touch or
        unlock it.
      </p>
      <Field label="Name (optional)">
        {({ id }) => (
          <Input
            id={id}
            placeholder="YubiKey 5C"
            value={label}
            onChange={(event) => {
              setLabel(event.target.value);
            }}
          />
        )}
      </Field>
      {error && <Callout tone="danger">{error}</Callout>}
      <div className="flex gap-2">
        <Button
          variant="primary"
          disabled={busy}
          onClick={() => {
            void register();
          }}
        >
          <KeyRound aria-hidden />
          {busy ? "Waiting for the key…" : "Register security key"}
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

export function TwoStepVerification() {
  const queryClient = useQueryClient();
  const reauth = useReauth();
  const mfa = useQuery(withQueryFn(meGetMyMfaOptions()));
  const [adding, setAdding] = useState<"totp" | "webauthn" | null>(null);
  const [setup, setSetup] = useState<TotpSetupOut | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: meGetMyMfaQueryKey() });
  const startTotp = useMutation({
    ...withReauth(reauth, meSetupTotpMutation()),
    onSuccess: (data) => {
      setSetup(data);
      setAdding("totp");
    },
  });
  const remove = useMutation({
    ...withReauth(reauth, meRemoveFactorMutation()),
    onSuccess: async () => {
      toast("Second factor removed");
      await refresh();
    },
  });
  const regenerate = useMutation({
    ...withReauth(reauth, meRegenerateRecoveryCodesMutation()),
    onSuccess: async (data) => {
      setCodes(data.recovery_codes);
      await refresh();
    },
  });

  const enrolled = async (recoveryCodes: string[]) => {
    setAdding(null);
    setSetup(null);
    toast("Two-step verification is on");
    if (recoveryCodes.length > 0) setCodes(recoveryCodes);
    await refresh();
  };

  if (mfa.isPending) return <LoadingRows rows={2} label="Loading two-step verification" />;
  if (mfa.isError) return <ErrorState reason={describeError(mfa.error).reason} />;

  const { factors, policy, required } = mfa.data;
  const canAdd = policy !== "off";
  const error = startTotp.error ?? remove.error ?? regenerate.error;

  return (
    <div className="flex max-w-3xl flex-col gap-4">
      {required && factors.length === 0 && (
        <Callout tone="warning" title="Your org requires two-step verification">
          Add an authenticator app or a security key. Until you do, you'll be asked to set one up at your next
          password sign-in.
        </Callout>
      )}
      {required && factors.length > 0 && (
        <p className="text-[13px] text-fg-secondary">
          Your org requires two-step verification for password sign-in, so the last factor can't be removed.
        </p>
      )}
      {!canAdd && factors.length === 0 && (
        <Callout tone="availability">Your org has turned off adding second factors.</Callout>
      )}
      {factors.length > 0 ? (
        <ul className="flex flex-col divide-y divide-divider-row rounded-card border border-border bg-surface">
          {factors.map((factor) => {
            const Icon = factor.kind === "totp" ? Smartphone : KeyRound;
            const last = required && factors.length === 1;
            return (
              <li key={factor.id} className="flex items-center gap-3 px-4 py-3">
                <Icon className="size-4 text-fg-muted" aria-hidden />
                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <span className="truncate text-[13.5px]">{factor.label || KIND_LABELS[factor.kind]}</span>
                  <span className="text-[12px] text-fg-muted">
                    {KIND_LABELS[factor.kind]} · added {formatWhen(factor.created_at)} ·{" "}
                    {factor.last_used_at ? `last used ${formatRelative(factor.last_used_at)}` : "never used"}
                  </span>
                </div>
                <Button
                  size="30"
                  variant="destructive-text"
                  aria-label={`Remove ${factor.label || KIND_LABELS[factor.kind]}`}
                  disabled={remove.isPending || last}
                  title={last ? "Your org requires a second factor" : undefined}
                  onClick={() => {
                    remove.mutate({ path: { factor_id: factor.id } });
                  }}
                >
                  Remove
                </Button>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="text-[13px] text-fg-secondary">
          Off. Add a second factor so a stolen password isn't enough to sign in as you.
        </p>
      )}
      {adding === "totp" && setup && (
        <TotpEnrollment
          setup={setup}
          onDone={(recoveryCodes) => void enrolled(recoveryCodes)}
          onCancel={() => {
            setAdding(null);
            setSetup(null);
          }}
        />
      )}
      {adding === "webauthn" && (
        <SecurityKeyEnrollment
          onDone={(recoveryCodes) => void enrolled(recoveryCodes)}
          onCancel={() => {
            setAdding(null);
          }}
        />
      )}
      {canAdd && adding === null && (
        <div className="flex flex-wrap gap-2">
          <Button
            variant="secondary"
            disabled={startTotp.isPending}
            onClick={() => {
              startTotp.mutate({});
            }}
          >
            <Smartphone aria-hidden />
            Add authenticator app
          </Button>
          {webauthnAvailable() && (
            <Button
              variant="secondary"
              onClick={() => {
                setAdding("webauthn");
              }}
            >
              <KeyRound aria-hidden />
              Add security key
            </Button>
          )}
        </div>
      )}
      {factors.length > 0 && (
        <div className="flex items-center gap-3 text-[13px]">
          <span className="text-fg-secondary">Recovery codes</span>
          <Badge tone={mfa.data.recovery_codes_left > 2 ? "muted" : "warning"}>
            {mfa.data.recovery_codes_left} left
          </Badge>
          <Button
            size="30"
            variant="outline"
            disabled={regenerate.isPending}
            onClick={() => {
              regenerate.mutate({});
            }}
          >
            Make new codes
          </Button>
        </div>
      )}
      {error && <Callout tone="danger">{describeError(error).reason}</Callout>}
      <RecoveryCodesDialog
        codes={codes}
        onClose={() => {
          setCodes(null);
        }}
      />
    </div>
  );
}
