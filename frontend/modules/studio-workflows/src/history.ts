// The builder's state outside the config: selection, the clipboard, and undo/redo. Every canvas edit is an immer
// recipe on the config; its inverse patches go on the undo stack, so any operation (insert, move, wrap, delete,
// an inspector change) can be undone. The config itself stays in the draft document, which autosaves it.
import type { Config } from "@agnostic/studio";
import { Immer, enablePatches, type Draft, type Patch } from "immer";
import { createStore, useStore, type StoreApi } from "zustand";

enablePatches();
// Our own instance: no global auto-freeze, since the draft document hands configs to code that copies them.
const immer = new Immer({ autoFreeze: false });
const LIMIT = 200;

type Entry = { undo: Patch[]; redo: Patch[]; label: string };

export type BuilderState = {
  selected: string | undefined;
  clipboard: Record<string, unknown> | undefined;
  past: Entry[];
  future: Entry[];
  select: (path: string | undefined) => void;
  copy: (node: Record<string, unknown> | undefined) => void;
};

export type BuilderStore = StoreApi<BuilderState>;

export function createBuilderStore(): BuilderStore {
  return createStore<BuilderState>()((set) => ({
    selected: undefined,
    clipboard: undefined,
    past: [],
    future: [],
    select: (path) => {
      set({ selected: path });
    },
    copy: (node) => {
      set({ clipboard: node ? structuredClone(node) : undefined });
    },
  }));
}

export function useBuilder<T>(store: BuilderStore, pick: (state: BuilderState) => T): T {
  return useStore(store, pick);
}

/** Apply `recipe` to the config through `setConfig`, recording how to undo it. Returns what the recipe returned. */
export function edit<T>(
  store: BuilderStore,
  config: Config,
  setConfig: (update: (config: Config) => Config) => void,
  label: string,
  recipe: (draft: Draft<Config>) => T,
): T {
  let result: T | undefined;
  const [next, patches, inverse] = immer.produceWithPatches(config, (draft) => {
    result = recipe(draft);
  });
  if (patches.length === 0) return result as T;
  setConfig(() => next);
  store.setState((state) => ({
    past: [...state.past, { undo: inverse, redo: patches, label }].slice(-LIMIT),
    future: [],
  }));
  return result as T;
}

export function undo(
  store: BuilderStore,
  setConfig: (update: (config: Config) => Config) => void,
): string | undefined {
  const entry = store.getState().past.at(-1);
  if (!entry) return undefined;
  setConfig((config) => immer.applyPatches(config, entry.undo));
  store.setState((state) => ({ past: state.past.slice(0, -1), future: [...state.future, entry] }));
  return entry.label;
}

export function redo(
  store: BuilderStore,
  setConfig: (update: (config: Config) => Config) => void,
): string | undefined {
  const entry = store.getState().future.at(-1);
  if (!entry) return undefined;
  setConfig((config) => immer.applyPatches(config, entry.redo));
  store.setState((state) => ({ future: state.future.slice(0, -1), past: [...state.past, entry] }));
  return entry.label;
}
