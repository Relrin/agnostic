# Add a frontend module

Use `frontend/modules/audit` as the template (one page, a nav entry, MSW-backed tests). This guide adds the
page for a `notes` backend module.

## 1. Create the workspace package

```json
// frontend/modules/notes/package.json
{
  "name": "@agnostic/module-notes",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "exports": { ".": "./src/index.ts" },
  "dependencies": {
    "@agnostic/api": "workspace:*",
    "@agnostic/core": "workspace:*",
    "@agnostic/ui": "workspace:*",
    "@tanstack/react-query": "5.105.0",
    "lucide-react": "1.65.0"
  },
  "peerDependencies": { "react": "19.3.1" },
  "devDependencies": { "@agnostic/testing": "workspace:*", "react": "19.3.1", "react-dom": "19.3.1" }
}
```

Copy `tsconfig.json` and `src/vitest-env.d.ts` from `modules/audit`, add the package to the root
`tsconfig.json` references and to `apps/web/tsconfig.json` references, then `yarn install`. `yarn constraints`
keeps versions exact and identical across workspaces.

## 2. Write the page

Use the generated client and the design system; never import Radix or another module.

```tsx
import { notesListNotesOptions, describeError } from "@agnostic/api";
import { PermissionGate, withQueryFn } from "@agnostic/core";
import { EmptyState, ErrorState, LoadingRows, PageIntro } from "@agnostic/ui";

export function NotesPage() {
  const notes = useQuery(withQueryFn(notesListNotesOptions({ query: { limit: 50 } })));
  ...
}
```

Every page needs loading (skeletons), empty and error states. Errors show the problem's explanation and request id
(`describeError`). Wrap actions the person may not be allowed to take in `<PermissionGate scope="notes:write">`.

## 3. Export the manifest

```ts
export const notesModule = defineModule({
  id: "notes",
  scope: "instance",
  routes: [{ path: "notes", component: NotesPage }],
  nav: [{ id: "notes", group: "context", label: "Notes", icon: NotebookPen, path: "notes", order: 50 }],
  commands: [{ id: "notes.open", label: "Open Notes", path: "notes" }],
});
```

To take over a page that's already in the design, reuse its nav id from `apps/web/src/shell/nav-catalog.ts`
(e.g. `approvals`); your entry replaces the placeholder and keeps the catalog's position.

## 4. Register it in the shell

```ts
// apps/web/src/modules.ts
export const MODULES = [identityModule, …, auditModule, notesModule];
```

and add `"@agnostic/module-notes": "workspace:*"` to `apps/web/package.json`.

## 5. Test

- Unit tests next to the code (`*.test.tsx`), rendered with `renderPage` (or `renderWithProviders`) and MSW
  handlers (`p01Handlers()` covers `/me`, `/org`, `/instances` and access).
- Stories for reusable widgets go in `@agnostic/ui` and must pass the axe checks.
- Add an e2e case in `apps/web/e2e` for the page's main flow.

```bash
cd frontend && yarn typecheck && yarn lint && yarn test
```
