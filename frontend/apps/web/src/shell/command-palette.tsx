import { scopedPath, type CommandDefinition, type ModuleScope, type Navigation } from "@agnostic/core";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@agnostic/ui";
import { useNavigate } from "@tanstack/react-router";
import { useEffect } from "react";

/** ⌘K / Ctrl+K: jump to any page, or run a module command. Entity search arrives with the search module (P02). */
export function CommandPalette({
  open,
  onOpenChange,
  navigation,
  commands,
  instance,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  navigation: Navigation;
  commands: readonly (CommandDefinition & { scope: ModuleScope })[];
  instance: string;
}) {
  const navigate = useNavigate();

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() === "k" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        onOpenChange(!open);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [open, onOpenChange]);

  const go = (scope: ModuleScope, path: string) => {
    onOpenChange(false);
    void navigate({ to: scopedPath(scope, path, instance) });
  };

  return (
    <CommandDialog open={open} onOpenChange={onOpenChange}>
      <CommandInput placeholder="Search or jump to…" />
      <CommandList>
        <CommandEmpty>Nothing matches. Entity search arrives with the search module.</CommandEmpty>
        {commands.length > 0 && (
          <CommandGroup heading="Actions">
            {commands.map((command) => (
              <CommandItem
                key={command.id}
                value={`${command.label} ${command.keywords?.join(" ") ?? ""}`}
                onSelect={() => {
                  if (command.path !== undefined) go(command.scope, command.path);
                }}
              >
                {command.icon && <command.icon aria-hidden />}
                {command.label}
              </CommandItem>
            ))}
          </CommandGroup>
        )}
        {[...navigation.groups, { id: "footer", label: "More", items: navigation.footer }].map((group) =>
          group.items.length === 0 ? null : (
            <CommandGroup key={group.id} heading={group.label ?? "Go to"}>
              {group.items.map((entry) => (
                <CommandItem
                  key={entry.id}
                  value={`${entry.label} ${group.label ?? ""}`}
                  onSelect={() => {
                    go(entry.scope, entry.path);
                  }}
                >
                  <entry.icon aria-hidden />
                  {entry.label}
                </CommandItem>
              ))}
            </CommandGroup>
          ),
        )}
      </CommandList>
    </CommandDialog>
  );
}
