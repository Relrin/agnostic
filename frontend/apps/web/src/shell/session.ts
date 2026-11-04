// Small per-browser conveniences for the shell (localStorage only for conveniences, wrapped in try/catch).
const LAST_INSTANCE_KEY = "agnostic.last-instance";

export function lastInstance(): string | undefined {
  try {
    return window.localStorage.getItem(LAST_INSTANCE_KEY) ?? undefined;
  } catch {
    return undefined;
  }
}

export function rememberInstance(slug: string): void {
  try {
    window.localStorage.setItem(LAST_INSTANCE_KEY, slug);
  } catch {
    // Private windows and blocked storage: nothing to remember, nothing breaks.
  }
}
