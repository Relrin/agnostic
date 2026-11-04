// Guided tour: popover steps anchored to elements marked `data-tour="…"`. The open step's target is outlined, focus
// moves into the step (and back to where it was when the tour ends), Escape or "Skip tour" dismisses it. A step
// whose target isn't on the page shows centred near the top instead.
import { Popover as PopoverPrimitive } from "radix-ui";
import {
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";

import { Button } from "../primitives/button";

export type TourStep = {
  /** The `data-tour` value of the element the step points at. */
  target: string;
  title: ReactNode;
  body: ReactNode;
};

export type TourEnd = "done" | "dismissed";

type Measurable = { getBoundingClientRect: () => DOMRect };

function findTarget(target: string): HTMLElement | null {
  return document.querySelector<HTMLElement>(`[data-tour="${CSS.escape(target)}"]`);
}

/** Frames to wait for a target that renders a moment after the step opens (data still loading). */
const FIND_FRAMES = 30;

export function Tour({
  steps,
  open,
  onEnd,
  label,
}: {
  steps: readonly TourStep[];
  open: boolean;
  /** "done" after the last step, "dismissed" on Escape or "Skip tour". */
  onEnd: (how: TourEnd) => void;
  /** What the tour is about, shown above each step ("Connect an instance"). */
  label?: string;
}) {
  const [index, setIndex] = useState(0);
  const [wasOpen, setWasOpen] = useState(open);
  const [target, setTarget] = useState<HTMLElement | null>(null);
  const content = useRef<HTMLDivElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const titleId = useId();
  const bodyId = useId();
  const step = steps[index];
  const last = index === steps.length - 1;

  // Every time the tour opens, it starts at the first step.
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) setIndex(0);
  }

  useLayoutEffect(() => {
    if (open)
      returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  }, [open]);

  useEffect(() => {
    if (!open || !step) return;
    let frame = 0;
    let tries = 0;
    const find = () => {
      const element = findTarget(step.target);
      if (element || tries >= FIND_FRAMES) {
        element?.scrollIntoView({ block: "nearest", inline: "nearest" });
        setTarget(element);
        return;
      }
      tries += 1;
      frame = requestAnimationFrame(find);
    };
    find();
    return () => {
      cancelAnimationFrame(frame);
    };
  }, [open, step]);

  useEffect(() => {
    if (!open || !target) return;
    target.setAttribute("data-tour-active", "");
    return () => {
      target.removeAttribute("data-tour-active");
    };
  }, [open, target]);

  // Each step change moves focus to the step, so screen readers read its title and text.
  useEffect(() => {
    if (open) content.current?.focus();
  }, [open, index, target]);

  const anchor = useMemo(
    (): RefObject<Measurable> => ({
      current: {
        getBoundingClientRect: () =>
          target
            ? target.getBoundingClientRect()
            : new DOMRect(window.innerWidth / 2, window.innerHeight / 4, 0, 0),
      },
    }),
    [target],
  );

  const end = (how: TourEnd) => {
    onEnd(how);
    returnFocus.current?.focus();
  };

  if (!step) return null;
  return (
    <PopoverPrimitive.Root
      open={open}
      onOpenChange={(next) => {
        if (!next) end("dismissed");
      }}
    >
      <PopoverPrimitive.Anchor virtualRef={anchor} />
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          ref={content}
          data-slot="tour-step"
          aria-labelledby={titleId}
          aria-describedby={bodyId}
          side={target ? "bottom" : "top"}
          align={target ? "start" : "center"}
          sideOffset={10}
          collisionPadding={16}
          tabIndex={-1}
          // Clicking or tabbing to the page doesn't end the tour: the highlighted control is meant to be tried.
          onInteractOutside={(event) => {
            event.preventDefault();
          }}
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            content.current?.focus();
          }}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
          }}
          className="z-50 flex w-80 flex-col gap-2 rounded-card border border-border-strong bg-popover p-4 text-fg shadow-popover outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent data-[state=open]:animate-in data-[state=open]:fade-in-0"
        >
          <span className="eyebrow">
            {label ? `${label} · ` : ""}Step {index + 1} of {steps.length}
          </span>
          <h2 id={titleId} className="text-[14px] font-semibold">
            {step.title}
          </h2>
          <div id={bodyId} className="text-[13px] text-fg-secondary">
            {step.body}
          </div>
          <div className="flex items-center gap-2 pt-2">
            <Button
              size="28"
              variant="ghost"
              onClick={() => {
                end("dismissed");
              }}
            >
              Skip tour
            </Button>
            <span className="flex-1" />
            {index > 0 && (
              <Button
                size="28"
                variant="outline"
                onClick={() => {
                  setIndex(index - 1);
                }}
              >
                Back
              </Button>
            )}
            <Button
              size="28"
              variant="primary"
              onClick={() => {
                if (last) end("done");
                else setIndex(index + 1);
              }}
            >
              {last ? "Done" : "Next"}
            </Button>
          </div>
          {target && (
            <PopoverPrimitive.Arrow className="fill-[var(--surface-raised)]" width={14} height={7} />
          )}
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}
