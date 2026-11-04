// `/i/:instance/ask?conversation=&q=&context=`: your conversations with Ask your OS on this instance. Answers are
// written by a worker; the newest one streams in, earlier ones come from the stored thread.
import {
  assistantDeleteConversationMutation,
  assistantGetConversationOptions,
  assistantGetConversationQueryKey,
  assistantListConversationsOptions,
  assistantListConversationsQueryKey,
  type MessageOut,
} from "@agnostic/api";
import {
  AnswerView,
  AskBox,
  fromMessage,
  settled,
  suggestionsFor,
  useAnswer,
  useAssistant,
} from "@agnostic/assistant";
import { STALE_TIME, formatRelative, withQueryFn } from "@agnostic/core";
import { Button, EmptyState, ErrorState, LoadingRows, PageIntro, UserBubble, cn } from "@agnostic/ui";
import { skipToken, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

function LiveAnswer({
  instance,
  message,
  onSettled,
}: {
  instance: string;
  message: MessageOut;
  onSettled: () => void;
}) {
  const { state, stop } = useAnswer(instance, message.id);
  const done = settled(state);
  useEffect(() => {
    if (done) onSettled();
  }, [done, onSettled]);
  return <AnswerView state={state} onStop={() => void stop()} />;
}

function Thread({
  instance,
  conversationId,
  pending,
}: {
  instance: string;
  conversationId: string;
  pending: string | undefined;
}) {
  const client = useQueryClient();
  const options = assistantGetConversationOptions({ path: { instance, conversation_id: conversationId } });
  const thread = useQuery({ ...withQueryFn(options), staleTime: STALE_TIME.live });
  const refresh = () => {
    void client.invalidateQueries({
      queryKey: assistantGetConversationQueryKey({ path: { instance, conversation_id: conversationId } }),
    });
  };
  // A question just asked may not be in the stored thread yet.
  useEffect(() => {
    if (pending) refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- refetch once per new question
  }, [pending]);

  if (thread.isPending) return <LoadingRows rows={3} />;
  if (thread.isError) return <ErrorState reason="This conversation couldn't be loaded." onRetry={refresh} />;
  return (
    <ol aria-label="Messages" className="flex flex-col gap-4">
      {thread.data.messages.map((message) => (
        <li key={message.id}>
          {message.role === "user" ? (
            <UserBubble
              attachments={
                message.attachments.length > 0 ? (
                  <span className="text-[12px] text-fg-muted">
                    {message.attachments.map((attachment) => attachment.name).join(", ")}
                  </span>
                ) : undefined
              }
            >
              {message.content}
            </UserBubble>
          ) : message.status === "queued" || message.status === "running" ? (
            <LiveAnswer instance={instance} message={message} onSettled={refresh} />
          ) : (
            <AnswerView state={fromMessage(message)} />
          )}
        </li>
      ))}
    </ol>
  );
}

export function AskPage() {
  const params = useParams({ strict: false }) as unknown as Record<string, string | undefined>;
  const search = useSearch({ strict: false }) as unknown as Record<string, unknown>;
  const navigate = useNavigate();
  const client = useQueryClient();
  const instance = params.instance ?? "";
  const conversationId = typeof search.conversation === "string" ? search.conversation : undefined;
  const initial = typeof search.q === "string" ? search.q : "";
  const context = typeof search.context === "string" ? search.context : undefined;
  const [pending, setPending] = useState<string>();
  const { available, status } = useAssistant();

  const listOptions = assistantListConversationsOptions({ path: { instance } });
  const conversations = useQuery({
    ...listOptions,
    queryFn: available ? (listOptions.queryFn ?? skipToken) : skipToken,
    staleTime: STALE_TIME.list,
  });
  const remove = useMutation({
    ...assistantDeleteConversationMutation(),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: assistantListConversationsQueryKey({ path: { instance } }) });
      go(undefined);
    },
  });

  const go = (conversation: string | undefined) => {
    void navigate({
      to: `/i/${encodeURIComponent(instance)}/ask`,
      search: conversation ? { conversation } : {},
    });
  };

  if (!available) {
    return (
      <div className="px-6 pt-5">
        <EmptyState title="Ask your OS is off">
          An admin can turn it on in Organization › AI features.
        </EmptyState>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0">
      <aside
        aria-label="Conversations"
        className="flex w-64 shrink-0 flex-col gap-1 overflow-y-auto border-r border-border-subtle p-3"
      >
        <Button
          variant="secondary"
          size="30"
          onClick={() => {
            go(undefined);
          }}
        >
          <Plus aria-hidden /> New conversation
        </Button>
        {(conversations.data ?? []).map((conversation) => (
          <div key={conversation.id} className="group flex items-center gap-1">
            <button
              type="button"
              aria-current={conversation.id === conversationId ? "page" : undefined}
              className={cn(
                "flex min-w-0 flex-1 cursor-pointer flex-col rounded-control px-2 py-1.5 text-left hover:bg-surface-hover",
                conversation.id === conversationId && "bg-surface-selected",
              )}
              onClick={() => {
                go(conversation.id);
              }}
            >
              <span className="truncate text-[13px]">{conversation.title}</span>
              <span className="text-[11.5px] text-fg-muted">{formatRelative(conversation.updated_at)}</span>
            </button>
            <Button
              variant="icon"
              size="28"
              aria-label={`Delete ${conversation.title}`}
              className="opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
              onClick={() => {
                remove.mutate({ path: { instance, conversation_id: conversation.id } });
              }}
            >
              <Trash2 aria-hidden />
            </Button>
          </div>
        ))}
      </aside>
      <section className="flex min-w-0 flex-1 flex-col gap-4 overflow-y-auto px-6 pt-5 pb-6">
        <PageIntro title="Ask your OS">
          Questions about this instance, answered from your traces, sessions, schedules, approvals and audit
          log, with your access. Answers are generated and list the pages they used.
        </PageIntro>
        <div className="flex flex-1 flex-col gap-4">
          {conversationId ? (
            <Thread instance={instance} conversationId={conversationId} pending={pending} />
          ) : (
            <p className="text-[13px] text-fg-muted">Start with a question below.</p>
          )}
        </div>
        <AskBox
          key={conversationId ?? "new"}
          instance={instance}
          conversationId={conversationId}
          context={context}
          initial={initial}
          notice={status?.data_notice}
          label={conversationId ? "Follow up" : "Ask your OS"}
          suggestions={suggestionsFor("home")}
          onAsked={(accepted) => {
            setPending(accepted.message_id);
            void client.invalidateQueries({
              queryKey: assistantListConversationsQueryKey({ path: { instance } }),
            });
            if (accepted.conversation_id && accepted.conversation_id !== conversationId)
              go(accepted.conversation_id);
          }}
        />
      </section>
    </div>
  );
}
