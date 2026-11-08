// Paces streamed text for reading. Model output arrives in bursts (a few tokens, a pause, a large chunk); revealing
// it at a steady, backlog-aware rate on animation frames reads as a calm, continuous flow instead of jumps.
import { useEffect, useRef, useState, useSyncExternalStore } from "react";

/** The slowest pace, in characters per second, used when there is only a little text waiting. */
const MIN_RATE = 80;
/** While streaming, how far behind the received text the reveal may trail, in seconds. */
const STREAMING_LAG = 0.45;
/** Once the stream ends, the rest is revealed within about this long. */
const FLUSH_LAG = 0.2;
/** Finish the word in progress when its end is this close, so the text never pauses mid-word. */
const WORD_LOOKAHEAD = 12;

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

function motionQuery(): MediaQueryList | undefined {
  // Some environments (server rendering, test DOMs) have no media queries.
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return undefined;
  return window.matchMedia(REDUCED_MOTION);
}

function subscribeMotion(onChange: () => void): () => void {
  const query = motionQuery();
  query?.addEventListener("change", onChange);
  return () => {
    query?.removeEventListener("change", onChange);
  };
}

function prefersReducedMotion(): boolean {
  return motionQuery()?.matches ?? false;
}

export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(subscribeMotion, prefersReducedMotion, () => false);
}

/** Where to reveal up to next: `step` characters on, extended to the end of the current word when that is near. */
export function nextReveal(text: string, from: number, step: number): number {
  const next = Math.min(text.length, from + Math.max(1, step));
  if (next >= text.length) return text.length;
  const space = text.slice(next, next + WORD_LOOKAHEAD).search(/\s/);
  return space > 0 ? next + space : next;
}

/**
 * The part of `text` to show right now. Text that is streaming in is revealed progressively; text that was never
 * streaming (history, a finished answer) is returned whole, and so is everything for reduced-motion users.
 * When the stream ends, whatever is still held back is revealed quickly rather than all at once.
 */
export function useSmoothText(text: string, streaming: boolean): string {
  const reduced = usePrefersReducedMotion();
  // Only text that was seen streaming is paced; it stays paced until it has caught up.
  const [animated, setAnimated] = useState(streaming);
  if (streaming && !animated) setAnimated(true);
  const [shown, setShown] = useState(() => (streaming ? 0 : text.length));
  const live = useRef({ text, streaming, position: shown });
  const frame = useRef<number | undefined>(undefined);

  useEffect(() => {
    live.current.text = text;
    live.current.streaming = streaming;
    if (!animated || reduced) return;
    if (live.current.position > text.length) {
      // The text was replaced by a shorter one (a final answer that differs from the stream): show it as is.
      live.current.position = text.length;
      setShown(text.length);
      return;
    }
    if (frame.current !== undefined || live.current.position >= text.length) return;
    let last = performance.now();
    let carry = 0;
    const tick = (now: number) => {
      const seconds = Math.min(0.1, (now - last) / 1000);
      last = now;
      const state = live.current;
      const backlog = state.text.length - state.position;
      if (backlog <= 0) {
        frame.current = undefined;
        return;
      }
      carry += Math.max(MIN_RATE, backlog / (state.streaming ? STREAMING_LAG : FLUSH_LAG)) * seconds;
      const step = Math.floor(carry);
      if (step >= 1) {
        carry -= step;
        state.position = nextReveal(state.text, state.position, step);
        setShown(state.position);
      }
      frame.current = state.position < state.text.length ? requestAnimationFrame(tick) : undefined;
    };
    frame.current = requestAnimationFrame(tick);
  }, [animated, reduced, streaming, text]);

  useEffect(
    () => () => {
      if (frame.current !== undefined) cancelAnimationFrame(frame.current);
      frame.current = undefined;
    },
    [],
  );

  if (!animated || reduced) return text;
  return text.slice(0, Math.min(shown, text.length));
}
