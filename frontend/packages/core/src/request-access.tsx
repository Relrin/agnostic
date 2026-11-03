// "Request access": a member asks approvers (Admins or group owners) for a temporary binding, from any place the
// UI explains a denial (WhyVisible, a `scope_missing` error state).
import {
  accessCreateRequestMutation,
  accessListRequestsQueryKey,
  accessListRolesOptions,
  describeError,
  isProblem,
  type ProblemDetails,
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
  SegmentedControl,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
  toast,
} from "@agnostic/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type SubmitEvent } from "react";

import { withQueryFn } from "./query";
import { useInstances, useOrg } from "./session";

const ALL = "__all__";
const DURATIONS = [1, 4, 8, 24, 72, 168] as const;

function durationLabel(hours: number): string {
  if (hours < 24) return `${String(hours)} hour${hours === 1 ? "" : "s"}`;
  const days = hours / 24;
  return `${String(days)} day${days === 1 ? "" : "s"}`;
}

/** The scopes a `scope_missing` problem says are missing (to prefill a request). */
export function missingScopes(error: unknown): string[] {
  if (!isProblem(error)) return [];
  const details = error as ProblemDetails;
  return details.missing_scopes ?? details.required_scopes ?? [];
}

export function RequestAccessDialog({
  open,
  onOpenChange,
  instance,
  scopes = [],
  roleId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Instance slug or id to prefill. */
  instance?: string | undefined;
  /** Missing scopes to prefill. */
  scopes?: readonly string[];
  roleId?: string | undefined;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Request access</DialogTitle>
          <DialogDescription>
            Approvers (Administrators or your group's owners) get the request. Access ends on its own when the
            time is up.
          </DialogDescription>
        </DialogHeader>
        {open && (
          <RequestAccessForm
            instance={instance}
            scopes={scopes}
            roleId={roleId}
            onDone={() => {
              onOpenChange(false);
            }}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function RequestAccessForm({
  instance: initialInstance,
  scopes: initialScopes,
  roleId,
  onDone,
}: {
  instance: string | undefined;
  scopes: readonly string[];
  roleId: string | undefined;
  onDone: () => void;
}) {
  const queryClient = useQueryClient();
  const instances = useInstances();
  const roles = useQuery(withQueryFn(accessListRolesOptions()));
  const org = useOrg();
  const max = org.data?.settings.temporary_access_max_hours;
  const durations = DURATIONS.filter((hours) => max === undefined || hours <= max);
  const [instance, setInstance] = useState(initialInstance ?? ALL);
  const [kind, setKind] = useState<"scopes" | "role">(
    roleId && initialScopes.length === 0 ? "role" : "scopes",
  );
  const [scopes, setScopes] = useState(initialScopes.join(", "));
  const [role, setRole] = useState(roleId ?? "");
  const [reason, setReason] = useState("");
  const [hours, setHours] = useState(8);
  const duration = durations.includes(hours as (typeof DURATIONS)[number])
    ? hours
    : (durations.at(-1) ?? Math.max(1, max ?? 8));

  const instanceOptions = instances.data ?? [];
  // A prefilled id becomes its slug once the instances load (the options are keyed by slug).
  const instanceValue = instanceOptions.find((item) => item.id === instance)?.slug ?? instance;

  const create = useMutation({
    ...accessCreateRequestMutation(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: accessListRequestsQueryKey() });
      toast("Request sent to approvers");
      onDone();
    },
  });

  const scopeList = scopes
    .split(/[\s,]+/)
    .map((item) => item.trim())
    .filter(Boolean);

  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    create.mutate({
      body: {
        instance: instanceValue === ALL ? null : instanceValue,
        ...(kind === "role" ? { role_id: role } : { scopes: scopeList }),
        reason: reason.trim(),
        duration_hours: duration,
      },
    });
  };

  const valid = reason.trim() !== "" && (kind === "role" ? role !== "" : scopeList.length > 0);

  return (
    <form className="flex flex-col gap-4" onSubmit={submit}>
      <Field label="Instance">
        {({ id }) => (
          <Select value={instanceValue} onValueChange={setInstance}>
            <SelectTrigger id={id} aria-label="Instance">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {instanceOptions.map((item) => (
                <SelectItem key={item.id} value={item.slug}>
                  {item.slug}
                </SelectItem>
              ))}
              {instanceValue !== ALL && !instanceOptions.some((item) => item.slug === instanceValue) && (
                <SelectItem value={instanceValue}>{instanceValue}</SelectItem>
              )}
              <SelectItem value={ALL}>All instances</SelectItem>
            </SelectContent>
          </Select>
        )}
      </Field>
      <SegmentedControl
        label="What to request"
        value={kind}
        options={[
          { value: "scopes", label: "Scopes" },
          { value: "role", label: "A role" },
        ]}
        onValueChange={setKind}
      />
      {kind === "scopes" ? (
        <Field label="Scopes" hint="Comma-separated, e.g. sessions:delete.">
          {({ id, describedBy }) => (
            <Input
              id={id}
              mono
              value={scopes}
              aria-describedby={describedBy}
              onChange={(event) => {
                setScopes(event.target.value);
              }}
            />
          )}
        </Field>
      ) : (
        <Field label="Role">
          {({ id }) => (
            <Select value={role} onValueChange={setRole}>
              <SelectTrigger id={id} aria-label="Role">
                <SelectValue placeholder="Choose a role" />
              </SelectTrigger>
              <SelectContent>
                {(roles.data ?? []).map((item) => (
                  <SelectItem key={item.id} value={item.id}>
                    {item.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </Field>
      )}
      <Field label="Reason" hint="Approvers see this; it's kept in the audit log.">
        {({ id, describedBy }) => (
          <Textarea
            id={id}
            required
            maxLength={500}
            className="min-h-20 font-sans text-[13px]"
            value={reason}
            aria-describedby={describedBy}
            onChange={(event) => {
              setReason(event.target.value);
            }}
          />
        )}
      </Field>
      <Field label="For how long" hint={max ? `Your org allows up to ${durationLabel(max)}.` : undefined}>
        {({ id, describedBy }) => (
          <Select
            value={String(duration)}
            onValueChange={(value) => {
              setHours(Number(value));
            }}
          >
            <SelectTrigger id={id} aria-label="For how long" aria-describedby={describedBy}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(durations.length > 0 ? durations : [duration]).map((value) => (
                <SelectItem key={value} value={String(value)}>
                  {durationLabel(value)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </Field>
      {create.error && <Callout tone="danger">{describeError(create.error).reason}</Callout>}
      <DialogFooter>
        <Button variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" disabled={!valid || create.isPending}>
          {create.isPending ? "Sending…" : "Send request"}
        </Button>
      </DialogFooter>
    </form>
  );
}

/** A "Request access" link that opens the dialog (for error states and denials). */
export function RequestAccessButton({
  instance,
  scopes,
  error,
  label = "Request access",
}: {
  instance?: string | undefined;
  scopes?: readonly string[];
  /** A `scope_missing` problem: its missing scopes prefill the request. */
  error?: unknown;
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        variant="link"
        size="28"
        onClick={() => {
          setOpen(true);
        }}
      >
        {label}
      </Button>
      <RequestAccessDialog
        open={open}
        onOpenChange={setOpen}
        instance={instance}
        scopes={scopes ?? missingScopes(error)}
      />
    </>
  );
}
