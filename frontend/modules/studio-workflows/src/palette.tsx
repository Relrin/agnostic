// The component sidebar: logic primitives and every executor a step can run (agents, teams, workflows, functions),
// in collapsible sections, searchable. Drag an item onto a "+", an empty group or empty canvas space (which adds it
// at the end); click it to add it after the selected step (or at the end).
import { Input, PaletteItem } from "@agnostic/ui";
import { Link } from "@tanstack/react-router";
import { ChevronRight } from "lucide-react";
import { useState, type DragEvent, type ReactNode } from "react";

import { DRAG_TYPE, useBuilderContext, type DragItem } from "./context";
import { kindLabel, type ExecutorOption } from "./schema";
import { parentOf, rootSteps, type Executor, type NodeType, type Slot } from "./tree";

const LOGIC: { type: NodeType; description: string }[] = [
  { type: "Step", description: "Run an agent, team or function" },
  { type: "Router", description: "Pick one choice by selector" },
  { type: "Condition", description: "If / else on a CEL check" },
  { type: "Loop", description: "Repeat until an end condition" },
  { type: "Parallel", description: "Run branches at once" },
  { type: "Steps", description: "Group steps in sequence" },
];

const SECTIONS: { kind: Executor["kind"]; label: string }[] = [
  { kind: "agent", label: "Agents" },
  { kind: "team", label: "Teams" },
  { kind: "workflow", label: "Workflows" },
  { kind: "function", label: "Functions" },
];

function dragStart(item: DragItem) {
  return (event: DragEvent<HTMLButtonElement>) => {
    event.dataTransfer.setData(DRAG_TYPE, JSON.stringify(item));
    event.dataTransfer.effectAllowed = "copy";
  };
}

function Section({
  label,
  count,
  open,
  onToggle,
  children,
}: {
  label: string;
  count: number;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  return (
    <section aria-label={label} className="flex flex-col gap-0.5">
      <button
        type="button"
        aria-expanded={open}
        onClick={onToggle}
        className="flex h-8 w-full cursor-pointer items-center gap-2 rounded-control border-0 bg-transparent px-1.5 text-left text-[12.5px] font-semibold text-fg hover:bg-surface-hover focus-visible:ring-1 focus-visible:ring-accent focus-visible:outline-none"
      >
        <ChevronRight
          aria-hidden
          className="size-3 shrink-0 text-fg-muted transition-transform"
          style={{ transform: open ? "rotate(90deg)" : undefined }}
        />
        <span className="flex-1">{label}</span>
        <span className="font-mono text-[11px] font-normal text-fg-muted">{count}</span>
      </button>
      {open && <div className="flex flex-col gap-0.5 pl-3">{children}</div>}
    </section>
  );
}

export function Palette({ executors, registryHref }: { executors: ExecutorOption[]; registryHref: string }) {
  const { actions, store, doc, readOnly } = useBuilderContext();
  const [query, setQuery] = useState("");
  const [closed, setClosed] = useState<Set<string>>(new Set(["Workflows"]));
  const needle = query.trim().toLowerCase();
  const slot = (): Slot => {
    const selected = store.getState().selected;
    const place = selected ? parentOf(selected) : undefined;
    return place
      ? { parent: place.parent, lane: place.lane, index: place.index + 1 }
      : { parent: "", lane: "steps", index: rootSteps(doc.config).length };
  };
  const toggle = (label: string) => {
    setClosed((current) => {
      const next = new Set(current);
      if (next.has(label)) next.delete(label);
      else next.add(label);
      return next;
    });
  };
  // A search opens every section with a match.
  const isOpen = (label: string) => Boolean(needle) || !closed.has(label);
  const logic = LOGIC.filter((item) => !needle || item.type.toLowerCase().includes(needle));
  const matching = executors.filter((item) => !needle || item.id.toLowerCase().includes(needle));
  return (
    <aside
      aria-label="Step palette"
      className="flex min-h-0 w-[228px] shrink-0 flex-col gap-1 overflow-y-auto border-r border-border bg-rail px-2.5 py-3"
    >
      <Input
        aria-label="Search steps and executors"
        placeholder="Search components"
        value={query}
        className="mb-1.5 shrink-0"
        onChange={(event) => {
          setQuery(event.target.value);
        }}
      />
      <Section
        label="Logic"
        count={logic.length}
        open={isOpen("Logic")}
        onToggle={() => {
          toggle("Logic");
        }}
      >
        {logic.map((item) => (
          <PaletteItem
            key={item.type}
            type={item.type}
            name={item.type}
            description={item.description}
            onAdd={() => {
              if (!readOnly) actions.add(slot(), item.type);
            }}
            onDragStart={dragStart({ type: item.type })}
          />
        ))}
      </Section>
      {SECTIONS.map((section) => {
        const items = matching.filter((item) => item.kind === section.kind);
        if (items.length === 0 && needle) return null;
        return (
          <Section
            key={section.kind}
            label={section.label}
            count={items.length}
            open={isOpen(section.label)}
            onToggle={() => {
              toggle(section.label);
            }}
          >
            {items.length === 0 && (
              <p className="m-0 px-1.5 py-1 text-[12px] text-fg-muted">None registered.</p>
            )}
            {items.map((item) => {
              const executor: Executor = { kind: item.kind, id: item.id };
              return (
                <PaletteItem
                  key={`${item.kind}:${item.id}`}
                  name={item.id}
                  kind={kindLabel(item.kind)}
                  executor={item.kind}
                  onAdd={() => {
                    if (!readOnly) actions.add(slot(), "Step", executor);
                  }}
                  onDragStart={dragStart({ type: "Step", executor })}
                />
              );
            })}
          </Section>
        );
      })}
      {needle && logic.length === 0 && matching.length === 0 && (
        <p className="m-0 px-1.5 text-[12px] text-fg-muted">Nothing matches.</p>
      )}
      <div className="mt-auto border-t border-border-subtle pt-2.5">
        <Link to={registryHref} className="px-1.5 text-[12px] no-underline">
          {`Open the registry · ${String(executors.length)}`}
        </Link>
      </div>
    </aside>
  );
}
