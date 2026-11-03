// Combobox: a Select-looking trigger that opens a searchable Command list in a Popover.
import { Check, ChevronDown } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

import { cn } from "../lib/cn";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "./command";
import { Popover, PopoverContent, PopoverTrigger } from "./popover";

export type ComboboxOption<T extends string = string> = {
  value: T;
  label: string;
  /** Muted text after the label (a provider, a version). */
  hint?: ReactNode;
  /** Extra words the search matches besides the label. */
  keywords?: string[];
  disabled?: boolean;
};

export type ComboboxProps<T extends string = string> = {
  value: T | undefined;
  onValueChange: (value: T) => void;
  options: readonly ComboboxOption<T>[];
  placeholder?: string;
  searchPlaceholder?: string;
  emptyText?: ReactNode;
  /** Heading above the options. */
  group?: string;
  id?: string;
  "aria-label"?: string;
  "aria-describedby"?: string;
  "aria-invalid"?: boolean;
  disabled?: boolean;
  mono?: boolean;
  className?: string;
};

export function Combobox<T extends string = string>({
  value,
  onValueChange,
  options,
  placeholder = "Select…",
  searchPlaceholder = "Search…",
  emptyText = "Nothing matches.",
  group,
  disabled,
  mono = false,
  className,
  ...aria
}: ComboboxProps<T>) {
  const [open, setOpen] = useState(false);
  const listId = useId();
  const selected = options.find((option) => option.value === value);
  const items = options.map((option) => (
    <CommandItem
      key={option.value}
      value={option.value}
      keywords={[option.label, ...(option.keywords ?? [])]}
      disabled={option.disabled ?? false}
      onSelect={() => {
        onValueChange(option.value);
        setOpen(false);
      }}
    >
      <Check
        aria-hidden
        className={cn("!text-accent", option.value === value ? "opacity-100" : "opacity-0")}
      />
      <span className={cn("truncate", mono && "font-mono text-[12.5px]")}>{option.label}</span>
      {option.hint && <span className="ml-auto shrink-0 text-[12px] text-fg-muted">{option.hint}</span>}
    </CommandItem>
  ));
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild disabled={disabled}>
        <button
          type="button"
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          data-slot="combobox-trigger"
          data-placeholder={selected ? undefined : ""}
          className={cn(
            "flex h-[34px] w-full cursor-pointer items-center justify-between gap-2 rounded-button border border-border-input bg-surface px-2.5 text-left text-[13px] text-fg focus-visible:border-accent focus-visible:outline-none disabled:cursor-not-allowed disabled:text-fg-disabled aria-invalid:border-danger data-[placeholder]:text-fg-muted",
            className,
          )}
          {...aria}
        >
          <span className={cn("truncate", mono && selected && "font-mono text-[12.5px]")}>
            {selected?.label ?? placeholder}
          </span>
          <ChevronDown className="size-4 shrink-0 text-fg-muted" aria-hidden />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[var(--radix-popover-trigger-width)] min-w-56 p-0">
        <Command>
          <CommandInput placeholder={searchPlaceholder} />
          <CommandList id={listId}>
            <CommandEmpty>{emptyText}</CommandEmpty>
            {group ? (
              <CommandGroup heading={group}>{items}</CommandGroup>
            ) : (
              <CommandGroup>{items}</CommandGroup>
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
