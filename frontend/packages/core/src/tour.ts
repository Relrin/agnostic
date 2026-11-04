// Tours opened by a link: `?tour=<id>` on a page opens that page's tour (Home's "Get started" links there).
import { useNavigate, useRouterState, useSearch } from "@tanstack/react-router";

/** Whether `?tour=<id>` is on the current URL, and `close()`, which drops it again. */
export function useTourFromSearch(id: string): { open: boolean; close: () => void } {
  const search = useSearch({ strict: false }) as unknown as Record<string, unknown>;
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const navigate = useNavigate();
  return {
    open: search.tour === id,
    close: () => {
      const rest = Object.fromEntries(Object.entries(search).filter(([key]) => key !== "tour"));
      void navigate({ to: pathname, search: rest, replace: true });
    },
  };
}
