// Re-authentication (step-up): sensitive changes answer 403 `reauth_required` unless the person confirmed it's
// them recently. `useReauth().run(fn)` catches that, asks again (password, authenticator code, security key or
// SSO), and retries once.
import {
  apiUrl,
  authSignInOptionsOptions,
  authStepUpMutation,
  authStepUpStatusOptions,
  authStepUpStatusQueryKey,
  authStepUpWebauthnOptionsMutation,
  describeError,
  isProblem,
  problemCode,
} from "@agnostic/api";
import {
  Button,
  Callout,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Field,
  Input,
  LoadingRows,
  SegmentedControl,
} from "@agnostic/ui";
import { useMutation, useQuery, useQueryClient, type UseMutationOptions } from "@tanstack/react-query";
import { KeyRound } from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
  type SubmitEvent,
} from "react";

import { withQueryFn } from "./query";
import { webauthnAvailable, webauthnError, webauthnGet } from "./webauthn";

export type Reauth = {
  /** Runs `fn`; on `reauth_required` asks the person to confirm it's them, then runs it once more. */
  run<T>(fn: () => Promise<T>): Promise<T>;
};

type Waiter = { resolve: () => void; reject: (error: unknown) => void; error: unknown };

const ReauthContext = createContext<((error: unknown) => Promise<void>) | null>(null);

export function isReauthRequired(error: unknown): boolean {
  return problemCode(error) === "reauth_required";
}

/** `reauth_window_seconds` from the problem body (how long a confirmation lasts). */
function windowSeconds(error: unknown): number | undefined {
  if (!isProblem(error)) return undefined;
  const value = (error as { reauth_window_seconds?: unknown }).reauth_window_seconds;
  return typeof value === "number" ? value : undefined;
}

/** Mount once near the app root: owns the one re-authentication dialog every `useReauth()` caller shares. */
export function ReauthProvider({ children }: { children: ReactNode }) {
  const waiters = useRef<Waiter[]>([]);
  const [request, setRequest] = useState<{ error: unknown } | null>(null);

  const ask = useCallback(
    (error: unknown) =>
      new Promise<void>((resolve, reject) => {
        waiters.current.push({ resolve, reject, error });
        setRequest((current) => current ?? { error });
      }),
    [],
  );

  const settle = (verified: boolean) => {
    const pending = waiters.current;
    waiters.current = [];
    setRequest(null);
    for (const waiter of pending) {
      if (verified) waiter.resolve();
      else waiter.reject(waiter.error);
    }
  };

  return (
    <ReauthContext.Provider value={ask}>
      {children}
      <ReauthDialog
        open={request !== null}
        windowSeconds={request ? windowSeconds(request.error) : undefined}
        onOpenChange={(open) => {
          if (!open) settle(false);
        }}
        onVerified={() => {
          settle(true);
        }}
      />
    </ReauthContext.Provider>
  );
}

/**
 * `run(fn)` retries `fn` once after the person confirms it's them. Without a `ReauthProvider` (tests, public
 * pages) the `reauth_required` error is thrown as it is.
 */
export function useReauth(): Reauth {
  const ask = useContext(ReauthContext);
  const run = useCallback(
    async <T,>(fn: () => Promise<T>): Promise<T> => {
      try {
        return await fn();
      } catch (error) {
        if (!isReauthRequired(error) || !ask) throw error;
        await ask(error);
        return fn();
      }
    },
    [ask],
  );
  return useMemo(() => ({ run }), [run]);
}

/** Wraps a generated mutation's `mutationFn` with `reauth.run`: `useMutation(withReauth(reauth, xMutation()))`. */
export function withReauth<TData, TError, TVariables, TOnMutateResult>(
  reauth: Reauth,
  options: UseMutationOptions<TData, TError, TVariables, TOnMutateResult>,
): UseMutationOptions<TData, TError, TVariables, TOnMutateResult> {
  const fn = options.mutationFn;
  if (!fn) return options;
  return { ...options, mutationFn: (...args) => reauth.run(() => fn(...args)) };
}

type Method = "password" | "totp" | "webauthn" | "sso";

const METHOD_LABELS: Record<Method, string> = {
  password: "Password",
  totp: "Authenticator app",
  webauthn: "Security key",
  sso: "Single sign-on",
};

function isMethod(value: string): value is Method {
  return value in METHOD_LABELS;
}

function currentPath(): string {
  return `${window.location.pathname}${window.location.search}`;
}

