import {
  describeError,
  helloCreateGreetingMutation,
  helloListGreetingsOptions,
  helloListGreetingsQueryKey,
  type GreetingOut,
} from "@agnostic/api";
import { Button, EmptyState, ErrorState, Input, LoadingRows, PageIntro, StatusPill } from "@agnostic/ui";
import { skipToken, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState, type SubmitEvent } from "react";

const MAX_LENGTH = 280;

function hasPending(greetings: readonly GreetingOut[] | undefined): boolean {
  return greetings?.some((greeting) => greeting.status === "pending") ?? false;
}

/** Sample page proving the module contract: reads and writes through the generated client, job-backed reply. */
export function HelloPage() {
  const queryClient = useQueryClient();
  const inputId = useId();
  const [message, setMessage] = useState("");

  const listOptions = helloListGreetingsOptions({ query: { limit: 20 } });
  const greetings = useQuery({
    ...listOptions,
    // Generated options declare `queryFn` optional; spreading them with extra options needs it explicit under
    // exactOptionalPropertyTypes. It is always set, so `skipToken` is only there for the type.
    queryFn: listOptions.queryFn ?? skipToken,
    // The reply is written by a background job; poll until it lands.
    refetchInterval: (query) => (hasPending(query.state.data?.data) ? 1000 : false),
  });

  const create = useMutation({
    ...helloCreateGreetingMutation(),
    onSuccess: async () => {
      setMessage("");
      await queryClient.invalidateQueries({ queryKey: helloListGreetingsQueryKey() });
    },
  });

  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (message.trim()) create.mutate({ body: { message } });
  };

  const createError = create.error ? describeError(create.error) : undefined;

  return (
    <div className="mx-auto flex w-full max-w-[1320px] flex-col gap-6 px-8 pt-6 pb-10">
      <PageIntro title="Hello">
        A sample module that proves the module contract end to end: a route, a table, a migration, a
        background job and generated client code. It goes away at the end of P01.
      </PageIntro>

      <form onSubmit={submit} className="flex max-w-2xl flex-col gap-2">
        <label htmlFor={inputId} className="text-[13px] text-fg-secondary">
          Greeting
        </label>
        <div className="flex gap-2">
          <Input
            id={inputId}
            value={message}
            maxLength={MAX_LENGTH}
            placeholder="Say something to the control plane"
            aria-invalid={createError ? true : undefined}
            onChange={(event) => {
              setMessage(event.target.value);
            }}
          />
          <Button type="submit" variant="primary" disabled={!message.trim() || create.isPending}>
            {create.isPending ? "Sending…" : "Send greeting"}
          </Button>
        </div>
        {createError && (
          <p role="alert" className="text-[12.5px] text-danger">
            {createError.reason}
          </p>
        )}
      </form>

      <section aria-labelledby="greetings-heading" className="flex flex-col gap-3">
        <h2 id="greetings-heading" className="text-[15px] font-semibold">
          Greetings
        </h2>
        {greetings.isPending ? (
          <LoadingRows rows={4} label="Loading greetings" />
        ) : greetings.isError ? (
          <ErrorState
            reason={describeError(greetings.error).reason}
            requestId={describeError(greetings.error).requestId}
            onRetry={() => void greetings.refetch()}
          />
        ) : greetings.data.data.length === 0 ? (
          <EmptyState title="No greetings yet">
            Greetings appear here once you send one. A background job writes the reply a moment later.
          </EmptyState>
        ) : (
          <ul className="flex flex-col divide-y divide-divider-row rounded-card border border-border bg-surface">
            {greetings.data.data.map((greeting) => (
              <li key={greeting.id} className="flex flex-col gap-1 px-4 py-3">
                <div className="flex items-center gap-2">
                  <StatusPill status={greeting.status === "replied" ? "COMPLETED" : "PENDING"} />
                  <span className="text-[13.5px]">{greeting.message}</span>
                  <span className="ml-auto font-mono text-[11.5px] text-fg-muted">{greeting.id}</span>
                </div>
                <p className="text-[13px] text-fg-secondary">
                  {greeting.reply ?? "Reply queued · the worker is on it"}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
