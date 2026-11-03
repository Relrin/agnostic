// Shared action pieces: a button hint naming the scope it needs, the "why are you disabling it?" dialog and the
// delete confirmation.
import {
  ApiHint,
  Button,
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Field,
  Textarea,
  Tooltip,
} from "@agnostic/ui";
import { useState, type ReactNode } from "react";

import type { Schedule } from "./schedules-api";

/** The API call and scope as a tooltip when allowed; "Needs {scope}" (and a disabled control) when not. */
export function ScopeHint({
  allowed,
  scope,
  call,
  children,
}: {
  allowed: boolean;
  scope: string;
  call: string;
  children: ReactNode;
}) {
  if (allowed)
    return (
      <ApiHint call={call} scope={scope}>
        {children}
      </ApiHint>
    );
  return (
    <Tooltip content={`Needs ${scope}`}>
      <span title={`Needs ${scope}`} className="inline-flex">
        {children}
      </span>
    </Tooltip>
  );
}

/** Asks why a schedule is being disabled; the reason is shown next to it until someone enables it again. */
export function DisableDialog({
  schedule,
  onConfirm,
  onCancel,
}: {
  schedule: Schedule | undefined;
  onConfirm: (schedule: Schedule, reason: string) => void;
  onCancel: () => void;
}) {
  const [reason, setReason] = useState("");
  return (
    <Dialog
      open={schedule !== undefined}
      onOpenChange={(open) => {
        if (!open) {
          setReason("");
          onCancel();
        }
      }}
    >
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Disable {schedule?.name}?</DialogTitle>
          <DialogDescription>
            It stops running until someone enables it again. The reason is shown next to the schedule.
          </DialogDescription>
        </DialogHeader>
        <form
          id="disable-schedule"
          onSubmit={(event) => {
            event.preventDefault();
            if (!schedule) return;
            onConfirm(schedule, reason.trim());
            setReason("");
          }}
        >
          <Field label="Reason" hint="Optional, e.g. “Waiting for research-team v3”.">
            {({ id, describedBy }) => (
              <Textarea
                id={id}
                aria-describedby={describedBy}
                rows={3}
                maxLength={500}
                className="font-sans text-[13px]"
                value={reason}
                onChange={(event) => {
                  setReason(event.target.value);
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
          <Button type="submit" form="disable-schedule" variant="primary" size="32">
            Disable
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function DeleteDialog({
  schedule,
  open,
  pending,
  onOpenChange,
  onConfirm,
}: {
  schedule: Schedule;
  open: boolean;
  pending: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Delete {schedule.name}?</DialogTitle>
          <DialogDescription>
            The schedule and its run history go away; runs it already started keep their sessions and traces.
            This can&apos;t be undone.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline" size="32">
              Cancel
            </Button>
          </DialogClose>
          <Button variant="destructive-outline" size="32" disabled={pending} onClick={onConfirm}>
            {pending ? "Deleting…" : "Delete schedule"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
