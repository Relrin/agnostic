// Accordion: stacked sections behind 42px header buttons (chevron, title, a one-line summary on the right).
// The adornment sits beside the button, not in it, since it can be a control of its own (a LineLinkBadge); the
// button's ::after covers the rest of the row, so a click anywhere else still toggles.
// Sections open independently; each is controlled (`open` + `onOpenChange`) or keeps its own state (`defaultOpen`).
import { ChevronRight } from "lucide-react";
import { useId, useState, type ComponentProps, type ReactNode } from "react";

import { cn } from "../lib/cn";

export function Accordion({ className, ...props }: ComponentProps<"div">) {
  return (
    <div
      data-slot="accordion"
      className={cn(
        "flex flex-col divide-y divide-border-subtle rounded-card border border-border bg-surface",
        className,
      )}
      {...props}
    />
  );
}

export type AccordionSectionProps = {
  title: ReactNode;
  /** Shown on the right of the header, truncated to one line (what the section holds while it is closed). */
  summary?: ReactNode;
  /** Something next to the title: a count, a LineLinkBadge, an error dot. */
  adornment?: ReactNode;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  id?: string;
  className?: string;
  contentClassName?: string;
  children: ReactNode;
};

export function AccordionSection({
  title,
  summary,
  adornment,
  open: controlled,
  defaultOpen = false,
  onOpenChange,
  id,
  className,
  contentClassName,
  children,
}: AccordionSectionProps) {
  const generated = useId();
  const base = id ?? generated;
  const [uncontrolled, setUncontrolled] = useState(defaultOpen);
  const open = controlled ?? uncontrolled;
  const toggle = () => {
    if (controlled === undefined) setUncontrolled(!open);
    onOpenChange?.(!open);
  };
  return (
    <section data-slot="accordion-section" data-state={open ? "open" : "closed"} className={className}>
      <h3 className="relative flex h-[42px] items-center gap-2 px-3 text-[13px] font-medium text-fg hover:bg-surface-hover has-[button:focus-visible]:bg-surface-hover">
        <button
          type="button"
          id={`${base}-header`}
          aria-expanded={open}
          aria-controls={`${base}-panel`}
          aria-describedby={summary ? `${base}-summary` : undefined}
          onClick={toggle}
          className="flex shrink-0 cursor-pointer items-center gap-2 text-left after:absolute after:inset-0 after:content-[''] focus-visible:outline-none"
        >
          <ChevronRight
            aria-hidden
            className={cn(
              "size-4 shrink-0 text-fg-muted transition-transform duration-[var(--motion-fast)]",
              open && "rotate-90",
            )}
          />
          <span>{title}</span>
        </button>
        {adornment && <span className="relative z-10 flex shrink-0 items-center">{adornment}</span>}
        {summary && (
          <span
            id={`${base}-summary`}
            className="ml-auto min-w-0 truncate pl-4 text-[12.5px] font-normal text-fg-muted"
          >
            {summary}
          </span>
        )}
      </h3>
      <div
        id={`${base}-panel`}
        role="region"
        aria-labelledby={`${base}-header`}
        hidden={!open}
        className={cn("px-3 pt-1 pb-3", contentClassName)}
      >
        {open && children}
      </div>
    </section>
  );
}
