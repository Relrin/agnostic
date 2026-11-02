// Debounced callbacks for inputs that save as you type (the Metrics price table).
import { useEffect, useRef } from "react";

/** Calls `callback` once `delay` ms after the last call; a pending call is flushed when the component unmounts. */
export function useDebouncedCallback<Args extends unknown[]>(
  callback: (...args: Args) => void,
  delay: number,
): (...args: Args) => void {
  const latest = useRef(callback);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const pending = useRef<Args | undefined>(undefined);

  useEffect(() => {
    latest.current = callback;
  }, [callback]);

  useEffect(
    () => () => {
      if (timer.current !== undefined) clearTimeout(timer.current);
      if (pending.current) latest.current(...pending.current);
    },
    [],
  );

  return (...args: Args) => {
    pending.current = args;
    if (timer.current !== undefined) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      timer.current = undefined;
      const next = pending.current;
      pending.current = undefined;
      if (next) latest.current(...next);
    }, delay);
  };
}
