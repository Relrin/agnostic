// Router assembled from module manifests (03 §3): instance pages under /i/$instance, org pages at the root.
// Catalog entries without a module get a placeholder route.
import type { ModuleManifest } from "@agnostic/core";
import type { QueryClient } from "@tanstack/react-query";
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  Outlet,
  redirect,
  type AnyRoute,
} from "@tanstack/react-router";

import { NAV_CATALOG } from "./shell/nav-catalog";
import { NotBuiltYet, NotFound } from "./shell/not-built-yet";
import { RootLayout } from "./shell/root-layout";
import { DEFAULT_INSTANCE } from "./shell/session";

export function buildRouter(modules: readonly ModuleManifest[], queryClient: QueryClient) {
  const rootRoute = createRootRouteWithContext<{ queryClient: QueryClient }>()({
    component: RootLayout,
    notFoundComponent: NotFound,
  });

  const indexRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/",
    beforeLoad: () => {
      // eslint-disable-next-line @typescript-eslint/only-throw-error -- TanStack Router's redirect protocol
      throw redirect({ to: "/i/$instance/home", params: { instance: DEFAULT_INSTANCE } });
    },
  });

  const instanceRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "i/$instance",
    component: Outlet,
  });

  const parentFor = (scope: ModuleManifest["scope"]): AnyRoute =>
    scope === "instance" ? instanceRoute : rootRoute;
  const instanceChildren: AnyRoute[] = [];
  const orgChildren: AnyRoute[] = [];
  const implemented = new Set<string>();

  for (const module of modules) {
    for (const route of module.routes) {
      const child = createRoute({
        getParentRoute: () => parentFor(module.scope),
        path: route.path,
        component: route.component,
      });
      (module.scope === "instance" ? instanceChildren : orgChildren).push(child);
    }
    for (const entry of module.nav ?? []) implemented.add(entry.id);
  }

  for (const entry of NAV_CATALOG) {
    if (implemented.has(entry.id)) continue;
    const child = createRoute({
      getParentRoute: () => parentFor(entry.scope),
      path: entry.path,
      component: () => <NotBuiltYet label={entry.label} phase={entry.phase} />,
    });
    (entry.scope === "instance" ? instanceChildren : orgChildren).push(child);
  }

  const routeTree = rootRoute.addChildren([
    indexRoute,
    instanceRoute.addChildren(instanceChildren),
    ...orgChildren,
  ]);
  return createRouter({
    routeTree,
    context: { queryClient },
    defaultPreload: "intent",
    scrollRestoration: true,
  });
}
