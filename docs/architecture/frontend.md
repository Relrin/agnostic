# Frontend

TypeScript (strict), React 19, Vite 8, Tailwind CSS v4, Radix (through `@agnostic/ui`), TanStack Router and
Query, Yarn 4 workspaces. The shell composes feature modules that register through manifests.

## Workspaces

| Package | Role | May import |
|---|---|---|
| `apps/web` (`@agnostic/web`) | shell: router assembly, sidebar, header, command palette, providers | everything |
| `packages/ui` (`@agnostic/ui`) | design system: tokens, primitives, patterns, Storybook | nothing internal |
| `packages/core` (`@agnostic/core`) | module SDK, navigation, query defaults, run streaming and `RunView` | packages |
| `packages/editor` (`@agnostic/editor`) | read-only code views on CodeMirror 6 (`CodeView`, loaded on demand) | `@agnostic/ui` |
| `packages/studio` (`@agnostic/studio`) | Studio editor building blocks: draft document, form, code and test panes, versions, publish and promote dialogs ([Studio](studio.md)) | packages |
| `packages/api` (`@agnostic/api`) | generated client + TanStack Query options | packages |
| `packages/testing` (`@agnostic/testing`) | render helpers, MSW handlers with sample data | packages |
| `modules/*` (`@agnostic/module-*`) | feature modules | packages only, never another module |

ESLint (`no-restricted-imports` per workspace) and TypeScript project references (`tsc -b`) both enforce the
table. Feature code never imports Radix directly; it uses `@agnostic/ui`.

## Module SDK

```ts
export const settingsModule = defineModule({
  id: "settings",
  scope: "instance",                       // lives under /i/:instance/… ("org" at the root, "public" outside the shell)
  routes: [
    { path: "settings", component: SettingsPage },
    { path: "settings/$section", component: SettingsPage },
  ],
  nav: [{ id: "settings", group: "footer", label: "Settings", icon: Settings, path: "settings", order: 10 }],
  commands: [{ id: "settings.keys", label: "Rotate the instance key pair", path: "settings/authorization" }],
});
```

The shell lists modules in `apps/web/src/modules.ts`, then:

- builds routes: instance-scoped modules under `/i/$instance`, org-scoped ones at the root, both inside the
  signed-in shell (anonymous visitors go to `/login`); public ones (sign-in, invitations, first run) outside it;
- builds the sidebar from the **nav catalog** (`apps/web/src/shell/nav-catalog.ts`, the prototype's full
  navigation) merged with module nav entries. Catalog entries no module implements yet open a "not built yet"
  page naming the phase that ships them;
- builds the ⌘K palette from nav entries and module commands.

`requires.capabilities` hides an instance module's nav entry when the active instance lacks the capability
(from its health/capability matrix); `requires.anyScope` hides it when the person holds none of the scopes. Inside pages, `useCan(scope, instance)` and `<PermissionGate>` from `@agnostic/core` hide or disable actions, and `<WhyVisible>` says which grant allows them.

## Data layer

- `yarn api:gen` generates `packages/api/src/generated` from `packages/api/openapi.json` (written by
  `agnostic openapi`). Use the generated `…Options()` and `…Mutation()` helpers with TanStack Query.
- `configureApi()` sets the base URL (same origin) and throws on errors; errors are problem bodies, so
  `describeError()` gives the human reason and the request id for `ErrorState`.
- `createQueryClient()` (core): 15 s default staleness, no retries on 4xx.

## Design system

Tokens come from the prototype ("AgentOS Control Plane — redesign") and live in
`packages/ui/src/styles/tokens.css` as CSS variables, mapped into Tailwind with `@theme inline`. Components use
semantic classes (`bg-surface`, `text-fg-muted`, `border-border-input`, `rounded-control`), never raw hex. Dark is
the only theme through GA; a light theme later is a second token block.

Primitives: `Button` (10 variants, 5 sizes), `Badge`/`StatusPill`, `Input`, `Select`, `SegmentedControl`, `Tabs`
(underline and pill), `Tooltip`, `Dialog`, `Sheet`, `DropdownMenu`, `Command`, `Sidebar` parts, `Breadcrumb`,
`Kbd`, `Avatar`, `Skeleton`, `Callout`. Patterns: `AppShell`, `AppSidebar`, `PageHeader`, `PageIntro`,
`InstanceSwitcher`, `EnvBadge`, `HealthIndicator`, `OrgBadge`, `EmptyState`, `ErrorState`, `LoadingRows`, `Card`,
`KpiTile`, `AttentionCard`, `DataTable`/`Pager`, `FilterChip`, `KeyValueList`, `ApiHint`, `MarkdownView` (Shiki on
demand), `JsonView`, `JsonEditor`, `StackedBarChart` (with "View as table"), `ShareList`, `Toaster`. Domain widgets:
`RunBlock`, `ToolCallChip`, `ApprovalCard`, `StepTimeline`, `StepHitlForm`, `Composer`, `SessionList`, `RunCard`,
`RunTimelineSeparator`, `UserBubble`, `EntitySquare`. For the Studio editors: `SortableList` (@dnd-kit, grip handle and
keyboard sorting), `Accordion`/`AccordionSection`, `Checkbox`, `Combobox` (Popover + `Command`), `LineLinkBadge` and
`GateResultList`.

`@agnostic/editor` holds `CodeView`: read-only Python or JSON on CodeMirror 6, themed from the `--syntax-*` tokens,
with a 3px change-mark strip (added/modified) beside the line numbers, a focused line (accent background, scrolled
into view), inline notes under a line with a wavy underline on their columns, and an `onCursor` callback for linking
lines back to form fields. CodeMirror loads in its own chunk on first render (`CodeViewSkeleton` meanwhile;
`preloadCodeView()` fetches it early).

Fonts (Geist, Geist Mono) are self-hosted through `@fontsource-variable`; there are no runtime CDN calls.

Storybook (`just storybook`) has a **Tokens** page, every primitive, and the shell with the prototype's sample
data. Every story runs through axe in CI; a unit test checks the WCAG contrast of the text/background pairs the
design relies on and that the TypeScript token mirror matches `tokens.css`.

## Operate pages

Home, Chat and Sessions (`modules/home`, `modules/chat`, `modules/sessions`) read AgentOS through the gateway with the
helpers in `@agnostic/core` (`useComponents`, `useSessions`, `useSessionRuns`, `useSessionActions`) and render runs
from one `RunState`, whether live (`RunStream`) or stored (`fromStoredRun`), with `RunView` from `@agnostic/core`
(inline approvals and step HITL included). `RunStream` can submit to another endpoint (`endpoint.submit`, e.g. a
draft test run) and skip `/resume` reconnects (`resumable: false`); `RunState.structured` holds the parsed output of
components with an output schema. `RealtimeProvider` (mounted by the shell)
holds the realtime connection and updates the query cache; the approvals nav badge comes from `useApprovalsCount`.
Catalog entries without a module are splat routes, so links below them (`traces/<id>`) land on the placeholder. See
[Operate and realtime](operate-and-realtime.md).
