import { contextDataSubjectRequest, describeError, type DataSubjectOut } from "@agnostic/api";
import {
  Button,
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
  toast,
} from "@agnostic/ui";
import { useMutation } from "@tanstack/react-query";
import { ShieldX } from "lucide-react";
import { useId, useState, type ReactElement } from "react";

import { LEARNING_TYPES, useLearningActions, type Learning, type LearningType } from "./learnings-api";

const IDENTITY_KEYED: readonly LearningType[] = ["user_profile", "user_memory"];

/** "+ New record": type, owner fields and JSON content; identity-keyed types get their id from AgentOS. */
export function NewRecordDialog({
  instance,
  type: initialType,
  onCreated,
  trigger,
}: {
  instance: string;
  type: LearningType;
  onCreated: (record: Learning) => void;
  trigger: ReactElement;
}) {
  const actions = useLearningActions(instance);
  const [open, setOpen] = useState(false);
  const [type, setType] = useState<LearningType>(initialType);
  const ids = useId();
  const [fields, setFields] = useState<Record<string, string>>({});
  const [content, setContent] = useState("{\n  \n}");
  const [metadata, setMetadata] = useState("{}");
  const [error, setError] = useState<string | undefined>(undefined);
  const field = (name: string, label: string) => (
    <Input
      aria-label={label}
      placeholder={label}
      mono
      className="h-8"
      value={fields[name] ?? ""}
      onChange={(event) => {
        setFields({ ...fields, [name]: event.target.value });
      }}
    />
  );

  const create = () => {
    try {
      const parsedContent = JSON.parse(content) as unknown;
      const parsedMetadata = JSON.parse(metadata) as unknown;
      if (typeof parsedContent !== "object" || parsedContent === null || Array.isArray(parsedContent))
        throw new Error("content must be a JSON object.");
      const clean = (name: string) => {
        const value = fields[name]?.trim();
        return value === undefined || value === "" ? null : value;
      };
      setError(undefined);
      actions.create.mutate(
        {
          learning_type: type,
          content: parsedContent as Record<string, unknown>,
          metadata: (parsedMetadata ?? null) as Record<string, unknown> | null,
          user_id: clean("user_id"),
          agent_id: clean("agent_id"),
          namespace: clean("namespace"),
          session_id: clean("session_id"),
          entity_type: clean("entity_type"),
          entity_id: clean("entity_id"),
        },
        {
          onSuccess: (record) => {
            setOpen(false);
            toast.success(`Created ${record.learning_id}`);
            onCreated(record);
          },
          onError: (problem) => {
            setError(describeError(problem).reason);
          },
        },
      );
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "Not valid JSON.");
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>New learning record</DialogTitle>
          <DialogDescription>
            {IDENTITY_KEYED.includes(type)
              ? "This type has one record per user: AgentOS derives the id, and refuses a second one."
              : "AgentOS generates the id."}
          </DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-2 gap-2">
          <Select
            value={type}
            onValueChange={(value) => {
              setType(value as LearningType);
            }}
          >
            <SelectTrigger aria-label="learning_type" className="h-8 font-mono">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {LEARNING_TYPES.map((item) => (
                <SelectItem key={item} value={item}>
                  {item}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {field("user_id", "user_id")}
          {field("agent_id", "agent_id")}
          {field("namespace", "namespace")}
          {type === "session_context" && field("session_id", "session_id")}
          {type === "entity_memory" && field("entity_type", "entity_type")}
          {type === "entity_memory" && field("entity_id", "entity_id")}
        </div>
        <label htmlFor={`${ids}-content`} className="flex flex-col gap-1 font-mono text-[11px] text-fg-muted">
          content
          <Textarea
            id={`${ids}-content`}
            rows={6}
            value={content}
            onChange={(event) => {
              setContent(event.target.value);
            }}
          />
        </label>
        <label
          htmlFor={`${ids}-metadata`}
          className="flex flex-col gap-1 font-mono text-[11px] text-fg-muted"
        >
          metadata
          <Textarea
            id={`${ids}-metadata`}
            rows={2}
            value={metadata}
            onChange={(event) => {
              setMetadata(event.target.value);
            }}
          />
        </label>
        {error && (
          <p role="alert" className="text-[12.5px] text-danger">
            {error}
          </p>
        )}
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline" size="32">
              Cancel
            </Button>
          </DialogClose>
          <Button variant="primary" size="32" disabled={actions.create.isPending} onClick={create}>
            Create record
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Org-wide data-subject request: delete one person's learnings on every instance you may delete them on. */
export function DataSubjectDialog() {
  const [open, setOpen] = useState(false);
  const [user, setUser] = useState("");
  const [confirm, setConfirm] = useState("");
  const [result, setResult] = useState<DataSubjectOut | undefined>(undefined);
  const request = useMutation({
    mutationFn: async () =>
      (await contextDataSubjectRequest({ body: { user_id: user.trim(), confirm }, throwOnError: true })).data,
    onSuccess: setResult,
    onError: (problem) => toast.error(describeError(problem).reason),
  });
  const ready = user.trim().length > 0 && confirm.trim() === user.trim();

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) {
          setUser("");
          setConfirm("");
          setResult(undefined);
        }
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline" size="32">
          <ShieldX aria-hidden />
          Data subject request
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Data subject request</DialogTitle>
          <DialogDescription>
            Deletes every learning of one user on each instance where you hold{" "}
            <code className="font-mono">learnings:delete</code>, and records it in the audit log. Memories and
            sessions are deleted separately.
          </DialogDescription>
        </DialogHeader>
        {result ? (
          <ul aria-label="Result per instance" className="flex flex-col gap-1.5 text-[13px]">
            {result.outcomes.map((outcome) => (
              <li key={outcome.instance_id} className="flex items-baseline justify-between gap-3">
                <span className="font-mono">{outcome.instance}</span>
                <span
                  className={
                    outcome.status === "deleted"
                      ? "text-accent"
                      : outcome.status === "failed"
                        ? "text-danger"
                        : "text-fg-muted"
                  }
                >
                  {outcome.status === "deleted"
                    ? `Deleted ${outcome.deleted === null ? "" : `${String(outcome.deleted)} `}records`
                    : `${outcome.status === "failed" ? "Failed" : "Skipped"}: ${outcome.reason ?? ""}`}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <div className="flex flex-col gap-2">
            <Input
              aria-label="user_id"
              placeholder="user_id, e.g. cus_48213"
              mono
              value={user}
              onChange={(event) => {
                setUser(event.target.value);
              }}
            />
            <Input
              aria-label="Confirmation"
              placeholder={
                user.trim() ? `Type ${user.trim()} to confirm` : "Type the user_id again to confirm"
              }
              mono
              value={confirm}
              onChange={(event) => {
                setConfirm(event.target.value);
              }}
            />
          </div>
        )}
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline" size="32">
              {result ? "Close" : "Cancel"}
            </Button>
          </DialogClose>
          {!result && (
            <Button
              variant="destructive-outline"
              size="32"
              disabled={!ready || request.isPending}
              onClick={() => {
                request.mutate();
              }}
            >
              {request.isPending ? "Deleting…" : "Delete on every instance"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
