// Router assembled from module manifests (03 §3): public pages at the root (sign-in, invitations, first run),
// everything else inside the signed-in shell; instance pages under /i/$instance, org pages at the root.
// Catalog entries without a module get a placeholder route.
import { instancesListInstancesOptions, meGetMeOptions, problemCode } from "@agnostic/api";
import { withQueryFn, type ModuleManifest, type ModuleScope } from "@agnostic/core";
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
import { lastInstance } from "./shell/session";

export function buildRouter(modules: readonly ModuleManifest[], queryClient: QueryClient) {
  const rootRoute = createRootRouteWithContext<{ queryClient: QueryClient }>()({
    component: Outlet,
    notFoundComponent: NotFound,
  });

  // The signed-in shell: anonymous visitors go to /login and come back afterwards.
  const appRoute = createRoute({
    getParentRoute: () => rootRoute,
    id: "app",
    component: RootLayout,
    beforeLoad: async ({ context, location }) => {
      try {
        await context.queryClient.query({ ...withQueryFn(meGetMeOptions()), staleTime: 15_000 });
      } catch (error) {
        if (problemCode(error) === "unauthenticated") {
          // eslint-disable-next-line @typescript-eslint/only-throw-error -- TanStack Router's redirect protocol
          throw redirect({ to: "/login", search: { next: location.href } });
        }
        throw error;
      }
    },
  });

  const indexRoute = createRoute({
    getParentRoute: () => appRoute,
    path: "/",
    beforeLoad: async ({ context }) => {
      const instances = await context.queryClient.query({
        ...withQueryFn(instancesListInstancesOptions()),
        staleTime: 15_000,
      });
      const remembered = lastInstance();
      const target = instances.find((item) => item.slug === remembered) ?? instances[0];
      // Home arrives in P02; until then an instance opens on its settings (connection and health).
      // eslint-disable-next-line @typescript-eslint/only-throw-error -- TanStack Router's redirect protocol
      throw target
        ? redirect({ to: "/i/$instance/settings", params: { instance: target.slug } })
        : redirect({ to: "/instances" });
    },
  });

  const instanceRoute = createRoute({
    getParentRoute: () => appRoute,
    path: "i/$instance",
    component: Outlet,
  });

  const children: Record<ModuleScope, AnyRoute[]> = { instance: [], org: [], public: [] };
  const parentFor = (scope: ModuleScope): AnyRoute =>
    scope === "instance" ? instanceRoute : scope === "org" ? appRoute : rootRoute;
  const implemented = new Set<string>();

  for (const module of modules) {
    for (const route of module.routes) {
      children[module.scope].push(
        createRoute({
          getParentRoute: () => parentFor(module.scope),
          path: route.path,
          component: route.component,
        }),
      );
    }
    for (const entry of module.nav ?? []) implemented.add(entry.id);
  }

  for (const entry of NAV_CATALOG) {
    if (implemented.has(entry.id)) continue;
    children[entry.scope].push(
      createRoute({
        getParentRoute: () => parentFor(entry.scope),
        path: entry.path,
        component: () => <NotBuiltYet label={entry.label} phase={entry.phase} />,
      }),
    );
  }

  const routeTree = rootRoute.addChildren([
    ...children.public,
    appRoute.addChildren([indexRoute, instanceRoute.addChildren(children.instance), ...children.org]),
  ]);
  return createRouter({
    routeTree,
    context: { queryClient },
    defaultPreload: "intent",
    scrollRestoration: true,
  });
}
