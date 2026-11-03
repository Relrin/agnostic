// Layout and helpers shared by the public pages (outside the signed-in shell).
import { authSignInOptionsOptions, type SignInProviderOut } from "@agnostic/api";
import { withQueryFn } from "@agnostic/core";
import { Button } from "@agnostic/ui";
import { useQuery } from "@tanstack/react-query";
import { useRouterState } from "@tanstack/react-router";
import { FileKey2, KeyRound } from "lucide-react";
import type { ReactNode } from "react";

export function PublicPage({
  title,
  intro,
  children,
}: {
  title: ReactNode;
  intro?: ReactNode;
  children: ReactNode;
}) {
  return (
    <main className="grid min-h-dvh place-items-center bg-canvas px-4 py-10">
      <div className="flex w-full max-w-[420px] flex-col gap-6">
        <div className="flex items-center gap-2.5">
          <span
            aria-hidden
            className="grid size-8 place-items-center rounded-control bg-accent text-[15px] font-bold text-accent-fg"
          >
            A
          </span>
          <span className="text-[15px] font-semibold">Agnostic</span>
        </div>
        <section className="flex flex-col gap-5 rounded-card border border-border bg-surface p-6">
          <div className="flex flex-col gap-1.5">
            <h1 className="text-[20px] font-semibold tracking-[-0.01em]">{title}</h1>
            {intro && <p className="text-[13.5px] text-fg-secondary">{intro}</p>}
          </div>
          {children}
        </section>
      </div>
    </main>
  );
}

/** A query-string parameter of the current location. */
export function useSearchParam(name: string): string | undefined {
  return useRouterState({
    select: (state) => {
      const value = (state.location.search as Record<string, unknown>)[name];
      return typeof value === "string" ? value : typeof value === "number" ? String(value) : undefined;
    },
  });
}

/** Only same-origin paths are allowed as post-sign-in destinations. */
export function safeNext(target: string | undefined): string {
  return target?.startsWith("/") && !target.startsWith("//") ? target : "/";
}

export function useSignInOptions() {
  return useQuery({ ...withQueryFn(authSignInOptionsOptions()), staleTime: 60_000 });
}

export function ssoStartUrl(provider: SignInProviderOut, next: string): string {
  return `/api/v1/auth/sso/${encodeURIComponent(provider.id)}/start?next=${encodeURIComponent(next)}`;
}

/** "Continue with GitHub" buttons; a full-page navigation, since the provider redirects back to the API. */
export function SsoButtons({ providers, next }: { providers: readonly SignInProviderOut[]; next: string }) {
  if (providers.length === 0) return null;
  return (
    <div className="flex flex-col gap-2">
      {providers.map((provider) => {
        const Icon = provider.preset === "saml" ? FileKey2 : KeyRound;
        return (
          <Button key={provider.id} asChild variant="secondary" size="36" className="w-full">
            <a href={ssoStartUrl(provider, next)} data-preset={provider.preset}>
              <Icon aria-hidden />
              Continue with {provider.display_name}
            </a>
          </Button>
        );
      })}
    </div>
  );
}

export const SSO_ERRORS: Record<string, string> = {
  not_invited: "You need an invitation to join this org. Ask an Owner or Administrator to invite you.",
  domain_not_allowed: "Your email domain isn't allowed to join this org.",
  seats_full: "All seats are taken. Ask an Owner to free one up.",
  email_unverified: "Verify your email address with your identity provider first, then try again.",
  email_missing: "Your identity provider didn't share an email address.",
  account_disabled: "Your account is disabled. Ask an Owner or Administrator.",
  state_expired: "The sign-in took too long or was already used. Try again.",
  state_mismatch: "The sign-in response didn't match. Try again.",
  nonce_mismatch: "The sign-in response was replayed or tampered with. Try again.",
  provider_denied: "Sign-in was cancelled at the identity provider.",
  provider_error:
    "The identity provider returned an error. Try again, or ask an administrator to check the logs.",
  saml_invalid:
    "The identity provider's SAML response couldn't be read. Ask an administrator to check the setup.",
  saml_signature:
    "The SAML response wasn't signed with the identity provider's certificate. Ask an administrator to refresh its metadata.",
  saml_audience:
    "The SAML response was meant for a different app. Ask an administrator to check the SP entity ID in the identity provider.",
  saml_expired: "The SAML response expired before it arrived. Check your device's clock and try again.",
  saml_replayed: "That SAML response was already used. Start the sign-in again.",
  sso_required: "Your org signs in with SSO. Continue with your identity provider.",
};
