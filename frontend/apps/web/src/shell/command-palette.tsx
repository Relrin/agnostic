import {
  AgentOSHttpError,
  gatewayJson,
  searchSearchOptions,
  type AgentOS,
  type SearchHitOut,
} from "@agnostic/api";
import {
  scopedPath,
  useComponents,
  type CommandDefinition,
  type ComponentSummary,
  type ModuleScope,
  type Navigation,
} from "@agnostic/core";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  EntitySquare,
} from "@agnostic/ui";
import { skipToken, useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { Box, MessagesSquare, Plus, ScanSearch, User } from "lucide-react";
import { useDeferredValue, useEffect, useState } from "react";

/** AgentOS ids people paste: UUIDs (sessions, runs), `ses_…`/`run_…`, 32-hex trace ids. */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const PREFIXED = /^(ses|run)_[\w-]{4,}$/i;
const TRACE = /^[0-9a-f]{32}$/i;

const KIND_OF = { agents: "agent", teams: "team", workflows: "workflow" } as const;

function hitKind(kind: string): "agent" | "team" | "workflow" | undefined {
  return kind === "agent" || kind === "team" || kind === "workflow" ? kind : undefined;
}

/** A pasted id → the session it names (as the person: isolation applies), or nothing. */
function useSessionLookup(instance: string, text: string, enabled: boolean) {
  const looksLikeId = UUID.test(text) || PREFIXED.test(text);
  return useQuery({
    queryKey: [instance, "agentos", "palette-session", text],
    queryFn:
      enabled && instance && looksLikeId
        ? async () => {
            try {
              return await gatewayJson<AgentOS.SessionSchema>(
                instance,
                `sessions/${encodeURIComponent(text)}`,
              );
            } catch (error) {
              if (error instanceof AgentOSHttpError) return null;
              throw error;
            }
          }
        : skipToken,
    retry: false,
    staleTime: 30_000,
  });
}

function useSessionNames(instance: string, text: string, enabled: boolean) {
  return useQuery({
    queryKey: [instance, "agentos", "palette-sessions", text],
    queryFn:
      enabled && instance && text.length >= 2 && !UUID.test(text)
        ? async () => {
            try {
              const page = await gatewayJson<AgentOS.PaginatedResponseSessionSchema>(
                instance,
                `sessions?session_name=${encodeURIComponent(text)}&limit=5`,
              );
              return page.data;
            } catch {
              return [];
            }
          }
        : skipToken,
    retry: false,
    staleTime: 30_000,
  });
}

/**
 * ⌘K / Ctrl+K: jump to any page, run a module command, find people, instances, agents, teams and workflows (the
 * search module), open a session or trace by pasting its id, or start a new session with a component.
 */
export function CommandPalette({
  open,
  onOpenChange,
  navigation,
  commands,
  instance,
  instanceId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  navigation: Navigation;
  commands: readonly (CommandDefinition & { scope: ModuleScope })[];
  instance: string;
  instanceId?: string | undefined;
}) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const text = useDeferredValue(query.trim());

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

  const searchOptions = searchSearchOptions({
    query: { q: text, ...(instanceId ? { instance: instanceId } : {}), limit: 8 },
  });
  const entities = useQuery({
    ...searchOptions,
    queryFn: open && text.length >= 2 ? (searchOptions.queryFn ?? skipToken) : skipToken,
    staleTime: 30_000,
    retry: false,
  });
  const session = useSessionLookup(instance, text, open);
  const named = useSessionNames(instance, text, open);
  const agents = useComponents(open && instance ? instance : undefined, "agents");
  const teams = useComponents(open && instance ? instance : undefined, "teams");
  const workflows = useComponents(open && instance ? instance : undefined, "workflows");
  const startable: ComponentSummary[] = [
    ...(agents.data ?? []),
    ...(teams.data ?? []),
    ...(workflows.data ?? []),
  ];

  const close = () => {
    onOpenChange(false);
    setQuery("");
  };
  const go = (to: string) => {
    close();
    void navigate({ to });
  };
  const goScoped = (scope: ModuleScope, path: string) => {
    go(scopedPath(scope, path, instance));
  };
  /** A command takes whatever was typed ("Ask your OS: …"), so something always matches. */
  const askAnything = query.trim().length > 0 && commands.some((command) => command.withQuery === true);
  // Server-side results always match what was typed; cmdk only needs to keep them.
  const keep = (label: string) => `${label} ${query}`;
  const hits: readonly SearchHitOut[] = text.length >= 2 ? (entities.data?.data ?? []) : [];

  return (
    <CommandDialog
      open={open}
      onOpenChange={(next) => {
        if (next) onOpenChange(true);
        else close();
      }}
    >
      <CommandInput placeholder="Search or jump to…" value={query} onValueChange={setQuery} />
      <CommandList>
        {!askAnything && (
          <CommandEmpty>
            {entities.isFetching || session.isFetching
              ? "Searching…"
              : "Nothing matches. Paste a session or trace id to open it."}
          </CommandEmpty>
        )}

        {session.data && (
          <CommandGroup heading="Session">
            <CommandItem
              value={keep(`session ${session.data.session_id}`)}
              onSelect={() => {
                go(
                  `/i/${encodeURIComponent(instance)}/sessions/${encodeURIComponent(session.data?.session_id ?? text)}`,
                );
              }}
            >
              <MessagesSquare aria-hidden />
              <span className="truncate">{session.data.session_name || session.data.session_id}</span>
              <span className="ml-auto font-mono text-[11.5px] text-fg-muted">{session.data.session_id}</span>
            </CommandItem>
          </CommandGroup>
        )}
        {(TRACE.test(text) || UUID.test(text) || PREFIXED.test(text)) && instance && (
          <CommandGroup heading="Open">
            <CommandItem
              value={keep(`open trace ${text}`)}
              onSelect={() => {
                go(
                  TRACE.test(text)
                    ? `/i/${encodeURIComponent(instance)}/traces/${encodeURIComponent(text)}`
                    : `/i/${encodeURIComponent(instance)}/traces?run_id=${encodeURIComponent(text)}`,
                );
              }}
            >
              <ScanSearch aria-hidden />
              Open trace… <span className="font-mono text-[11.5px] text-fg-muted">{text}</span>
            </CommandItem>
          </CommandGroup>
        )}
        {hits.length > 0 && (
          <CommandGroup heading="Results">
            {hits.map((hit) => {
              const kind = hitKind(hit.kind);
              return (
                <CommandItem
                  key={`${hit.kind}:${hit.instance_id ?? "-"}:${hit.ref}`}
                  value={keep(`${hit.title} ${hit.subtitle} ${hit.ref}`)}
                  onSelect={() => {
                    go(hit.url_path);
                  }}
                >
                  {kind ? (
                    <EntitySquare kind={kind} />
                  ) : hit.kind === "member" ? (
                    <User aria-hidden />
                  ) : (
                    <Box aria-hidden />
                  )}
                  <span className="truncate">{hit.title}</span>
                  <span className="ml-auto truncate text-[11.5px] text-fg-muted">{hit.kind}</span>
                </CommandItem>
              );
            })}
          </CommandGroup>
        )}
        {(named.data ?? []).length > 0 && (
          <CommandGroup heading="Sessions">
            {(named.data ?? []).map((item) => (
              <CommandItem
                key={item.session_id}
                value={keep(`session ${item.session_name} ${item.session_id}`)}
                onSelect={() => {
                  go(`/i/${encodeURIComponent(instance)}/sessions/${encodeURIComponent(item.session_id)}`);
                }}
              >
                <MessagesSquare aria-hidden />
                <span className="truncate">{item.session_name || item.session_id}</span>
              </CommandItem>
            ))}
          </CommandGroup>
        )}
        {startable.length > 0 && (
          <CommandGroup heading="New session with…">
            {startable.slice(0, 12).map((component) => (
              <CommandItem
                key={`${component.family}:${component.id}`}
                value={`new session with ${component.id} ${component.name} ${component.family}`}
                onSelect={() => {
                  go(
                    `/i/${encodeURIComponent(instance)}/chat/${component.family}/${encodeURIComponent(component.id)}`,
                  );
                }}
              >
                <Plus aria-hidden />
                <EntitySquare kind={KIND_OF[component.family]} />
                New session with <span className="font-mono">{component.id}</span>
              </CommandItem>
            ))}
          </CommandGroup>
        )}
        {commands.length > 0 && (
          <CommandGroup heading="Actions" forceMount={askAnything}>
            {commands.map((command) => (
              <CommandItem
                key={command.id}
                value={`${command.label} ${command.keywords?.join(" ") ?? ""}`}
                // A command that takes what was typed ("Ask your OS: …") matches anything typed.
                forceMount={command.withQuery === true && query.trim().length > 0}
                onSelect={() => {
                  if (command.path === undefined) return;
                  const target = scopedPath(command.scope, command.path, instance);
                  const typed = query.trim();
                  go(command.withQuery && typed ? `${target}?q=${encodeURIComponent(typed)}` : target);
                }}
              >
                {command.icon && <command.icon aria-hidden />}
                <span className="truncate">
                  {command.label}
                  {command.withQuery && query.trim() && (
                    <span className="text-fg-muted">: {query.trim()}</span>
                  )}
                </span>
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
                    goScoped(entry.scope, entry.path);
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
