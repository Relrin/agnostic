// Display density from the signed-in person's preferences (`me.preferences.density`): the provider sets
// `data-density` on <html> for the CSS tokens and passes the value to components with fixed JS sizes.
import { meGetMeQueryKey, type MeOut } from "@agnostic/api";
import { DensityContext, type Density } from "@agnostic/ui";
import { useQueryClient } from "@tanstack/react-query";
import { useLayoutEffect, useSyncExternalStore, type ReactNode } from "react";

/**
 * `me` as the cache has it, without observing the query: the provider sits above the router, whose sign-in check
 * loads `me`, and an observer that mounts and unmounts there (StrictMode) would cancel that request.
 */
function useCachedMe(): MeOut | undefined {
  const queryClient = useQueryClient();
  return useSyncExternalStore(
    (onChange) => queryClient.getQueryCache().subscribe(onChange),
    () => queryClient.getQueryData<MeOut>(meGetMeQueryKey()),
  );
}

/** "comfortable" (the default, and before anyone is signed in) or "compact". */
export function useDensity(): Density {
  return useCachedMe()?.preferences.density === "compact" ? "compact" : "comfortable";
}

/** Wraps the app: applies the preference everywhere, including pages outside the signed-in shell. */
export function DensityProvider({ children }: { children: ReactNode }) {
  const density = useDensity();
  useLayoutEffect(() => {
    document.documentElement.dataset.density = density;
  }, [density]);
  return <DensityContext.Provider value={density}>{children}</DensityContext.Provider>;
}
