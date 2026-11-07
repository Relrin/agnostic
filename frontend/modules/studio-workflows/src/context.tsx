// What every part of the builder shares: the draft, the builder store (selection, clipboard, history) and the edits.
// Edits go through `edit()`, so each one is a single undoable step.
import type { Config, DraftDocument } from "@agnostic/studio";
import { toast } from "@agnostic/ui";
import { createContext, useContext, useMemo } from "react";

import { edit, redo, undo, type BuilderStore } from "./history";
import {
  cloneSubtree,
  insertNode,
  moveNode,
  names,
  newNode,
  nodeAt,
  nodeName,
  removeNode,
  removeNodes,
  unwrapNode,
  updateNode,
  wrapNode,
  type Executor,
  type NodeType,
  type Slot,
  type WorkflowNode,
} from "./tree";

export const DRAG_TYPE = "application/x-agnostic-step";

/** What a palette item carries when dragged. */
export type DragItem = { type: NodeType; executor?: Executor | undefined } | { move: string };

export type Actions = {
  add: (slot: Slot, type: NodeType, executor?: Executor) => string | undefined;
  drop: (slot: Slot, item: DragItem) => void;
  remove: (path: string) => void;
  /** Remove several steps as one undoable edit. */
  removeMany: (paths: readonly string[]) => void;
  update: (path: string, label: string, recipe: (node: WorkflowNode) => void) => void;
  updateWorkflow: (label: string, recipe: (config: Config) => void) => void;
  wrap: (path: string, type: Exclude<NodeType, "Step">) => void;
  unwrap: (path: string) => void;
  copy: (path: string) => void;
  /** Copy a step and remove it, to paste it somewhere else. */
  cut: (path: string) => void;
  paste: (slot: Slot) => void;
  undo: () => void;
  redo: () => void;
};

export type Builder = {
  instance: string;
  componentId: string;
  doc: DraftDocument;
  store: BuilderStore;
  readOnly: boolean;
  actions: Actions;
};

const BuilderContext = createContext<Builder | undefined>(undefined);

export const BuilderProvider = BuilderContext.Provider;

export function useBuilderContext(): Builder {
  const found = useContext(BuilderContext);
  if (!found) throw new Error("useBuilderContext needs a BuilderProvider.");
  return found;
}

export function readDragItem(data: DataTransfer): DragItem | undefined {
  try {
    const raw = data.getData(DRAG_TYPE);
    return raw ? (JSON.parse(raw) as DragItem) : undefined;
  } catch {
    return undefined;
  }
}

/** The builder's edits on `doc`, each recorded on `store`'s history. */
export function useActions(doc: DraftDocument, store: BuilderStore, readOnly: boolean): Actions {
  return useMemo(() => {
    const run = <T,>(label: string, recipe: (config: Config) => T): T | undefined => {
      if (readOnly || !doc.config) return undefined;
      return edit(store, doc.config, doc.setConfig, label, recipe);
    };
    const select = (path: string | undefined) => {
      store.getState().select(path);
    };
    const remove = (path: string) => {
      const name = nodeName(nodeAt(doc.config, path));
      run(`Remove ${name || "step"}`, (config) => {
        removeNode(config, path);
      });
      select(undefined);
      store.getState().pick([]);
      toast(`Removed ${name || "the step"}.`, {
        action: {
          label: "Undo",
          onClick: () => {
            undo(store, doc.setConfig);
          },
        },
      });
    };
    return {
      add: (slot, type, executor) => {
        const path = run(`Add ${type}`, (config) =>
          insertNode(config, slot, newNode(type, names(config), executor)),
        );
        select(path);
        return path;
      },
      drop: (slot, item) => {
        if ("move" in item) {
          const path = run("Move step", (config) => moveNode(config, item.move, slot));
          if (path) select(path);
          else toast.error("A step can't move into itself.");
          return;
        }
        const path = run(`Add ${item.type}`, (config) =>
          insertNode(config, slot, newNode(item.type, names(config), item.executor)),
        );
        select(path);
      },
      remove,
      removeMany: (paths) => {
        if (paths.length === 0) return;
        const [only] = paths;
        if (paths.length === 1 && only) {
          remove(only);
          return;
        }
        const removed = run(`Remove ${String(paths.length)} steps`, (config) => removeNodes(config, paths));
        if (!removed?.length) return;
        select(undefined);
        store.getState().pick([]);
        toast(`Removed ${String(removed.length)} step${removed.length === 1 ? "" : "s"}.`, {
          action: {
            label: "Undo",
            onClick: () => {
              undo(store, doc.setConfig);
            },
          },
        });
      },
      update: (path, label, recipe) => {
        run(label, (config) => {
          updateNode(config, path, recipe);
        });
      },
      updateWorkflow: (label, recipe) => {
        run(label, recipe);
      },
      wrap: (path, type) => {
        run(`Wrap in ${type}`, (config) => wrapNode(config, path, type));
      },
      unwrap: (path) => {
        const kept = run("Unwrap", (config) => unwrapNode(config, path));
        select(kept);
      },
      copy: (path) => {
        const node = nodeAt(doc.config, path);
        store.getState().copy(node);
        if (node) toast.success(`Copied ${nodeName(node) || "the step"}.`);
      },
      cut: (path) => {
        const node = nodeAt(doc.config, path);
        if (!node) return;
        store.getState().copy(node);
        const name = nodeName(node);
        run(`Cut ${name || "step"}`, (config) => {
          removeNode(config, path);
        });
        select(undefined);
        store.getState().pick([]);
        toast(`Cut ${name || "the step"}: select where it goes and press Ctrl+V.`);
      },
      paste: (slot) => {
        const copied = store.getState().clipboard;
        if (!copied) return;
        const path = run("Paste", (config) => insertNode(config, slot, cloneSubtree(copied, names(config))));
        select(path);
      },
      undo: () => {
        undo(store, doc.setConfig);
      },
      redo: () => {
        redo(store, doc.setConfig);
      },
    };
  }, [doc.config, doc.setConfig, readOnly, store]);
}
