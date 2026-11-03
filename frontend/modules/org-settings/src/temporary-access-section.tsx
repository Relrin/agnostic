// Temporary access: the longest a requested or granted temporary binding may last.
import { describeError, orgGetOrgQueryKey, orgUpdateOrgMutation } from "@agnostic/api";
import { useOrg, useReauth, withReauth } from "@agnostic/core";
import { Button, Callout, ErrorState, Field, Input, LoadingRows, toast } from "@agnostic/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type SubmitEvent } from "react";

import { Section, useWritable } from "./shared";

const DEFAULT_MAX_HOURS = 168;

function MaxHoursForm({ current, writable }: { current: number; writable: boolean }) {
  const queryClient = useQueryClient();
  const reauth = useReauth();
  const [hours, setHours] = useState(String(current));
  const save = useMutation({
    ...withReauth(reauth, orgUpdateOrgMutation()),
    onSuccess: (data) => {
      queryClient.setQueryData(orgGetOrgQueryKey(), data);
      toast("Temporary access limit saved");
    },
  });
  const value = Number(hours);
  const valid = Number.isInteger(value) && value >= 1 && value <= 2160;
  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    save.mutate({ body: { settings: { temporary_access_max_hours: value } } });
  };
  return (
    <form className="flex flex-col gap-4" onSubmit={submit}>
      <fieldset disabled={!writable} className="max-w-xs">
        <Field
          label="Longest temporary access (hours)"
          hint="Between 1 hour and 90 days (2160 hours)."
          error={hours !== "" && !valid ? "Enter a whole number of hours from 1 to 2160." : undefined}
        >
          {({ id, describedBy, invalid }) => (
            <Input
              id={id}
              type="number"
              min={1}
              max={2160}
              inputMode="numeric"
              aria-describedby={describedBy}
              aria-invalid={invalid || undefined}
              value={hours}
              onChange={(event) => {
                setHours(event.target.value);
              }}
            />
          )}
        </Field>
      </fieldset>
      {save.error && <Callout tone="danger">{describeError(save.error).reason}</Callout>}
      {writable && (
        <div>
          <Button type="submit" variant="primary" disabled={!valid || value === current || save.isPending}>
            {save.isPending ? "Saving…" : "Save limit"}
          </Button>
        </div>
      )}
    </form>
  );
}

export function TemporaryAccessSection() {
  const { writable, note } = useWritable("org:write");
  const org = useOrg();
  const current = org.data?.settings.temporary_access_max_hours ?? DEFAULT_MAX_HOURS;
  return (
    <div className="flex flex-col gap-5">
      {note}
      <Section
        title="Temporary access"
        description="Members ask for access with “Request access” wherever something is denied; Administrators or group owners approve it, and the binding expires on its own. Admins can also grant temporary access from People or the audit log."
      >
        {org.isPending ? (
          <LoadingRows rows={1} label="Loading the org" />
        ) : org.isError ? (
          <ErrorState reason={describeError(org.error).reason} />
        ) : (
          <MaxHoursForm key={current} current={current} writable={writable} />
        )}
      </Section>
    </div>
  );
}
