// What the builder knows about each node type, from the workflow's JSON Schema (`GET /studio/schema/workflow`): the
// inspector's sections and field metadata per type, and which human-review options each type supports. Plus the
// executors a step can run: the instance's registry and its stored components.
import { studioListComponentsOptions, studioSchemaOptions } from "@agnostic/api";
import { STALE_TIME, withQueryFn } from "@agnostic/core";
import { isRecord, useRegistry, type FieldInfo, type Section } from "@agnostic/studio";
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { NODE_TYPES, type Executor, type NodeType } from "./tree";

const DEFS: Record<NodeType, string> = {
  Step: "StepNode",
  Steps: "StepsNode",
  Parallel: "ParallelNode",
  Condition: "ConditionNode",
  Loop: "LoopNode",
  Router: "RouterNode",
};

export type WorkflowSchema = {
  /** Field metadata per node type. */
  fields: Record<NodeType, Record<string, FieldInfo>>;
  sections: Record<NodeType, Section[]>;
  /** `human_review` fields with their metadata. */
  review: Record<string, FieldInfo>;
  /** Review groups (confirmation, user_input, …) → their fields. */
  groups: Record<string, string[]>;
  /** Node type → the review groups it supports. */
  support: Record<string, string[]>;
  isPending: boolean;
};

function metaOf(definition: unknown): Record<string, FieldInfo> {
  const properties = isRecord(definition) && isRecord(definition.properties) ? definition.properties : {};
  const fields: Record<string, FieldInfo> = {};
  for (const [name, property] of Object.entries(properties)) {
    if (!isRecord(property) || !isRecord(property["x-agnostic"])) continue;
    const meta = property["x-agnostic"] as Omit<FieldInfo, "options">;
    const branches = Array.isArray(property.anyOf) ? property.anyOf : [property];
    const options = branches.find((branch) => isRecord(branch) && Array.isArray(branch.enum)) as
      { enum: unknown[] } | undefined;
    fields[name] = { ...meta, ...(options ? { options: options.enum.map(String) } : {}) };
  }
  return fields;
}

export function useWorkflowSchema(): WorkflowSchema {
  const query = useQuery({
    ...withQueryFn(studioSchemaOptions({ path: { kind: "workflow" } })),
    staleTime: Infinity,
  });
  return useMemo(() => {
    const schema = query.data ?? {};
    const defs = isRecord(schema.$defs) ? schema.$defs : {};
    const nodes = isRecord(schema["x-agnostic-nodes"]) ? schema["x-agnostic-nodes"] : {};
    const review = isRecord(schema["x-agnostic-human-review"]) ? schema["x-agnostic-human-review"] : {};
    const fields = {} as WorkflowSchema["fields"];
    const sections = {} as WorkflowSchema["sections"];
    for (const type of NODE_TYPES) {
      fields[type] = metaOf(defs[DEFS[type]]);
      sections[type] = Array.isArray(nodes[type]) ? (nodes[type] as Section[]) : [];
    }
    return {
      fields,
      sections,
      review: metaOf(defs.HumanReview),
      groups: isRecord(review.groups) ? (review.groups as Record<string, string[]>) : {},
      support: isRecord(review.support) ? (review.support as Record<string, string[]>) : {},
      isPending: query.isPending,
    };
  }, [query.data, query.isPending]);
}

export type ExecutorOption = Executor & { label: string; source: "registry" | "studio" };

const KIND_LABEL: Record<Executor["kind"], string> = {
  agent: "agent",
  team: "team",
  workflow: "workflow",
  function: "fn",
};

export function executorLabel(executor: Executor): string {
  return `${KIND_LABEL[executor.kind]} · ${executor.id}`;
}

export function kindLabel(kind: Executor["kind"]): string {
  return KIND_LABEL[kind];
}

/** What a step can run here: registered agents, teams, workflows and functions, and stored components. */
export function useExecutors(
  instance: string,
  exclude?: string,
): { options: ExecutorOption[]; isPending: boolean } {
  const registry = useRegistry(instance);
  const stored = useQuery({
    ...withQueryFn(studioListComponentsOptions({ path: { instance }, query: { kind: "agent" } })),
    staleTime: STALE_TIME.config,
  });
  const teams = useQuery({
    ...withQueryFn(studioListComponentsOptions({ path: { instance }, query: { kind: "team" } })),
    staleTime: STALE_TIME.config,
  });
  const workflows = useQuery({
    ...withQueryFn(studioListComponentsOptions({ path: { instance }, query: { kind: "workflow" } })),
    staleTime: STALE_TIME.config,
  });
  return useMemo(() => {
    const seen = new Set<string>();
    const options: ExecutorOption[] = [];
    const push = (option: ExecutorOption) => {
      const key = `${option.kind}:${option.id}`;
      if (seen.has(key) || option.id === exclude) return;
      seen.add(key);
      options.push(option);
    };
    for (const [list, kind] of [
      [stored.data, "agent"],
      [teams.data, "team"],
      [workflows.data, "workflow"],
    ] as const) {
      for (const row of list ?? []) {
        push({
          kind,
          id: row.component.id,
          label: row.component.name,
          source: row.component.source === "code" ? "registry" : "studio",
        });
      }
    }
    for (const entry of registry.entries) {
      const kind = entry.type === "function" ? "function" : entry.type;
      if (kind !== "agent" && kind !== "team" && kind !== "workflow" && kind !== "function") continue;
      push({ kind, id: entry.id ?? entry.name, label: entry.name, source: "registry" });
    }
    options.sort((a, b) => a.kind.localeCompare(b.kind) || a.id.localeCompare(b.id));
    return { options, isPending: registry.isPending || stored.isPending };
  }, [
    registry.entries,
    registry.isPending,
    stored.data,
    stored.isPending,
    teams.data,
    workflows.data,
    exclude,
  ]);
}
