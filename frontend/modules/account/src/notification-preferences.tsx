// Which channels each event reaches you through, and quiet hours that hold back email and Slack.
import {
  describeError,
  notificationsMyPreferencesOptions,
  notificationsMyPreferencesQueryKey,
  notificationsUpdateMyPreferencesMutation,
  type PersonalChannelName,
  type PreferencesOut,
} from "@agnostic/api";
import { formattingTimeZone, withQueryFn } from "@agnostic/core";
import { Button, Callout, ErrorState, Input, LoadingRows, Switch, toast } from "@agnostic/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

const CHANNELS: { id: PersonalChannelName; label: string }[] = [
  { id: "in_app", label: "In app" },
  { id: "email", label: "Email" },
  { id: "slack", label: "Slack" },
];

function QuietHours({
  value,
  onSave,
  saving,
}: {
  value: PreferencesOut["quiet_hours"];
  onSave: (next: PreferencesOut["quiet_hours"]) => void;
  saving: boolean;
}) {
  const [start, setStart] = useState(value?.start ?? "22:00");
  const [end, setEnd] = useState(value?.end ?? "07:00");
  const zone = value?.timezone ?? formattingTimeZone();
  const fromId = useId();
  const toId = useId();
  return (
    <div className="flex flex-col gap-3">
      <Switch
        label="Quiet hours"
        description="Hold back email and Slack during these hours. The bell still shows everything."
        checked={value !== null}
        disabled={saving}
        onCheckedChange={(checked) => {
          onSave(checked ? { start, end, timezone: zone } : null);
        }}
      />
      {value && (
        <div className="flex flex-wrap items-end gap-3 pl-1">
          <div className="flex flex-col gap-1 text-[12px] text-fg-muted">
            <label htmlFor={fromId}>From</label>
            <Input
              id={fromId}
              type="time"
              value={start}
              onChange={(event) => {
                setStart(event.target.value);
              }}
              className="w-28"
            />
          </div>
          <div className="flex flex-col gap-1 text-[12px] text-fg-muted">
            <label htmlFor={toId}>To</label>
            <Input
              id={toId}
              type="time"
              value={end}
              onChange={(event) => {
                setEnd(event.target.value);
              }}
              className="w-28"
            />
          </div>
          <span className="pb-2 font-mono text-[12px] text-fg-muted">{zone}</span>
          <Button
            variant="outline"
            size="32"
            disabled={saving || (start === value.start && end === value.end)}
            onClick={() => {
              onSave({ start, end, timezone: zone });
            }}
          >
            Save hours
          </Button>
        </div>
      )}
    </div>
  );
}

export function NotificationPreferences() {
  const queryClient = useQueryClient();
  const preferences = useQuery(withQueryFn(notificationsMyPreferencesOptions()));
  const update = useMutation({
    ...notificationsUpdateMyPreferencesMutation(),
    onSuccess: (data) => {
      queryClient.setQueryData(notificationsMyPreferencesQueryKey(), data);
    },
    onError: (error) => toast.error(describeError(error).reason),
  });

  if (preferences.isPending) return <LoadingRows rows={4} label="Loading notification preferences" />;
  if (preferences.isError) return <ErrorState reason={describeError(preferences.error).reason} />;
  const data = preferences.data;

  return (
    <div className="flex max-w-3xl flex-col gap-5">
      {!data.slack_available && (
        <Callout tone="availability">
          Slack messages need a Slack bot that may send direct messages; an org admin adds it in Settings ›
          Notifications.
        </Callout>
      )}
      <table className="w-full text-[13px]">
        <caption className="sr-only">Channels per event</caption>
        <thead>
          <tr className="text-left text-[11.5px] text-fg-muted">
            <th className="py-1.5 font-medium">Event</th>
            {CHANNELS.map((channel) => (
              <th key={channel.id} className="w-20 py-1.5 text-center font-medium">
                {channel.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-divider-row">
          {data.events.map((preference) => (
            <tr key={preference.event.name}>
              <td className="py-2 pr-4">
                <div className="font-medium">{preference.event.label}</div>
                <div className="text-[12px] text-fg-muted">
                  {preference.event.description}
                  {preference.custom ? "" : " · org default"}
                </div>
              </td>
              {CHANNELS.map((channel) => {
                const checked = preference.channels.includes(channel.id);
                return (
                  <td key={channel.id} className="text-center">
                    <input
                      type="checkbox"
                      aria-label={`${preference.event.label} by ${channel.label}`}
                      className="size-4 accent-[var(--accent)]"
                      checked={checked}
                      disabled={
                        update.isPending || (channel.id === "slack" && !data.slack_available && !checked)
                      }
                      onChange={() => {
                        const next = checked
                          ? preference.channels.filter((id) => id !== channel.id)
                          : [...preference.channels, channel.id];
                        update.mutate({ body: { events: { [preference.event.name]: next } } });
                      }}
                    />
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <QuietHours
        key={`${data.quiet_hours?.start ?? ""}-${data.quiet_hours?.end ?? ""}`}
        value={data.quiet_hours}
        saving={update.isPending}
        onSave={(next) => {
          update.mutate({ body: next ? { quiet_hours: next } : { clear_quiet_hours: true } });
        }}
      />
    </div>
  );
}
