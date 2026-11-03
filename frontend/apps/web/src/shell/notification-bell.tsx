// The bell in the header: unread count, the latest notifications, mark read, and a way to the preferences.
import {
  describeError,
  notificationsListNotificationsOptions,
  notificationsMarkReadMutation,
  notificationsUnreadCountQueryKey,
  type NotificationOut,
} from "@agnostic/api";
import { formatRelative, STALE_TIME, useUnreadNotifications, withQueryFn } from "@agnostic/core";
import { Button, cn, Popover, PopoverContent, PopoverTrigger, toast } from "@agnostic/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { Bell } from "lucide-react";
import { useState } from "react";

const LIST = { query: { limit: 10 } } as const;

export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const unread = useUnreadNotifications();
  const list = useQuery({
    ...withQueryFn(notificationsListNotificationsOptions(LIST)),
    enabled: open,
    staleTime: STALE_TIME.live,
  });
  const markRead = useMutation({
    ...notificationsMarkReadMutation(),
    onSuccess: (data) => {
      queryClient.setQueryData(notificationsUnreadCountQueryKey(), { unread: data.unread });
      void list.refetch();
    },
    onError: (error) => toast.error(describeError(error).reason),
  });

  const count = unread.data?.unread ?? 0;
  const label = count ? `Notifications, ${String(count)} unread` : "Notifications";

  const openItem = (item: NotificationOut) => {
    if (!item.read_at) markRead.mutate({ body: { ids: [item.id] } });
    setOpen(false);
    if (item.link) void navigate({ to: item.link });
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="icon" size="32" aria-label={label} className="relative">
          <Bell aria-hidden />
          {count > 0 && (
            <span
              aria-hidden
              className="absolute -top-0.5 -right-0.5 min-w-4 rounded-full bg-warning px-1 text-center font-mono text-[10px] leading-4 font-semibold text-bg"
            >
              {count > 99 ? "99+" : count}
            </span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent aria-label="Notifications" className="flex w-96 flex-col">
        <header className="flex items-center justify-between gap-2 border-b border-divider-row px-3 py-2">
          <span className="text-[13px] font-semibold">Notifications</span>
          <Button
            variant="ghost"
            size="28"
            disabled={count === 0 || markRead.isPending}
            onClick={() => {
              markRead.mutate({ body: {} });
            }}
          >
            Mark all read
          </Button>
        </header>
        <ul className="max-h-96 divide-y divide-divider-row overflow-y-auto">
          {list.isPending ? (
            <li className="px-3 py-4 text-[12.5px] text-fg-muted">Loading…</li>
          ) : list.isError ? (
            <li className="px-3 py-4 text-[12.5px] text-danger">{describeError(list.error).reason}</li>
          ) : list.data.data.length === 0 ? (
            <li className="px-3 py-4 text-[12.5px] text-fg-muted">Nothing yet.</li>
          ) : (
            list.data.data.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  onClick={() => {
                    openItem(item);
                  }}
                  className="flex w-full flex-col gap-0.5 px-3 py-2.5 text-left hover:bg-surface-hover"
                >
                  <span className="flex items-center gap-2">
                    <span
                      aria-label={item.read_at ? undefined : "Unread"}
                      className={cn(
                        "size-1.5 shrink-0 rounded-full",
                        item.read_at ? "bg-transparent" : "bg-warning",
                      )}
                    />
                    <span className="truncate text-[13px] font-medium">{item.title}</span>
                  </span>
                  {item.body && (
                    <span className="line-clamp-2 pl-3.5 text-[12px] text-fg-secondary">{item.body}</span>
                  )}
                  <span className="pl-3.5 text-[11.5px] text-fg-muted">
                    {formatRelative(item.created_at)}
                  </span>
                </button>
              </li>
            ))
          )}
        </ul>
        <footer className="border-t border-divider-row px-3 py-2">
          <Button
            variant="link"
            size="28"
            onClick={() => {
              setOpen(false);
              void navigate({ to: "/account", hash: "notifications" });
            }}
          >
            Notification settings
          </Button>
        </footer>
      </PopoverContent>
    </Popover>
  );
}
