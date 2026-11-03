// An "Access role: Any" filter chip that opens a short list of choices.
import { FilterChip, Popover, PopoverContent, PopoverTrigger } from "@agnostic/ui";
import { Check } from "lucide-react";
import { useState } from "react";

export type FilterOption = { value: string; label: string };

export function FilterMenu({
  label,
  current,
  options,
  onSelect,
}: {
  label: string;
  current: string | undefined;
  options: readonly FilterOption[];
  onSelect: (value: string | undefined) => void;
}) {
  const [open, setOpen] = useState(false);
  const shown = current ? (options.find((option) => option.value === current)?.label ?? current) : "Any";
  const items: { value: string | undefined; label: string }[] = [
    { value: undefined, label: "Any" },
    ...options,
  ];
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <FilterChip label={label} value={shown} />
      </PopoverTrigger>
      <PopoverContent align="start" className="flex w-60 flex-col p-1.5">
        <ul aria-label={label} className="flex max-h-64 flex-col overflow-y-auto">
          {items.map((item) => {
            const active = item.value === current;
            return (
              <li key={item.value ?? "any"}>
                <button
                  type="button"
                  aria-pressed={active}
                  className="flex w-full cursor-pointer items-center justify-between gap-2 rounded-control px-2 py-1.5 text-left text-[13px] hover:bg-surface-hover"
                  onClick={() => {
                    onSelect(item.value);
                    setOpen(false);
                  }}
                >
                  <span className="truncate">{item.label}</span>
                  {active && <Check className="size-3.5 shrink-0 text-accent" aria-hidden />}
                </button>
              </li>
            );
          })}
        </ul>
      </PopoverContent>
    </Popover>
  );
}