/** "Confirm it's you": the methods `GET /auth/step-up` offers this person. */
export function ReauthDialog({
  open,
  onOpenChange,
  onVerified,
  windowSeconds: seconds,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onVerified: () => void;
  /** How long the confirmation lasts, from the `reauth_required` problem. */
  windowSeconds?: number | undefined;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Confirm it's you</DialogTitle>
          <DialogDescription>
            This change needs a recent sign-in.
            {seconds ? ` Confirming lasts ${String(Math.round(seconds / 60))} minutes.` : ""}
          </DialogDescription>
        </DialogHeader>
        {open && (
          <ReauthForm
            onVerified={onVerified}
            onCancel={() => {
              onOpenChange(false);
            }}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function ReauthForm({ onVerified, onCancel }: { onVerified: () => void; onCancel: () => void }) {
  const queryClient = useQueryClient();
  const status = useQuery({ ...withQueryFn(authStepUpStatusOptions()), staleTime: 0, retry: false });
  const signIn = useQuery({ ...withQueryFn(authSignInOptionsOptions()), staleTime: 60_000 });
  const methods = (status.data?.methods ?? []).filter(isMethod);
  const [chosen, setChosen] = useState<Method | undefined>(undefined);
  const method = chosen && methods.includes(chosen) ? chosen : methods[0];
  const [secret, setSecret] = useState("");
  const [keyError, setKeyError] = useState<string | undefined>(undefined);

  const stepUp = useMutation({
    ...authStepUpMutation(),
    onSuccess: (data) => {
      queryClient.setQueryData(authStepUpStatusQueryKey(), data);
      onVerified();
    },
  });
  const keyOptions = useMutation(authStepUpWebauthnOptionsMutation());

  if (status.isPending) return <LoadingRows rows={2} label="Loading sign-in methods" />;
  if (status.isError) return <Callout tone="danger">{describeError(status.error).reason}</Callout>;

  const failure = stepUp.error
    ? problemCode(stepUp.error) === "step_up_failed"
      ? method === "password"
        ? "That password isn't right."
        : "That code isn't right, or it expired."
      : describeError(stepUp.error).reason
    : undefined;

  const signWithKey = async () => {
    setKeyError(undefined);
    try {
      const options = await keyOptions.mutateAsync({});
      const credential = await webauthnGet(options);
      stepUp.mutate({ body: { webauthn: credential } });
    } catch (error) {
      setKeyError(isProblem(error) ? describeError(error).reason : webauthnError(error));
    }
  };

  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (method === "password") stepUp.mutate({ body: { password: secret } });
    else if (method === "totp") stepUp.mutate({ body: { code: secret.replace(/\s+/g, "") } });
  };

  const providerName = (id: string) =>
    signIn.data?.providers.find((provider) => provider.id === id)?.display_name ?? id;

  return (
    <div className="flex flex-col gap-4">
      {methods.length > 1 && method && (
        <SegmentedControl
          label="How to confirm"
          value={method}
          options={methods.map((value) => ({ value, label: METHOD_LABELS[value] }))}
          onValueChange={(value) => {
            setChosen(value);
            setSecret("");
            stepUp.reset();
            setKeyError(undefined);
          }}
        />
      )}
      {methods.length === 0 && (
        <Callout tone="warning">
          There's no way to confirm it's you on this account. Sign out and sign in again, then retry.
        </Callout>
      )}
      {(method === "password" || method === "totp") && (
        <form className="flex flex-col gap-4" onSubmit={submit}>
          {method === "password" ? (
            <Field label="Password" error={failure}>
              {({ id, describedBy, invalid }) => (
                <Input
                  id={id}
                  type="password"
                  autoComplete="current-password"
                  required

                  value={secret}
                  aria-describedby={describedBy}
                  aria-invalid={invalid || undefined}
                  onChange={(event) => {
                    setSecret(event.target.value);
                  }}
                />
              )}
            </Field>
          ) : (
            <Field
              label="Authenticator code"
              hint="The 6-digit code from your authenticator app."
              error={failure}
            >
              {({ id, describedBy, invalid }) => (
                <Input
                  id={id}
                  mono
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  required

                  value={secret}
                  aria-describedby={describedBy}
                  aria-invalid={invalid || undefined}
                  onChange={(event) => {
                    setSecret(event.target.value);
                  }}
                />
              )}
            </Field>
          )}
          <DialogFooter>
            <Button variant="ghost" onClick={onCancel}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" disabled={stepUp.isPending || secret === ""}>
              {stepUp.isPending ? "Confirming…" : "Confirm"}
            </Button>
          </DialogFooter>
        </form>
      )}
      {method === "webauthn" && (
        <div className="flex flex-col gap-3">
          <p className="text-[13px] text-fg-secondary">Touch your security key or use your passkey.</p>
          {!webauthnAvailable() && (
            <Callout tone="warning">This browser doesn't support security keys.</Callout>
          )}
          {(keyError ?? failure) && <Callout tone="danger">{keyError ?? failure}</Callout>}
          <DialogFooter>
            <Button variant="ghost" onClick={onCancel}>
              Cancel
            </Button>
            <Button
              variant="primary"
              disabled={!webauthnAvailable() || keyOptions.isPending || stepUp.isPending}
              onClick={() => {
                void signWithKey();
              }}
            >
              <KeyRound aria-hidden />
              Use security key
            </Button>
          </DialogFooter>
        </div>
      )}
      {method === "sso" && (
        <div className="flex flex-col gap-3">
          <p className="text-[13px] text-fg-secondary">
            Sign in again with your identity provider. You'll come back to this page; then repeat the change.
          </p>
          {status.data.sso_providers.map((id) => (
            <Button key={id} asChild variant="secondary" size="36" className="w-full">
              <a
                href={apiUrl(
                  `/api/v1/auth/sso/${encodeURIComponent(id)}/start?next=${encodeURIComponent(currentPath())}`,
                )}
              >
                <KeyRound aria-hidden />
                Continue with {providerName(id)}
              </a>
            </Button>
          ))}
          <DialogFooter>
            <Button variant="ghost" onClick={onCancel}>
              Cancel
            </Button>
          </DialogFooter>
        </div>
      )}
    </div>
  );
}
