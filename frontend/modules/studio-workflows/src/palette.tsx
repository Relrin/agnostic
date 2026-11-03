// The step palette: the six primitives and every executor a step can run, searchable. Drag an item onto a "+" or an
// empty container; click it to add it after the selected step (or at the end).
import { Input, PaletteItem } from "@agnostic/ui";
import { useState, type DragEvent } from "react";

import { DRAG_TYPE, useBuilderContext, type DragItem } from "./context";
import { kindLabel, type ExecutorOption } from "./schema";
import { NODE_TYPES, parentOf, rootSteps, type Executor, type NodeType, type Slot } from "./tree";

const DESCRIPTIONS: Record<NodeType, string> = {
  Step: "Run an agent, team or function",
  Steps: "Group steps in sequence",
  Parallel: "Run branches at once",
  Condition: "If / else on a CEL check",
  Loop: "Repeat until an end condition",
  Router: "Pick one choice by selector",
};

const EXECUTOR_COLORS: Record<Executor["kind"], string> = {
  agent: "var(--entity-agent)",
  team: "var(--entity-team)",
  workflow: "var(--entity-workflow)",
  function: "var(--entity-fn)",
};

function dragStart(item: DragItem) {
  return (event: DragEvent<HTMLButtonElement>) => {
    event.dataTransfer.setData(DRAG_TYPE, JSON.stringify(item));
    event.dataTransfer.effectAllowed = "copy";
  };
}

export function Palette({ executors }: { executors: ExecutorOption[] }) {
  const { actions, store, doc, readOnly } = useBuilderContext();
  const [query, setQuery] = useState("");
  const needle = query.trim().toLowerCase();
  const slot = (): Slot => {
    const selected = store.getState().selected;
    const place = selected ? parentOf(selected) : undefined;
    return place
      ? { parent: place.parent, lane: place.lane, index: place.index + 1 }
      : { parent: "", lane: "steps", index: rootSteps(doc.config).length };
  };
  const primitives = NODE_TYPES.filter((type) => !needle || type.toLowerCase().includes(needle));
  const matching = executors.filter((item) => !needle || item.id.toLowerCase().includes(needle));
  return (
    <aside
      aria-label="Step palette"
      className="flex min-h-0 w-[208px] shrink-0 flex-col gap-3 overflow-y-auto border-r border-border bg-surface p-3"
    >
      <Input
        aria-label="Search steps and executors"
        placeholder="Add a step…"
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
        }}
      />
      <section aria-label="Control flow" className="flex flex-col gap-0.5">
        <h2 className="px-2 font-mono text-[10.5px] tracking-wide text-fg-muted uppercase">Control flow</h2>
        {primitives.map((type) => (
          <PaletteItem
            key={type}
            type={type}
            name={type}
            description={DESCRIPTIONS[type]}
            onAdd={() => {
              if (!readOnly) actions.add(slot(), type);
            }}
            onDragStart={dragStart({ type })}
          />
        ))}
      </section>
      <section aria-label="Executors" className="flex flex-col gap-0.5">
        <h2 className="px-2 font-mono text-[10.5px] tracking-wide text-fg-muted uppercase">Executors</h2>
        {matching.length === 0 && (
          <p className="px-2 text-[12px] text-fg-muted">Nothing registered matches.</p>
        )}
        {matching.map((item) => {
          const executor: Executor = { kind: item.kind, id: item.id };
          return (
            <PaletteItem
              key={`${item.kind}:${item.id}`}
              name={item.id}
              kind={kindLabel(item.kind)}
              color={EXECUTOR_COLORS[item.kind]}
              onAdd={() => {
                if (!readOnly) actions.add(slot(), "Step", executor);
              }}
              onDragStart={dragStart({ type: "Step", executor })}
            />
          );
        })}
      </section>
    </aside>
  );
}
