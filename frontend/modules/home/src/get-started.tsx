// "Get started" on Home: three first steps whose progress comes from data (an instance, a chat session, sign-in
// providers or other people in the org). "Show me" opens the page with its tour; dismissing it is remembered in
// `me.preferences` ("onboarding.dismissed").
import { authSignInOptionsOptions, meGetMeQueryKey, meUpdateMeMutation } from "@agnostic/api";
import { useInstances, useMe, useOrg, useSessions, withQueryFn } from "@agnostic/core";
import { Button, Card, cn } from "@agnostic/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Check } from "lucide-react";
import type { ReactNode } from "react";

export const ONBOARDING_DISMISSED = "onboarding.dismissed";

type Step = {
  id: string;
  title: string;
  detail: string;
  done: boolean;
  actions: ReactNode;
};

function StepItem({ step, number }: { step: Step; number: number }) {
  return (
    <li className="flex gap-3 py-3 first:pt-0 last:pb-0">
      <span
        aria-hidden
        className={cn(
          "mt-0.5 inline-flex size-6 shrink-0 items-center justify-center rounded-full border font-mono text-[11.5px]",
          step.done ? "border-accent bg-accent text-accent-fg" : "border-border-strong text-fg-secondary",
        )}
      >
        {step.done ? <Check className="size-3.5" /> : number}
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <h3 className={cn("text-[13.5px] font-medium", step.done && "text-fg-secondary line-through")}>
          {step.title}
          <span className="sr-only">{step.done ? " (done)" : " (to do)"}</span>
        </h3>
        <p className="text-[12.5px] text-fg-secondary">{step.detail}</p>
        {!step.done && <div className="flex flex-wrap gap-2 pt-1.5">{step.actions}</div>}
      </div>
    </li>
  );
}

/** The checklist card; nothing once it's dismissed or every step is done. */
export function GetStarted({ instance }: { instance: string }) {
  const queryClient = useQueryClient();
  const me = useMe();
  const org = useOrg();
  const instances = useInstances();
  const sessions = useSessions(instance, { limit: 1 }, Boolean(instance));
  const signIn = useQuery({ ...withQueryFn(authSignInOptionsOptions()), staleTime: 60_000 });
  const dismiss = useMutation({
    ...meUpdateMeMutation(),
    onSuccess: (data) => {
      queryClient.setQueryData(meGetMeQueryKey(), data);
    },
  });

  if (!me.data || me.data.preferences[ONBOARDING_DISMISSED] === true) return null;
  // Wait for the facts each step is decided by, so the card doesn't flash steps as to-do.
  if (instances.isPending || org.isPending || sessions.isPending || signIn.isPending) return null;

  const scoped = (target: string) => `/i/${encodeURIComponent(instance)}/${target}`;
  const steps: Step[] = [
    {
      id: "instance",
      title: "Connect your first instance",
      detail: "Point Agnostic at an AgentOS endpoint and test the connection.",
      done: (instances.data?.length ?? 0) > 0,
      actions: (
        <>
          <Button asChild size="28" variant="primary">
            <Link to="/instances/connect">Connect an instance</Link>
          </Button>
          <Button asChild size="28" variant="outline">
            <Link to="/instances/connect" search={{ tour: "connect" }}>
              Show me
            </Link>
          </Button>
        </>
      ),
    },
    {
      id: "chat",
      title: "Chat with your first agent",
      detail: "Pick an agent, team or workflow and send it a message; the run shows step by step.",
      done: (sessions.data?.data.length ?? 0) > 0,
      actions: (
        <>
          <Button asChild size="28" variant="primary">
            <Link to={scoped("chat")}>Open Chat</Link>
          </Button>
          <Button asChild size="28" variant="outline">
            <Link to={scoped("chat")} search={{ tour: "chat" }}>
              Show me
            </Link>
          </Button>
        </>
      ),
    },
    {
      id: "people",
      title: "Set up sign-in and invite people",
      detail: "Add your identity provider (OIDC or SAML), then invite your team and give them roles.",
      done:
        (signIn.data?.providers.length ?? 0) > 0 ||
        (org.data?.member_count ?? 0) > 1 ||
        (org.data?.pending_invitations ?? 0) > 0,
      actions: (
        <>
          <Button asChild size="28" variant="primary">
            <Link to="/access/people">Invite people</Link>
          </Button>
          <Button asChild size="28" variant="outline">
            <Link to="/org/settings/$section" params={{ section: "authentication" }}>
              Sign-in settings
            </Link>
          </Button>
        </>
      ),
    },
  ];
  const done = steps.filter((step) => step.done).length;
  if (done === steps.length) return null;

  return (
    <Card
      title="Get started"
      meta={`${String(done)} of ${String(steps.length)} done`}
      aria-label="Get started"
      action={
        <Button
          size="28"
          variant="ghost"
          disabled={dismiss.isPending}
          onClick={() => {
            dismiss.mutate({ body: { preferences: { [ONBOARDING_DISMISSED]: true } } });
          }}
        >
          Dismiss
        </Button>
      }
    >
      <ol aria-label="First steps" className="flex flex-col divide-y divide-divider-row">
        {steps.map((step, index) => (
          <StepItem key={step.id} step={step} number={index + 1} />
        ))}
      </ol>
    </Card>
  );
}
