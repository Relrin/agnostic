// Accordion: stacked sections behind 42px header buttons (chevron, title, a one-line summary on the right).
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
      <h3 className="flex">
        <button
          type="button"
          id={`${base}-header`}
          aria-expanded={open}
          aria-controls={`${base}-panel`}
          onClick={toggle}
          className="flex h-[42px] w-full min-w-0 cursor-pointer items-center gap-2 px-3 text-left text-[13px] font-medium text-fg hover:bg-surface-hover focus-visible:bg-surface-hover focus-visible:outline-none"
        >
          <ChevronRight
            aria-hidden
            className={cn(
              "size-4 shrink-0 text-fg-muted transition-transform duration-[var(--motion-fast)]",
              open && "rotate-90",
            )}
          />
          <span className="shrink-0">{title}</span>
          {adornment && <span className="flex shrink-0 items-center">{adornment}</span>}
          {summary && (
            <span className="ml-auto min-w-0 truncate pl-4 text-[12.5px] font-normal text-fg-muted">
              {summary}
            </span>
          )}
        </button>
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
