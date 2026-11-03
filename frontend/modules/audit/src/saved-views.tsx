// Saved views: named filter sets as pills with event counts ("All events" first), "+ Save current filters" (personal,
// or shared with everyone who reads the log) and removing the view you're on.
import {
  auditCreateViewMutation,
  auditDeleteViewMutation,
  auditListViewsQueryKey,
  describeError,
  type SavedViewOut,
} from "@agnostic/api";
import { formatCount } from "@agnostic/core";
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
  Switch,
  cn,
  toast,
} from "@agnostic/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { eventsQuery, filtersOf, hasFilters, sameFilters, type AuditFilters } from "./audit-api";

/** "999+" when the server stopped counting. */
export function viewCount(view: Pick<SavedViewOut, "count" | "count_capped">): string {
  return view.count_capped ? `${formatCount(view.count)}+` : formatCount(view.count);
}

/** The saved view whose filters are exactly the current ones. */
export function activeView(views: readonly SavedViewOut[], filters: AuditFilters): SavedViewOut | undefined {
  return views.find((view) => sameFilters(filtersOf(view.filters), filters));
}

function Pill({
  active,
  name,
  count,
  onClick,
}: {
  active: boolean;
  name: string;
  count: string | undefined;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "inline-flex h-8 cursor-pointer items-center gap-2 rounded-full border px-3 text-[12.5px] transition-colors",
        active
          ? "border-accent bg-accent/8 text-fg"
          : "border-border-strong text-fg-secondary hover:bg-surface-hover hover:text-fg",
      )}
    >
      <span>{name}</span>{" "}
      {count !== undefined && (
        <span className={cn("font-mono text-[11.5px]", active ? "text-accent" : "text-fg-muted")}>
          {count}
        </span>
      )}
    </button>
  );
}

function SaveViewDialog({
  open,
  onOpenChange,
  filters,
  summary,
  canShare,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  filters: AuditFilters;
  summary: string;
  canShare: boolean;
}) {
  const client = useQueryClient();
  const [name, setName] = useState("");
  const [shared, setShared] = useState(false);
  const create = useMutation({
    ...auditCreateViewMutation(),
    onSuccess: async (view) => {
      toast.success(`Saved “${view.name}”`);
      onOpenChange(false);
      setName("");
      setShared(false);
      await client.invalidateQueries({ queryKey: auditListViewsQueryKey() });
    },
    onError: (error) => toast.error(describeError(error).reason),
  });
  const trimmed = name.trim();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Save current filters</DialogTitle>
          <DialogDescription>
            A view is a named set of filters; its pill shows how many events match.
          </DialogDescription>
        </DialogHeader>
        <form
          id="save-audit-view"
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (!trimmed) return;
            create.mutate({ body: { name: trimmed, filters: eventsQuery(filters), shared } });
          }}
        >
          <Field label="Name">
            {({ id }) => (
              <Input
                id={id}
                maxLength={120}
                placeholder="e.g. Denied in production"
                value={name}
                onChange={(event) => {
                  setName(event.target.value);
                }}
              />
            )}
          </Field>
          <p className="rounded-tile border border-border-subtle px-3 py-2 font-mono text-[12px] text-fg-secondary">
            {summary}
          </p>
          {canShare && (
            <Switch
              label="Share with everyone who can read the log"
              description="Shared views appear for the whole org; only exporters and org admins can change them."
              checked={shared}
              onCheckedChange={setShared}
            />
          )}
        </form>
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline" size="32">
              Cancel
            </Button>
          </DialogClose>
          <Button
            type="submit"
            form="save-audit-view"
            variant="primary"
            size="32"
            disabled={!trimmed || create.isPending}
          >
            {create.isPending ? "Saving…" : "Save view"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function DeleteViewDialog({
  view,
  open,
  onOpenChange,
  onDeleted,
}: {
  view: SavedViewOut;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDeleted: () => void;
}) {
  const client = useQueryClient();
  const remove = useMutation({
    ...auditDeleteViewMutation(),
    onSuccess: async () => {
      onOpenChange(false);
      onDeleted();
      await client.invalidateQueries({ queryKey: auditListViewsQueryKey() });
    },
    onError: (error) => toast.error(describeError(error).reason),
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Delete “{view.name}”?</DialogTitle>
          <DialogDescription>
            {view.shared
              ? "The view goes away for everyone in the org. Events aren't affected."
              : "Only the saved filters go away; events aren't affected."}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline" size="32">
              Cancel
            </Button>
          </DialogClose>
          <Button
            variant="destructive-outline"
            size="32"
            disabled={remove.isPending}
            onClick={() => {
              remove.mutate({ path: { view_id: view.id } });
            }}
          >
            {remove.isPending ? "Deleting…" : "Delete view"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function SavedViewsBar({
  views,
  filters,
  allCount,
  summary,
  canShare,
  onApply,
}: {
  views: readonly SavedViewOut[];
  filters: AuditFilters;
  /** Known only when every unfiltered event is loaded. */
  allCount: number | undefined;
  summary: string;
  canShare: boolean;
  onApply: (filters: AuditFilters) => void;
}) {
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const sorted = [...views].sort((a, b) => a.position - b.position || a.name.localeCompare(b.name));
  const active = activeView(sorted, filters);
  const all = !hasFilters(filters);
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div role="group" aria-label="Saved views" className="flex flex-wrap items-center gap-2">
        <Pill
          active={all}
          name="All events"
          count={allCount === undefined ? undefined : formatCount(allCount)}
          onClick={() => {
            onApply({});
          }}
        />
        {sorted.map((view) => (
          <Pill
            key={view.id}
            active={active?.id === view.id}
            name={view.name}
            count={viewCount(view)}
            onClick={() => {
              onApply(filtersOf(view.filters));
            }}
          />
        ))}
      </div>
      {!all && !active && (
        <Button
          variant="dashed-add"
          size="30"
          className="rounded-full"
          onClick={() => {
            setSaving(true);
          }}
        >
          <Plus aria-hidden />
          Save current filters
        </Button>
      )}
      {active?.editable && (
        <Button
          variant="icon"
          size="30"
          aria-label={`Delete view ${active.name}`}
          onClick={() => {
            setDeleting(true);
          }}
        >
          <Trash2 aria-hidden />
        </Button>
      )}
      <SaveViewDialog
        open={saving}
        onOpenChange={setSaving}
        filters={filters}
        summary={summary}
        canShare={canShare}
      />
      {active && (
        <DeleteViewDialog
          view={active}
          open={deleting}
          onOpenChange={setDeleting}
          onDeleted={() => {
            onApply({});
          }}
        />
      )}
    </div>
  );
}
