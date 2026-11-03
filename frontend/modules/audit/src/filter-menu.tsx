// An "Actor: Any" filter chip that opens a searchable list of choices, optionally with a free-text value.
import { FilterChip, Input, Popover, PopoverContent, PopoverTrigger, cn } from "@agnostic/ui";
import { Check } from "lucide-react";
import { useState, type ReactNode } from "react";

export type FilterOption = {
  value: string;
  label: string;
  /** Shown before the label (an avatar, a dot). */
  icon?: ReactNode;
  /** Shown after the label, muted (a count). */
  meta?: ReactNode;
  mono?: boolean;
};

export function FilterMenu({
  label,
  current,
  shown,
  options,
  onSelect,
  searchable = false,
  freeText,
  children,
  listCurrent = true,
}: {
  label: string;
  current: string | undefined;
  /** What the chip says when a value is set (defaults to the option's label, or the value). */
  shown?: string | undefined;
  options: readonly FilterOption[];
  onSelect: (value: string | undefined) => void;
  /** A search box above long lists (actors, actions). */
  searchable?: boolean;
  /** Lets people type a value that isn't among the options (an action prefix like `gateway.*`). */
  freeText?: { label: string; placeholder: string };
  /** Extra content under the list (the date range inputs). */
  children?: (close: () => void) => ReactNode;
  /** List a current value that isn't among the options (off for the date chip, whose value is a range). */
  listCurrent?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const value = current
    ? (shown ?? options.find((option) => option.value === current)?.label ?? current)
    : "Any";
  const choose = (next: string | undefined) => {
    onSelect(next);
    setOpen(false);
  };
  const needle = text.trim().toLowerCase();
  const matching = needle
    ? options.filter(
        (option) =>
          option.label.toLowerCase().includes(needle) || option.value.toLowerCase().includes(needle),
      )
    : options;
  const items: FilterOption[] = [...matching];
  if (listCurrent && current && !options.some((option) => option.value === current) && !needle)
    items.unshift({ value: current, label: shown ?? current, mono: true });
  const typed = text.trim();
  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) setText("");
      }}
    >
      <PopoverTrigger asChild>
        <FilterChip label={label} value={value} />
      </PopoverTrigger>
      <PopoverContent align="start" className="flex w-72 flex-col gap-1 p-1.5">
        {(searchable || freeText) && (
          <form
            className="p-1 pb-1.5"
            onSubmit={(event) => {
              event.preventDefault();
              if (freeText && typed) choose(typed);
              else if (matching.length === 1 && matching[0]) choose(matching[0].value);
            }}
          >
            <Input
              aria-label={freeText?.label ?? `Search ${label.toLowerCase()}`}
              placeholder={freeText?.placeholder ?? "Search"}
              mono={Boolean(freeText)}
              className="h-8"
              value={text}
              onChange={(event) => {
                setText(event.target.value);
              }}
            />
          </form>
        )}
        <ul aria-label={label} className="flex max-h-72 flex-col overflow-y-auto">
          {!needle && (
            <li>
              <button
                type="button"
                aria-pressed={current === undefined}
                className="flex w-full cursor-pointer items-center justify-between gap-2 rounded-control px-2 py-1.5 text-left text-[13px] hover:bg-surface-hover"
                onClick={() => {
                  choose(undefined);
                }}
              >
                <span>Any</span>
                {current === undefined && <Check className="size-3.5 shrink-0 text-accent" aria-hidden />}
              </button>
            </li>
          )}
          {items.map((item) => {
            const active = item.value === current;
            return (
              <li key={item.value}>
                <button
                  type="button"
                  aria-pressed={active}
                  className={cn(
                    "flex w-full cursor-pointer items-center gap-2 rounded-control px-2 py-1.5 text-left text-[13px] hover:bg-surface-hover",
                    item.mono && "font-mono text-[12.5px]",
                  )}
                  onClick={() => {
                    choose(item.value);
                  }}
                >
                  {item.icon}
                  <span className="min-w-0 flex-1 truncate">{item.label}</span>
                  {item.meta !== undefined && (
                    <span className="shrink-0 font-mono text-[11.5px] text-fg-muted">{item.meta}</span>
                  )}
                  {active && <Check className="size-3.5 shrink-0 text-accent" aria-hidden />}
                </button>
              </li>
            );
          })}
          {needle && items.length === 0 && (
            <li className="px-2 py-1.5 text-[12.5px] text-fg-muted">
              {freeText ? (
                <>
                  Press Enter to filter by <code className="font-mono">{typed}</code>
                </>
              ) : (
                "Nothing matches."
              )}
            </li>
          )}
        </ul>
        {children?.(() => {
          setOpen(false);
        })}
      </PopoverContent>
    </Popover>
  );
}
