// A "Type: Any" filter chip that opens a short list of choices, optionally with a free-text value.
import { FilterChip, Input, Popover, PopoverContent, PopoverTrigger, cn } from "@agnostic/ui";
import { Check } from "lucide-react";
import { useState } from "react";

export type FilterOption = { value: string; label: string };

export function FilterMenu({
  label,
  current,
  options,
  onSelect,
  freeText,
}: {
  label: string;
  current: string | undefined;
  options: readonly FilterOption[];
  onSelect: (value: string | undefined) => void;
  /** Lets people type a value that isn't among the options (a user id, a schedule id). */
  freeText?: { label: string; placeholder: string };
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const shown = current ? (options.find((option) => option.value === current)?.label ?? current) : "Any";
  const choose = (value: string | undefined) => {
    onSelect(value);
    setOpen(false);
  };
  const items: { value: string | undefined; label: string }[] = [
    { value: undefined, label: "Any" },
    ...options,
  ];
  if (current && !options.some((option) => option.value === current))
    items.push({ value: current, label: current });
  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) setText("");
      }}
    >
      <PopoverTrigger asChild>
        <FilterChip label={label} value={shown} />
      </PopoverTrigger>
      <PopoverContent align="start" className="flex w-64 flex-col gap-1 p-1.5">
        <ul aria-label={label} className="flex max-h-64 flex-col overflow-y-auto">
          {items.map((item) => {
            const active = item.value === current;
            return (
              <li key={item.value ?? "any"}>
                <button
                  type="button"
                  aria-pressed={active}
                  className={cn(
                    "flex w-full cursor-pointer items-center justify-between gap-2 rounded-control px-2 py-1.5 text-left text-[13px] hover:bg-surface-hover",
                    item.value && "font-mono text-[12.5px]",
                  )}
                  onClick={() => {
                    choose(item.value);
                  }}
                >
                  <span className="truncate">{item.label}</span>
                  {active && <Check className="size-3.5 shrink-0 text-accent" aria-hidden />}
                </button>
              </li>
            );
          })}
        </ul>
        {freeText && (
          <form
            className="border-t border-border-subtle p-1 pt-2"
            onSubmit={(event) => {
              event.preventDefault();
              if (text.trim()) choose(text.trim());
            }}
          >
            <Input
              aria-label={freeText.label}
              placeholder={freeText.placeholder}
              mono
              className="h-8"
              value={text}
              onChange={(event) => {
                setText(event.target.value);
              }}
            />
          </form>
        )}
      </PopoverContent>
    </Popover>
  );
}
