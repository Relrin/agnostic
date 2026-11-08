// Viewport width as React state, for layouts that render a part one way or another (inline or in a Sheet) rather
// than hide one of two copies with CSS. Breakpoints match Tailwind's: lg is 1024px, xl is 1280px.
import { useSyncExternalStore } from "react";

export const BREAKPOINTS = { lg: 1024, xl: 1280 } as const;

function query(minWidth: number): MediaQueryList | undefined {
  // Some environments (server rendering, test DOMs) have no media queries; they count as wide.
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return undefined;
  return window.matchMedia(`(min-width: ${minWidth}px)`);
}

/** Whether the viewport is at least `minWidth` pixels wide; re-renders when that changes. */
export function useMinWidth(minWidth: number): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const list = query(minWidth);
      list?.addEventListener("change", onChange);
      return () => {
        list?.removeEventListener("change", onChange);
      };
    },
    () => query(minWidth)?.matches ?? true,
    () => true,
  );
}
