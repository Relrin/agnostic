# Frontend

`frontend/`: TypeScript (strict), React 19, Vite 8, Tailwind CSS v4, Radix (through `@agnostic/ui`), TanStack Router
and Query, Yarn 4 workspaces. The shell composes feature modules that register through manifests.

## Workspaces

| Package | Role | May import |
|---|---|---|
| `apps/web` | shell: routes, sidebar, header, palette, bell, providers | everything |
| `packages/ui` | design system: tokens, primitives, patterns, domain widgets, Storybook | nothing internal |
| `packages/core` | module SDK, navigation, permissions, query defaults, run streaming, realtime | packages |
| `packages/api` | generated client, TanStack Query options, AgentOS types | packages |
| `packages/editor` | CodeMirror 6 on demand: `CodeView`, `CodeEditor`, `CelEditor` | packages |
| `packages/studio`, `packages/assistant` | [Studio](studio.md) and [assistant](assistant.md) building blocks | packages |
| `packages/testing` | render helpers, MSW handlers (`sampleOrgHandlers`, `operateHandlers`, …) | packages |
| `modules/*` | 30 feature modules (`@agnostic/module-*`) | packages, never another module |

ESLint `no-restricted-imports` and `tsc -b` project references enforce the table; feature code never imports Radix.

## Module SDK

```ts
export const settingsModule = defineModule({
  id: "settings",
  scope: "instance",                       // under /i/:instance/… ("org" at the root, "public" outside the shell)
  routes: [{ path: "settings", component: SettingsPage }, { path: "settings/$section", component: SettingsPage }],
  nav: [{ id: "settings", group: "footer", label: "Settings", icon: Settings, path: "settings", order: 10 }],
  commands: [{ id: "settings.keys", label: "Rotate the instance key pair", path: "settings/authorization" }],
});
```

`apps/web/src/modules.ts` lists the modules (static imports, so each stays code-split). The shell mounts instance
modules under `/i/$instance` and org modules at the root inside the signed-in shell, public ones outside; builds the
sidebar from `shell/nav-catalog.ts` merged with module entries; and builds ⌘K from nav entries and commands. A
catalog entry no visible module claims opens the "unavailable" page (`shell/not-found.tsx`).

`requires` hides a module by `capabilities` (the instance's capability matrix), `anyScope` and `features`
(`GET /api/v1/system/features`). In pages, `useCan`, `<PermissionGate>` and `<WhyVisible>` handle actions.

## Data layer

- `yarn api:gen` generates `packages/api/src/generated` from `openapi.json` (`agnostic openapi`); use the generated
  `…Options()` / `…Mutation()` helpers. Errors are problem bodies; `describeError()` gives reason and request id.
- `createQueryClient()`: 15 s staleness, no retries on 4xx.
- AgentOS is read through the gateway with `@agnostic/core` helpers (`useComponents`, `useSessions`, …); runs render
  from one `RunState` with `RunView`. `RealtimeProvider` keeps the cache current
  ([operate](operate-and-realtime.md)).

## Design system

Tokens are CSS variables in `packages/ui/src/styles/tokens.css`, mapped into Tailwind with `@theme inline`;
components use semantic classes, never raw hex. Dark is the only theme. Fonts are self-hosted
(`@fontsource-variable`), no runtime CDN calls. Storybook (`just storybook`) shows every component; stories run
through axe in CI, and a unit test checks WCAG contrast of token pairs and the TypeScript token mirror.

`@agnostic/editor` loads CodeMirror in its own chunk, themed from `--syntax-*` tokens. The workflow builder
(`modules/studio-workflows`) draws a left-to-right flow with `@xyflow/react` (component nodes with typed ports, group
frames, a port legend, a minimap and sticky notes; the node widgets live in `@agnostic/ui`), laid out by ELK in a
worker; edits are immer patches in a zustand store, so each undoes.
