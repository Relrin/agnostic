// "Grant temporary access…" (admins, straight to a binding that expires) and "Request access" (the person who was
// denied, to the approvers), prefilled from a denied event: who, where and the scope that was missing.
import {
  accessCreateRequestMutation,
  accessGrantTemporaryMutation,
  describeError,
  type AuditEventOut,
} from "@agnostic/api";
import { useOrg } from "@agnostic/core";
import {
  Button,
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Field,
  Input,
  KeyValueList,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
  toast,
} from "@agnostic/ui";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { scopesToGrant } from "./audit-api";

const DURATIONS = [1, 4, 8, 24, 72] as const;
/** The org's ceiling when settings don't say (the backend default). */
const DEFAULT_MAX_HOURS = 72;

function hoursLabel(hours: number): string {
  return hours === 1 ? "1 hour" : `${String(hours)} hours`;
}

export type AccessMode = "grant" | "request";

export function AccessDialog({
  mode,
  event,
  instanceName,
  open,
  onOpenChange,
}: {
  mode: AccessMode;
  event: AuditEventOut;
  instanceName: string | undefined;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const org = useOrg();
  const max = org.data?.settings.temporary_access_max_hours ?? DEFAULT_MAX_HOURS;
  const durations = DURATIONS.filter((hours) => hours <= max);
  const choices = durations.length ? durations : [Math.max(1, max)];
  const [hours, setHours] = useState(() => String(choices.includes(4) ? 4 : (choices.at(-1) ?? 1)));
  const [scopes, setScopes] = useState(() => scopesToGrant(event).join(", "));
  const [reason, setReason] = useState("");

  const done = (message: string) => {
    toast.success(message);
    onOpenChange(false);
    setReason("");
  };
  const grant = useMutation({
    ...accessGrantTemporaryMutation(),
    onSuccess: (binding) => {
      done(`Granted ${binding.scopes.join(", ")} to ${event.actor.display} for ${hoursLabel(Number(hours))}`);
    },
    onError: (error) => toast.error(describeError(error).reason),
  });
  const request = useMutation({
    ...accessCreateRequestMutation(),
    onSuccess: () => {
      done("Access requested · approvers are notified");
    },
    onError: (error) => toast.error(describeError(error).reason),
  });
  const pending = grant.isPending || request.isPending;
  const list = scopes
    .split(/[\s,]+/)
    .map((scope) => scope.trim())
    .filter(Boolean);
  const trimmed = reason.trim();
  const valid = list.length > 0 && trimmed.length > 0;
  const where = instanceName ?? event.instance_id ?? "the org";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{mode === "grant" ? "Grant temporary access" : "Request access"}</DialogTitle>
          <DialogDescription>
            {mode === "grant"
              ? "Adds a binding that ends on its own. It's audited, and the person sees it on their next request."
              : "Approvers (org admins and the group's owners) get the request; access ends on its own."}
          </DialogDescription>
        </DialogHeader>
        <form
          id="audit-access"
          className="flex flex-col gap-4"
          onSubmit={(submit) => {
            submit.preventDefault();
            if (!valid) return;
            const duration = Number(hours);
            if (mode === "grant")
              grant.mutate({
                body: {
                  principal_id: event.actor.id,
                  instance: event.instance_id,
                  scopes: list,
                  reason: trimmed,
                  duration_hours: duration,
                },
              });
            else
              request.mutate({
                body: {
                  instance: event.instance_id,
                  scopes: list,
                  reason: trimmed,
                  duration_hours: duration,
                },
              });
          }}
        >
          <KeyValueList
            items={[
              ...(mode === "grant" ? [{ key: "who", label: "Person", value: event.actor.display }] : []),
              { key: "where", label: "Instance", value: where, mono: true },
            ]}
          />
          <Field label="Scopes" hint="The scope the request was missing; separate several with commas.">
            {({ id, describedBy }) => (
              <Input
                id={id}
                mono
                aria-describedby={describedBy}
                value={scopes}
                onChange={(change) => {
                  setScopes(change.target.value);
                }}
              />
            )}
          </Field>
          <Field label="Duration" hint={`Up to ${hoursLabel(max)} in this org.`}>
            {({ id, describedBy }) => (
              <Select value={hours} onValueChange={setHours}>
                <SelectTrigger id={id} aria-describedby={describedBy} className="w-48">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {choices.map((choice) => (
                    <SelectItem key={choice} value={String(choice)}>
                      {hoursLabel(choice)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </Field>
          <Field label="Reason" hint="Shown to approvers and kept in the audit log.">
            {({ id, describedBy }) => (
              <Textarea
                id={id}
                aria-describedby={describedBy}
                rows={3}
                maxLength={500}
                className="font-sans text-[13px]"
                placeholder={
                  mode === "grant" ? "e.g. Ship the v4 fix while Dana is out" : "What you need it for"
                }
                value={reason}
                onChange={(change) => {
                  setReason(change.target.value);
                }}
              />
            )}
          </Field>
        </form>
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline" size="32">
              Cancel
            </Button>
          </DialogClose>
          <Button type="submit" form="audit-access" variant="primary" size="32" disabled={!valid || pending}>
            {pending ? "Sending…" : mode === "grant" ? "Grant access" : "Send request"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
